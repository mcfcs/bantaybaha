"""bantay.forecast: scoring (WIS, coverage, surge probability), the seasonal-naive baseline, leak-free features and
targets, surge thresholds, R calibration on past outcomes only, benchmark loading and the median ensemble, and the
rolling-origin / production-fit training windows (with a stand-in model, so no XGBoost fit is needed)."""

import json

import numpy as np
import pandas as pd
import pytest

from bantay import forecast as F, leadlag
from bantay.config import MODEL_END, QUANTILES

pytestmark = pytest.mark.usefixtures("isolated_status")
Q = np.array(QUANTILES)


# ---------------------------------------------------------------- scoring

def pinball(qs, y):
    return ((y[:, None] < qs) - Q[None, :]) * (qs - y[:, None])


def test_wis_perfect_point_forecast_is_zero():
    y = np.array([0.0, 3.0, 120.0])
    assert F.wis(np.repeat(y[:, None], 23, axis=1), y).tolist() == [0.0, 0.0, 0.0]


def test_wis_of_a_point_forecast_is_the_absolute_error():
    qs = np.full((2, 23), 10.0)
    assert F.wis(qs, np.array([4.0, 13.0])) == pytest.approx([6.0, 3.0])


def test_wis_hand_computed_interval():
    qs = np.tile(100 * Q, (1, 1))  # quantile at level tau = 100 tau
    # y = 50 (the median): every interval covers it, WIS = sum_k alpha_k/2 * width_k / (K + 1/2)
    widths = [100 * (1 - 2 * a) for a in Q[:11]]
    expected = sum((2 * a) / 2 * w for a, w in zip(Q[:11], widths)) / 11.5
    assert F.wis(qs, np.array([50.0]))[0] == pytest.approx(expected)
    assert expected == pytest.approx(pinball(qs, np.array([50.0])).sum() / 11.5)
    assert expected == pytest.approx(85.855 / 11.5)  # 0.01 x 98 + 0.025 x 95 + 0.05 x 90 + ... + 0.45 x 10


def test_wis_equals_mean_pinball_loss_identity():
    rng = np.random.default_rng(0)
    qs = np.sort(rng.normal(size=(200, 23)) * 5, axis=1)
    y = rng.normal(size=200) * 6
    assert F.wis(qs, y) == pytest.approx(pinball(qs, y).sum(axis=1) / 11.5)


def test_coverage_uses_the_matching_quantiles_inclusively():
    qs = np.tile(100 * Q, (5, 1))  # 90%: [5, 95]; 50%: [25, 75]
    y = np.array([5.0, 95.0, 4.9, 95.1, 50.0])
    assert F.coverage(qs, y, 0.9).tolist() == [1, 1, 0, 0, 1]
    assert F.coverage(qs, y, 0.5).tolist() == [0, 0, 0, 0, 1]


def test_prob_exceed_tails_monotone_and_clipped():
    q = 100 * Q
    thr = np.linspace(-10, 110, 400)
    p = F.prob_exceed(np.tile(q, (len(thr), 1)), thr)
    assert (np.diff(p) <= 1e-12).all()  # non-increasing in the threshold
    assert p.min() >= 0.005 and p.max() <= 0.995
    assert F.prob_exceed(q[None], [-1.0])[0] == pytest.approx(0.995)  # below every quantile
    assert F.prob_exceed(q[None], [200.0])[0] == pytest.approx(0.005)  # above every quantile
    assert F.prob_exceed(q[None], [50.0])[0] == pytest.approx(0.5)
    assert F.prob_exceed(q[None], [80.0])[0] == pytest.approx(0.2)
    assert np.isnan(F.prob_exceed(q[None], [np.nan])[0])
    bad = q.copy()
    bad[3] = np.nan
    assert np.isnan(F.prob_exceed(bad[None], [50.0])[0])


