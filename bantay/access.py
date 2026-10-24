"""Layer 3: road + RoRo ferry access graph, travel time to the nearest hospital, and storm scenarios.

Network method
  Roads: OSM highway lines (Geofabrik PBF, read through GDAL). Ways are split into edges at shared vertices (OSM ways
  share node objects, so shared coordinates = junctions). Travel time = length / class speed; direction is ignored.
  Ferries: the 108 roroph RoRo routes (2024-2026 operations, a proxy for 2018-2020; coarse port coordinates snapped to
  the nearest road node within 25 km). Time = crossing time + half the headway (capped at 12 h).
  Hospitals: DOH NHFR when its manual download is present, else HOT OSM hospitals + UP NOAH facilities whose name says
  hospital / medical centre (a labelled fallback).
  Demand: WorldPop 2020 summed to ~1 km cells, joined to the nearest road node (walking at 5 km/h, max 5 km).
  A storm removes ferry routes that cross its gale swath and cuts / slows road edges in observed flood (Sentinel-1;
  EMS for the Ompong AOIs) or, when no observed flood exists (GEE pending, shifted tracks), in NOAH 25-yr hazard inside
  the swath (high = cut, medium = slowed): `flood_source` says which.
  A cell is cut off if it had a route at baseline and in the storm has none, or its trip at least doubles and grows by
  more than 1 h. Access loss A = cut-off population / population.

Raster method (MAP motorised friction surface 2019, GEE; `FrictionGrid`): cost-distance from the same hospitals over
the ~1 km friction grid, run in parallel with the network for every scenario when the GeoTIFF is on disk. Sea is
impassable except along the RoRo route lines (same crossing + half-headway hours, same cancellations); the storm rules
are the network's, applied at cell centres (observed flood or NOAH high hazard in the swath = impassable, medium =
slowed); the same cut-off rule. The network stays the primary method; the gap between the two is reported as
uncertainty (A_lo / A_hi).
"""

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from .config import RAW, INTERIM, CRS_M, have, missing, record

PBF = RAW / "osm" / "philippines-latest.osm.pbf"
ROADS = INTERIM / "road_graph.npz"
SPEED = {  # km/h, rural Philippine assumptions; links at 80% of their road; a sensitivity parameter
    "motorway": 80, "trunk": 60, "primary": 50, "secondary": 40, "tertiary": 30, "unclassified": 25,
    "residential": 20, "living_street": 10, "road": 20, "track": 10,
}
SPEED |= {f"{k}_link": v * 0.8 for k, v in SPEED.items() if k in ("motorway", "trunk", "primary", "secondary", "tertiary")}
WALK_KMH, MAX_SNAP_KM = 5.0, 5.0
LAT0 = 12.0  # local equirectangular projection for KD-tree snapping


def _xy(lon, lat):
    k = 111.32 * np.cos(np.radians(LAT0))
    return np.c_[np.asarray(lon) * k, np.asarray(lat) * 110.57]  # km


