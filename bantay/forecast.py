"""Forecast: pooled multi-quantile XGBoost, 1-4 weeks ahead, with rolling-origin evaluation and WIS scoring.

Target: y = log1p(incidence per 100k) at t+h. One model per horizon outputs the 23 FluSight quantiles (sorted to stop
crossing); quantiles are back-transformed to cases with the unit's population, which preserves them. A second model
predicts the 4-week cumulative incidence directly, giving the surge probability R = P(next-4-week incidence > the unit's
90th percentile of 4-week incidence in the training window).

Rolling origin (never a random split): the model, the lead-lag graph and the surge thresholds are refit every
`refit_weeks` on data up to the refit date only, and forecast every origin until the next refit. Training targets never
go past the refit date, and 2020 is never a target (COVID reporting collapse). Compared against a seasonal-naive
baseline (same week last year, empirical quantiles of its training errors) and an ablation without graph features.

R is recalibrated with isotonic regression fitted on past rolling-origin surge forecasts only (`cum4_eval` for
the evaluation, `surge_calibrator` for the scenarios). Benchmark models (Chronos-2, TabPFN-TS, MPNN-LSTM, ...) drop
`bench_<model>.parquet` files with rolling-origin quantiles into data/processed/app/; `evaluate_models` scores them on
the same rows as xgb / naive and builds the median ensemble, with no XGBoost refit.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from .config import QUANTILES, MODEL_END, APP_DATA, missing, record
from . import leadlag

Q = np.array(QUANTILES)
IQ50 = int(np.argmin(np.abs(Q - 0.5)))
HORIZONS = (1, 2, 3, 4)
SURGE_PCTL = 0.9

GROUPS = {  # feature -> driver group shown in the dashboard
    "recent cases": ["y0", "y1", "y2", "y3", "ym4", "ym8", "dy4", "ylast_year", "ylast_year_pm2"],
    "season": ["woy_sin", "woy_cos", "woy"],
    "rain": ["chirps_7d_l0", "chirps_7d_l1", "chirps_7d_l2", "chirps_7d_l3", "chirps_4w", "chirps_8w", "chirps_3d_l0",
             "imerg_7d_l0", "imerg_7d_l1", "imerg_4w", "imerg_8w"],
    "river": ["river_up_7d_l0", "river_up_4w", "river_excess_4w"],
    "storm / flood": ["storm_gale_4w", "storm_dist_4w", "storm_wind_4w", "storm_hazard_4w", "s1_flood_frac",
                      "hazard_any_5yr", "hazard_any_25yr", "hazard_high_25yr"],
    "outbreak graph": ["leader_growth", "leader_anom", "n_leaders"],
    "unit": ["unit", "log_pop"],
}
GRAPH_FEATURES = GROUPS["outbreak graph"]
ENV_FEATURES = GROUPS["rain"] + GROUPS["river"] + GROUPS["storm / flood"]  # dropped in the "xgb_noenv" ablation
MODELS = ("xgb", "xgb_nograph", "xgb_noenv", "naive")

# R recalibration: an isotonic map is fitted only once this many past surge outcomes (rolling-origin cum4 forecasts whose
# 4-week target window has ended) exist: 10 weeks x 85 units. Before that, R is left as the raw model probability.
CAL_MIN_ROWS = 850
R_CLIP = (0.005, 0.995)  # same clip as prob_exceed
CUM4_FILE = "eval_cum4.parquet"  # rolling-origin cum4 forecasts, persisted by the forecast stage for the scenarios
ENSEMBLE = "ens_median"
BENCH_GLOB = "bench_*.parquet"
# headline benchmarks (members of the median ensemble). Other bench_*.parquet files are variants (e.g. chronos2_log1p,
# mpnn_lstm_border): scored by scripts/benchmark_score.py, ignored here so they cannot tilt the ensemble.
BENCH_MODELS = ("chronos2", "tabpfn_ts", "mpnn_lstm")
BAND = {"q05": 2, "q25": 6, "q50": IQ50, "q75": 16, "q95": 20}  # fan-chart levels (indices into Q)


# ---------------------------------------------------------------- features

def base_features(panel):
    """Leak-free features at each (unit, origin week t): only values at weeks <= t (static layers aside)."""
    p = panel.sort_values(["unit_id", "week"]).copy()
    p["y"] = np.log1p(p.incidence)
    g = p.groupby("unit_id", sort=False)
    f = p[["unit_id", "week"]].copy()
    for k in range(4):
        f[f"y{k}"] = g.y.shift(k)
    f["ym4"] = g.y.transform(lambda s: s.rolling(4, min_periods=2).mean())
    f["ym8"] = g.y.transform(lambda s: s.rolling(8, min_periods=4).mean())
    f["dy4"] = f.y0 - g.y.shift(4)
    f["log_pop"] = np.log(p["pop"])
    for src in ("chirps", "imerg"):
        c = f"{src}_7d"
        if p[c].notna().any():
            for k in range(4 if src == "chirps" else 2):
                f[f"{c}_l{k}"] = g[c].shift(k)
            f[f"{src}_4w"] = g[c].transform(lambda s: s.rolling(4, min_periods=3).sum())
            f[f"{src}_8w"] = g[c].transform(lambda s: s.rolling(8, min_periods=6).sum())
    if p.chirps_3d.notna().any():
        f["chirps_3d_l0"] = p.chirps_3d
    if p.river_up_7d.notna().any():
        f["river_up_7d_l0"] = p.river_up_7d
        f["river_up_4w"] = g.river_up_7d.transform(lambda s: s.rolling(4, min_periods=3).sum())
        f["river_excess_4w"] = g.river_excess_7d.transform(lambda s: s.rolling(4, min_periods=3).sum())
    roll_max = lambda c: g[c].transform(lambda s: s.rolling(4, min_periods=1).max())
    f["storm_gale_4w"] = roll_max("storm_gale_hit")
    f["storm_wind_4w"] = roll_max("storm_max_wind_near_kt")
    f["storm_dist_4w"] = g.storm_min_dist_km.transform(lambda s: s.rolling(4, min_periods=1).min())
    if p.storm_hazard_exposure.notna().any():
        f["storm_hazard_4w"] = roll_max("storm_hazard_exposure")
    for c in ("hazard_any_5yr", "hazard_any_25yr", "hazard_high_25yr", "s1_flood_frac"):
        if p[c].notna().any():
            f[c] = p[c]
    f["unit"] = pd.Categorical(p.unit_id, categories=sorted(p.unit_id.unique()))
    f["y"] = p.y.values
    f["pop"] = p["pop"].values
    return f.reset_index(drop=True)


def target_frame(f, h):
    """Features at origin t with target y(t+h), its week and the seasonal-naive value y(t+h-52)."""
    g = f.groupby("unit_id", sort=False)
    out = f.copy()
    out["target"] = g.y.shift(-h)
    out["target_week"] = out.week + pd.Timedelta(weeks=h)
    out["ylast_year"] = g.y.shift(52 - h)  # value at t+h-52, known at t
    out["ylast_year_pm2"] = g.y.transform(lambda s: s.rolling(5, center=True, min_periods=3).mean()).groupby(f.unit_id).shift(52 - h)
    woy = out.target_week.dt.isocalendar().week.astype(int)
    out["woy"] = woy
    out["woy_sin"], out["woy_cos"] = np.sin(2 * np.pi * woy / 52.18), np.cos(2 * np.pi * woy / 52.18)
    return out


def cum4_frame(f):
    """Target = log1p(sum of incidence over t+1..t+4) (NaN unless all 4 weeks are known)."""
    g = f.groupby("unit_id", sort=False)
    inc = np.expm1(f.y)
    s = sum(inc.groupby(f.unit_id).shift(-h) for h in HORIZONS)
    out = target_frame(f, 2).drop(columns=["target", "target_week"])  # season features centred on the 4-week window
    out["target"] = np.log1p(s)
    out["target_week"] = out.week + pd.Timedelta(weeks=4)
    return out


def graph_features(f, edges):
    """Leader signals for each follower at origin t: weighted mean of leaders' 4-week log-incidence growth and of their
    year-on-year anomaly, plus the number of leaders. Uses only leader values at weeks <= t."""
    Y = f.pivot(index="week", columns="unit_id", values="y")
    growth = Y.rolling(2, min_periods=1).mean() - Y.shift(4).rolling(2, min_periods=1).mean()
    anom = Y - Y.shift(52)
    out = pd.DataFrame(index=f.index, columns=GRAPH_FEATURES, dtype=float)
    out["n_leaders"] = 0.0
    if edges is None or edges.empty:
        return out
    for tgt, e in edges.groupby("target"):
        w = e.weight.abs().to_numpy()
        src = e.source.to_numpy()
        gr = (growth[src] * w).sum(axis=1, min_count=1) / w.sum()
        an = (anom[src] * w).sum(axis=1, min_count=1) / w.sum()
        idx = f.index[f.unit_id == tgt]
        wk = f.loc[idx, "week"]
        out.loc[idx, "leader_growth"] = gr.reindex(wk).to_numpy()
        out.loc[idx, "leader_anom"] = an.reindex(wk).to_numpy()
        out.loc[idx, "n_leaders"] = float(len(e))
    return out


def feature_columns(df, use_graph=True, use_env=True):
    cols = [c for g, cs in GROUPS.items() for c in cs if c in df.columns]
    if not use_graph:
        cols = [c for c in cols if c not in GRAPH_FEATURES]
    if not use_env:
        cols = [c for c in cols if c not in ENV_FEATURES]
    return cols


# ---------------------------------------------------------------- models

def fit_quantile_model(X, y, seed=0):
    m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=Q, tree_method="hist", n_estimators=150,
                         learning_rate=0.08, max_depth=4, min_child_weight=5, subsample=0.8, colsample_bytree=0.8,
                         enable_categorical=True, max_cat_to_onehot=1, random_state=seed)
    m.fit(X, y)
    return m


def predict_quantiles(m, X):
    return np.sort(m.predict(X).reshape(len(X), len(Q)), axis=1)


def usable(train, cols):
    """Drop features that are all-NaN in the training rows (e.g. IMERG or Sentinel-1 before GEE)."""
    return [c for c in cols if train[c].notna().any()]


def seasonal_naive(train, test):
    """Median = y(t+h-52); quantiles = median + empirical quantiles of the training residuals (log space)."""
    r = (train.target - train.ylast_year).dropna()
    off = np.quantile(r, Q) if len(r) else np.zeros(len(Q))
    return np.sort(test.ylast_year.to_numpy()[:, None] + off[None, :], axis=1)


def prob_exceed(qs, thr):
    """P(Y > thr) from quantiles (rows) by linear interpolation of the quantile function; clipped to [0.005, 0.995]."""
    out = np.empty(len(qs))
    for i, (q, t) in enumerate(zip(qs, thr)):
        if not np.isfinite(t) or np.isnan(q).any():
            out[i] = np.nan
        elif t <= q[0]:
            out[i] = 1 - Q[0] / 2
        elif t >= q[-1]:
            out[i] = (1 - Q[-1]) / 2
        else:
            out[i] = 1 - np.interp(t, q, Q)
    return np.clip(out, 0.005, 0.995)


def surge_thresholds(f, end):
    """Each unit's 90th percentile of 4-week incidence over windows fully inside the training data (<= end)."""
    inc = np.expm1(f.y)
    s4 = inc.groupby(f.unit_id).transform(lambda s: s.rolling(4, min_periods=4).sum())
    ok = (f.week <= end) & (f.week <= pd.Timestamp(MODEL_END))
    return s4[ok].groupby(f.unit_id[ok]).quantile(SURGE_PCTL).rename("surge_thr")


