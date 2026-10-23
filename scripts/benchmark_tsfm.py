"""Optional zero-shot benchmark: Chronos-2 on the same rolling-origin weeks as the XGBoost evaluation.

Needs the heavy optional packages (torch + chronos-forecasting >= 2), which are not in requirements.txt:
    pip install -r requirements-bench.txt
    python scripts/benchmark_tsfm.py [--device cuda]

Writes data/processed/app/eval_chronos.csv (WIS / coverage by horizon, relative to the seasonal-naive rows of
eval_scores.parquet). If the packages are missing it records that in status.json and exits without error.
Context per forecast = the unit's log1p(incidence) up to the origin only (no leakage); no covariates.
UNTESTED in this repo so far: the Chronos-2 call follows the chronos-forecasting 2.x `predict_df` API.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bantay import config as C, panel as PN, forecast as F  # noqa: E402


def main(device):
    try:
        from chronos import Chronos2Pipeline
    except ImportError:
        C.missing("chronos2", "chronos-forecasting / torch not installed (pip install -r requirements-bench.txt)")
        return
    sc = pd.read_parquet(C.APP_DATA / "eval_scores.parquet")
    p = PN.load_panel()
    p["y"] = np.log1p(p.incidence)
    pipe = Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map=device)
    origins = sorted(sc.week.unique())
    rows = []
    for o in origins:
        ctx = p[p.week <= o][["unit_id", "week", "y"]].dropna().rename(columns={"unit_id": "id", "week": "timestamp", "y": "target"})
        pred = pipe.predict_df(ctx, prediction_length=4, quantile_levels=list(F.QUANTILES), id_column="id",
                               timestamp_column="timestamp", target="target")
        qcols = sorted((c for c in pred.columns if _isfloat(c)), key=float)
        pred = pred.assign(origin=o, horizon=pred.groupby("id").cumcount() + 1)
        rows.append(pred[["id", "origin", "horizon"] + qcols].rename(columns={"id": "unit_id"}))
        print(f"  origin {pd.Timestamp(o).date()}")
    fc = pd.concat(rows)
    m = sc.merge(fc, left_on=["unit_id", "week", "horizon"], right_on=["unit_id", "origin", "horizon"])
    pop = m.unit_id.map(p.groupby("unit_id")["pop"].first()).to_numpy()
    qs = F.to_cases(np.sort(m[qcols].to_numpy(float), axis=1), pop)
    m["wis_chronos"] = F.wis(qs, m.cases.to_numpy())
    m["cov90_chronos"] = F.coverage(qs, m.cases.to_numpy(), 0.9)
    out = m.groupby("horizon").agg(n=("wis_chronos", "size"), wis_chronos=("wis_chronos", "mean"), wis_naive=("wis_naive", "mean"),
                                   wis_xgb=("wis_xgb", "mean"), cov90_chronos=("cov90_chronos", "mean"))
    out["relWIS chronos/naive"] = out.wis_chronos / out.wis_naive
    out.to_csv(C.APP_DATA / "eval_chronos.csv")
    C.record("chronos2", True, f"relWIS chronos/naive = {out.wis_chronos.mean() / out.wis_naive.mean():.3f}")
    print(out.round(3).to_string())


def _isfloat(c):
    try:
        float(c)
        return True
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda")
    main(ap.parse_args().device)
