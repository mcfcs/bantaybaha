"""Layer 1 flood exposure: NOAH hazard (static), Copernicus EMS and Sentinel-1 (observed, per typhoon).

NOAH (finding 6): per-province shapefiles, 5/25-year, hazard classes Var 1-3 (low/medium/high). They are rasterised onto
the WorldPop 100 m grid as one national raster per return period: 255 = no map for this area, 0 = mapped, no hazard,
1-3 = hazard class. Units without a map get NaN hazard shares (never 0).

Sentinel-1 (before/after change detection in the UN-SPIDER workflow, with a dB-difference rule instead of its ratio;
scripts/download_gee.py `s1_flood`): uint8 tiles per typhoon, 1 = new flood,
0 = not flooded, 255 = no data. EMS EMSR312 gives observed flood polygons for 6 Northern Luzon AOIs (Ompong only).
"""

import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.windows import from_bounds, Window
from rasterio.warp import reproject, Resampling

from .config import RAW, INTERIM, STORMS, have, missing, record
from .grids import WORLDPOP, UNIT_RASTER, unit_index, iter_blocks, worldpop_clean, fresh
from .units import read_adm, read_crosswalk, ADM2_XW, UNITS_GPKG

NOAH = RAW / "noah"
EMS = RAW / "copernicus_ems"
S1 = RAW / "s1_flood"
RPS = ("5yr", "25yr")


def hazard_raster_path(rp):
    return INTERIM / f"noah_{rp}_hazard_100m.tif"


# ---------------------------------------------------------------- NOAH file -> units

def _nk(s):
    return re.sub(r"[^A-Z]", "", re.sub(r"\(.*?\)", "", s.upper()))