# ---------------------------------------------------------------- scoring

def to_cases(qlog, pop):
    return np.expm1(np.clip(qlog, 0, None)) * pop[:, None] / 1e5


def wis(qs, y):
    """Weighted interval score (Bracher et al. 2021) for 23 quantiles; qs (n, 23), y (n,)."""
    k = len(Q) // 2
    m = qs[:, IQ50]
    total = 0.5 * np.abs(y - m)
    for i in range(k):
        alpha = 2 * Q[i]
        lo, hi = qs[:, i], qs[:, -1 - i]
        is_ = (hi - lo) + (2 / alpha) * (lo - y) * (y < lo) + (2 / alpha) * (y - hi) * (y > hi)
        total = total + alpha / 2 * is_
    return total / (k + 0.5)


def coverage(qs, y, level):
    lo_i = int(np.argmin(np.abs(Q - (1 - level) / 2)))
    hi_i = int(np.argmin(np.abs(Q - (1 + level) / 2)))
    return ((y >= qs[:, lo_i]) & (y <= qs[:, hi_i])).astype(float)


# ---------------------------------------------------------------- rolling origin

def refit_dates(start="2018-01-07", end=MODEL_END, refit_weeks=13):
    return list(pd.date_range(start, end, freq=f"{refit_weeks}W-SUN"))