def test_score_rows_nan_rows_are_nan():
    qs = np.tile(np.log1p(100 * Q), (3, 1))
    qs[1, 4] = np.nan
    y, rows = F.score_rows({"m": qs}, np.log1p(np.array([50.0, 50.0, 50.0])), np.full(3, 1e5))
    assert y == pytest.approx([50.0, 50.0, 50.0])  # incidence per 100k x pop 100k = cases
    assert np.isnan(rows["wis_m"][1]) and np.isnan(rows["cov90_m"][1]) and np.isnan(rows["cov50_m"][1])
    assert rows["cov90_m"][0] == 1 and rows["ae_m"][0] == pytest.approx(0, abs=1e-9)


def test_to_cases_back_transform():
    q = np.array([[0.0, np.log1p(10.0), -0.5]])  # negative log incidence is clipped to 0 cases
    assert F.to_cases(q, np.array([2e5]))[0] == pytest.approx([0.0, 20.0, 0.0])


# ---------------------------------------------------------------- seasonal naive

def test_seasonal_naive_adds_training_residual_quantiles():
    train = pd.DataFrame({"target": [1.0, 2.0, 3.0, np.nan], "ylast_year": [1.0, 1.0, 1.0, 1.0]})
    test = pd.DataFrame({"ylast_year": [2.0, np.nan]})
    out = F.seasonal_naive(train, test)
    off = np.quantile([0.0, 1.0, 2.0], Q)
    assert out.shape == (2, 23)
    assert out[0] == pytest.approx(2.0 + off)
    assert out[0, F.IQ50] == pytest.approx(3.0)  # median = last year + median residual
    assert np.isnan(out[1]).all()
    assert (np.diff(out[0]) >= 0).all()


def test_seasonal_naive_without_training_residuals_is_last_year():
    out = F.seasonal_naive(pd.DataFrame({"target": [np.nan], "ylast_year": [1.0]}), pd.DataFrame({"ylast_year": [0.7]}))
    assert out[0] == pytest.approx(np.full(23, 0.7))


# ---------------------------------------------------------------- features and targets

TIME_COLS = ["incidence", "chirps_7d", "imerg_7d", "chirps_3d", "river_up_7d", "river_excess_7d", "storm_gale_hit",
             "storm_max_wind_near_kt", "storm_min_dist_km", "storm_hazard_exposure", "s1_flood_frac"]


def make_panel(n_units=3, start="2016-01-10", end="2020-03-29", seed=0):
    rng = np.random.default_rng(seed)
    wk = pd.date_range(start, end, freq="W-SUN")
    p = pd.MultiIndex.from_product([[f"U{i}" for i in range(n_units)], wk], names=["unit_id", "week"]).to_frame(index=False)
    n = len(p)
    season = 1 + np.sin(2 * np.pi * p.week.dt.dayofyear / 365.25)
    p["incidence"] = rng.gamma(2, 2, n) * season
    p["pop"] = p.unit_id.map({f"U{i}": 1e5 * (i + 1) for i in range(n_units)})
    for c in TIME_COLS[1:]:
        p[c] = rng.gamma(2, 10, n)
    p["storm_gale_hit"] = (rng.random(n) < 0.05).astype(float)
    p["s1_flood_frac"] = np.where(rng.random(n) < 0.02, rng.random(n), np.nan)
    for c in ("hazard_any_5yr", "hazard_any_25yr", "hazard_high_25yr"):
        p[c] = p.unit_id.map({f"U{i}": 0.1 * (i + 1) for i in range(n_units)})
    return p


def perturb_after(p, t0, seed=1):
    rng = np.random.default_rng(seed)
    p = p.copy()
    late = p.week > pd.Timestamp(t0)
    for c in TIME_COLS:
        p.loc[late, c] = rng.gamma(3, 50, late.sum())
    return p


T0 = pd.Timestamp("2018-06-03")


