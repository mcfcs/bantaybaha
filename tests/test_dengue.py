"""bantay.dengue: loading rules (HXL row, stripped `loc`, Sunday weeks, no deaths) and the unit-week sum, which is
NaN unless every member reporting unit reported. Hand-built CSV and crosswalk in a temporary folder."""

import numpy as np
import pandas as pd
import pytest

from bantay import config, dengue
from bantay.units import write_csv_with_header

pytestmark = pytest.mark.usefixtures("isolated_status")

ROWS = [  # loc, cases, deaths, date (m/d/Y as in the HDX file), Region
    (" ALPHA ", 5, 999, "01/10/2016", "R1"), ("BETA CITY", 3, 999, "01/10/2016", "R1"), ("GAMMA", 2, 999, "01/10/2016", "R2"),
    ("ALPHA", 4, 999, "01/17/2016", "R1"),  # BETA CITY has no row this week -> U1 is NaN, not 4
    ("GAMMA", 0, 999, "01/17/2016", "R2"),  # a reported zero stays zero
    ("ALPHA", 1, np.nan, "01/24/2016", "R1"), ("BETA CITY", np.nan, 0, "01/24/2016", "R1"),  # a NaN count = not reported
]


def write_inputs(tmp_path, monkeypatch, rows=ROWS):
    csv = tmp_path / "dengue.csv"
    df = pd.DataFrame(rows, columns=["loc", "cases", "deaths", "date", "Region"])
    hxl = pd.DataFrame([["#adm1+name", "#affected+infected", "#affected+killed", "#date", "#region"]], columns=df.columns)
    pd.concat([hxl, df]).to_csv(csv, index=False)
    xw = tmp_path / "dengue_loc_to_unit.csv"
    write_csv_with_header(pd.DataFrame({"dengue_loc": ["ALPHA", "BETA CITY", "GAMMA"], "unit_id": ["U1", "U1", "U2"]}), xw, "test")
    monkeypatch.setattr(dengue, "DENGUE", csv)
    monkeypatch.setattr(dengue, "DENGUE_XW", xw)


def test_load_skips_hxl_strips_loc_and_drops_deaths(tmp_path, monkeypatch):
    write_inputs(tmp_path, monkeypatch)
    dg = dengue.load_dengue()
    assert list(dg.columns) == ["loc", "date", "cases", "Region"]  # deaths never leave the loader
    assert set(dg["loc"]) == {"ALPHA", "BETA CITY", "GAMMA"}
    assert len(dg) == len(ROWS)  # the HXL tag row is not data
    assert (dg.date.dt.weekday == 6).all()
    assert config.status()["dengue_hdx"]["available"] is True


def test_unit_week_needs_every_member(tmp_path, monkeypatch):
    write_inputs(tmp_path, monkeypatch)
    out = dengue.unit_week_cases().set_index(["unit_id", "week"])
    w1, w2, w3, w4 = pd.to_datetime(["2016-01-10", "2016-01-17", "2016-01-24", "2016-01-31"])
    assert out.loc[("U1", w1), "cases"] == 8
    assert out.loc[("U2", w1), "cases"] == 2
    assert np.isnan(out.loc[("U1", w2), "cases"])  # BETA CITY missing
    assert out.loc[("U1", w2), "n_reporting"] == 1 and out.loc[("U1", w2), "n_members"] == 2
    assert out.loc[("U2", w2), "cases"] == 0
    assert np.isnan(out.loc[("U1", w3), "cases"])  # BETA CITY row with a NaN count
    assert np.isnan(out.loc[("U2", w4), "cases"])  # no row at all: NaN, never 0
    assert "deaths" not in out.columns
    assert len(out) == 2 * len(dengue.weeks())  # the full weekly grid
    assert (out.n_members == 2).groupby(level=0).all().to_dict() == {"U1": True, "U2": False}


def test_deaths_do_not_change_cases(tmp_path, monkeypatch):
    write_inputs(tmp_path, monkeypatch)
    a = dengue.unit_week_cases()
    rows = [(l, c, -12345, d, r) for l, c, _, d, r in ROWS]
    write_inputs(tmp_path, monkeypatch, rows)
    b = dengue.unit_week_cases()
    pd.testing.assert_frame_equal(a, b)


def test_non_sunday_week_is_rejected(tmp_path, monkeypatch):
    write_inputs(tmp_path, monkeypatch, ROWS + [("ALPHA", 1, 0, "01/18/2016", "R1")])  # a Monday
    with pytest.raises(AssertionError, match="Sunday"):
        dengue.load_dengue()


def test_reporting_unit_without_crosswalk_row_fails(tmp_path, monkeypatch):
    write_inputs(tmp_path, monkeypatch, ROWS + [("DELTA", 1, 0, "01/10/2016", "R3")])
    with pytest.raises(AssertionError, match="crosswalk"):
        dengue.unit_week_cases()


def test_missing_file_is_recorded_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(dengue, "DENGUE", tmp_path / "nope.csv")
    assert dengue.load_dengue() is None
    assert dengue.unit_week_cases() is None
    st = config.status()
    assert st["dengue_hdx"]["available"] is False and st["dengue_unit_week"]["available"] is False


def test_weekly_grid():
    w = dengue.weeks()
    assert w[0] == pd.Timestamp(config.FIRST_WEEK) and w[-1] == pd.Timestamp(config.LAST_WEEK)
    assert (w.weekday == 6).all() and len(w) == 262