def noah_file_units(adm2, xw2):
    """{zip path: [unit_id, ...]} for every NOAH zip, by shapefile name or old 9-digit PSGC (notebook section 8)."""
    a2n = {_nk(n): [n] for n in adm2.adm2_name} | {_nk(n.split("(")[1]): [n] for n in adm2.adm2_name if "(" in n and "not a" not in n}
    a2n |= {"MAGUINDANAO": [n for n in adm2.adm2_name if n.startswith("Maguindanao")],
            "MINDORO": ["Occidental Mindoro", "Oriental Mindoro"],
            "METROMANILA": [n for n in adm2.adm2_name if n.startswith("Metropolitan Manila")]}
    by_pc = dict(zip(adm2.adm2_pcode, adm2.adm2_name))
    to_unit = dict(zip(xw2.adm2_name, xw2.unit_id))
    out, unmatched = {}, []
    for rp in RPS:
        for z in sorted((NOAH / rp).glob("*.zip")):
            names = set()
            for st in (Path(n).stem for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp")):
                pc = re.match(r"PH(\d{2})(\d{2})\d{5}", st)
                if pc and f"PH{pc[1]}0{pc[2]}" in by_pc:
                    names.add(by_pc[f"PH{pc[1]}0{pc[2]}"])
                else:
                    got = a2n.get(_nk(re.split(r"_(?:Flood|FH)", st)[0]))
                    names |= set(got) if got else set()
                    if not got:
                        unmatched.append(f"{rp}/{z.name}:{st}")
            out[z] = sorted({to_unit[n] for n in names if n in to_unit})
    if unmatched:
        print(f"  WARNING NOAH shapefiles not matched to a unit ({len(unmatched)}):", unmatched[:10])
    return out


def _hazard_col(g):
    return next(c for c in g.columns if c.lower() in ("var", "haz", "hazard", "class", "gridcode"))


def build_hazard_raster(units, rp, force=False):
    """National NOAH hazard raster for one return period on the WorldPop grid (see module docstring)."""
    out = hazard_raster_path(rp)
    zips = sorted((NOAH / rp).glob("*.zip"))
    if not zips:
        return missing(f"noah_{rp}", f"no NOAH {rp} zips in {NOAH / rp}")
    record(f"noah_{rp}", True, f"{len(zips)} zips")
    if not force and fresh(out, *zips, UNITS_GPKG):  # coverage is rasterised from the unit polygons too
        return out
    if not have("worldpop", WORLDPOP):
        return None
    adm2, xw2 = read_adm(2, geometry=False), read_crosswalk(ADM2_XW)
    cover = noah_file_units(adm2, xw2)
    ug = units.set_index("unit_id").geometry
    with rasterio.open(WORLDPOP) as src:
        prof = src.profile | dict(dtype="uint8", nodata=None, count=1, compress="lzw", tiled=True, blockxsize=512, blockysize=512)
        crs, T, H, W = src.crs, src.transform, src.height, src.width
    tmp = out.with_suffix(".part.tif")
    with rasterio.open(tmp, "w+", **prof) as dst:  # w+: windows are read back and merged
        for r0 in range(0, H, 2048):  # start as "no map"
            h = min(2048, H - r0)
            dst.write(np.full((h, W), 255, "uint8"), 1, window=Window(0, r0, W, h))
        for z in zips:
            uids = cover.get(z, [])
            if not uids:
                continue
            cov_geom = ug.loc[uids].to_crs(crs)
            minx, miny, maxx, maxy = cov_geom.total_bounds
            win = from_bounds(minx, miny, maxx, maxy, T).round_offsets().round_lengths()
            win = win.intersection(Window(0, 0, W, H))
            wt = rasterio.windows.transform(win, T)
            shape = (int(win.height), int(win.width))
            cov = features.rasterize(((g, 1) for g in cov_geom), out_shape=shape, transform=wt, fill=0, dtype="uint8").astype(bool)
            haz = np.zeros(shape, "uint8")
            for shp in (n for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp")):
                g = gpd.read_file(f"zip://{z.as_posix()}!{shp}")
                if g.empty:
                    continue
                col = _hazard_col(g)
                g = g[g[col].between(1, 3)].to_crs(crs).sort_values(col)
                h = features.rasterize(((geom, int(v)) for geom, v in zip(g.geometry, g[col])), out_shape=shape,
                                       transform=wt, fill=0, dtype="uint8")
                haz = np.maximum(haz, h)
            cur = dst.read(1, window=win)
            cur = np.where(cov, np.maximum(np.where(cur == 255, 0, cur), haz), cur)
            dst.write(cur, 1, window=win)
            print(f"    {rp} {z.name}: units {uids}")
    tmp.replace(out)
    return out


def unit_hazard_shares(units, min_cover=0.5):
    """Share of each unit's population in NOAH hazard (any class / high class) per return period. NaN = no map."""
    if not UNIT_RASTER.exists():
        return None
    inv = {v: k for k, v in unit_index(units).items()}
    n = len(inv) + 1
    res = pd.DataFrame({"unit_id": [inv[i] for i in range(1, n)]})
    with rasterio.open(WORLDPOP) as s:
        nd = s.nodata
    for rp in RPS:
        p = hazard_raster_path(rp)
        if not p.exists():
            res[[f"hazard_any_{rp}", f"hazard_high_{rp}", f"hazard_cover_{rp}"]] = np.nan
            continue
        tot, cov, anyh, high = (np.zeros(n) for _ in range(4))
        for _, (pop, uid, hz) in iter_blocks(WORLDPOP, UNIT_RASTER, p):
            pop = worldpop_clean(pop, nd).ravel()
            uid, hz = uid.ravel(), hz.ravel()
            tot += np.bincount(uid, pop, n)
            cov += np.bincount(uid, pop * (hz != 255), n)
            anyh += np.bincount(uid, pop * ((hz >= 1) & (hz <= 3)), n)
            high += np.bincount(uid, pop * (hz == 3), n)
        with np.errstate(invalid="ignore", divide="ignore"):
            cf = cov[1:] / tot[1:]
            ok = cf >= min_cover
            res[f"hazard_any_{rp}"] = np.where(ok, anyh[1:] / cov[1:], np.nan)
            res[f"hazard_high_{rp}"] = np.where(ok, high[1:] / cov[1:], np.nan)
            res[f"hazard_cover_{rp}"] = cf
    n_map = res["hazard_any_25yr"].notna().sum() if "hazard_any_25yr" in res else 0
    record("noah_hazard_shares", n_map > 0, f"{n_map}/{len(res)} units have a 25-yr hazard share (others NaN = no map)")
    return res


# ---------------------------------------------------------------- Copernicus EMS (observed, Ompong only)

def ems_observed_flood(activation="EMSR312", record_status=True):
    """Observed-flood polygons (EPSG:4326) from the EMS delineation packages; None if absent. record_status=False for
    readers outside the build (the documents), so reading never rewrites data/processed/status.json."""
    zs = sorted((EMS / activation).glob("*DELINEATION*.zip"))
    if not zs:
        return missing(f"ems_{activation}", f"no {activation} delineation zips in {EMS / activation}") if record_status else None
    out = []
    for z in zs:
        for n in zipfile.ZipFile(z).namelist():
            if re.search(r"observed.?event", n, re.I) and n.endswith((".shp", ".json", ".geojson")):
                g = gpd.read_file(f"zip://{z.as_posix()}!{n}").to_crs(4326)
                g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
                g["product"] = "MONIT01" if "MONIT" in z.name else "MAP"
                out.append(g[["product", "geometry"]])
    if not out:
        return missing(f"ems_{activation}", "no observedEvent layer in the delineation packages") if record_status else None
    if record_status:
        record(f"ems_{activation}", True, f"{len(zs)} packages")
    return gpd.GeoDataFrame(pd.concat(out, ignore_index=True), crs=4326)


# ---------------------------------------------------------------- Sentinel-1 (observed, from GEE)

def s1_tiles(storm):
    d = S1 / STORMS[storm]["gee"]
    return sorted(d.glob("*.tif")) if d.exists() else []


def _tile_cell(path):
    """Nominal 1-degree cell (left, bottom, right, top) of an S1 tile named like s1flood_121E_17N.tif, else None."""
    m = re.search(r"_(\d+)E_(\d+)N", Path(path).stem)
    return (int(m[1]), int(m[2]), int(m[1]) + 1, int(m[2]) + 1) if m else None


def _s1_zone_sums(tiles, zone_raster, n, crop=False):
    """Observed (seen), flooded pixel counts and flooded WorldPop people per zone code (0..n-1) of `zone_raster`
    (unit or ADM3 codes on the WorldPop grid), over the S1 tiles of one storm resampled to that grid (nearest).
    crop: read each tile only over its nominal 1-degree cell. The tiles are 1115 px of 0.000898 deg, so neighbours
    overlap by ~2 WorldPop pixels and the uncropped sums count those strips twice (s1_unit_flood keeps that, the panel
    was built with it; the overlap is ~0.3% of a tile)."""
    seen, flooded, pop_fl = np.zeros(n), np.zeros(n), np.zeros(n)
    with rasterio.open(WORLDPOP) as sp, rasterio.open(zone_raster) as su:
        for t in tiles:
            with rasterio.open(t) as st:
                b = st.bounds
                if crop and _tile_cell(t):
                    l, bo, r, to = _tile_cell(t)
                    b = (max(b.left, l), max(b.bottom, bo), min(b.right, r), min(b.top, to))
                win = from_bounds(*b, sp.transform).round_offsets().round_lengths().intersection(Window(0, 0, sp.width, sp.height))
                wt = rasterio.windows.transform(win, sp.transform)
                fl = np.full((int(win.height), int(win.width)), 255, "uint8")
                reproject(st.read(1), fl, src_transform=st.transform, src_crs=st.crs, dst_transform=wt, dst_crs=sp.crs,
                          resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
            pop = worldpop_clean(sp.read(1, window=win), sp.nodata).ravel()
            uid = su.read(1, window=win).ravel()
            fl = fl.ravel()
            seen += np.bincount(uid, (fl != 255).astype(float), n)
            flooded += np.bincount(uid, (fl == 1).astype(float), n)
            pop_fl += np.bincount(uid, pop * (fl == 1), n)
    return seen, flooded, pop_fl


def s1_unit_flood(units, storm):
    """Per unit: flooded fraction of observed land and flooded population, from the S1 tiles of one storm."""
    tiles = s1_tiles(storm)
    if not tiles:
        return missing(f"s1_flood_{storm}", f"no Sentinel-1 flood tiles in {S1 / STORMS[storm]['gee']} (needs GEE)")
    if not UNIT_RASTER.exists() or not WORLDPOP.exists():
        return missing(f"s1_flood_{storm}", "WorldPop / unit raster needed to aggregate S1 flood")
    n = len(unit_index(units)) + 1
    seen, flooded, pop_fl = _s1_zone_sums(tiles, UNIT_RASTER, n)
    inv = {v: k for k, v in unit_index(units).items()}
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(seen[1:] > 0, flooded[1:] / seen[1:], np.nan)
    record(f"s1_flood_{storm}", True, f"{len(tiles)} tiles")
    return pd.DataFrame({"unit_id": [inv[i] for i in range(1, n)], "s1_flood_frac": frac,
                         "s1_flood_pop": np.where(seen[1:] > 0, pop_fl[1:], np.nan), "storm": storm})


def s1_adm3_flood(adm3, storms=None):
    """Layer 1 per municipality: for each storm with S1 tiles, the flooded share of observed land (s1_flood_frac),
    people in observed new flood (s1_flood_pop, WorldPop 2020) and the share of the municipality's land the radar
    observed (seen_frac; NaN fractions / populations where it saw none). Same tiles, grid and rules as s1_unit_flood,
    on the ADM3 raster, with each tile cropped to its 1-degree cell so overlapping tile edges are counted once.
    adm3: polygons with adm3_pcode, adm3_name, unit_id (units.adm3_with_units)."""
    from .grids import build_adm3_raster, adm3_index

    storms = list(STORMS) if storms is None else storms
    todo = {k: s1_tiles(k) for k in storms}
    if not any(todo.values()):
        return missing("s1_adm3", "no Sentinel-1 flood tiles on disk")
    zr = build_adm3_raster(adm3)
    if zr is None or not WORLDPOP.exists():
        return missing("s1_adm3", "WorldPop / ADM3 raster needed to aggregate S1 flood per municipality")
    code = adm3_index(adm3)
    n = len(code) + 1
    total = np.zeros(n)
    for _, (z,) in iter_blocks(zr):
        total += np.bincount(z.ravel(), minlength=n)
    inv = {v: k for k, v in code.items()}
    meta = adm3.drop_duplicates("adm3_pcode").set_index("adm3_pcode")
    rows = []
    for storm, tiles in todo.items():
        if not tiles:
            missing(f"s1_flood_{storm}", f"no Sentinel-1 flood tiles in {S1 / STORMS[storm]['gee']} (needs GEE)")
            continue
        seen, flooded, pop_fl = _s1_zone_sums(tiles, zr, n, crop=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            pc = [inv[i] for i in range(1, n)]
            rows.append(pd.DataFrame({
                "storm": storm, "adm3_pcode": pc, "adm3_name": meta.adm3_name.reindex(pc).to_numpy(),
                "unit_id": meta.unit_id.reindex(pc).to_numpy(),
                "s1_flood_frac": np.where(seen[1:] > 0, flooded[1:] / seen[1:], np.nan),
                "s1_flood_pop": np.where(seen[1:] > 0, pop_fl[1:], np.nan),
                "seen_frac": np.where(total[1:] > 0, seen[1:] / total[1:], np.nan)}))
    out = pd.concat(rows, ignore_index=True)
    record("s1_adm3", True, f"{out.storm.nunique()} storms x {out.adm3_pcode.nunique()} municipalities")
    return out


def s1_flood_lookup(storm):
    """Callable (x, y arrays in EPSG:4326) -> 1 flooded / 0 not / 255 no data, over the S1 tiles of a storm."""
    tiles = s1_tiles(storm)
    if not tiles:
        return None
    grids = []
    for t in tiles:  # tiles are small (~1 Mpx uint8): read once, then index with array maths
        with rasterio.open(t) as s:
            grids.append((s.bounds, ~s.transform, s.read(1)))

    def lookup(xs, ys):
        xs, ys = np.asarray(xs), np.asarray(ys)
        out = np.full(len(xs), 255, "uint8")
        for b, inv, a in grids:
            m = (xs >= b.left) & (xs < b.right) & (ys > b.bottom) & (ys <= b.top) & (out == 255)
            if m.any():
                cols, rows = inv * (xs[m], ys[m])
                rows = np.clip(rows.astype(int), 0, a.shape[0] - 1)
                cols = np.clip(cols.astype(int), 0, a.shape[1] - 1)
                out[m] = a[rows, cols]
        return out

    return lookup