def rolling_origin(panel, start="2018-01-07", end=MODEL_END, refit_weeks=13, graph_method="pcmciplus", log=print):
    """Forecasts for every origin t in [start, end - h]. Returns (forecasts long frame, graphs per refit)."""
    f = base_features(panel)
    refits = refit_dates(start, end, refit_weeks)
    frames, graphs = {h: target_frame(f, h) for h in HORIZONS}, []
    frames["cum4"] = cum4_frame(f)
    out = []
    for k, R in enumerate(refits):
        nxt = refits[k + 1] if k + 1 < len(refits) else pd.Timestamp(end) + pd.Timedelta(weeks=1)
        edges, nodes, meta = leadlag.learn(panel, R, method=graph_method)
        graphs.append((edges, nodes, meta))
        gf = graph_features(f, edges)
        thr = surge_thresholds(f, R)
        log(f"  refit {R.date()}: graph {meta['n_edges']} edges (T={meta['T']}), forecasting origins < {nxt.date()}")
        for h, df in frames.items():
            hh = 4 if h == "cum4" else h
            d = pd.concat([df, gf], axis=1)
            train = d[(d.target_week <= R) & (d.target_week <= pd.Timestamp(MODEL_END)) & d.target.notna()]
            test = d[(d.week >= R) & (d.week < nxt) & (d.target_week <= pd.Timestamp(end))]
            if test.empty:
                continue
            res = test[["unit_id", "week", "target_week", "target", "pop"]].copy()
            res["horizon"], res["refit"] = h if h == "cum4" else int(h), R
            # ablations: no graph features; no rain / river / storm / flood features (graph kept)
            for name, use_graph, use_env in (("xgb_nograph", False, True), ("xgb", True, True), ("xgb_noenv", True, False)):
                if h == "cum4" and name == "xgb_noenv":
                    continue  # the surge model is not ablated
                if name == "xgb" and edges.empty:  # no lead-lag links in this window: the graph model is the ablation
                    res[name] = res["xgb_nograph"]
                    continue
                cols = usable(train, feature_columns(train, use_graph, use_env))
                m = fit_quantile_model(train[cols], train.target)
                res[name] = list(predict_quantiles(m, test[cols]))
            if h != "cum4":
                res["naive"] = list(seasonal_naive(train, test))
            else:
                res["surge_thr"] = res.unit_id.map(thr).to_numpy()
                for name in ("xgb", "xgb_nograph"):
                    res[f"R_{name}"] = prob_exceed(np.vstack(res[name]), np.log1p(res.surge_thr.to_numpy()))
            out.append(res)
    return pd.concat(out, ignore_index=True), graphs


