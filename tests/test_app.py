"""Fast Streamlit AppTest checks: every tab renders without exceptions, the controls change the outputs, the SUS form
saves to a temporary file, and the hooks for outputs that other stages will add render when their files appear."""

import shutil

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import APP, APP_DATA, needs_data

pytestmark = needs_data
TABS = ["Action map", "Risk vs access", "Provinces", "Municipalities", "Outbreak graph", "Forecast skill",
        "Validation", "Data & caveats", "Usability test"]


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


def test_every_tab_renders(at):
    assert [t.label for t in at.tabs] == TABS
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


# ---------------------------------------------------------------- hooks for outputs other stages will add
@pytest.fixture
def hooked(tmp_path, sus_csv, monkeypatch):
    """A temp copy of the build outputs plus test-only stand-ins for the optional files and columns.

    The stand-ins are derived from the real outputs (or are plain placeholders) and live only in tmp_path; they
    check that the dashboard picks the files up, not what the numbers will be."""
    app = tmp_path / "app"
    shutil.copytree(APP_DATA, app)
    status = APP_DATA.parent / "status.json"
    if status.exists():
        shutil.copy2(status, tmp_path / "status.json")
    s = pd.read_parquet(app / "scenarios.parquet")
    s = s.assign(A_raster=s.A, A_lo=s.A * 0.9, A_hi=s.A * 1.1, P_lo=s.P * 0.9, P_hi=s.P * 1.1,
                 pop_cut_u5=s.pop_cut * 0, pop_cut_60=s.pop_cut * 0, R_raw=s.R)
    s.to_parquet(app / "scenarios.parquet")
    cat = s[(s.storm == "ompong") & (s.dlat == 0) & (s.dlon == 0)].assign(storm="fixture_storm")
    cat.to_parquet(app / "scenarios_catalog_fixture.parquet")
    pd.DataFrame({"note": ["test fixture"]}).to_csv(app / "lepto_fixture.csv", index=False)
    pd.DataFrame({"method": ["network", "raster"], "note": ["test fixture"] * 2}).to_csv(app / "access_methods.csv",
                                                                                            index=False)
    pd.read_csv(app / "eval_summary.csv").head(1).assign(model="fixture").to_csv(app / "eval_models.csv", index=False)
    a3 = pd.read_parquet(app / "scenarios_adm3.parquet")
    a3[["adm3_pcode", "storm"]].drop_duplicates().assign(s1_fixture=0.0).to_parquet(app / "s1_adm3.parquet")
    f = pd.read_parquet(app / "eval_forecasts.parquet")
    f.assign(fixture_q05=f.xgb_q05, fixture_q50=f.xgb_q50, fixture_q95=f.xgb_q95).to_parquet(
        app / "eval_forecasts.parquet")
    monkeypatch.setenv("BANTAY_APP_DATA", str(app))
    return run()


def test_hooks_render_when_files_exist(hooked):
    at = hooked
    assert "Leptospirosis" in [t.label for t in at.tabs]
    assert "Fixture Storm" in at.sidebar.selectbox(key="storm").options
    ranked = [d for d in at.dataframe if "Main drivers" in d.value.columns][0].value
    for c in ("A range", "A raster %", "P range", "Under-5 cut off", "Aged 60+ cut off", "R raw"):
        assert c in ranked.columns, c
    assert "fixture" in at.selectbox(key="evalmodel").options
    assert any("method" in d.value.columns for d in at.dataframe)  # access_methods.csv
    assert any("s1_fixture" in d.value.columns for d in at.dataframe)
    assert any("recalibrated" in m.value for m in at.markdown)
    at.sidebar.selectbox(key="storm").set_value("fixture_storm").run()
    assert not at.exception
    assert at.title[0].value.startswith("Storm Fixture Storm")
