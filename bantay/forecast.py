"""Forecast: pooled multi-quantile XGBoost, 1-4 weeks ahead, with rolling-origin evaluation and WIS scoring.

Target: y = log1p(incidence per 100k) at t+h. One model per horizon outputs the 23 FluSight quantiles (sorted to stop
crossing); quantiles are back-transformed to cases with the unit's population, which preserves them. A second model
predicts the 4-week cumulative incidence directly, giving the surge probability R = P(next-4-week incidence > the unit's
90th percentile of 4-week incidence in the training window).

Rolling origin (never a random split): the model, the lead-lag graph and the surge thresholds are refit every
`refit_weeks` on data up to the refit date only, and forecast every origin until the next refit. Training targets never
go past the refit date, and 2020 is never a target (COVID reporting collapse). Compared against a seasonal-naive
baseline (same week last year, empirical quantiles of its training errors) and an ablation without graph features.
"""

import numpy as np
import pandas as pd
import xgboost as xgb

from .config import QUANTILES, MODEL_END
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


def score(fc):
    """Per-row WIS / coverage on case counts for each model; plus an online conformal 90% check on xgb."""
    fc = fc[fc.horizon != "cum4"].copy()
    fc = fc[fc.target.notna()]
    pop = fc["pop"].to_numpy()
    y = np.expm1(fc.target.to_numpy()) * pop / 1e5
    rows = {}
    for name in MODELS:
        qs = to_cases(np.vstack(fc[name]), pop)
        rows[f"wis_{name}"] = wis(qs, y)
        rows[f"ae_{name}"] = np.abs(qs[:, IQ50] - y)
        rows[f"cov50_{name}"] = coverage(qs, y, 0.5)
        rows[f"cov90_{name}"] = coverage(qs, y, 0.9)
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


def surge_calibration(fc):
    """Brier score and reliability of R on the evaluation weeks (observed surge = cum4 incidence > threshold)."""
    c = fc[(fc.horizon == "cum4") & fc.target.notna()].copy()
    c["surge"] = (np.expm1(c.target) > c.surge_thr).astype(float)
    out = {}
    for m in ("xgb", "xgb_nograph"):
        r = c[f"R_{m}"]
        out[m] = dict(brier=float(((r - c.surge) ** 2).mean()), base_rate=float(c.surge.mean()),
                      brier_climatology=float(((c.surge.mean() - c.surge) ** 2).mean()))
    c["bin"] = pd.cut(c.R_xgb, [0, .1, .2, .3, .5, .7, 1.0], include_lowest=True)
    rel = c.groupby("bin", observed=True).agg(n=("surge", "size"), mean_R=("R_xgb", "mean"), observed=("surge", "mean")).reset_index()
    rel["bin"] = rel["bin"].astype(str)
    return out, rel


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