def score_rows(mats, target, pop):
    """Per-row WIS / absolute error / 50% and 90% coverage on case counts. `mats`: {model: (n, 23) log1p-incidence
    quantiles}; a row with any NaN quantile scores NaN (coverage too), so models can be compared on the same rows."""
    y = np.expm1(target) * pop / 1e5
    rows = {}
    for name, qlog in mats.items():
        qs = to_cases(qlog, pop)
        bad = np.isnan(qs).any(axis=1)
        rows[f"wis_{name}"] = wis(qs, y)
        rows[f"ae_{name}"] = np.abs(qs[:, IQ50] - y)
        rows[f"cov50_{name}"] = np.where(bad, np.nan, coverage(qs, y, 0.5))
        rows[f"cov90_{name}"] = np.where(bad, np.nan, coverage(qs, y, 0.9))
    return y, rows


def score(fc):
    """Per-row WIS / coverage on case counts for each model; plus an online conformal 90% check on xgb."""
    fc = fc[fc.horizon != "cum4"].copy()
    fc = fc[fc.target.notna()]
    pop = fc["pop"].to_numpy()
    y, rows = score_rows({name: np.vstack(fc[name]) for name in MODELS}, fc.target.to_numpy(), pop)
    s = fc[["unit_id", "week", "target_week", "horizon", "refit"]].assign(cases=y, **rows)
    # online conformal (EnbPI-style check): 90% band = median +- the 90th pct of past |log errors| at this horizon,
    # using only forecasts whose target week is before the current origin
    med = np.vstack(fc.xgb)[:, IQ50]
    err = np.abs(fc.target.to_numpy() - med)
    cov = np.full(len(fc), np.nan)
    for h in HORIZONS:
        idx = np.flatnonzero(fc.horizon.to_numpy() == h)
        tw, wk = fc.target_week.to_numpy()[idx], fc.week.to_numpy()[idx]
        for j, i in enumerate(idx):
            past = err[idx][tw < wk[j]]
            if len(past) >= 200:
                r = np.quantile(past, 0.9)
                cov[i] = float(abs(fc.target.to_numpy()[i] - med[i]) <= r)
    s["cov90_conformal"] = cov
    return s


