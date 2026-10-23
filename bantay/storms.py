"""IBTrACS tracks: gale radius with fallbacks, swath buffers, shifted tracks and unit-week storm exposure.

Gale radius per fix (finding 8: USA_R34 is missing on 15-58% of fixes of the backtest storms):
  1. USA_R34: max of the four quadrants (34-kt radius, nm)
  2. TOKYO_R30_LONG: JMA 30-kt radius, long axis (nm); slightly larger than a 34-kt radius
  3. a fixed radius (default 150 km), a sensitivity parameter
The source used is kept per fix (`r_source`) so outputs can say how much of a swath is a fallback.
"""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import unary_union

from .config import RAW, STORMS, CRS_M, week_ending, missing, record

NM_KM = 1.852
IBTRACS = RAW / "ibtracs" / "ibtracs.WP.list.v04r01.csv"
R34 = ["USA_R34_NE", "USA_R34_SE", "USA_R34_SW", "USA_R34_NW"]
COLS = ["SID", "SEASON", "NAME", "ISO_TIME", "NATURE", "LAT", "LON", "USA_WIND", "WMO_WIND", "TOKYO_WIND",
        "TOKYO_R30_LONG", "DIST2LAND", "TRACK_TYPE"] + R34


def load_ibtracs(seasons=(2016, 2020), bbox=(105, -5, 140, 30)):
    if not IBTRACS.exists():
        return missing("ibtracs", f"{IBTRACS} not found")
    ib = pd.read_csv(IBTRACS, skiprows=[1], usecols=COLS, low_memory=False, na_values=[" ", ""])
    ib = ib[ib.SEASON.between(*seasons) & ib.LON.between(bbox[0], bbox[2]) & ib.LAT.between(bbox[1], bbox[3])].copy()
    ib = ib[ib.TRACK_TYPE == "main"]
    ib["time"] = pd.to_datetime(ib.ISO_TIME)
    ib["wind_kt"] = ib.USA_WIND.fillna(ib.WMO_WIND).fillna(ib.TOKYO_WIND)
    record("ibtracs", True, f"{ib.SID.nunique()} storms {seasons[0]}-{seasons[1]}")
    return ib.drop(columns=["ISO_TIME"]).reset_index(drop=True)


def gale_radius(tr, fixed_km=150.0):
    """Adds radius_km and r_source to a track frame (see module docstring)."""
    tr = tr.copy()
    usa = tr[R34].max(axis=1, skipna=True)
    jma = tr["TOKYO_R30_LONG"]
    tr["radius_km"] = np.where(usa.notna() & (usa > 0), usa * NM_KM, np.where(jma.notna() & (jma > 0), jma * NM_KM, fixed_km))
    tr["r_source"] = np.where(usa.notna() & (usa > 0), "USA_R34", np.where(jma.notna() & (jma > 0), "TOKYO_R30", f"fixed_{fixed_km:g}km"))
    # below gale strength there is no gale radius: keep the fixes but with no swath
    weak = tr.wind_kt.notna() & (tr.wind_kt < 34)
    tr.loc[weak, "radius_km"] = 0.0
    tr.loc[weak, "r_source"] = "below_gale"
    return tr


def storm_track(key=None, sid=None, ib=None):
    """Track of a backtest storm (key in config.STORMS) or any SID."""
    ib = load_ibtracs() if ib is None else ib
    if ib is None:
        return None
    if key is not None:
        s = STORMS[key]
        tr = ib[(ib.NAME == s["name"]) & (ib.SEASON == s["season"])]
    else:
        tr = ib[ib.SID == sid]
    return tr.sort_values("time").reset_index(drop=True)


def shift_track(tr, dlat=0.0, dlon=0.0, dhours=0.0):
    """A shifted variant of a track: same intensity and radii, displaced in space and time."""
    out = tr.copy()
    out["LAT"] = out.LAT + dlat
    out["LON"] = out.LON + dlon
    out["time"] = out.time + pd.Timedelta(hours=dhours)
    return out


def interpolate(tr, hours=1):
    """Linear interpolation of position and radius to a regular time step (IBTrACS fixes are 3-hourly)."""
    t = tr.set_index("time")[["LAT", "LON", "radius_km", "wind_kt"]].astype(float)
    t = t[~t.index.duplicated()]
    grid = pd.date_range(t.index.min(), t.index.max(), freq=f"{hours}h")
    return t.reindex(t.index.union(grid)).interpolate("time").reindex(grid).reset_index(names="time")