def _hav_km(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------- road graph

def build_road_graph(force=False):
    """OSM highways -> node coordinates + edge list (u, v, km, speed, midpoint), cached in data/interim/road_graph.npz."""
    if ROADS.exists() and not force and ROADS.stat().st_mtime > PBF.stat().st_mtime:
        return dict(np.load(ROADS, allow_pickle=True))
    if not have("osm", PBF):
        return None
    import pyogrio

    classes = ",".join(f"'{c}'" for c in SPEED)
    g = pyogrio.read_dataframe(PBF.as_posix(), layer="lines", columns=["highway"], where=f"highway IN ({classes})")
    g = g[g.geometry.notna() & (g.geom_type == "LineString")].reset_index(drop=True)
    coords, way = shapely.get_coordinates(g.geometry.values, return_index=True)
    key = np.round(coords[:, 0] * 1e7).astype(np.int64) * (1 << 31) + np.round(coords[:, 1] * 1e7).astype(np.int64)
    uniq, node = np.unique(key, return_inverse=True)
    first = np.r_[True, way[1:] != way[:-1]]
    last = np.r_[way[1:] != way[:-1], True]
    deg = np.bincount(node, minlength=len(uniq))
    junction = (deg[node] >= 2) | first | last
    same = way[1:] == way[:-1]
    seg = np.where(same, _hav_km(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1]), 0.0)
    cum = np.r_[0.0, np.cumsum(seg)]
    j = np.flatnonzero(junction)
    a, b = j[:-1], j[1:]
    ok = way[a] == way[b]
    a, b = a[ok], b[ok]
    km = cum[b] - cum[a]
    mid = (a + b) // 2
    speed = g.highway.map(SPEED).to_numpy()[way[a]]
    # compact node ids to junction nodes only
    used, inv = np.unique(np.r_[node[a], node[b]], return_inverse=True)
    u, v = inv[: len(a)], inv[len(a):]
    lonlat = np.c_[(uniq[used] // (1 << 31)) / 1e7, (uniq[used] % (1 << 31)) / 1e7]
    out = dict(lon=lonlat[:, 0], lat=lonlat[:, 1], u=u, v=v, km=np.maximum(km, 1e-4), speed=speed.astype(float),
               mid_lon=coords[mid, 0], mid_lat=coords[mid, 1], highway=g.highway.to_numpy()[way[a]].astype(str))
    ROADS.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ROADS, **out)
    record("road_graph", True, f"{len(lonlat):,} nodes, {len(u):,} edges from {len(g):,} OSM ways")
    return out


# ---------------------------------------------------------------- hospitals

def _nhfr():
    d = RAW / "nhfr"
    files = sorted([*d.glob("*.csv"), *d.glob("*.xlsx"), *d.glob("*.xls")]) if d.exists() else []
    if not files:
        return None
    f = files[-1]
    df = pd.read_csv(f, low_memory=False) if f.suffix == ".csv" else pd.read_excel(f)
    cols = {c.lower(): c for c in df.columns}
    lat = next((cols[c] for c in cols if "lat" in c), None)
    lon = next((cols[c] for c in cols if "lon" in c or "lng" in c), None)
    typ = next((cols[c] for c in cols if "type" in c and "major" not in c), None) or next((cols[c] for c in cols if "type" in c), None)
    name = next((cols[c] for c in cols if "name" in c and "facility" in c), None) or next((cols[c] for c in cols if "name" in c), None)
    if lat is None or lon is None:
        print(f"  WARNING NHFR file {f.name} has no latitude/longitude columns; using the fallback")
        return None
    df = df.rename(columns={lat: "lat", lon: "lon"})
    df["lat"], df["lon"] = pd.to_numeric(df.lat, errors="coerce"), pd.to_numeric(df.lon, errors="coerce")
    if typ is not None:
        df = df[df[typ].astype(str).str.contains("hospital", case=False)]
    df = df[df.lat.between(4, 22) & df.lon.between(116, 127.5)]
    return gpd.GeoDataFrame({"name": df[name] if name else "", "source": "nhfr"},
                            geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)


def load_hospitals():
    h = _nhfr()
    if h is not None and len(h):
        record("hospitals", True, f"NHFR: {len(h)} hospitals")
        record("nhfr", True, f"{len(h)} hospitals")  # clears an earlier 'missing' from a build before the file arrived
        return h, "nhfr"
    missing("nhfr", "NHFR manual download not in data/raw/nhfr/; using HOT OSM + NOAH facilities (fallback)")
    parts = []
    z = RAW / "hotosm_health" / "hotosm_phl_health_facilities_osm_gpkg.zip"
    if z.exists():
        import zipfile

        gp = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".gpkg"))
        o = gpd.read_file(f"zip://{z.as_posix()}!{gp}")
        o = o[(o.amenity == "hospital") | (o.get("healthcare") == "hospital")]
        o = o.assign(geometry=o.geometry.representative_point(), source="osm")[["name", "source", "geometry"]]
        parts.append(o.to_crs(4326))
    nf = RAW / "noah_facilities" / "hospitals.geojson"
    if nf.exists():
        n = gpd.read_file(nf)
        n = n[n.name.fillna("").str.contains(r"hospital|medical cent|medical center|infirmary", case=False)]
        parts.append(n.assign(source="noah")[["name", "source", "geometry"]].to_crs(4326))
    if not parts:
        return missing("hospitals", "no hospital source on disk"), None
    h = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    xy = _xy(h.geometry.x, h.geometry.y)
    pairs = cKDTree(xy).query_pairs(0.3)  # same facility in both sources: within 300 m
    drop = {max(p) for p in pairs}
    h = h.drop(index=list(drop)).reset_index(drop=True)
    record("hospitals", True, f"fallback: {len(h)} hospitals ({h.source.value_counts().to_dict()}), duplicates < 300 m dropped")
    return h, "osm+noah_fallback"


