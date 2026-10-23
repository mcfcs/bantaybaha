"""Shared helpers for the benchmark scripts (scripts/benchmark_*.py): evaluation rows, panel arrays, output contract.

Not a script. Imported by benchmark_tsfm.py (Chronos-2), benchmark_tabpfn.py (TabPFN-TS), benchmark_mpnn.py
(MPNN-LSTM) and benchmark_score.py. Needs only pandas / numpy and `bantay`.

Output contract, one file per model in data/processed/app/:
    bench_<model>.parquet  unit_id (str), week (datetime64[ns], forecast origin, a Sunday), horizon (int 1-4),
                           q (list of 23 floats at bantay.config.QUANTILES, log1p(incidence per 100k), ascending)
    bench_<model>.json     package versions, device, runtime, context, covariates, quantile interpolation, notes
Rows = exactly the (unit_id, week, horizon) rows of data/processed/app/eval_scores.parquet (the XGBoost evaluation).
"""

import json
import platform
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bantay import config as C  # noqa: E402

Q = np.array(C.QUANTILES)
HORIZONS = (1, 2, 3, 4)
KEY = ["unit_id", "week", "horizon"]


def eval_rows():
    """The rolling-origin evaluation rows (unit_id, week = origin, horizon) with the observed cases and per-row scores."""
    s = pd.read_parquet(C.APP_DATA / "eval_scores.parquet")
    s["unit_id"] = s.unit_id.astype(str)
    s["week"] = pd.to_datetime(s.week).astype("datetime64[ns]")
    s["horizon"] = s.horizon.astype(int)
    return s


def panel():
    """The build's panel with y = log1p(incidence per 100k), sorted by unit and week (weekly grid, complete)."""
    p = pd.read_parquet(C.PROCESSED / "panel.parquet")
    p["unit_id"] = p.unit_id.astype(str)
    p["week"] = pd.to_datetime(p.week).astype("datetime64[ns]")
    p = p.sort_values(["unit_id", "week"]).reset_index(drop=True)
    p["y"] = np.log1p(p.incidence)
    return p


def wide(p, col):
    """unit x week matrix of `col` (rows sorted by unit_id, columns by week)."""
    return p.pivot(index="unit_id", columns="week", values=col).sort_index()


def interp_levels(qs, levels, target=Q):
    """Map quantiles at `levels` (..., len(levels)) to the 23 FluSight levels by linear interpolation of the quantile
    function in level space (np.interp per row); levels outside the source range are clamped to its end quantiles."""
    levels = np.asarray(levels, float)
    flat = qs.reshape(-1, qs.shape[-1])
    out = np.vstack([np.interp(target, levels, r) for r in flat])
    return np.sort(out, axis=1).reshape(*qs.shape[:-1], len(target))


def write_bench(model, fc, meta):
    """Check the contract (exact eval row set, 23 sorted finite quantiles) and write bench_<model>.parquet / .json."""
    rows = eval_rows()[KEY]
    fc = fc[KEY + ["q"]].copy()
    fc["unit_id"] = fc.unit_id.astype(str)
    fc["week"] = pd.to_datetime(fc.week).astype("datetime64[ns]")
    fc["horizon"] = fc.horizon.astype(int)
    out = rows.merge(fc, on=KEY, how="left", validate="one_to_one")
    qa = np.vstack([np.asarray(q, float) if q is not None and len(q) == len(Q) else np.full(len(Q), np.nan)
                    for q in out.q])
    n_bad = int((~np.isfinite(qa)).any(axis=1).sum())
    if n_bad:
        raise ValueError(f"{model}: {n_bad} evaluation rows have no forecast or non-finite quantiles")
    qa = np.sort(qa, axis=1)
    assert (out.week.dt.dayofweek == 6).all(), "origins must be Sundays"
    out["q"] = [list(map(float, r)) for r in qa]
    C.APP_DATA.mkdir(parents=True, exist_ok=True)
    out.to_parquet(C.APP_DATA / f"bench_{model}.parquet", index=False)
    meta = dict(model=model, n_rows=len(out), quantile_levels=list(map(float, Q)), space="log1p(incidence per 100k)",
                rows="exactly the (unit_id, week, horizon) rows of data/processed/app/eval_scores.parquet",
                python=platform.python_version(), platform=platform.platform(), **meta)
    (C.APP_DATA / f"bench_{model}.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    print(f"  wrote bench_{model}.parquet ({len(out)} rows) and bench_{model}.json")
    return out


def versions(*pkgs):
    out = {}
    for p in pkgs:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


def device_info(device):
    try:
        import torch
        if device.startswith("cuda") and torch.cuda.is_available():
            return f"{device} ({torch.cuda.get_device_name(0)}, torch {torch.__version__}, CUDA {torch.version.cuda})"
        return f"{device} (torch {torch.__version__})"
    except ImportError:
        return device


def quick_score(out, label):
    """Print WIS on case counts vs the per-row wis_naive / wis_xgb (same rows as the build's summary)."""
    from bantay import forecast as F

    s = eval_rows()
    m = s.merge(out, on=KEY)
    pop = m.unit_id.map(panel().groupby("unit_id")["pop"].first()).to_numpy()
    qs = F.to_cases(np.vstack(m.q), pop)
    m["wis"] = F.wis(qs, m.cases.to_numpy())
    m = m.dropna(subset=["wis_naive", "wis_xgb"])
    print(f"  {label}: WIS {m.wis.mean():.2f} | rel. naive {m.wis.mean() / m.wis_naive.mean():.3f} | "
          f"rel. xgb {m.wis.mean() / m.wis_xgb.mean():.3f} (n={len(m)})")
