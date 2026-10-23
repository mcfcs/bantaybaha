"""Zero-shot benchmark: TabPFN-TS (Hoo et al., 2025; tabpfn-time-series) on the rolling-origin evaluation rows.

Runs in the separate bench venv (see requirements-bench.txt), locally on the GPU, with no account or token:
    %USERPROFILE%\\.venvs\\bantay-bench\\Scripts\\python scripts/benchmark_tabpfn.py [--variant uni|lagcov]

Weights: tabpfn-time-series 1.3 defaults to TabPFN v3.5, whose weights are gated (browser licence acceptance with a
Prior Labs login, or the TabPFN client API with an account). Neither is used here. The script pins the TabPFN **v2**
regressor checkpoint (`tabpfn-v2-regressor.ckpt`, Hugging Face Prior-Labs/TabPFN-v2-reg, freely downloadable with no
licence gate; the version the TabPFN-TS paper used). TABPFN_DISABLE_TELEMETRY=1 is set.

For every evaluation origin t and unit, the context is the unit's weekly y = log1p(incidence per 100k) for weeks
<= t (NaN weeks dropped, as TabPFN-TS does); TabPFN-TS adds its default temporal features (running index, calendar,
auto-seasonal) and regresses y on them per series. TabPFN-TS only uses *known-future* covariates (past-only columns are
ignored), so --variant uni (default) has none. --variant lagcov adds covariates lagged 4 weeks (rain 7-day and 4-week
sum, upstream river rain, gale hit in the past 4 weeks), whose values for target weeks t+1..t+4 are known at t.
The 23 FluSight quantiles are TabPFN outputs (no interpolation). Zero-shot: no training, the forecast at t uses
weeks <= t only.

Per-origin results are cached in data/interim/bench/tabpfn_<variant>/ so an interrupted run resumes. Writes
data/processed/app/bench_tabpfn_ts.parquet / .json (variant uni) or bench_tabpfn_ts_<variant>.*.
"""

import argparse
import os
import time
import warnings

os.environ.setdefault("TABPFN_DISABLE_TELEMETRY", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import benchmark_common as B  # noqa: E402

LAG = 4


def lagged_covariates(p):
    """Covariates shifted by LAG weeks: the value used for week w is from week w - LAG (known at t for w <= t + LAG)."""
    g = p.groupby("unit_id", sort=False)
    out = pd.DataFrame({"unit_id": p.unit_id, "week": p.week})
    out["chirps_7d_lag4"] = g.chirps_7d.shift(LAG)
    out["chirps_4w_lag4"] = g.chirps_7d.transform(lambda s: s.rolling(4, min_periods=3).sum().shift(LAG))
    out["river_up_7d_lag4"] = g.river_up_7d.shift(LAG)
    out["storm_gale_4w_lag4"] = g.storm_gale_hit.transform(lambda s: s.rolling(4, min_periods=1).max().shift(LAG))
    return out


def main(variant):
    import torch
    from tabpfn import TabPFNRegressor
    from tabpfn.constants import ModelVersion
    from tabpfn_time_series import TabPFNTSPipeline, TabPFNMode

    warnings.filterwarnings("ignore", category=UserWarning)
    device = "cuda" if torch.cuda.is_available() else "cpu"  # TabPFN-TS picks its GPU worker whenever CUDA exists
    t0 = time.time()
    model_path = TabPFNRegressor.create_default_for_version(ModelVersion.V2).model_path
    pipe = TabPFNTSPipeline(tabpfn_mode=TabPFNMode.LOCAL, tabpfn_model_config={"model_path": model_path})
    rows = B.eval_rows()
    p = B.panel()
    d = p[["unit_id", "week", "y"]].rename(columns={"unit_id": "item_id", "week": "timestamp", "y": "target"})
    cov_cols = []
    if variant == "lagcov":
        lc = lagged_covariates(p)
        cov_cols = [c for c in lc.columns if c not in ("unit_id", "week")]
        d = pd.concat([d, lc[cov_cols].reset_index(drop=True)], axis=1)
    cache = B.ROOT / "data" / "interim" / "bench" / f"tabpfn_{variant}"
    cache.mkdir(parents=True, exist_ok=True)
    levels = [float(q) for q in B.Q]
    origins = sorted(rows.week.unique())
    parts = []
    for k, o in enumerate(origins):
        f = cache / f"{pd.Timestamp(o).date()}.parquet"
        if not f.exists():
            ctx = d[(d.timestamp <= o) & d.target.notna()]
            # explicit future frame (t+1..t+4 for every unit): frequency inference fails on series with dropped NaN weeks
            fut = d[(d.timestamp > o) & (d.timestamp <= o + pd.Timedelta(weeks=4))][["item_id", "timestamp"] + cov_cols]
            r = pipe.predict_df(ctx, future_df=fut, quantiles=levels)
            r = r.reset_index()
            r["horizon"] = ((r.timestamp - o) / pd.Timedelta(weeks=1)).round().astype(int)
            r = r[r.horizon.between(1, 4)]
            out = pd.DataFrame({"unit_id": r.item_id.astype(str), "week": o, "horizon": r.horizon,
                                "q": list(r[levels].to_numpy(float))})
            out.to_parquet(f, index=False)
            print(f"  origin {pd.Timestamp(o).date()} ({k + 1}/{len(origins)}, {time.time() - t0:.0f} s)", flush=True)
        parts.append(pd.read_parquet(f))
    fc = pd.concat(parts, ignore_index=True)
    name = "tabpfn_ts" if variant == "uni" else f"tabpfn_ts_{variant}"
    runtime = time.time() - t0
    res = B.write_bench(name, fc, dict(
        packages=B.versions("tabpfn-time-series", "tabpfn", "torch", "numpy", "pandas"),
        weights=f"TabPFN v2 regressor ({os.path.basename(model_path)}, Prior-Labs/TabPFN-v2-reg, no licence gate); "
                "the tabpfn-time-series default v3.5 is gated (Prior Labs login / licence acceptance) and was not used",
        mode="TabPFNMode.LOCAL (no client API, no token)",
        device=B.device_info(device), runtime_s=round(runtime, 1),
        runtime_note="sum over origins of this run; origins read from the cache are not re-timed",
        context="each unit's weekly log1p(incidence per 100k) for weeks <= origin, NaN weeks dropped (TabPFN-TS default)",
        temporal_features="TabPFN-TS defaults: RunningIndexFeature, CalendarFeature, AutoSeasonalFeature",
        covariates=(dict(type=f"known-future, lagged {LAG} weeks (values at weeks <= origin)", columns=cov_cols)
                    if cov_cols else "none (TabPFN-TS ignores past-only covariates)"),
        quantile_interpolation="none: the 23 FluSight levels are requested from TabPFN directly",
        leakage="zero-shot, no training; per-series in-context regression on weeks <= origin only",
        n_origins=len(origins)))
    B.quick_score(res, name)
    print(f"  done in {runtime:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="uni", choices=["uni", "lagcov"])
    a = ap.parse_args()
    main(a.variant)