# ---------------------------------------------------------------- ferries

def load_ferries():
    f = RAW / "roroph" / "roro_routes.rda"
    if not have("roroph", f):
        return None
    import rdata

    rr = rdata.read_rda(f)["roro_routes"].reset_index(drop=True)  # data only; nautical_highway.R is never run
    rr["hours"] = rr.avg_time_hrs + np.minimum(12.0, 0.5 * 24.0 / rr.freq_daily.clip(lower=0.1))
    rr["geometry"] = [shapely.LineString([(a, b), (c, d)]) for a, b, c, d in zip(rr.from_lon, rr.from_lat, rr.to_lon, rr.to_lat)]
    return gpd.GeoDataFrame(rr, geometry="geometry", crs=4326)


# ---------------------------------------------------------------- network + solver

class Network:
    """Road + ferry graph with hospital and population attachments; `solve` gives hours to the nearest hospital."""

    def __init__(self, roads, ferries, hospitals, cells, speed_factor=1.0):
        self.r = roads
        self.n = len(roads["lon"])
        tree = cKDTree(_xy(roads["lon"], roads["lat"]))
        self.tree = tree
        # hospitals
        d, i = tree.query(_xy(hospitals.geometry.x, hospitals.geometry.y))
        ok = d <= MAX_SNAP_KM
        self.h_nodes = np.unique(i[ok])
        # population cells (WorldPop CRS is EPSG:4326)
        d, i = tree.query(_xy(cells.geometry.x, cells.geometry.y))
        self.c_node, self.c_walk = i, d / WALK_KMH
        self.c_road = d <= MAX_SNAP_KM
        # ferries
        self.ferries = ferries
        if ferries is not None:
            da, ia = tree.query(_xy(ferries.from_lon, ferries.from_lat))
            db, ib = tree.query(_xy(ferries.to_lon, ferries.to_lat))
            self.f_ok = (da <= 25) & (db <= 25) & (ia != ib)
            self.f_u, self.f_v = ia, ib
            self.f_hours = ferries.hours.to_numpy() + (da + db) / 30.0  # port access at 30 km/h
        self.speed_factor = speed_factor
        record("access_network", True, f"{len(self.h_nodes)} hospital nodes, {int(self.c_road.sum()):,}/{len(cells):,} cells "
                                        f"within {MAX_SNAP_KM:g} km of a road, {int(self.f_ok.sum()) if ferries is not None else 0} ferry routes snapped")

    def road_hours(self, speed_mult=None):
        s = self.r["speed"] * self.speed_factor
        if speed_mult is not None:
            s = s * speed_mult
        with np.errstate(divide="ignore"):
            return np.where(s > 0, self.r["km"] / s, np.inf)

    def solve(self, road_hours, ferry_keep=None):
        u, v, w = self.r["u"], self.r["v"], road_hours
        ok = np.isfinite(w)
        uu, vv, ww = [u[ok]], [v[ok]], [w[ok]]
        if self.ferries is not None:
            keep = self.f_ok if ferry_keep is None else (self.f_ok & ferry_keep)
            uu.append(self.f_u[keep]), vv.append(self.f_v[keep]), ww.append(self.f_hours[keep])
        u, v, w = np.concatenate(uu), np.concatenate(vv), np.concatenate(ww)
        a, b = np.minimum(u, v), np.maximum(u, v)
        order = np.lexsort((w, b, a))  # keep the fastest of parallel edges (csr would add them)
        a, b, w = a[order], b[order], w[order]
        first = np.r_[True, (a[1:] != a[:-1]) | (b[1:] != b[:-1])]
        a, b, w = a[first], b[first], np.maximum(w[first], 1e-7)
        g = sparse.csr_matrix((w, (a, b)), shape=(self.n, self.n))
        dist = dijkstra(g, directed=False, indices=self.h_nodes, min_only=True)
        t = dist[self.c_node] + self.c_walk
        return np.where(self.c_road, t, np.inf)