def summarise(s):
    def agg(d):
        # every model on the same rows: the naive baseline is NaN where y(t+h-52) is missing, and averaging each model
        # over its own non-NaN rows would make relWIS compare different samples
        d = d.dropna(subset=[f"wis_{m}" for m in MODELS])
        r = {"n": len(d)}
        for m in MODELS:
            r[f"WIS {m}"] = d[f"wis_{m}"].mean()
            r[f"MAE {m}"] = d[f"ae_{m}"].mean()
            r[f"cov50 {m}"] = d[f"cov50_{m}"].mean()
            r[f"cov90 {m}"] = d[f"cov90_{m}"].mean()
        r["relWIS xgb/naive"] = r["WIS xgb"] / r["WIS naive"]
        r["relWIS nograph/naive"] = r["WIS xgb_nograph"] / r["WIS naive"]
        r["relWIS xgb/nograph"] = r["WIS xgb"] / r["WIS xgb_nograph"]
        r["relWIS noenv/naive"] = r["WIS xgb_noenv"] / r["WIS naive"]
        r["relWIS xgb/noenv"] = r["WIS xgb"] / r["WIS xgb_noenv"]
        r["cov90 conformal"] = d.cov90_conformal.mean()
        return pd.Series(r)

    by_h = s.groupby("horizon").apply(agg)
    by_h.loc["all"] = agg(s)
    return by_h


class SurgeCalibrator:
    """Isotonic map from raw R to the observed surge frequency, fitted on past forecasts only. `fit_end` is the last
    target week (end of the 4-week window) among the fitted rows; `n` the number of past outcomes used."""

    def __init__(self, r, y, fit_end):
        self.iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip").fit(r, y)
        self.n, self.fit_end, self.base_rate = len(r), pd.Timestamp(fit_end), float(np.mean(y))

    def __call__(self, r):
        r = np.asarray(r, float)
        out = np.full(len(r), np.nan)
        ok = np.isfinite(r)
        if ok.any():  # sklearn rejects an empty array (every R NaN, e.g. no surge threshold at an origin)
            out[ok] = np.clip(self.iso.predict(r[ok]), *R_CLIP)
        return out


def fit_calibrator(r, y, target_week, end):
    """Calibrator fitted on rows whose outcome is known at `end` (target_week <= end, the same rule as model training:
    a week's cases are known at the end of that week). None if fewer than CAL_MIN_ROWS outcomes or a single class."""
    r, y, tw = np.asarray(r, float), np.asarray(y, float), pd.to_datetime(pd.Series(target_week)).to_numpy()
    past = (tw <= np.datetime64(pd.Timestamp(end))) & np.isfinite(r) & np.isfinite(y)
    if past.sum() < CAL_MIN_ROWS or np.unique(y[past]).size < 2:
        return None
    assert tw[past].max() <= np.datetime64(pd.Timestamp(end)), "calibration would use an outcome after its origin"
    return SurgeCalibrator(r[past], y[past], tw[past].max())


def cum4_eval(fc):
    """Rolling-origin surge forecasts (one row per unit x origin) with the observed surge and an expanding-window
    recalibrated R: each origin t is calibrated with a model fitted on forecasts whose target window ended by t
    (target_week <= t), so R_xgb_cal never uses an outcome later than its origin. Rows before CAL_MIN_ROWS past outcomes
    keep the raw R (cal_n = number of past outcomes available, R_cal_applied flags the calibrated rows)."""
    c = fc[fc.horizon == "cum4"][["unit_id", "week", "target_week", "refit", "target", "pop", "surge_thr", "R_xgb", "R_xgb_nograph"]].copy()
    c = c.reset_index(drop=True)
    known = c.target.notna() & c.surge_thr.notna()
    c["surge"] = (np.expm1(c.target) > c.surge_thr).astype(float).where(known)
    c["R_xgb_cal"] = c.R_xgb.to_numpy()
    c["R_cal_applied"] = False
    c["cal_n"] = 0
    c["cal_fit_end"] = pd.NaT
    for t in sorted(c.week.unique()):
        idx = c.index[c.week == t]
        n_past = int(((c.target_week <= t) & c.surge.notna() & c.R_xgb.notna()).sum())
        c.loc[idx, "cal_n"] = n_past
        cal = fit_calibrator(c.R_xgb, c.surge, c.target_week, t)
        if cal is None:
            continue
        c.loc[idx, "R_xgb_cal"] = cal(c.loc[idx, "R_xgb"])
        c.loc[idx, "R_cal_applied"] = True
        c.loc[idx, "cal_fit_end"] = cal.fit_end
    done = c.R_cal_applied
    assert (c.cal_fit_end[done] <= c.week[done]).all(), "leakage: a calibration was fitted on an outcome after its origin"
    return c


RELIABILITY_BINS = [0, .1, .2, .3, .5, .7, 1.0]


def _reliability(c, col):
    b = pd.cut(c[col], RELIABILITY_BINS, include_lowest=True)
    return c.groupby(b, observed=True).agg(n=("surge", "size"), mean_R=(col, "mean"), observed=("surge", "mean"))


