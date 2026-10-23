"""Zero-shot benchmark: Chronos-2 (Ansari et al., 2025) on the rolling-origin evaluation rows of the XGBoost forecast.

Runs in the separate bench venv (torch + chronos-forecasting >= 2; see requirements-bench.txt for the exact setup):
    %USERPROFILE%\\.venvs\\bantay-bench\\Scripts\\python scripts/benchmark_tsfm.py [--device cuda] [--variant cov|nocov]
    [--cross-learning] [--space incidence|log1p]

For every evaluation origin t (2018-01-07 .. 2019-12-22) and unit, the context is the unit's weekly
y = log1p(incidence per 100k) from 2016-01-10 up to and including t (missing weeks stay NaN, Chronos-2 masks them).
--variant cov (default, "with rainfall and flood covariates") adds past-only covariates over the same weeks <= t:
CHIRPS 7-day rain, upstream river rain and its excess, gale hit, max wind near the unit, storm x NOAH-hazard exposure
and the Sentinel-1 flood fraction (NaN outside the storm windows / without a NOAH map: passed as missing, never 0).
Chronos-2 supports past-only covariates natively (keys in `past_covariates` but not in `future_covariates`), so no
future rain is used. --variant nocov is the univariate ablation. No training and no fitted normalisation (Chronos-2
scales each context itself), so the forecast at t sees weeks <= t only.

--space incidence (default) feeds incidence per 100k and maps the output quantiles to log1p (a monotone map, so quantiles
carry over; negative values clipped to 0). --space log1p feeds y = log1p(incidence), as first specified, and is kept as
the variant chronos2_log1p: after a one-week reporting spike that context gives Chronos-2 upper tails of 15-24 in log
space (10^6-10^10 per 100k), and back-transformed they dominate a mean WIS on counts (relWIS vs naive ~112). The
headline was switched to incidence after seeing that failure (Chronos-2 scales its context itself); both are reported.

Chronos-2 outputs 21 quantile levels (0.01, 0.05, 0.10, ..., 0.95, 0.99); the 23 FluSight levels are taken directly
where they coincide and 0.025 / 0.975 are linearly interpolated in level space between 0.01-0.05 / 0.95-0.99.

Writes data/processed/app/bench_chronos2.parquet / .json (variant cov, incidence) or bench_chronos2_<suffixes>.parquet
(see benchmark_common.py for the contract). Score with scripts/benchmark_score.py.
"""

import argparse
import time

import numpy as np
import pandas as pd

import benchmark_common as B

COVARIATES = ["chirps_7d", "river_up_7d", "river_excess_7d", "storm_gale_hit", "storm_max_wind_near_kt",
              "storm_hazard_exposure", "s1_flood_frac"]


def main(device, variant, cross_learning, batch_size, space):
    import torch
    from chronos import Chronos2Pipeline

    t0 = time.time()
    torch.manual_seed(0)
    rows = B.eval_rows()
    p = B.panel()
    Y = B.wide(p, "y" if space == "log1p" else "incidence")
    weeks = Y.columns
    units = Y.index.tolist()
    covs = {c: B.wide(p, c).reindex(index=Y.index, columns=weeks).to_numpy(float) for c in COVARIATES} if variant == "cov" else {}
    pipe = Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map=device)
    levels = list(pipe.quantiles)
    origins = sorted(rows.week.unique())
    Ya = Y.to_numpy(float)
    out = []
    for k, o in enumerate(origins):
        j = int(np.flatnonzero(weeks == o)[0])  # context = weeks[0 .. j], i.e. <= origin
        inputs = []
        for i in range(len(units)):
            d = {"target": Ya[i, : j + 1]}
            if covs:
                d["past_covariates"] = {c: a[i, : j + 1] for c, a in covs.items()}
            inputs.append(d)
        preds = pipe.predict(inputs, prediction_length=4, batch_size=batch_size, cross_learning=cross_learning)
        qraw = np.stack([pr[0].float().cpu().numpy().T for pr in preds])  # (unit, horizon, 21 levels)
        if space == "incidence":
            qraw = np.log1p(np.clip(qraw, 0, None))
        q23 = B.interp_levels(qraw, levels)
        for i, u in enumerate(units):
            for h in B.HORIZONS:
                out.append((u, o, h, q23[i, h - 1]))
        if k % 13 == 0:
            print(f"  origin {pd.Timestamp(o).date()}  ({time.time() - t0:.0f} s)", flush=True)
    fc = pd.DataFrame(out, columns=["unit_id", "week", "horizon", "q"])
    name = "chronos2" if variant == "cov" else f"chronos2_{variant}"
    if cross_learning:
        name += "_xl"
    if space == "log1p":
        name += "_log1p"
    runtime = time.time() - t0
    res = B.write_bench(name, fc, dict(
        packages=B.versions("chronos-forecasting", "torch", "transformers", "numpy", "pandas"),
        weights="amazon/chronos-2 (Hugging Face, Apache-2.0, not gated), 119.5 M parameters",
        device=B.device_info(device), runtime_s=round(runtime, 1),
        context=f"each unit's weekly {'log1p(incidence per 100k)' if space == 'log1p' else 'incidence per 100k'} from "
                "2016-01-10 to the origin week inclusive (105-207 weeks; model max 8192); missing weeks passed as NaN"
                + ("" if space == "log1p" else "; output quantiles mapped to log1p after clipping at 0"),
        target_space=space,
        covariates=(dict(type="past-only (Chronos-2 past_covariates, no future values)", columns=COVARIATES,
                         missing="NaN passed as missing (storm_hazard_exposure has no NOAH map for 11 units; "
                                 "s1_flood_frac exists only in the Sentinel-1 storm windows)")
                    if covs else "none (univariate)"),
        cross_learning=cross_learning, batch_size=batch_size, prediction_length=4,
        model_quantile_levels=levels,
        quantile_interpolation="levels 0.025 and 0.975 linearly interpolated in level space between Chronos-2's "
                               "0.01/0.05 and 0.95/0.99 quantiles; the other 21 FluSight levels are Chronos-2 outputs",
        leakage="zero-shot, no training or fitted normalisation; the forecast at origin t uses weeks <= t only",
        n_origins=len(origins)))
    B.quick_score(res, name)
    print(f"  done in {runtime:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--variant", default="cov", choices=["cov", "nocov"])
    ap.add_argument("--cross-learning", action="store_true", help="share information across the 85 units of an origin")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--space", default="incidence", choices=["incidence", "log1p"], help="series fed to Chronos-2")
    a = ap.parse_args()
    main(a.device, a.variant, a.cross_learning, a.batch_size, a.space)