def cut_off(base, storm, ratio=2.0, extra_h=1.0):
    reach = np.isfinite(base)
    return reach & (~np.isfinite(storm) | ((storm >= ratio * base) & (storm - base > extra_h)))


# ---------------------------------------------------------------- storm effects

def ferry_keep_mask(ferries, swath_m, rule="crosses"):
    """True = route still sails. rule 'crosses': cancelled if the route line meets the swath; 'ports': if a port is in it."""
    if swath_m is None:
        return np.ones(len(ferries), bool)
    f = ferries.to_crs(CRS_M)
    if rule == "ports":
        a = gpd.GeoSeries(gpd.points_from_xy(ferries.from_lon, ferries.from_lat), crs=4326).to_crs(CRS_M)
        b = gpd.GeoSeries(gpd.points_from_xy(ferries.to_lon, ferries.to_lat), crs=4326).to_crs(CRS_M)
        return ~(a.intersects(swath_m).to_numpy() | b.intersects(swath_m).to_numpy())
    return ~f.intersects(swath_m).to_numpy()


def edges_in(swath_m, roads):
    if swath_m is None:
        return np.zeros(len(roads["u"]), bool)
    from pyproj import Transformer

    x, y = Transformer.from_crs(4326, CRS_M, always_xy=True).transform(roads["mid_lon"], roads["mid_lat"])
    shapely.prepare(swath_m)
    return shapely.contains_xy(swath_m, x, y)


def hazard_at(roads, rp="25yr"):
    """NOAH hazard class at each edge midpoint (255 = no map), from the national hazard raster."""
    import rasterio
    from .flood import hazard_raster_path

    p = hazard_raster_path(rp)
    if not p.exists():
        return None
    with rasterio.open(p) as r:
        rows, cols = rasterio.transform.rowcol(r.transform, roads["mid_lon"], roads["mid_lat"])
        rows, cols = np.asarray(rows), np.asarray(cols)
        out = np.full(len(rows), 255, "uint8")
        ok = (rows >= 0) & (rows < r.height) & (cols >= 0) & (cols < r.width)
        # read in row bands to keep memory bounded
        for r0 in range(0, r.height, 4096):
            m = ok & (rows >= r0) & (rows < r0 + 4096)
            if m.any():
                band = r.read(1, window=rasterio.windows.Window(0, r0, r.width, min(4096, r.height - r0)))
                out[m] = band[rows[m] - r0, cols[m]]
    return out


def road_multiplier(roads, in_swath, haz=None, observed=None, slow=0.5):
    """Speed multiplier per edge: 0 = cut. observed (bool per edge) wins; else NOAH proxy inside the swath."""
    mult = np.ones(len(roads["u"]))
    if observed is not None:
        mult[observed] = 0.0
        return mult, "observed"
    if haz is None:
        return mult, "none"
    mult[in_swath & (haz == 3)] = 0.0
    mult[in_swath & (haz == 2)] = slow
    return mult, "noah_25yr_proxy"


# ---------------------------------------------------------------- raster method (MAP friction)

FRICTION = RAW / "map_friction" / "friction_surface_2019_motorized_phl.tif"
# MAP encodes open sea as this constant, not nodata (finding 15): 3.16 min/km motorised. Sea cells (this value and
# outside every unit polygon, all_touched) are impassable except along the RoRo routes; cells inside a unit polygon keep
# MAP's value whatever it is (coastal mixed cells, lakes).
SEA_MIN_PER_M = 0.00316
RASTER_SNAP_KM = 3.0  # a population cell whose centre falls on an impassable (sea) cell uses the nearest land cell