def test_base_features_use_no_future_values():
    p = make_panel()
    a, b = F.base_features(p), F.base_features(perturb_after(p, T0))
    k = a.week <= T0
    pd.testing.assert_frame_equal(a[k], b[k])
    static = ["unit", "week", "unit_id", "pop", "log_pop"]
    assert not a[~k].drop(columns=static).equals(b[~k].drop(columns=static))  # the perturbation did reach later rows


@pytest.mark.parametrize("h", [1, 2, 3, 4])
def test_target_frame_features_at_t_never_use_t_plus_h(h):
    p = make_panel()
    fa, fb = F.base_features(p), F.base_features(perturb_after(p, T0))
    a, b = F.target_frame(fa, h), F.target_frame(fb, h)
    k = a.week <= T0
    pd.testing.assert_frame_equal(a[k].drop(columns="target"), b[k].drop(columns="target"))
    # the target is the future: it changes exactly where t + h passes T0
    changed = ~np.isclose(a.target, b.target, equal_nan=True)
    assert (changed[k] == (a.week[k] + pd.Timedelta(weeks=h) > T0)).all()
    assert (a.target_week - a.week == pd.Timedelta(weeks=h)).all()


def test_target_frame_values():
    f = F.base_features(make_panel())
    t = F.target_frame(f, 2)
    y = f.set_index(["unit_id", "week"]).y
    r = t.iloc[150]
    assert r.target == pytest.approx(y[(r.unit_id, r.week + pd.Timedelta(weeks=2))])
    assert r.ylast_year == pytest.approx(y[(r.unit_id, r.week + pd.Timedelta(weeks=2 - 52))])
    last = t.groupby("unit_id").tail(2)  # t + 2 is past the unit's last week: no borrowing from the next unit
    assert last.target.isna().all()


def test_cum4_target_is_the_next_four_weeks():
    f = F.base_features(make_panel())
    c = F.cum4_frame(f)
    inc = f.set_index(["unit_id", "week"]).y.pipe(np.expm1)
    r = c.iloc[200]
    s = sum(inc[(r.unit_id, r.week + pd.Timedelta(weeks=h))] for h in (1, 2, 3, 4))
    assert r.target == pytest.approx(np.log1p(s))
    assert (c.target_week - c.week == pd.Timedelta(weeks=4)).all()
    assert c.groupby("unit_id").tail(4).target.isna().all()
    fb = F.base_features(perturb_after(make_panel(), T0))
    b = F.cum4_frame(fb)
    k = c.week <= T0
    pd.testing.assert_frame_equal(c[k].drop(columns="target"), b[k].drop(columns="target"))


def test_cum4_target_nan_unless_all_four_weeks_known():
    p = make_panel()
    p.loc[(p.unit_id == "U0") & (p.week == pd.Timestamp("2017-03-05")), "incidence"] = np.nan
    c = F.cum4_frame(F.base_features(p)).set_index(["unit_id", "week"])
    for w in pd.date_range("2017-02-05", "2017-02-26", freq="W-SUN"):  # windows that contain 03-05
        assert np.isnan(c.loc[("U0", w), "target"])
    assert np.isfinite(c.loc[("U0", pd.Timestamp("2017-03-05")), "target"])


def test_surge_thresholds_use_only_weeks_up_to_end():
    p = make_panel()
    end = pd.Timestamp("2018-01-07")
    f = F.base_features(p)
    thr = F.surge_thresholds(f, end)
    thr_b = F.surge_thresholds(F.base_features(perturb_after(p, end)), end)
    pd.testing.assert_series_equal(thr, thr_b)
    u0 = p[(p.unit_id == "U0")].set_index("week").incidence
    s4 = u0.rolling(4, min_periods=4).sum()
    assert thr["U0"] == pytest.approx(s4[s4.index <= end].quantile(F.SURGE_PCTL))
    late = F.surge_thresholds(f, pd.Timestamp("2021-01-10"))  # never past MODEL_END either
    assert late["U0"] == pytest.approx(s4[s4.index <= pd.Timestamp(MODEL_END)].quantile(F.SURGE_PCTL))


