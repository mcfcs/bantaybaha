"""Score the benchmark forecasts (data/processed/app/bench_<model>.parquet) exactly like the XGBoost evaluation.

    %USERPROFILE%\\.venvs\\bantay-bench\\Scripts\\python scripts/benchmark_score.py [model ...]
    (default: the three headline models, then every other bench_*.parquet variant found; the main venv works too,
    it needs only pandas / numpy / bantay)

WIS (bantay.forecast.wis, 23 FluSight quantiles) and 50% / 90% coverage on case counts (bantay.forecast.to_cases with
the unit's population), on the rows of eval_scores.parquet where both reference scores exist (wis_naive is NaN on
120 rows without y(t+h-52)), so every model is averaged over the same 34,050 rows as the build's summary. Relative
WIS = mean WIS of the model / mean per-row wis_naive (or wis_xgb) over those rows. Because a mean WIS on counts can be
dominated by a handful of rows, the median per-row WIS and the relative WIS without the single worst origin of each
model are reported as well (diagnostics only; the headline is the plain mean).

Writes data/processed/app/bench_summary.csv (one row per model x horizon, plus 'all').
"""

import sys

import numpy as np
import pandas as pd

import benchmark_common as B
from bantay import forecast as F

MODELS = ["chronos2", "tabpfn_ts", "mpnn_lstm"]


def per_row(model, s, pop):
    f = pd.read_parquet(B.C.APP_DATA / f"bench_{model}.parquet")
    f["week"] = pd.to_datetime(f.week).astype("datetime64[ns]")
    m = s.merge(f, on=B.KEY, how="left", validate="one_to_one")
    assert m.q.notna().all(), f"{model}: missing rows"
    qs = F.to_cases(np.vstack(m.q), m.unit_id.map(pop).to_numpy())
    y = m.cases.to_numpy()
    return m.assign(wis=F.wis(qs, y), cov50=F.coverage(qs, y, 0.5), cov90=F.coverage(qs, y, 0.9))


def agg(d):
    worst = d.groupby(["unit_id", "week"]).wis.sum().idxmax()
    dd = d[~((d.unit_id == worst[0]) & (d.week == worst[1]))]
    return pd.Series({
        "n": len(d), "WIS": d.wis.mean(), "WIS naive": d.wis_naive.mean(), "WIS xgb": d.wis_xgb.mean(),
        "relWIS vs naive": d.wis.mean() / d.wis_naive.mean(), "relWIS vs xgb": d.wis.mean() / d.wis_xgb.mean(),
        "cov50": d.cov50.mean(), "cov90": d.cov90.mean(), "cov50 xgb": d.cov50_xgb.mean(), "cov90 xgb": d.cov90_xgb.mean(),
        "median WIS": d.wis.median(), "median WIS naive": d.wis_naive.median(), "median WIS xgb": d.wis_xgb.median(),
        "relWIS vs naive excl. worst origin": dd.wis.mean() / dd.wis_naive.mean(),
        "relWIS vs xgb excl. worst origin": dd.wis.mean() / dd.wis_xgb.mean(),
        "worst origin": f"{worst[0]} {pd.Timestamp(worst[1]).date()}",
        "share of WIS in top 0.1% rows": d.wis.nlargest(max(1, len(d) // 1000)).sum() / d.wis.sum(),
    })


def main(models):
    s = B.eval_rows().dropna(subset=["wis_naive", "wis_xgb"])
    pop = B.panel().groupby("unit_id")["pop"].first()
    out = []
    for model in models:
        if not (B.C.APP_DATA / f"bench_{model}.parquet").exists():
            print(f"  {model}: no bench_{model}.parquet, skipped")
            continue
        d = per_row(model, s, pop)
        t = d.groupby("horizon").apply(agg, include_groups=False)
        t.loc["all"] = agg(d)
        out.append(t.reset_index().assign(model=model))
    res = pd.concat(out, ignore_index=True)
    res = res[["model"] + [c for c in res.columns if c != "model"]]
    res.to_csv(B.C.APP_DATA / "bench_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(res[["model", "horizon", "n", "WIS", "WIS naive", "WIS xgb", "relWIS vs naive", "relWIS vs xgb", "cov50",
                   "cov90", "median WIS", "relWIS vs naive excl. worst origin", "worst origin"]].round(3).to_string(index=False))
    print(f"  wrote {B.C.APP_DATA / 'bench_summary.csv'}")


def all_models():
    found = sorted(f.stem[len("bench_"):] for f in B.C.APP_DATA.glob("bench_*.parquet"))
    return [m for m in MODELS if m in found] + [m for m in found if m not in MODELS]


if __name__ == "__main__":
    main(sys.argv[1:] or all_models())