class FrictionGrid:
    """Raster access method: cost-distance from hospitals over the MAP motorised friction surface 2019 (~1 km).

    Cost per cell = friction (min/m) x cell size (geometric mean of the cell's E-W and N-S metres at its latitude), in
    hours; skimage's MCP_Geometric walks 8-connected (diagonals x sqrt 2). Ferries: each RoRo route is drawn as a
    straight line of grid cells between its ports; its sea cells get cost = (crossing + half headway hours, as in the
    network) / the line's 8-connected length, so a full crossing costs about the same as in the network. A storm
    cancels the same routes as the network (`ferry_keep`), which closes their sea cells again. Flooded land cells are
    impassable and slowed cells cost 1/slow times more (`mult`, as `road_multiplier` for road edges), so the raster gets
    the same storm rules as the roads, evaluated at cell centres. Population cells map to the friction cell under their
    centre (the nearest land cell within RASTER_SNAP_KM if that one is sea); there is no walking leg, and people whose
    own cell is flooded are cut off.
    """

    def __init__(self, units, hospitals, cells, ferries=None, ferry_ok=None):
        import rasterio
        from rasterio import features
        from skimage.draw import line

        with rasterio.open(FRICTION) as r:
            fr = r.read(1).astype("float64")
            self.T, nd = r.transform, r.nodata
        H, W = fr.shape
        self.shape = (H, W)
        land = features.rasterize(((g, 1) for g in units.to_crs(4326).geometry), out_shape=fr.shape, transform=self.T,
                                  fill=0, all_touched=True, dtype="uint8").astype(bool)
        bad = (fr == nd) | ~np.isfinite(fr) | (fr <= 0)
        sea = (np.isclose(fr, SEA_MIN_PER_M, rtol=0, atol=1e-7) & ~land) | bad
        lat = self.T.f + self.T.e * (np.arange(H) + 0.5)
        cell_m = abs(self.T.a) * 111320.0 * np.sqrt(np.cos(np.radians(lat)))
        cost = fr * cell_m[:, None] / 60.0  # hours to cross one cell
        cost[sea] = -1.0  # MCP: negative = impassable
        self.cost0 = cost.ravel()
        self.land_idx = np.flatnonzero(~sea.ravel())  # passable land cells: storm rules are evaluated at their centres
        rr, cc = np.divmod(self.land_idx, W)
        self.lon, self.lat = (np.asarray(v) for v in rasterio.transform.xy(self.T, rr, cc))
        # ferries: sea cells of each route line, and their per-cell cost
        self.f_cells, self.f_cost = [], []
        if ferries is not None:
            ok = np.ones(len(ferries), bool) if ferry_ok is None else np.asarray(ferry_ok)
            r0, c0 = rasterio.transform.rowcol(self.T, ferries.from_lon, ferries.from_lat)
            r1, c1 = rasterio.transform.rowcol(self.T, ferries.to_lon, ferries.to_lat)
            for i, (a, b, c, d, h) in enumerate(zip(r0, c0, r1, c1, ferries.hours)):
                lr, lc = line(int(a), int(b), int(c), int(d))
                m = (lr >= 0) & (lr < H) & (lc >= 0) & (lc < W)
                idx = lr[m] * W + lc[m]
                idx = idx[sea.ravel()[idx]]
                dr, dc = abs(int(c) - int(a)), abs(int(d) - int(b))
                L = max(dr, dc) + (np.sqrt(2) - 1) * min(dr, dc)
                self.f_cells.append(idx if ok[i] else idx[:0])
                self.f_cost.append(float(h) / max(L, 1.0))
        # hospitals and population cells
        hr, hc = (np.asarray(v) for v in rasterio.transform.rowcol(self.T, hospitals.geometry.x, hospitals.geometry.y))
        inside = (hr >= 0) & (hr < H) & (hc >= 0) & (hc < W)
        self.h_idx = np.unique(hr[inside] * W + hc[inside])
        cr, cc = rasterio.transform.rowcol(self.T, cells.geometry.x, cells.geometry.y)
        c_idx = np.clip(np.asarray(cr), 0, H - 1) * W + np.clip(np.asarray(cc), 0, W - 1)
        on_sea = sea.ravel()[c_idx]
        self.c_ok = np.ones(len(c_idx), bool)
        if on_sea.any():
            tree = cKDTree(_xy(self.lon, self.lat))
            d, j = tree.query(_xy(cells.geometry.x.to_numpy()[on_sea], cells.geometry.y.to_numpy()[on_sea]))
            c_idx[on_sea] = self.land_idx[j]
            self.c_ok[np.flatnonzero(on_sea)[d > RASTER_SNAP_KM]] = False
        self.c_idx = c_idx
        self.haz = None
        self.n_snapped = int(on_sea.sum())
        record("map_friction", True, f"{FRICTION.name}: {len(self.land_idx):,} passable land cells, {len(self.h_idx)} "
                                     f"hospital cells, {self.n_snapped} population cells snapped off sea, "
                                     f"{sum(len(c) > 0 for c in self.f_cells)} ferry lines")

    def hazard(self, rp="25yr"):
        """NOAH hazard class at the centre of every passable land cell (255 = no map; None without the raster)."""
        if self.haz is None:
            self.haz = hazard_at({"mid_lon": self.lon, "mid_lat": self.lat}, rp)
        return self.haz

    def in_swath(self, swath_m):
        return edges_in(swath_m, {"u": self.lon, "mid_lon": self.lon, "mid_lat": self.lat})

    def solve(self, mult=None, ferry_keep=None, speed_factor=1.0):
        """Hours to the nearest hospital per population cell (inf = no route). mult: speed multiplier per passable land
        cell (0 = impassable), as `road_multiplier` gives for road edges; ferry_keep: True = route still sails."""
        from skimage.graph import MCP_Geometric

        cost = self.cost0.copy()
        land = cost[self.land_idx]
        if mult is not None:
            land = np.where(mult > 0, land / np.where(mult > 0, mult, 1.0), -1.0)
        cost[self.land_idx] = np.where(land > 0, land / speed_factor, -1.0)
        for i, (idx, c) in enumerate(zip(self.f_cells, self.f_cost)):
            if len(idx) and (ferry_keep is None or ferry_keep[i]):
                cur = cost[idx]
                cost[idx] = np.where(cur > 0, np.minimum(cur, c / speed_factor), c / speed_factor)
        starts = self.h_idx[cost[self.h_idx] > 0]  # a hospital in a flooded cell is not a start
        if not len(starts):  # every hospital flooded: nobody has a route
            return np.full(len(self.c_idx), np.inf)
        acc, _ = MCP_Geometric(cost.reshape(self.shape)).find_costs(np.c_[np.divmod(starts, self.shape[1])])
        t = acc.ravel()[self.c_idx]
        return np.where(self.c_ok & np.isfinite(t), t, np.inf)