def swath(tr, fixed_km=150.0, t0=None, t1=None):
    """Union of gale-radius circles along the (hourly interpolated) track, in EPSG:32651. None if no gale."""
    tr = gale_radius(tr, fixed_km)
    if t0 is not None:
        tr = tr[(tr.time >= t0) & (tr.time <= t1)]
    if tr.empty:
        return None
    it = interpolate(tr)
    it = it[it.radius_km > 0]
    if it.empty:
        return None
    pts = gpd.GeoSeries(gpd.points_from_xy(it.LON, it.LAT), crs=4326).to_crs(CRS_M)
    return unary_union([p.buffer(r * 1000, 16) for p, r in zip(pts, it.radius_km)])


def track_line(tr):
    return LineString(zip(tr.LON, tr.LAT)) if len(tr) > 1 else Point(tr.LON.iloc[0], tr.LAT.iloc[0])


def unit_week_exposure(units, ib=None, fixed_km=150.0, near_km=300.0):
    """Storm exposure per harmonised unit and DOH week, from every WP track in the window.

    units: GeoDataFrame with unit_id + geometry. Returns unit_id, week, storm_min_dist_km (nearest fix to the unit
    polygon), storm_gale_hit (unit polygon inside any gale swath that week), storm_max_wind_near_kt (max wind of fixes
    within `near_km`), storm_n (distinct storms within `near_km`).
    """
    ib = load_ibtracs() if ib is None else ib
    if ib is None:
        return None
    ib = gale_radius(ib, fixed_km)
    u = units.to_crs(CRS_M)[["unit_id", "geometry"]].reset_index(drop=True)
    pts = gpd.GeoDataFrame(ib, geometry=gpd.points_from_xy(ib.LON, ib.LAT), crs=4326).to_crs(CRS_M)
    # only fixes that can matter: within near_km of PHL
    land = u.union_all().simplify(2000)
    pts = pts[pts.distance(land) <= near_km * 1000].copy()
    pts["week"] = week_ending(pts.time).values
    rows = []
    for i, geom in enumerate(u.geometry):
        d = pts.distance(geom) / 1000  # km from fix to the unit polygon (0 inside)
        near = pts.assign(d=d.values)
        near["hit"] = near.d <= near.radius_km
        g = near.groupby("week")
        df = pd.DataFrame({
            "storm_min_dist_km": g.d.min(),
            "storm_gale_hit": g.hit.max().astype(int),
            "storm_max_wind_near_kt": near[near.d <= near_km].groupby("week").wind_kt.max(),
            "storm_n": near[near.d <= near_km].groupby("week").SID.nunique(),
        })
        df["unit_id"] = u.unit_id.iloc[i]
        rows.append(df.reset_index())
    out = pd.concat(rows, ignore_index=True)
    out["storm_max_wind_near_kt"] = out.storm_max_wind_near_kt.fillna(0)
    out["storm_n"] = out.storm_n.fillna(0).astype(int)
    return out


def origin_exposure(units, ib, origin, fixed_km=150.0, near_km=300.0, weeks=4):
    """The forecast's storm features at `origin` (storm_gale_4w, storm_wind_4w, storm_dist_4w), computed exactly as the
    panel and forecast.base_features compute them: unit_week_exposure over every fix in `ib` whose DOH week is one of
    the `weeks` weeks ending at `origin`. Pass an `ib` with one storm's fixes moved to score a shifted track: the other
    storms' fixes and every rule stay as in training, and fixes after the origin week are never used."""
    origin = pd.Timestamp(origin)
    wk = week_ending(ib.time)
    sub = ib[(wk > origin - pd.Timedelta(weeks=weeks)) & (wk <= origin)]
    out = units[["unit_id"]].reset_index(drop=True).copy()
    ex = unit_week_exposure(units, sub, fixed_km, near_km) if len(sub) else None
    if ex is None or ex.empty:
        return out.assign(storm_gale_4w=0.0, storm_wind_4w=0.0, storm_dist_4w=2000.0)
    g = ex.groupby("unit_id")
    out["storm_gale_4w"] = out.unit_id.map(g.storm_gale_hit.max()).fillna(0).astype(float)
    out["storm_wind_4w"] = out.unit_id.map(g.storm_max_wind_near_kt.max()).fillna(0).astype(float)
    out["storm_dist_4w"] = out.unit_id.map(g.storm_min_dist_km.min()).fillna(2000.0)  # panel: weeks with no fix = 2000
    return out


def shift_storm(ib, key, dlat=0.0, dlon=0.0):
    """IBTrACS fixes with one backtest storm (key in config.STORMS) displaced; every other storm unchanged."""
    s = STORMS[key]
    m = (ib.NAME == s["name"]) & (ib.SEASON == s["season"])
    out = ib.copy()
    out.loc[m, "LAT"] = out.loc[m, "LAT"] + dlat
    out.loc[m, "LON"] = out.loc[m, "LON"] + dlon
    return out