def _brier(c, col):
    return float(((c[col] - c.surge) ** 2).mean())


def surge_calibration(fc, c=None):
    """Brier score and reliability of R on the evaluation weeks (observed surge = cum4 incidence > threshold), raw and
    recalibrated. Returns (summary dict, reliability table, cum4 frame). The keys `xgb` / `xgb_nograph` and the columns
    bin, n, mean_R, observed describe the raw R as before; `calibrated` and the *_cal columns are the recalibrated R."""
    c = cum4_eval(fc) if c is None else c
    s = c[c.surge.notna()].copy()
    out = {}
    for m in ("xgb", "xgb_nograph"):
        out[m] = dict(brier=_brier(s, f"R_{m}"), base_rate=float(s.surge.mean()),
                      brier_climatology=float(((s.surge.mean() - s.surge) ** 2).mean()))
    on = s[s.R_cal_applied]

    def block(d):
        return dict(n=int(len(d)), base_rate=float(d.surge.mean()), mean_R_raw=float(d.R_xgb.mean()),
                    mean_R_cal=float(d.R_xgb_cal.mean()), brier_raw=_brier(d, "R_xgb"), brier_cal=_brier(d, "R_xgb_cal"),
                    brier_climatology=float(((d.surge.mean() - d.surge) ** 2).mean()))

    out["calibrated"] = dict(
        model="xgb", method="isotonic regression of the observed surge on raw R, expanding window over past rolling-origin "
                            "forecasts with target_week <= origin; raw R kept until CAL_MIN_ROWS past outcomes",
        min_rows=CAL_MIN_ROWS, n_scored=int(len(s)), n_uncalibrated=int((~s.R_cal_applied).sum()),
        uncalibrated_origins=[str(pd.Timestamp(w).date()) for w in sorted(s.week[~s.R_cal_applied].unique())],
        first_calibrated_origin=str(pd.Timestamp(on.week.min()).date()) if len(on) else None,
        all_rows=block(s), calibrated_rows=block(on) if len(on) else None)
    rel = _reliability(s, "R_xgb")
    cal = _reliability(s, "R_xgb_cal").rename(columns=lambda k: f"{k}_cal")
    rel = rel.join(cal, how="left").reset_index().rename(columns={"R_xgb": "bin"})
    rel["bin"] = rel["bin"].astype(str)
    return out, rel, c


def surge_calibrator(train_end, path=None, log=print):
    """Calibrator for a production fit trained to `train_end`: isotonic on every persisted rolling-origin cum4 forecast
    (xgb) with target_week <= train_end. None (R stays raw) if the file is missing or too few outcomes; recorded."""
    path = Path(path) if path is not None else APP_DATA / CUM4_FILE
    end = pd.Timestamp(train_end)
    if not path.exists():
        return missing("surge_calibration", f"{path.name} not found (run build.py forecast): scenario R left uncalibrated")
    c = pd.read_parquet(path)
    cal = fit_calibrator(c.R_xgb, c.surge, c.target_week, end)
    if cal is None:
        n = int(((c.target_week <= end) & c.surge.notna()).sum())
        log(f"  surge calibration for train end {end.date()}: only {n} past outcomes (< {CAL_MIN_ROWS}): R left raw")
        return None
    assert cal.fit_end <= end
    record("surge_calibration", True, f"isotonic on {cal.n} past rolling-origin forecasts (target week <= {end.date()})")
    return cal


def calibrate_R(fc, cal):
    """Scenario hook: keep the model probability as R_raw and set R to the calibrated value (raw if cal is None)."""
    fc = fc.copy()
    fc["R_raw"] = fc.R.to_numpy()
    if cal is not None:
        fc["R"] = cal(fc.R_raw)
    fc["R_calibrated"] = cal is not None
    fc["R_cal_n"] = cal.n if cal is not None else 0
    return fc


# ---------------------------------------------------------------- benchmark models and the median ensemble

def eval_quantiles(fc):
    """The rolling-origin horizon 1-4 rows with every model's 23 quantiles (log1p incidence per 100k), so benchmark
    files can be scored and ensembled later without refitting XGBoost."""
    q = fc[fc.horizon != "cum4"][["unit_id", "week", "target_week", "horizon", "refit", "target", "pop"] + list(MODELS)].copy()
    q["horizon"] = q.horizon.astype(int)
    for m in MODELS:
        q[m] = [np.asarray(v) for v in q[m]]  # native dtype (xgb float32), so re-scoring reproduces score() exactly
    return q.reset_index(drop=True)


