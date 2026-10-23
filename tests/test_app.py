"""Fast Streamlit AppTest checks: every tab renders without exceptions, the controls change the outputs, the SUS form
saves to a temporary file, and the hooks for outputs that other stages will add render when their files appear."""

import shutil

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import APP, APP_DATA, needs_data

pytestmark = needs_data
CORE_TABS = ["Action map", "Risk vs access", "Provinces", "Municipalities", "Outbreak graph", "Forecast skill",
             "Validation", "Data & caveats", "Usability test"]
OPTIONAL_TABS = {"Leptospirosis"}  # appear only when their build outputs exist
APP_FILES = {p.name for p in APP_DATA.glob("*")}


def run():
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def metrics(at):
    return {m.label: m.value for m in at.metric}


@pytest.fixture
def at(sus_csv, monkeypatch):
    monkeypatch.delenv("BANTAY_APP_DATA", raising=False)
    return run()


def tab(at, label):
    return [t for t in at.tabs if t.label == label][0]


def specs(block):
    return [c.proto.spec for c in block.get("plotly_chart")]


def test_every_tab_renders(at):
    labels = [t.label for t in at.tabs]
    assert [x for x in labels if x not in OPTIONAL_TABS] == CORE_TABS
    assert set(labels) - set(CORE_TABS) <= OPTIONAL_TABS
    assert at.title[0].value == "Typhoon Ompong"
    m = metrics(at)
    for k in ("Deploy mobile clinics", "Pre-position supplies", "Cut off from a hospital", "Ferries cancelled",
              "Top priority"):
        assert k in m
    charts = at.get("plotly_chart")
    assert len(charts) >= 5  # map, 2x2, municipal bars, reliability, forecast fan
    assert len(at.dataframe) >= 8
    assert not at.error


def test_numbers_match_outputs(at):
    s = pd.read_parquet(APP_DATA / "scenarios.parquet")
    o = s[(s.storm == "ompong") & (s.dlat == 0) & (s.dlon == 0)]
    m = metrics(at)
    assert m["Pre-position supplies"] == str(int((o.tier == 2).sum()))
    assert m["Deploy mobile clinics"] == str(int((o.tier == 3).sum()))
    assert m["Ferries cancelled"] == str(int(o.ferries_cancelled.iloc[0]))


def test_shift_changes_outputs(at):
    before = metrics(at)
    at.sidebar.select_slider(key="dlat").set_value(-1.0).run()
    assert not at.exception
    after = metrics(at)
    assert after != before
    assert "south" in at.title[0].value
    assert any("NOAH" in w.value or "hazard" in w.value for w in at.info)  # shifted tracks use the proxy
    at.sidebar.button[0].click().run()  # back to observed track
    assert metrics(at) == before


def test_storm_changes_outputs(at):
    before = metrics(at)
    at.sidebar.selectbox(key="storm").set_value("rolly").run()
    assert not at.exception
    assert at.title[0].value == "Typhoon Rolly"
    assert metrics(at) != before
    assert any("COVID" in w.value for w in at.warning)  # 2020 caveat is prominent


def test_map_colour_and_drilldowns(at):
    at.radio(key="color_by").set_value("Access loss A").run()
    at.selectbox(key="muni_unit").select_index(1).run()
    at.radio(key="evalh").set_value(4).run()
    assert not at.exception


def test_sus_form_saves_to_temp_file(at, sus_csv):
    at.selectbox(key="sus_role").set_value("DRRM office")
    at.radio(key="sus_outcome").set_value("Completed")
    for i in range(1, 11):
        at.radio(key=f"sus_q{i}").set_value(4 if i % 2 else 2)
    [b for b in at.button if b.label == "Submit answers"][0].click().run()
    assert not at.exception
    assert any("75.0" in s.value for s in at.success)
    r = pd.read_csv(sus_csv)
    assert len(r) == 1 and r.sus.iloc[0] == 75.0 and r.role.iloc[0] == "DRRM office"


def test_sus_form_rejects_incomplete(at, sus_csv):
    at.selectbox(key="sus_role").set_value("Other")
    [b for b in at.button if b.label == "Submit answers"][0].click().run()
    assert any("Not saved" in e.value for e in at.error)
    assert not sus_csv.exists()


# ---------------------------------------------------------------- outputs added by the other stages (real files)
needs = lambda *f: pytest.mark.skipif(not set(f) <= APP_FILES, reason=f"needs {f}")  # noqa: E731


@needs("scenarios_catalog.parquet", "tracks_catalog.parquet")
def test_catalogue_storm(at):
    cat = pd.read_parquet(APP_DATA / "scenarios_catalog.parquet")
    first = cat.sort_values("closest_time").iloc[0]
    label = f"{first['name'].title()} {first.season}"
    opts = at.sidebar.selectbox(key="storm").options
    assert opts[:4] == ["Ompong (Mangkhut, 2018)", "Tisoy (Kammuri, 2019)", "Rolly (Goni, 2020)",
                        "Ulysses (Vamco, 2020)"]
    assert opts[4] == label and len(opts) == 4 + cat.storm.nunique()
    at.sidebar.selectbox(key="storm").set_value(first.storm).run()
    assert not at.exception
    assert at.title[0].value == label
    assert not at.sidebar.select_slider  # observed track only
    assert "Storm track" in specs(tab(at, "Action map"))[0]  # catalogue track drawn from tracks_catalog
    o = cat[cat.storm == first.storm]
    if not o.R_calibrated.all():
        assert any("not calibrated" in w.value for w in at.warning)
    assert {m.label: m.value for m in at.metric}["Ferries cancelled"] == str(int(o.ferries_cancelled.iloc[0]))