def friction_grid(units, hospitals, cells, ferries=None, ferry_ok=None):
    """FrictionGrid, or None (recorded as missing) if the MAP friction GeoTIFF is not on disk."""
    if not FRICTION.exists():
        return missing("map_friction", f"{FRICTION.name} not found (needs scripts/download_gee.py map_friction)")
    return FrictionGrid(units, hospitals, cells, ferries, ferry_ok)


# ---------------------------------------------------------------- summaries

def summarise(cells, base, storm, cut, level="unit_id"):
    c = pd.DataFrame({level: cells[level].to_numpy(), "pop": cells["pop"].to_numpy(), "base": base, "storm": storm, "cut": cut})
    c["no_access_base"] = ~np.isfinite(c.base)
    fin = np.isfinite(c.base)
    g = c.groupby(level)
    out = pd.DataFrame({
        "pop": g["pop"].sum(),
        "pop_cut": c[c.cut].groupby(level)["pop"].sum(),
        "pop_no_access_base": c[c.no_access_base].groupby(level)["pop"].sum(),
        "base_hours": c[fin].assign(w=lambda d: d.base * d["pop"]).groupby(level).w.sum() / c[fin].groupby(level)["pop"].sum(),
    }).fillna({"pop_cut": 0, "pop_no_access_base": 0})
    out["A"] = out.pop_cut / out["pop"]
    return out.reset_index()