def test_graph_features_follow_the_leader_and_ignore_the_future():
    p = make_panel()
    edges = pd.DataFrame({"source": ["U0"], "target": ["U1"], "lag": [1], "weight": [-0.4]})
    f = F.base_features(p)
    g = F.graph_features(f, edges)
    Y = f.pivot(index="week", columns="unit_id", values="y")
    growth = Y.rolling(2, min_periods=1).mean() - Y.shift(4).rolling(2, min_periods=1).mean()
    i = f.index[(f.unit_id == "U1")][100]
    assert g.loc[i, "leader_growth"] == pytest.approx(growth.loc[f.loc[i, "week"], "U0"])
    assert g.loc[i, "n_leaders"] == 1
    assert g.loc[f.unit_id == "U0", "n_leaders"].eq(0).all() and g.loc[f.unit_id == "U0", "leader_growth"].isna().all()
    gb = F.graph_features(F.base_features(perturb_after(p, T0)), edges)
    k = f.week <= T0
    pd.testing.assert_frame_equal(g[k], gb[k])
    empty = F.graph_features(f, edges.iloc[:0])
    assert (empty.n_leaders == 0).all() and empty.leader_growth.isna().all()


def test_feature_columns_ablations():
    df = pd.DataFrame(columns=["y0", "woy", "chirps_7d_l0", "storm_gale_4w", "leader_growth", "unit", "junk"])
    assert "junk" not in F.feature_columns(df)
    assert "leader_growth" not in F.feature_columns(df, use_graph=False)
    no_env = F.feature_columns(df, use_env=False)
    assert "chirps_7d_l0" not in no_env and "storm_gale_4w" not in no_env and "y0" in no_env
    train = pd.DataFrame({"a": [np.nan, np.nan], "b": [1.0, np.nan]})
    assert F.usable(train, ["a", "b"]) == ["b"]


def test_refit_dates():
    r = F.refit_dates()
    assert r[0] == pd.Timestamp("2018-01-07") and r[-1] <= pd.Timestamp(MODEL_END)
    assert len(r) == len(pd.date_range("2018-01-07", MODEL_END, freq="13W-SUN")) and all(d.weekday() == 6 for d in r)
    assert set(np.diff(r)) == {pd.Timedelta(weeks=13)}


# ---------------------------------------------------------------- training windows (stand-in model)

class FakeModel:
    def predict(self, X):
        return np.tile(np.log1p(Q * 10), (len(X), 1))


@pytest.fixture
def spy(monkeypatch):
    """Record each fit's refit date / training end and the latest target week in its training rows."""
    log = dict(ends=[], fits=[])

    def learn(panel, end, method="pcmciplus", boot=0):
        log["ends"].append(pd.Timestamp(end))
        nodes = pd.DataFrame({"unit_id": sorted(panel.unit_id.unique())})
        return pd.DataFrame(columns=leadlag.EDGE_COLS), nodes, dict(n_edges=0, T=0)

    real_usable = F.usable

    def usable(train, cols):
        log["fits"].append((log["ends"][-1], train.target_week.max(), len(train)))
        return real_usable(train, cols)

    monkeypatch.setattr(leadlag, "learn", learn)
    monkeypatch.setattr(F, "usable", usable)
    monkeypatch.setattr(F, "fit_quantile_model", lambda X, y, seed=0: FakeModel())
    return log