@needs("catalog_storms.csv")
def test_skipped_storms_listed(at):
    skipped = [d for d in at.dataframe if "reason" in d.value.columns]
    assert skipped and len(skipped[0].value) > 0


def test_access_methods_shown(at):
    s = pd.read_parquet(APP_DATA / "scenarios.parquet")
    if "A_raster" not in s:
        pytest.skip("no raster access method in this build")
    ranked = [d for d in at.dataframe if "Main drivers" in d.value.columns][0].value
    for c in ("A range", "A raster %", "P range", "Cut off, raster", "Under-5 cut off", "Aged 60+ cut off", "R raw"):
        assert c in ranked.columns, c
    assert any("travel-time raster" in c.value for c in at.caption)  # method range under the KPIs
    muni = [d for d in at.dataframe if "adm3_name" in d.value.columns][0].value
    assert {"A_raster", "pop_cut_raster", "pop_cut_u5", "pop_cut_60"} <= set(muni.columns)
    if "s1_adm3.parquet" in APP_FILES:  # Ompong observed track: radar columns
        assert {"s1_flood_frac", "s1_flood_pop", "seen_frac"} <= set(muni.columns)
    if "access_methods.csv" in APP_FILES:
        v = tab(at, "Validation")
        assert any("Road network" in d.value.columns for d in at.dataframe)
        assert any("Methods agree" in sp for sp in specs(v))


@needs("surge_reliability.csv", "surge_calibration.json")
def test_calibrated_reliability(at):
    rel = pd.read_csv(APP_DATA / "surge_reliability.csv")
    if "mean_R_cal" not in rel:
        pytest.skip("uncalibrated build")
    sp = " ".join(specs(tab(at, "Forecast skill")))
    assert "Calibrated R (used on the map)" in sp and "Raw R (before calibration)" in sp
    assert any("Calibrated surge risk R" in m.value for m in tab(at, "Forecast skill").get("markdown"))


@needs("eval_models.csv")
def test_model_comparison_and_benchmark_fans(at):
    em = pd.read_csv(APP_DATA / "eval_models.csv")
    opts = at.selectbox(key="evalmodel").options
    assert opts[0] == "Bantay-Baha (XGBoost)"
    names = {"ens_median": "Median ensemble", "chronos2": "Chronos-2", "tabpfn_ts": "TabPFN-TS", "mpnn_lstm": "MPNN-LSTM"}
    if "eval_forecasts_models.parquet" in APP_FILES:
        f = pd.read_parquet(APP_DATA / "eval_forecasts_models.parquet")
        bench = sorted({c[:-4] for c in f.columns if c.endswith("_q50")})
        for m in bench:
            at.selectbox(key="evalmodel").set_value(m).run()
            assert not at.exception, m
        assert {names.get(m, m) for m in bench} <= set(opts)
    best = em[em.horizon.astype(str) == "all"].sort_values("WIS").model.iloc[0]
    lines = [m.value for m in tab(at, "Forecast skill").get("markdown") if "Lowest mean WIS" in m.value]
    assert lines and best in ("xgb", "naive") or names.get(best, best) in lines[0]
    assert any("Storm scenarios use XGBoost" in i.value for i in at.info)


@needs("lepto_city_lag.csv", "lepto_national_lag.csv", "lepto_weekly.parquet", "lepto_events_did.csv")
def test_lepto_charts(at):
    lt = tab(at, "Leptospirosis")
    assert len(lt.get("plotly_chart")) == 3  # lag profile, weekly cases + rain, event study
    assert any("12 cities (CCHAIN), not provincial; association, not forecast." in i.value for i in at.info)
    city = pd.read_csv(APP_DATA / "lepto_city_lag.csv")
    j = city[(city.model == "joint") & (city.variant == "12 cities") & (city.exposure == "rain_7d") & city.lag.notna()]
    peak = j.loc[j.irr.idxmax()]
    assert any(f"{int(peak.lag)} weeks after rain: IRR {peak.irr:.2f}" in m.value for m in lt.get("markdown"))
    for e in ("Heavy-rain week", "Gale"):
        at.radio(key="lepto_exposure").set_value(e).run()
        assert not at.exception
    w = pd.read_parquet(APP_DATA / "lepto_weekly.parquet")
    at.selectbox(key="lepto_place").set_value(w[w.level == "city"].id.iloc[0]).run()
    assert not at.exception


# ---------------------------------------------------------------- an older build without the optional outputs
CORE_FILES = ["scenarios.parquet", "scenarios_adm3.parquet", "tracks.parquet", "swaths.parquet", "ferries.parquet",
              "ferries_status.parquet", "leadlag_edges_pcmciplus.parquet", "leadlag_nodes_pcmciplus.parquet",
              "leadlag_edges_xcorr.parquet", "leadlag_meta.json", "eval_forecasts.parquet", "eval_summary.csv",
              "validation.csv", "sensitivity.csv", "benchmark_ncr.csv", "surge_reliability.csv",
              "surge_calibration.json", "units_simplified.geojson", "hospitals.parquet"]


def test_minimal_build_still_renders(tmp_path, sus_csv, monkeypatch):
    """Every optional section is guarded: with only the core outputs the app renders, without the optional tabs."""
    app = tmp_path / "app"
    app.mkdir()
    for f in CORE_FILES:
        if (APP_DATA / f).exists():
            shutil.copy2(APP_DATA / f, app / f)
    monkeypatch.setenv("BANTAY_APP_DATA", str(app))
    at = run()
    assert [t.label for t in at.tabs] == CORE_TABS
    assert len(at.sidebar.selectbox(key="storm").options) == 4
