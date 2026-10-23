"""Downstream rainfall routing on HydroRIVERS (Australasia file, finding 13).

For each reach, local weekly rain (CHIRPS cell at the reach) times its own catchment area is accumulated downstream;
dividing by the upstream area gives the upstream-mean rainfall that reaches that point. A unit's feature
`river_up_7d` is the discharge-weighted mean of that over the reaches inside it, so a river-mouth province "feels"
rain that fell upstream. `river_excess_7d` = river_up_7d minus the unit's own area-mean rain.
"""

import numpy as np
import pandas as pd
import geopandas as gpd

from .config import RAW, BBOX, have

HR_ZIP = RAW / "hydrorivers" / "HydroRIVERS_v10_au_shp.zip"
HR_LAYER = "HydroRIVERS_v10_au_shp/HydroRIVERS_v10_au.shp"


def load_reaches(units):
    """PHL reaches with the unit they fall in (by representative point; coastal stubs to the nearest unit)."""
    if not have("hydrorivers", HR_ZIP):
        return None
    hr = gpd.read_file(f"zip://{HR_ZIP.as_posix()}!{HR_LAYER}", bbox=BBOX,
                       columns=["HYRIV_ID", "NEXT_DOWN", "CATCH_SKM", "UPLAND_SKM", "DIS_AV_CMS", "ORD_STRA"])
    pts = gpd.GeoDataFrame(hr.drop(columns="geometry"), geometry=hr.geometry.representative_point(), crs=hr.crs)
    u = units[["unit_id", "geometry"]].to_crs(hr.crs)
    j = gpd.sjoin(pts, u, how="left", predicate="within").drop(columns="index_right")
    j = j[~j.index.duplicated()]
    out = j[j.unit_id.notna()]
    rest = j[j.unit_id.isna()].drop(columns="unit_id")
    if len(rest):  # reach points just off a simplified coastline: nearest unit within ~2 km
        near = gpd.sjoin_nearest(rest.to_crs(3857), u.to_crs(3857), how="inner", max_distance=2000).drop(columns="index_right")
        near = near[~near.index.duplicated()].to_crs(hr.crs)
        out = pd.concat([out, near])
    return out.sort_values("UPLAND_SKM").reset_index(drop=True)


def accumulate(reaches, local):
    """local: (n_reach, n_t) rain in mm, reaches sorted by UPLAND_SKM (upstream first). Returns upstream-mean mm."""
    vol = local * reaches.CATCH_SKM.to_numpy()[:, None]
    pos = pd.Series(np.arange(len(reaches)), index=reaches.HYRIV_ID.to_numpy())
    down = reaches.NEXT_DOWN.map(pos).to_numpy()  # NaN when the outlet or a reach outside the clip
    for i in range(len(reaches)):
        d = down[i]
        if d == d:  # not NaN
            vol[int(d)] += vol[i]
    return vol / reaches.UPLAND_SKM.to_numpy()[:, None]


def unit_week_river(reaches, reach_daily, unit_rain_7d):
    """reach_daily: (date x reach) CHIRPS mm in `reaches` order. unit_rain_7d: long frame with chirps_7d."""
    from .config import week_ending

    d = reach_daily.copy()
    wk = week_ending(pd.Series(d.index)).values
    weekly = d.groupby(wk).sum(min_count=7)  # (week x reach)
    local = np.nan_to_num(weekly.to_numpy().T)
    up = accumulate(reaches, local)  # (reach x week)
    wgt = reaches.DIS_AV_CMS.clip(lower=1e-3).to_numpy()
    df = pd.DataFrame(up.T * wgt, index=weekly.index, columns=reaches.unit_id.values)
    num = df.T.groupby(level=0).sum().T
    den = pd.Series(wgt, index=reaches.unit_id.values).groupby(level=0).sum()
    river = (num / den).stack().rename("river_up_7d").reset_index()
    river.columns = ["week", "unit_id", "river_up_7d"]
    river = river.merge(unit_rain_7d[["week", "unit_id", "chirps_7d"]], on=["week", "unit_id"], how="left")
    river["river_excess_7d"] = river.river_up_7d - river.chirps_7d
    weekly_missing = weekly.isna().all(axis=1)
    river.loc[river.week.isin(weekly.index[weekly_missing]), ["river_up_7d", "river_excess_7d"]] = np.nan
    return river.drop(columns="chirps_7d")