def test_rolling_origin_trains_only_on_past_targets(spy):
    fc, graphs = F.rolling_origin(make_panel(), log=lambda *a: None)
    assert spy["ends"] == F.refit_dates()
    assert spy["fits"] and all(tw <= R and tw <= pd.Timestamp(MODEL_END) for R, tw, n in spy["fits"])
    assert all(n > 0 for _, _, n in spy["fits"])
    nxt = {R: N for R, N in zip(F.refit_dates(), F.refit_dates()[1:] + [pd.Timestamp(MODEL_END) + pd.Timedelta(weeks=1)])}
    assert (fc.week >= fc.refit).all() and (fc.week < fc.refit.map(nxt)).all()  # each origin uses the latest refit
    assert (fc.target_week <= pd.Timestamp(MODEL_END)).all()
    assert set(fc.horizon) == {1, 2, 3, 4, "cum4"}
    h = fc[fc.horizon != "cum4"]
    assert (h.target_week - h.week == pd.to_timedelta(h.horizon.astype(int) * 7, unit="D")).all()
    c = fc[fc.horizon == "cum4"]
    assert c.R_xgb.between(0.005, 0.995).all() and c.surge_thr.notna().all()
    assert len(graphs) == len(F.refit_dates())


@pytest.mark.parametrize("origin, end", [("2018-09-16", "2018-09-16"), ("2020-11-15", MODEL_END)])
def test_fit_at_trains_to_min_origin_model_end(spy, origin, end):
    p = make_panel(end="2020-12-27")
    fitted = F.fit_at(p, origin)
    end = pd.Timestamp(end)
    assert fitted["train_end"] == end and spy["ends"] == [end]
    assert len(spy["fits"]) == 5 and all(tw <= end for _, tw, _ in spy["fits"])
    pd.testing.assert_series_equal(fitted["thr"], F.surge_thresholds(F.base_features(p), end))


# ---------------------------------------------------------------- R calibration

def cal_rows(n_past=1000, n_future=500, seed=0):
    rng = np.random.default_rng(seed)
    end = pd.Timestamp("2019-01-06")
    r = rng.random(n_past + n_future)
    y = (rng.random(len(r)) < r).astype(float)  # calibrated-ish past
    tw = np.r_[end - pd.to_timedelta(rng.integers(0, 50, n_past) * 7, unit="D"),
               end + pd.to_timedelta(rng.integers(1, 50, n_future) * 7, unit="D")]
    y[n_past:] = 1 - (r[n_past:] > 0.5)  # adversarial future outcomes: would flip the map if used
    return r, y, pd.to_datetime(tw), end


def test_fit_calibrator_ignores_outcomes_after_the_cutoff():
    r, y, tw, end = cal_rows()
    cal = F.fit_calibrator(r, y, tw, end)
    past = np.asarray(tw <= end)
    ref = F.fit_calibrator(r[past], y[past], tw[past], end)
    grid = np.linspace(0, 1, 101)
    assert cal(grid) == pytest.approx(ref(grid))
    assert cal.n == past.sum() and cal.fit_end <= end
    assert (np.diff(cal(grid)) >= -1e-12).all()  # isotonic
    assert cal(grid).min() >= F.R_CLIP[0] and cal(grid).max() <= F.R_CLIP[1]
    mixed = cal([np.nan, 0.5])
    assert np.isnan(mixed[0]) and np.isfinite(mixed[1])


def test_calibrator_on_all_nan_input_returns_nan():
    r, y, tw, end = cal_rows()
    cal = F.fit_calibrator(r, y, tw, end)
    assert np.isnan(cal([np.nan, np.nan])).all()


def test_fit_calibrator_needs_enough_rows_and_both_classes():
    r, y, tw, end = cal_rows(n_past=F.CAL_MIN_ROWS - 1)
    assert F.fit_calibrator(r, y, tw, end) is None
    r, y, tw, end = cal_rows(n_past=F.CAL_MIN_ROWS)
    assert F.fit_calibrator(r, y, tw, end) is not None
    assert F.fit_calibrator(r, np.zeros_like(y), tw, end) is None  # one class only
    r[:5] = np.nan  # NaN forecasts do not count as outcomes
    assert F.fit_calibrator(r, y, tw, end) is None


