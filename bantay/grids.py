"""WorldPop-aligned grids: a unit-id raster at 100 m, unit population totals and 1 km population cells.

Everything raster-based (NOAH hazard shares, Sentinel-1 flooded population, access demand points) is computed on the
WorldPop 2020 UN-adjusted 100 m grid so population and hazard line up cell for cell.
"""

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.windows import Window

from .config import RAW, INTERIM, have
from .units import UNITS_GPKG

WORLDPOP = RAW / "worldpop" / "phl_ppp_2020_UNadj.tif"
UNIT_RASTER = INTERIM / "units_100m.tif"
POP_CELLS = INTERIM / "pop_cells_1km.parquet"
BLOCK = 2048


def fresh(path, *inputs):
    """True if `path` exists and is newer than every existing input (e.g. the unit geometry it was built from)."""
    if not path.exists():
        return False
    return all(path.stat().st_mtime >= p.stat().st_mtime for p in map(type(path), inputs) if p.exists())


def unit_index(units):
    """Stable unit_id <-> raster code (1..n; 0 = outside every unit)."""
    ids = sorted(units.unit_id)
    return {u: i + 1 for i, u in enumerate(ids)}


def build_unit_raster(units, force=False):
    if fresh(UNIT_RASTER, UNITS_GPKG) and not force:
        return UNIT_RASTER
    if not have("worldpop", WORLDPOP):
        return None
    code = unit_index(units)
    with rasterio.open(WORLDPOP) as src:
        prof = src.profile | dict(dtype="uint8", nodata=0, count=1, compress="lzw", tiled=True, blockxsize=512, blockysize=512)
        u = units.to_crs(src.crs)
        shapes = [(g, code[i]) for g, i in zip(u.geometry, u.unit_id)]
        INTERIM.mkdir(parents=True, exist_ok=True)
        with rasterio.open(UNIT_RASTER, "w", **prof) as dst:
            for r0 in range(0, src.height, BLOCK):
                for c0 in range(0, src.width, BLOCK):
                    w = Window(c0, r0, min(BLOCK, src.width - c0), min(BLOCK, src.height - r0))
                    arr = features.rasterize(shapes, out_shape=(int(w.height), int(w.width)),
                                             transform=src.window_transform(w), fill=0, dtype="uint8")
                    dst.write(arr, 1, window=w)
    return UNIT_RASTER


def iter_blocks(*paths):
    """Yield (window, [arrays]) over aligned rasters of identical shape, block by block."""
    srcs = [rasterio.open(p) for p in paths]
    try:
        h, w = srcs[0].height, srcs[0].width
        for r0 in range(0, h, BLOCK):
            for c0 in range(0, w, BLOCK):
                win = Window(c0, r0, min(BLOCK, w - c0), min(BLOCK, h - r0))
                yield win, [s.read(1, window=win) for s in srcs]
    finally:
        for s in srcs:
            s.close()


def worldpop_clean(a, nodata):
    a = a.astype("float64")
    a[(a == nodata) | ~np.isfinite(a) | (a < 0)] = 0
    return a


def unit_population_worldpop(units):
    """WorldPop 2020 population per unit (fallback when the 2020 census table is missing)."""
    if build_unit_raster(units) is None:
        return None
    with rasterio.open(WORLDPOP) as s:
        nd = s.nodata
    tot = np.zeros(len(units) + 1)
    for _, (pop, uid) in iter_blocks(WORLDPOP, UNIT_RASTER):
        tot += np.bincount(uid.ravel(), weights=worldpop_clean(pop, nd).ravel(), minlength=len(tot))
    inv = {v: k for k, v in unit_index(units).items()}
    return pd.DataFrame({"unit_id": [inv[i] for i in range(1, len(tot))], "pop_worldpop": tot[1:]})


def build_pop_cells(units, adm3=None, factor=10, force=False):
    """WorldPop summed to ~1 km (factor x factor cells) -> points with pop, unit_id and (optionally) adm3_pcode."""
    if fresh(POP_CELLS, UNITS_GPKG, UNIT_RASTER) and not force:
        return gpd.read_parquet(POP_CELLS)
    if build_unit_raster(units) is None:
        return None
    inv = {v: k for k, v in unit_index(units).items()}
    rows = []
    with rasterio.open(WORLDPOP) as sp, rasterio.open(UNIT_RASTER) as su:
        nd = sp.nodata
        step = BLOCK - BLOCK % factor
        for r0 in range(0, sp.height, step):
            for c0 in range(0, sp.width, step):
                win = Window(c0, r0, min(step, sp.width - c0), min(step, sp.height - r0))
                pop = worldpop_clean(sp.read(1, window=win), nd)
                uid = su.read(1, window=win)
                hh, ww = (pop.shape[0] // factor) * factor, (pop.shape[1] // factor) * factor
                if hh == 0 or ww == 0:
                    continue
                p = pop[:hh, :ww].reshape(hh // factor, factor, ww // factor, factor).sum(axis=(1, 3))
                # unit of the block = unit of its centre cell; coastal blocks with a sea centre take any unit in the block
                ub = uid[:hh, :ww].reshape(hh // factor, factor, ww // factor, factor)
                centre = ub[:, factor // 2, :, factor // 2]
                centre = np.where(centre > 0, centre, ub.max(axis=(1, 3)))
                rr, cc = np.nonzero(p > 0)
                if not len(rr):
                    continue
                t = sp.window_transform(win)
                x, y = t * ((cc + 0.5) * factor, (rr + 0.5) * factor)
                rows.append(pd.DataFrame({"x": x, "y": y, "pop": p[rr, cc], "code": centre[rr, cc]}))
        crs = sp.crs
    df = pd.concat(rows, ignore_index=True)
    df = df[df.code > 0]
    df["unit_id"] = df.code.map(inv)
    g = gpd.GeoDataFrame(df.drop(columns="code"), geometry=gpd.points_from_xy(df.x, df.y), crs=crs)
    if adm3 is not None:
        a3 = adm3[["adm3_pcode", "adm3_name", "geometry"]].to_crs(crs)
        j = gpd.sjoin(g, a3, how="left", predicate="within")
        g = j[~j.index.duplicated()].drop(columns="index_right")
        off = g.adm3_pcode.isna()  # coastal cells whose centre is just offshore: nearest municipality (metric CRS)
        if off.any():
            near = gpd.sjoin_nearest(g.loc[off, ["geometry"]].to_crs(3857), a3.to_crs(3857), how="left")
            near = near[~near.index.duplicated()]
            g.loc[off, "adm3_pcode"], g.loc[off, "adm3_name"] = near.adm3_pcode, near.adm3_name
    g = g.reset_index(drop=True)
    g.to_parquet(POP_CELLS)
    return g