def _key(df):
    return pd.DataFrame({"unit_id": df.unit_id.astype(str).to_numpy(),
                         "week": pd.to_datetime(df.week).astype("datetime64[ns]").to_numpy(),
                         "horizon": df.horizon.astype(int).to_numpy()})


def load_bench(q, bench_dir=None, log=print):
    """Benchmark files bench_<model>.parquet (unit_id, week = origin Sunday, horizon 1-4, q = 23 sorted quantiles of
    log1p incidence per 100k) aligned to the rows of `q`. Returns ({model: (n, 23) array, NaN where absent}, meta).
    A file with the wrong schema is skipped with a warning, never fatal."""
    bench_dir = Path(bench_dir) if bench_dir is not None else APP_DATA
    keys = _key(q)
    mats, meta = {}, {}
    for p in sorted(bench_dir.glob(BENCH_GLOB)):
        name = p.stem[len("bench_"):]
        if name not in BENCH_MODELS:
            meta[name] = dict(file=p.name, ignored="variant: not in forecast.BENCH_MODELS")
            continue
        info = dict(file=p.name)
        js = p.with_suffix(".json")
        if js.exists():
            try:
                info["meta"] = json.loads(js.read_text(encoding="utf-8"))
            except ValueError as e:
                info["meta_error"] = str(e)
        try:
            b = pd.read_parquet(p)
            if not {"unit_id", "week", "horizon", "q"} <= set(b.columns):
                raise ValueError(f"columns {sorted(b.columns)}; need unit_id, week, horizon, q")
            if name in MODELS or name == ENSEMBLE or not name:
                raise ValueError(f"model name '{name}' clashes with a built-in model")
            arr = [np.asarray(v, float) if v is not None else np.full(len(Q), np.nan) for v in b.q]
            good = np.array([a.shape == (len(Q),) and np.isfinite(a).all() for a in arr])
            b = _key(b).assign(q=[np.sort(a) if g else None for a, g in zip(arr, good)])
            good &= b.horizon.isin(HORIZONS).to_numpy()
            dup = b[good].duplicated(["unit_id", "week", "horizon"]).sum()
            b = b[good].drop_duplicates(["unit_id", "week", "horizon"], keep="first")
            m = keys.merge(b, on=["unit_id", "week", "horizon"], how="left", validate="one_to_one")
            M = np.full((len(q), len(Q)), np.nan)
            hit = m.q.notna().to_numpy()
            if hit.any():
                M[hit] = np.vstack(m.q[hit].to_numpy())
            info.update(rows_in_file=int(len(arr)), rows_invalid=int((~good).sum()), rows_duplicate=int(dup),
                        rows_matched=int(hit.sum()), rows_eval=int(len(q)))
            if not hit.any():
                raise ValueError("no row matches a rolling-origin (unit_id, week, horizon)")
            mats[name] = M
            log(f"  bench {name}: {hit.sum():,} of {len(q):,} rolling-origin rows ({info['rows_invalid']} invalid rows dropped)")
        except Exception as e:  # a bad benchmark file must not block the build
            info["error"] = str(e)
            print(f"  WARNING bench file {p.name} skipped: {e}")
        meta[name] = info
    return mats, meta