def test_surge_calibrator_reads_past_rows_only(tmp_path):
    r, y, tw, end = cal_rows()
    p = tmp_path / "eval_cum4.parquet"
    pd.DataFrame({"R_xgb": r, "surge": y, "target_week": tw}).to_parquet(p)
    cal = F.surge_calibrator(end, path=p, log=lambda *a: None)
    assert cal.n == int((tw <= end).sum()) and cal.fit_end <= end
    early = F.surge_calibrator(end - pd.Timedelta(weeks=45), path=p, log=lambda *a: None)
    assert early is None  # too few outcomes before that training end: R stays raw
    assert F.surge_calibrator(end, path=tmp_path / "absent.parquet") is None


def test_calibrate_R_keeps_raw():
    fc = pd.DataFrame({"R": [0.1, 0.6, 0.95]})
    raw = F.calibrate_R(fc, None)
    assert raw.R.tolist() == raw.R_raw.tolist() == [0.1, 0.6, 0.95]
    assert not raw.R_calibrated.any() and (raw.R_cal_n == 0).all()
    r, y, tw, end = cal_rows()
    cal = F.fit_calibrator(r, y, tw, end)
    out = F.calibrate_R(fc, cal)
    assert out.R_raw.tolist() == [0.1, 0.6, 0.95] and out.R.tolist() == pytest.approx(list(cal(fc.R)))
    assert out.R_calibrated.all() and (out.R_cal_n == cal.n).all()
    assert fc.columns.tolist() == ["R"]  # input untouched


def cum4_fc(n_units=100, n_weeks=30, seed=0):
    rng = np.random.default_rng(seed)
    wk = pd.date_range("2018-01-07", periods=n_weeks, freq="W-SUN")
    fc = pd.MultiIndex.from_product([range(n_units), wk], names=["unit_id", "week"]).to_frame(index=False)
    fc["horizon"] = "cum4"
    fc["target_week"] = fc.week + pd.Timedelta(weeks=4)
    fc["refit"] = wk[0]
    fc["pop"] = 1e5
    fc["surge_thr"] = 10.0
    fc["R_xgb"] = rng.random(len(fc))
    fc["R_xgb_nograph"] = fc.R_xgb
    fc["target"] = np.log1p(np.where(rng.random(len(fc)) < fc.R_xgb, 20.0, 5.0))
    return fc


