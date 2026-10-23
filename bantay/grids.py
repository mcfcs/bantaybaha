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

from .config import RAW, INTERIM, have, record
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


# ---------------------------------------------------------------- vulnerable populations (Meta HRSL)

HRSL = {"pop_u5": RAW / "meta_hrsl" / "phl_children_under_five_2020_geotiff.zip",
        "pop_60": RAW / "meta_hrsl" / "phl_elderly_60_plus_2020_geotiff.zip"}
HRSL_CELLS = INTERIM / "pop_cells_hrsl.parquet"
HRSL_ROWS = 1024  # rows per read of the ~30 m HRSL rasters (39,600 columns of float64)


def _hrsl_block_sums(zpath, factor=10):
    """Sum one HRSL raster (~30 m, inside its zip) onto the WorldPop 1 km blocks that build_pop_cells uses: each 30 m
    pixel goes to the block holding its centre. Rows are read top to bottom (the zip member is deflated: sequential
    reads avoid re-inflating). Returns (block sums as a flat array, n block columns, total, total outside WorldPop)."""
    import zipfile

    name = next(n for n in zipfile.ZipFile(zpath).namelist() if n.endswith(".tif"))
    with rasterio.open(WORLDPOP) as sp:
        wt, wh, ww = sp.transform, sp.height, sp.width
    nbr, nbc = -(-wh // factor), -(-ww // factor)
    sums = np.zeros(nbr * nbc)
    total = outside = 0.0
    with rasterio.open(f"zip://{zpath.as_posix()}!{name}") as src:
        t = src.transform
        lon = t.c + t.a * (np.arange(src.width) + 0.5)
        wcol = np.floor((lon - wt.c) / wt.a).astype(np.int64)
        for r0 in range(0, src.height, HRSL_ROWS):
            h = min(HRSL_ROWS, src.height - r0)
            a = src.read(1, window=Window(0, r0, src.width, h))
            rr, cc = np.nonzero(np.isfinite(a) & (a > 0))
            if not len(rr):
                continue
            v = a[rr, cc]
            lat = t.f + t.e * (r0 + rr + 0.5)
            wrow = np.floor((lat - wt.f) / wt.e).astype(np.int64)
            wc = wcol[cc]
            ok = (wrow >= 0) & (wrow < wh) & (wc >= 0) & (wc < ww)
            total += v.sum()
            outside += v[~ok].sum()
            sums += np.bincount((wrow[ok] // factor) * nbc + wc[ok] // factor, weights=v[ok], minlength=len(sums))
    return sums, nbc, total, outside


def build_vulnerable_cells(cells, factor=10, force=False):
    """Meta HRSL 2020 under-5 and 60+ people per 1 km population cell (same rows as `cells`), cached in
    data/interim/pop_cells_hrsl.parquet. People in blocks without a WorldPop cell (no WorldPop population, or outside
    every unit) are dropped and their share recorded. Columns are NaN for a layer whose zip is missing."""
    if cells is None:
        return None
    zips = [z for z in HRSL.values() if z.exists()]
    if HRSL_CELLS.exists() and not force and fresh(HRSL_CELLS, POP_CELLS, *zips):
        v = pd.read_parquet(HRSL_CELLS)
        if len(v) == len(cells) and np.allclose(v.x, cells.x) and np.allclose(v.y, cells.y):
            return v
    from concurrent.futures import ThreadPoolExecutor

    with rasterio.open(WORLDPOP) as sp:
        wt = sp.transform
    br = np.floor((cells.y.to_numpy() - wt.f) / wt.e).astype(np.int64) // factor
    bc = np.floor((cells.x.to_numpy() - wt.c) / wt.a).astype(np.int64) // factor
    out = pd.DataFrame({"x": cells.x.to_numpy(), "y": cells.y.to_numpy()})
    todo = {k: z for k, z in HRSL.items() if have(f"meta_hrsl_{k}", z)}
    with ThreadPoolExecutor(max(1, len(todo))) as ex:  # GDAL reads release the GIL: both layers at once
        res = dict(zip(todo, ex.map(_hrsl_block_sums, todo.values())))
    for k in HRSL:
        if k not in res:
            out[k] = np.nan
            continue
        sums, nbc, total, outside = res[k]
        out[k] = sums[br * nbc + bc]
        kept = out[k].sum()
        record(f"meta_hrsl_{k}", True, f"{total:,.0f} people in the raster, {kept:,.0f} on population cells "
                                       f"({kept / total:.1%}); {outside:,.0f} outside the WorldPop grid")
    HRSL_CELLS.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(HRSL_CELLS)
    return out


# ---------------------------------------------------------------- municipality (ADM3) raster

ADM3_RASTER = INTERIM / "adm3_100m.tif"


def adm3_index(adm3):
    """Stable adm3_pcode <-> raster code (1..n; 0 = outside every municipality)."""
    return {p: i + 1 for i, p in enumerate(sorted(adm3.adm3_pcode))}


def build_adm3_raster(adm3, force=False):
    """COD-AB ADM3 polygons on the WorldPop 100 m grid (uint16 codes from adm3_index), cached in data/interim/."""
    if fresh(ADM3_RASTER, UNITS_GPKG) and not force:
        return ADM3_RASTER
    if adm3 is None or not have("worldpop", WORLDPOP):
        return None
    code = adm3_index(adm3)
    with rasterio.open(WORLDPOP) as src:
        prof = src.profile | dict(dtype="uint16", nodata=0, count=1, compress="lzw", tiled=True, blockxsize=512, blockysize=512)
        a = adm3.to_crs(src.crs).reset_index(drop=True)
        codes = a.adm3_pcode.map(code).to_numpy()
        tmp = ADM3_RASTER.with_suffix(".part.tif")
        INTERIM.mkdir(parents=True, exist_ok=True)
        with rasterio.open(tmp, "w", **prof) as dst:
            for r0 in range(0, src.height, BLOCK):
                for c0 in range(0, src.width, BLOCK):
                    w = Window(c0, r0, min(BLOCK, src.width - c0), min(BLOCK, src.height - r0))
                    wt = src.window_transform(w)
                    hit = a.sindex.query(_box(rasterio.windows.bounds(w, src.transform)))
                    arr = np.zeros((int(w.height), int(w.width)), "uint16")
                    if len(hit):
                        arr = features.rasterize(((a.geometry.iloc[i], int(codes[i])) for i in hit),
                                                 out_shape=arr.shape, transform=wt, fill=0, dtype="uint16")
                    dst.write(arr, 1, window=w)
    tmp.replace(ADM3_RASTER)
    return ADM3_RASTER


def _box(bounds):
    from shapely.geometry import box

    return box(*bounds)