def evaluate_models(q, bench_dir=None, log=print):
    """Score xgb, its ablations, the seasonal-naive baseline, every benchmark file and the median ensemble (element-wise
    median of the 23 quantiles over xgb + all benchmarks, re-sorted, only on rows where all of them exist) on the same
    rows: those where every model has a score. Returns (model x horizon table, fan-chart bands for the benchmarks and the
    ensemble (None without benchmarks), meta). With no benchmark file the table holds the built-in models only, on the
    rows of eval_summary.csv, and there is no ensemble (a median of xgb alone is xgb)."""
    bench, meta = load_bench(q, bench_dir, log)
    mats = {m: np.vstack(q[m].to_numpy()) for m in MODELS}
    mats.update(bench)
    members = ["xgb"] + list(bench)
    if bench:
        mats[ENSEMBLE] = np.sort(np.median(np.stack([mats[m] for m in members]), axis=0), axis=1)  # NaN unless all present
    kind = {m: "ablation" if m.startswith("xgb_") else "baseline" if m == "naive" else "model" for m in MODELS}
    kind.update({m: "benchmark" for m in bench}, **({ENSEMBLE: "ensemble"} if bench else {}))
    sc = q[q.target.notna()].reset_index(drop=True)
    keep = q.target.notna().to_numpy()
    y, rows = score_rows({m: v[keep] for m, v in mats.items()}, sc.target.to_numpy(), sc["pop"].to_numpy())
    s = pd.DataFrame(rows).assign(horizon=sc.horizon.to_numpy())
    base_ok = s[[f"wis_{m}" for m in MODELS]].notna().all(axis=1)
    same = s[[f"wis_{m}" for m in mats]].notna().all(axis=1)
    out = []
    for h, d in [(h, s[same & (s.horizon == h)]) for h in HORIZONS] + [("all", s[same])]:
        for m in mats:
            n_model = int(s.loc[base_ok & ((s.horizon == h) if h != "all" else True), f"wis_{m}"].notna().sum())
            out.append(dict(model=m, kind=kind[m], horizon=str(h), n=len(d), WIS=d[f"wis_{m}"].mean(), MAE=d[f"ae_{m}"].mean(),
                            cov50=d[f"cov50_{m}"].mean(), cov90=d[f"cov90_{m}"].mean(),
                            relWIS_vs_naive=d[f"wis_{m}"].mean() / d.wis_naive.mean(),
                            relWIS_vs_xgb=d[f"wis_{m}"].mean() / d.wis_xgb.mean(), n_model_rows=n_model))
    tab = pd.DataFrame(out)
    meta = dict(models=list(mats), benchmarks=meta, ensemble=dict(name=ENSEMBLE, members=members) if bench else None,
                n_base_rows=int(base_ok.sum()), n_common_rows=int(same.sum()),
                note="every model scored on the same rows (all models have a score); WIS on case counts")
    bands = None
    if bench:
        bands = q[["unit_id", "week", "target_week", "horizon"]].copy()
        bands["cases"] = np.expm1(q.target.to_numpy()) * q["pop"].to_numpy() / 1e5
        pop = q["pop"].to_numpy()
        for m in list(bench) + [ENSEMBLE]:
            cases = to_cases(mats[m], pop)
            for k, i in BAND.items():
                bands[f"{m}_{k}"] = cases[:, i]
    return tab, bands, meta


# ---------------------------------------------------------------- production fit (for scenarios and the dashboard)

def fit_at(panel, origin, graph_method="pcmciplus", boot=0):
    """Fit all models with data up to min(origin, MODEL_END) and return a predictor for that origin."""
    origin = pd.Timestamp(origin)
    end = min(origin, pd.Timestamp(MODEL_END))
    f = base_features(panel)
    edges, nodes, meta = leadlag.learn(panel, end, method=graph_method, boot=boot)
    gf = graph_features(f, edges)
    thr = surge_thresholds(f, end)
    models, frames = {}, {}
    for h in list(HORIZONS) + ["cum4"]:
        df = pd.concat([cum4_frame(f) if h == "cum4" else target_frame(f, h), gf], axis=1)
        frames[h] = df  # kept for predict_at: it only needs the origin rows, for any number of scenarios
        train = df[(df.target_week <= end) & df.target.notna()]
        cols = usable(train, feature_columns(train, True))
        models[h] = (fit_quantile_model(train[cols], train.target), cols)
    return dict(origin=origin, train_end=end, edges=edges, nodes=nodes, meta=meta, thr=thr, models=models, frames=frames)


def predict_at(fitted, overrides=None):
    """Forecast every unit from the fitted origin. `overrides`: DataFrame unit_id + feature columns replacing the
    origin-week values (used for shifted storm tracks). Returns one row per unit with quantiles, R and SHAP drivers."""
    rows = None
    for h, (m, cols) in fitted["models"].items():
        df = fitted["frames"][h]
        X = df[df.week == fitted["origin"]].copy()
        if overrides is not None:
            o = overrides.set_index("unit_id")
            for c in o.columns:
                if c in X.columns:
                    X[c] = X.unit_id.map(o[c]).fillna(X[c]).to_numpy()
        q = predict_quantiles(m, X[cols])
        if rows is None:
            rows = X[["unit_id", "pop"]].reset_index(drop=True)
        rows[f"q_{h}"] = list(q)
        if h == "cum4":
            thr = rows.unit_id.map(fitted["thr"]).to_numpy()
            rows["surge_thr"] = thr
            rows["R"] = prob_exceed(q, np.log1p(thr))
            contrib = m.get_booster().predict(xgb.DMatrix(X[cols], enable_categorical=True), pred_contribs=True)
            contrib = contrib[:, IQ50, :] if contrib.ndim == 3 else contrib
            grp = {g: [i for i, c in enumerate(cols) if c in cs] for g, cs in GROUPS.items()}
            for g, ii in grp.items():
                rows[f"shap_{g}"] = contrib[:, ii].sum(axis=1) if ii else 0.0
    return rows