FIRST_CAL = -(-F.CAL_MIN_ROWS // 100) + 3  # 100 units in cum4_fc


def test_cum4_eval_expanding_window_is_leak_free():
    fc = cum4_fc()
    c = F.cum4_eval(fc)
    assert (c.surge == (np.expm1(c.target) > c.surge_thr)).all()
    on = c[c.R_cal_applied]
    assert len(on) and (on.cal_fit_end <= on.week).all()
    off = c[~c.R_cal_applied]
    assert (off.R_xgb_cal == off.R_xgb).all() and (off.cal_n < F.CAL_MIN_ROWS).all()
    assert (on.cal_n >= F.CAL_MIN_ROWS).all()
    # origin k (0-based) has 100 units x (k - 3) known 4-week windows: calibrated from the first k reaching CAL_MIN_ROWS
    assert on.week.min() == sorted(fc.week.unique())[FIRST_CAL]
    # changing outcomes whose window ends after t leaves R at t unchanged
    t = pd.Timestamp(sorted(fc.week.unique())[20])
    fb = fc.copy()
    late = fb.target_week > t
    fb.loc[late, "target"] = np.log1p(np.where(fb.loc[late, "R_xgb"] > 0.5, 0.0, 50.0))
    cb = F.cum4_eval(fb)
    k = c.week <= t
    assert c.R_xgb_cal[k].tolist() == pytest.approx(cb.R_xgb_cal[k].tolist())
    assert not np.allclose(c.R_xgb_cal[~k], cb.R_xgb_cal[~k])


def test_surge_calibration_summary():
    out, rel, c = F.surge_calibration(cum4_fc())
    assert out["calibrated"]["min_rows"] == F.CAL_MIN_ROWS
    assert out["calibrated"]["n_uncalibrated"] == FIRST_CAL * 100
    assert 0 <= out["xgb"]["brier"] <= 1 and set(rel.columns) >= {"bin", "n", "mean_R", "observed", "observed_cal"}


# ---------------------------------------------------------------- benchmarks and the ensemble

def eval_q(n_units=4, n_weeks=6, seed=0):
    rng = np.random.default_rng(seed)
    wk = pd.date_range("2018-01-07", periods=n_weeks, freq="W-SUN")
    q = pd.MultiIndex.from_product([[f"U{i}" for i in range(n_units)], wk, [1, 2]], names=["unit_id", "week", "horizon"]).to_frame(index=False)
    q["target_week"] = q.week + pd.to_timedelta(q.horizon * 7, unit="D")
    q["refit"] = wk[0]
    q["target"] = np.log1p(rng.gamma(2, 2, len(q)))
    q["pop"] = 1e5
    for i, m in enumerate(F.MODELS):
        q[m] = [np.sort(np.log1p(rng.gamma(2, 2, 23)) + 0.1 * i) for _ in range(len(q))]
    return q


def bench_file(d, name, q, rows=None, **kw):
    b = q[["unit_id", "week", "horizon"]].copy() if rows is None else rows
    rng = np.random.default_rng(len(name))
    b["q"] = [rng.permutation(np.log1p(rng.gamma(2, 2, 23))) for _ in range(len(b))]  # unsorted on purpose
    for k, v in kw.items():
        b[k] = v
    b.to_parquet(d / f"bench_{name}.parquet")
    return b


def test_load_bench_schema_variants_and_sorting(tmp_path, capsys):
    q = eval_q()
    good = bench_file(tmp_path, "chronos2", q, q[["unit_id", "week", "horizon"]].iloc[::2].copy())
    (tmp_path / "bench_chronos2.json").write_text(json.dumps({"model": "test"}), encoding="utf-8")
    bench_file(tmp_path, "chronos2_log1p", q)  # a variant: never joins
    pd.DataFrame({"unit_id": ["U0"], "week": [q.week[0]], "horizon": [1]}).to_parquet(tmp_path / "bench_tabpfn_ts.parquet")  # no q
    m = q[["unit_id", "week", "horizon"]].copy()
    mp = bench_file(tmp_path, "mpnn_lstm", q, m)
    mp.at[0, "q"] = np.zeros(5)  # wrong length -> invalid
    mp = pd.concat([mp, mp.iloc[[3]], mp.iloc[[4]].assign(horizon=7)], ignore_index=True)  # a duplicate, a bad horizon
    mp.to_parquet(tmp_path / "bench_mpnn_lstm.parquet")
    mats, meta = F.load_bench(q, tmp_path, log=lambda *a: None)
    assert set(mats) == {"chronos2", "mpnn_lstm"}
    assert "ignored" in meta["chronos2_log1p"] and "error" in meta["tabpfn_ts"]
    assert "WARNING bench file bench_tabpfn_ts.parquet skipped" in capsys.readouterr().out
    assert meta["chronos2"]["meta"] == {"model": "test"} and meta["chronos2"]["rows_matched"] == len(good)
    c = mats["chronos2"]
    assert c.shape == (len(q), 23)
    assert np.isnan(c[1::2]).all() and np.isfinite(c[::2]).all()
    assert (np.diff(c[::2], axis=1) >= 0).all()  # re-sorted
    assert c[0] == pytest.approx(np.sort(good.q.iloc[0]))
    assert meta["mpnn_lstm"]["rows_invalid"] == 2 and meta["mpnn_lstm"]["rows_duplicate"] == 1
    assert np.isnan(mats["mpnn_lstm"][0]).all() and np.isfinite(mats["mpnn_lstm"][1:]).all()


def test_load_bench_rejects_unmatched_and_builtin_names(tmp_path):
    q = eval_q()
    bench_file(tmp_path, "chronos2", q, pd.DataFrame({"unit_id": ["ZZ"], "week": [q.week[0]], "horizon": [1]}))
    mats, meta = F.load_bench(q, tmp_path, log=lambda *a: None)
    assert mats == {} and "no row matches" in meta["chronos2"]["error"]
    assert set(F.BENCH_MODELS) & (set(F.MODELS) | {F.ENSEMBLE}) == set()


def test_ensemble_is_the_elementwise_median_on_common_rows(tmp_path):
    q = eval_q()
    rows = q[["unit_id", "week", "horizon"]]
    bench_file(tmp_path, "chronos2", q, rows.iloc[2:].copy())  # rows 0, 1 missing
    bench_file(tmp_path, "mpnn_lstm", q, rows.copy())
    bench_file(tmp_path, "chronos2_nocov", q)  # variant, must not join
    tab, bands, meta = F.evaluate_models(q, tmp_path, log=lambda *a: None)
    mats, _ = F.load_bench(q, tmp_path, log=lambda *a: None)
    assert meta["ensemble"]["members"] == ["xgb", "chronos2", "mpnn_lstm"]
    ens = np.sort(np.median(np.stack([np.vstack(q.xgb), mats["chronos2"], mats["mpnn_lstm"]]), axis=0), axis=1)
    cases = F.to_cases(ens, q["pop"].to_numpy())
    assert bands["ens_median_q50"].to_numpy() == pytest.approx(cases[:, F.IQ50], nan_ok=True)
    assert bands["ens_median_q50"].iloc[:2].isna().all()  # NaN unless every member exists
    all_ = tab[tab.horizon == "all"].set_index("model")
    assert set(all_.index) == set(F.MODELS) | {"chronos2", "mpnn_lstm", F.ENSEMBLE}
    assert all_.n.nunique() == 1 and all_.n.iloc[0] == len(q) - 2  # every model on the same rows
    assert meta["n_common_rows"] == len(q) - 2
    assert all_.loc["naive", "relWIS_vs_naive"] == pytest.approx(1.0)
    assert all_.loc["xgb", "relWIS_vs_xgb"] == pytest.approx(1.0)


def test_evaluate_models_without_benchmarks(tmp_path):
    q = eval_q()
    tab, bands, meta = F.evaluate_models(q, tmp_path, log=lambda *a: None)
    assert bands is None and meta["ensemble"] is None
    assert set(tab.model) == set(F.MODELS)


# ---------------------------------------------------------------- one real fit (small)

def test_fit_and_predict_at_small_panel(monkeypatch):
    def learn(panel, end, method="pcmciplus", boot=0):
        nodes = pd.DataFrame({"unit_id": sorted(panel.unit_id.unique())})
        return pd.DataFrame(columns=leadlag.EDGE_COLS), nodes, dict(n_edges=0, T=0)

    monkeypatch.setattr(leadlag, "learn", learn)
    p = make_panel(start="2016-01-10", end="2018-12-30")
    fitted = F.fit_at(p, "2018-09-16")
    base = F.predict_at(fitted)
    assert sorted(base.unit_id) == ["U0", "U1", "U2"]
    assert base.R.between(0.005, 0.995).all()
    for h in [1, 2, 3, 4, "cum4"]:
        q = np.vstack(base[f"q_{h}"])
        assert q.shape == (3, 23) and (np.diff(q, axis=1) >= 0).all()
    assert {f"shap_{g}" for g in F.GROUPS} <= set(base.columns)
    ov = pd.DataFrame({"unit_id": ["U1"], "storm_gale_4w": [1.0], "storm_wind_4w": [150.0], "not_a_feature": [1.0]})
    moved = F.predict_at(fitted, ov)
    keep = base.unit_id != "U1"
    assert np.vstack(moved.q_cum4[keep]) == pytest.approx(np.vstack(base.q_cum4[keep]))  # other units untouched
