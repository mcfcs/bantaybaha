"""Invariants of the build outputs in data/processed/ (read-only; each test skips when its files are missing) and of the
tracked crosswalks in data/crosswalks/."""

import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from bantay import forecast as F, scenarios as SC
from bantay.config import CROSSWALKS, MODEL_END, RAW, STORMS, S1_AFTER_DAYS, week_ending
from bantay.panel import COLUMNS
from bantay.units import read_crosswalk
from conftest import APP_DATA, PROCESSED, need

pytestmark = pytest.mark.data
ORIGIN = {k: week_ending(s["landfall"]) for k, s in STORMS.items()}
KNOWN = {k: week_ending(pd.Timestamp(s["landfall"]) + pd.Timedelta(days=S1_AFTER_DAYS)) for k, s in STORMS.items()}


def pq(name):
    p = APP_DATA / name if not name.startswith("../") else PROCESSED / name[3:]
    need(p)
    return pd.read_parquet(p)


def csv(name, **kw):
    need(APP_DATA / name)
    return pd.read_csv(APP_DATA / name, **kw)


# ---------------------------------------------------------------- crosswalks (tracked in git)

def test_crosswalk_126_dengue_units_to_85_units():
    xd = read_crosswalk(CROSSWALKS / "dengue_loc_to_unit.csv")
    x2 = read_crosswalk(CROSSWALKS / "adm2_to_unit.csv")
    assert len(xd) == xd.dengue_loc.nunique() == 126
    assert (xd.match != "UNMATCHED").all() and xd.unit_id.notna().all()
    assert xd.unit_id.nunique() == 85 == x2.unit_id.nunique()
    assert set(xd.unit_id) <= set(x2.unit_id)
    m = xd.set_index("dengue_loc").unit_id
    assert m["QUEZON CITY"] == "PH13074" and m["QUEZON"] == "PH04056"
    assert m["ISABELA"] == "PH02031" and m["ISABELA CITY"] == "PH19007"
    assert m["MAGUINDANAO"] == m["COTABATO CITY"] == "PH_MAGUINDANAO_2016"
    x = x2.set_index("adm2_name").unit_id
    assert x["Special Geographic Area"] == x["Cotabato (North Cotabato)"]
    assert x["Maguindanao del Norte"] == x["Maguindanao del Sur"] == "PH_MAGUINDANAO_2016"
    assert sum(n.startswith("Metropolitan Manila") for n in x2.unit_name.unique()) == 4
    for f in ("dengue_loc_to_unit.csv", "adm2_to_unit.csv"):
        assert (CROSSWALKS / f).read_text(encoding="utf-8").startswith("# ")  # header comment with the source


def test_every_raw_dengue_unit_has_a_crosswalk_row():
    p = RAW / "dengue_hdx" / "doh-epi-dengue-data-2016-2021.csv"
    need(p)
    locs = set(pd.read_csv(p, skiprows=[1], usecols=["loc"])["loc"].str.strip())
    assert locs == set(read_crosswalk(CROSSWALKS / "dengue_loc_to_unit.csv").dengue_loc)


# ---------------------------------------------------------------- panel

@pytest.fixture(scope="module")
def panel():
    return pq("../panel.parquet")


def test_panel_grid(panel):
    assert panel.unit_id.nunique() == 85 and panel.week.nunique() == 262 and len(panel) == 85 * 262
    assert not panel.duplicated(["unit_id", "week"]).any()
    assert (panel.week.dt.weekday == 6).all()
    assert panel.week.min() == pd.Timestamp("2016-01-10") and panel.week.max() == pd.Timestamp("2021-01-10")
    assert set(COLUMNS) <= set(panel.columns) and "deaths" not in panel.columns


def test_panel_cases_rules(panel):
    full = panel.n_reporting == panel.n_members
    assert panel.cases[~full].isna().all()  # NaN unless every member reported
    ok = panel.cases.notna()
    assert np.allclose(panel.incidence[ok], panel.cases[ok] / panel["pop"][ok] * 1e5)
    assert (panel.groupby("unit_id")["pop"].nunique() == 1).all() and (panel["pop"] > 0).all()


def test_panel_storm_columns(panel):
    assert set(panel.storm_gale_hit.unique()) <= {0, 1}
    assert (panel.storm_min_dist_km >= 0).all() and (panel.storm_min_dist_km <= 2000).all()


