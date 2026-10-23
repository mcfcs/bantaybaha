"""Daily rainfall grids -> unit-week rainfall features (CHIRPS v2.0 open; GPM IMERG V07 from GEE when present).

CHIRPS from the IRI Data Library has a julian_day time axis (finding 14): T - 2440587.5 = days since 1970-01-01.
Unit rainfall is the mean over the grid cells whose centre falls in the unit (NaN sea cells ignored); tiny islands with
no cell centre fall back to the nearest land cell. Weeks are Monday-Sunday, labelled by the Sunday (DOH convention).
"""

import re

import numpy as np
import pandas as pd
from affine import Affine
from rasterio import features
from scipy import sparse

from .config import RAW, week_ending, have, missing

CHIRPS_DIR = RAW / "chirps"
IMERG_DIR = RAW / "imerg"


def zonal_weights(units, transform, shape, land=None):
    """Sparse (n_units x n_cells) row-normalised weights of a regular grid. `land`: bool mask of valid cells."""
    rows, cols = [], []
    for i, geom in enumerate(units.geometry):
        m = features.rasterize([(geom, 1)], out_shape=shape, transform=transform, fill=0, dtype="uint8").astype(bool)
        if land is not None:
            m &= land
        if not m.any():  # small island: nearest valid cell to the representative point
            p = geom.representative_point()
            col, row = ~transform * (p.x, p.y)
            rr, cc = np.nonzero(land if land is not None else np.ones(shape, bool))
            k = np.argmin((rr - row) ** 2 + (cc - col) ** 2)
            m = np.zeros(shape, bool)
            m[rr[k], cc[k]] = True
        idx = np.flatnonzero(m)
        rows += [i] * len(idx)
        cols += idx.tolist()
    w = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(units), shape[0] * shape[1]))
    return sparse.diags(1 / np.asarray(w.sum(1)).ravel()) @ w


def apply_weights(w, cube):
    """cube (T, ny, nx) with NaN -> (T, n_units), NaN-aware weighted mean."""
    x = cube.reshape(cube.shape[0], -1)
    ok = ~np.isnan(x)
    num = (w @ np.where(ok, x, 0).T).T
    den = (w @ ok.T.astype(float)).T
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _grid_transform(lon, lat):
    """Affine for cell-centre coordinate vectors; returns (transform, flip) where flip means lat was ascending."""
    dx, dy = float(lon[1] - lon[0]), float(lat[1] - lat[0])
    flip = dy > 0
    top = lat.max() + abs(dy) / 2
    return Affine(dx, 0, lon.min() - dx / 2, 0, -abs(dy), top), flip


def nearest_cells(xs, ys, transform, land):
    """Flat index of the nearest valid (land) cell to each point."""
    from scipy.spatial import cKDTree

    rr, cc = np.nonzero(land)
    cx, cy = transform * (cc + 0.5, rr + 0.5)
    _, k = cKDTree(np.c_[cx, cy]).query(np.c_[xs, ys])
    return rr[k] * land.shape[1] + cc[k]


def chirps_daily_units(units, points=None):
    """Daily CHIRPS rainfall (mm) per unit -> DataFrame (date x unit_id). None if CHIRPS is missing.

    With `points` (GeoSeries, EPSG:4326) also returns the daily value at the nearest land cell of each point."""
    import xarray as xr

    files = sorted(CHIRPS_DIR.glob("chirps_v2_daily_p05_phl_*.nc"))
    if not files:
        return missing("chirps", f"no CHIRPS files in {CHIRPS_DIR}")
    frames, pframes, w = [], [], None
    for f in files:
        ds = xr.open_dataset(f, decode_times=False, engine="scipy")  # netCDF3 classic; avoids the netCDF4 DLL (blocked on some machines)
        assert ds["T"].attrs.get("units") == "julian_day", "CHIRPS time axis changed"
        t = pd.to_datetime(ds["T"].values - 2440587.5, unit="D").normalize()
        lon, lat = ds["X"].values, ds["Y"].values
        cube = ds["prcp"].transpose("T", "Y", "X").values.astype("float32")
        tr, flip = _grid_transform(lon, lat)
        if flip:
            cube = cube[:, ::-1, :]
        if w is None:
            land = ~np.isnan(cube).all(axis=0)
            w = zonal_weights(units, tr, cube.shape[1:], land)
            pidx = None if points is None else nearest_cells(points.x.values, points.y.values, tr, land)
        frames.append(pd.DataFrame(apply_weights(w, cube), index=t, columns=units.unit_id.values))
        if pidx is not None:
            pframes.append(pd.DataFrame(cube.reshape(len(t), -1)[:, pidx], index=t))
        ds.close()
    have("chirps", CHIRPS_DIR, pattern="*.nc")
    daily = pd.concat(frames).sort_index()
    return daily if points is None else (daily, pd.concat(pframes).sort_index())


def imerg_daily_units(units):
    """Daily IMERG (mm) per unit from the monthly GeoTIFF stacks written by scripts/download_gee.py. None if missing."""
    import rasterio

    files = sorted(IMERG_DIR.glob("imerg_v07_daily_mm_phl_*.tif"))
    if not files:
        return missing("imerg", f"no IMERG stacks in {IMERG_DIR} (needs scripts/download_gee.py)")
    frames, w = [], None
    for f in files:
        y, m = re.search(r"_(\d{4})(\d{2})\.tif$", f.name).groups()
        with rasterio.open(f) as r:
            cube = r.read().astype("float32")
            if r.nodata is not None:
                cube[cube == r.nodata] = np.nan
            if w is None:
                w = zonal_weights(units, r.transform, cube.shape[1:])
            t = pd.date_range(f"{y}-{m}-01", periods=r.count, freq="D")
        frames.append(pd.DataFrame(apply_weights(w, cube), index=t, columns=units.unit_id.values))
    have("imerg", IMERG_DIR, pattern="*.tif")
    return pd.concat(frames).sort_index()


def weekly(daily, prefix):
    """Daily (date x unit) -> long unit-week: {prefix}_7d (Mon-Sun sum), _3d (Fri-Sun), _max1d."""
    d = daily.copy()
    d.index = pd.DatetimeIndex(d.index)
    wk = week_ending(pd.Series(d.index)).values
    last3 = pd.Series(d.index).dt.weekday.isin([4, 5, 6]).values
    out = {
        f"{prefix}_7d": d.groupby(wk).sum(min_count=7),
        f"{prefix}_3d": d[last3].groupby(wk[last3]).sum(min_count=3),
        f"{prefix}_max1d": d.groupby(wk).max(),
    }
    long = [v.stack().rename(k) for k, v in out.items()]
    res = pd.concat(long, axis=1)
    res.index.names = ["week", "unit_id"]
    return res.reset_index()