def test_s1_never_at_its_own_origin_week(panel):
    s1 = panel.dropna(subset=["s1_flood_frac"])
    windows = {k: pd.date_range(w0, periods=4, freq="W-SUN") for k, w0 in KNOWN.items()}
    allowed = set().union(*[set(w) for w in windows.values()])
    assert set(s1.week) <= allowed  # only the 4 weeks after each map is known
    for k in STORMS:
        assert KNOWN[k] > ORIGIN[k]
        covering = [j for j, w in windows.items() if ORIGIN[k] in w]
        assert k not in covering  # a storm's own map never reaches its origin week
        if not covering:
            assert panel[panel.week == ORIGIN[k]].s1_flood_frac.isna().all()
    # Ulysses' origin week holds Rolly's map (images to 2020-11-11, known that week), never Ulysses' own
    by = pq("../s1_unit_storm.parquet")
    at = panel[panel.week == ORIGIN["ulysses"]].set_index("unit_id").s1_flood_frac
    rolly = by[by.storm == "rolly"].set_index("unit_id").s1_flood_frac
    pd.testing.assert_series_equal(at.sort_index(), rolly.reindex(at.index).sort_index(), check_names=False)


# ---------------------------------------------------------------- scenarios and catalogue

@pytest.fixture(scope="module")
def scen():
    return pq("scenarios.parquet")


def test_scenarios_shape_and_ranges(scen):
    assert set(scen.storm) == set(STORMS)
    assert len(scen[["storm", "dlat", "dlon"]].drop_duplicates()) == len(STORMS) * len(SC.SHIFTS)
    assert (scen.groupby(["storm", "dlat", "dlon"]).unit_id.nunique() == 85).all()
    assert scen.R.between(0, 1).all() and scen.R_raw.between(0, 1).all()
    a = scen.A.dropna()
    assert len(a) and a.between(0, 1).all()
    both = scen.A_lo.notna() & scen.A_hi.notna()
    assert both.any() and (scen.A_lo[both] <= scen.A_hi[both]).all()
    assert ((scen.A_lo[both] <= scen.A[both] + 1e-12) & (scen.A[both] <= scen.A_hi[both] + 1e-12)).all()
    assert np.allclose(scen.P, scen.R * scen.A, equal_nan=True)
    assert (scen.tier.to_numpy() == SC.tier(scen.R, scen.A)).all()


def test_scenarios_training_windows(scen):
    assert (scen.train_end <= scen.origin).all() and (scen.train_end <= pd.Timestamp(MODEL_END)).all()
    for k in STORMS:
        assert (scen[scen.storm == k].origin == ORIGIN[k]).all()
    assert scen.groupby("storm").flag_2020.first().to_dict() == {k: s["season"] >= 2020 for k, s in STORMS.items()}


def test_catalogue_is_leak_free():
    c = pq("scenarios_catalog.parquet")
    assert (pd.to_datetime(c.train_end) <= pd.to_datetime(c.origin)).all()
    assert (pd.to_datetime(c.train_end) <= pd.Timestamp(MODEL_END)).all()
    assert c.R.between(0, 1).all()
    back = {(s["name"], s["season"]) for s in STORMS.values()}
    assert not set(zip(c.name.str.upper(), c.season)) & back  # backtests live in scenarios.parquet
    st = csv("catalog_storms.csv")
    inc = st[st.status == "included"]
    assert set(inc.sid) == set(c.sid) and (inc.history_weeks >= SC.CATALOG_MIN_HISTORY_WEEKS).all()


# ---------------------------------------------------------------- forecast evaluation

def test_eval_models_same_rows_and_ensemble_members():
    m = csv("eval_models.csv", dtype={"horizon": str})
    assert (m.groupby("horizon").n.nunique() == 1).all()  # every model scored on the same n
    meta = json.loads((APP_DATA / "eval_models.json").read_text(encoding="utf-8"))
    ens = meta["ensemble"]
    assert ens["name"] == F.ENSEMBLE and set(ens["members"]) == {"xgb", *F.BENCH_MODELS}
    assert set(m.model) == set(F.MODELS) | set(F.BENCH_MODELS) | {F.ENSEMBLE}
    al = m[m.horizon == "all"].set_index("model")
    assert al.n.iloc[0] == meta["n_common_rows"]
    assert al.loc["naive", "relWIS_vs_naive"] == pytest.approx(1.0) and al.loc["xgb", "relWIS_vs_xgb"] == pytest.approx(1.0)


def test_eval_forecasts_rolling_origin():
    fc = pq("eval_forecasts.parquet")
    assert (fc.week >= fc.refit).all() and (fc.target_week <= pd.Timestamp(MODEL_END)).all()
    assert set(pd.to_datetime(fc.refit.unique())) <= set(F.refit_dates())


def test_cum4_calibration_is_leak_free():
    c = pq(F.CUM4_FILE)
    on = c[c.R_cal_applied]
    assert len(on) and (on.cal_fit_end <= on.week).all() and (on.cal_n >= F.CAL_MIN_ROWS).all()
    off = c[~c.R_cal_applied]
    assert np.allclose(off.R_xgb_cal, off.R_xgb, equal_nan=True)
    assert c.R_xgb_cal.dropna().between(*F.R_CLIP).all() or not c.R_cal_applied.any()


def test_leadlag_edges():
    e = pq("leadlag_edges_pcmciplus.parquet")
    assert e.lag.between(1, 3).all() and (e.source != e.target).all() and (e.q < 0.05).all()
    assert not e.duplicated(["source", "target"]).any()
    g = csv("eval_graphs.csv")
    assert (pd.to_datetime(g.end) <= pd.Timestamp(MODEL_END)).all()
    from bantay.leadlag import MIN_T

    assert (g[g["T"] < MIN_T].n_edges == 0).all()


# ---------------------------------------------------------------- status.json

def test_status_json_well_formed():
    p = PROCESSED / "status.json"
    need(p)
    st = json.loads(p.read_text(encoding="utf-8"))
    assert st and all(re.fullmatch(r"[A-Za-z0-9_]+", k) for k in st)
    for k, v in st.items():
        assert set(v) == {"available", "detail", "checked"}, k
        assert isinstance(v["available"], bool) and isinstance(v["detail"], str)
        datetime.fromisoformat(v["checked"])
    for k in ("dengue_hdx", "panel", "scenarios"):
        assert st[k]["available"], k


def test_eval_models_built_in_rows_match_eval_summary():
    """With every model on the base rows (no benchmark row missing), eval_models' built-in models equal eval_summary."""
    m = csv("eval_models.csv", dtype={"horizon": str})
    e = csv("eval_summary.csv", index_col=0)
    e.index = e.index.astype(str)
    meta = json.loads((APP_DATA / "eval_models.json").read_text(encoding="utf-8"))
    assert meta["n_common_rows"] <= meta["n_base_rows"] == int(e.loc["all", "n"])
    if meta["n_common_rows"] != meta["n_base_rows"]:
        pytest.skip("benchmarks cover fewer rows than the base models: the two tables score different rows")
    for r in m[m.model.isin(F.MODELS)].itertuples():
        row = e.loc[r.horizon]
        assert r.n == row["n"] and r.WIS == pytest.approx(row[f"WIS {r.model}"]), (r.model, r.horizon)
        assert r.cov90 == pytest.approx(row[f"cov90 {r.model}"]), (r.model, r.horizon)


def test_scenario_intervals_and_municipal_sums(scen):
    assert ((scen.cases4_lo90 <= scen.cases4_med + 1e-9) & (scen.cases4_med <= scen.cases4_hi90 + 1e-9)).all()
    assert (scen.pop_cut.dropna() <= scen.pop_cells.dropna() + 1e-6).all()
    a3 = pq("scenarios_adm3.parquet")
    assert a3.A.dropna().between(0, 1).all()
    # the same population cells summarised two ways: totals agree per track (a municipality whose cells straddle a unit
    # boundary is listed under one unit, so per-unit sums can differ), and municipalities carry their unit's R
    tot = scen.groupby(["storm", "dlat", "dlon"])[["pop_cut", "pop_cells"]].sum()
    tot3 = a3.groupby(["storm", "dlat", "dlon"])[["pop_cut", "pop"]].sum().reindex(tot.index)
    assert np.allclose(tot.pop_cut, tot3.pop_cut, rtol=1e-6) and np.allclose(tot.pop_cells, tot3["pop"], rtol=1e-6)
    for k in STORMS:
        s0 = scen[(scen.storm == k) & (scen.dlat == 0) & (scen.dlon == 0)].set_index("unit_id")
        m0 = a3[(a3.storm == k) & (a3.dlat == 0) & (a3.dlon == 0)]
        assert np.allclose(m0.R, m0.unit_id.map(s0.R)), k
