"""bantay.config: the DOH week rule and the missing-input registry (status.json, sent to a temporary file)."""

import json
from datetime import datetime

import pandas as pd
import pytest

from bantay import config
from conftest import ROOT

pytestmark = pytest.mark.usefixtures("isolated_status")


@pytest.mark.parametrize("day, sunday", [
    ("2018-09-10", "2018-09-16"),  # Monday -> the Sunday that ends its week
    ("2018-09-15", "2018-09-16"),  # Saturday
    ("2018-09-16", "2018-09-16"),  # a Sunday maps to itself
    ("2018-09-16 23:59", "2018-09-16"),  # time of day is dropped
    ("2018-09-17 00:00", "2018-09-23"),  # the next Monday starts the next week
    ("2020-12-28", "2021-01-03"),  # across a year end
])
def test_week_ending_scalar(day, sunday):
    out = config.week_ending(day)
    assert isinstance(out, pd.Timestamp)
    assert out == pd.Timestamp(sunday)
    assert out.weekday() == 6


def test_week_ending_series_keeps_index():
    s = pd.Series(pd.to_datetime(["2016-01-04", "2016-01-10", "2016-01-11"]), index=[10, 20, 30])
    out = config.week_ending(s)
    assert isinstance(out, pd.Series)
    assert list(out.index) == [10, 20, 30]
    assert list(out) == list(pd.to_datetime(["2016-01-10", "2016-01-10", "2016-01-17"]))


def test_week_ending_is_identity_on_the_weekly_grid():
    wk = pd.date_range(config.FIRST_WEEK, config.LAST_WEEK, freq=config.WEEK_FREQ)
    assert (pd.DatetimeIndex(config.week_ending(pd.Series(wk))) == wk).all()
    assert len(wk) == 262


def test_quantiles_are_flusight_23():
    q = config.QUANTILES
    assert len(q) == 23 and q == sorted(q)
    assert q[:2] == [0.01, 0.025] and q[-2:] == [0.975, 0.99] and 0.5 in q
    assert all(abs(a + b - 1) < 1e-12 for a, b in zip(q, q[::-1]))  # symmetric pairs


def test_record_round_trip(isolated_status):
    assert config.status() == {}
    config.record("chirps", True, "5 files")
    st = json.loads(isolated_status.read_text(encoding="utf-8"))
    assert st["chirps"]["available"] is True and st["chirps"]["detail"] == "5 files"
    datetime.fromisoformat(st["chirps"]["checked"])
    assert config.status() == st


def test_missing_then_available_clears_the_gap(isolated_status, capsys):
    assert config.missing("imerg", "no tif files") is None
    assert "WARNING missing imerg: no tif files" in capsys.readouterr().out
    assert config.status()["imerg"]["available"] is False
    config.record("other", True)
    config.record("imerg", True, "arrived")
    st = config.status()
    assert st["imerg"] == dict(available=True, detail="arrived", checked=st["imerg"]["checked"])
    assert set(st) == {"imerg", "other"}  # merged, not overwritten


def test_have_records_presence_and_absence(tmp_path):
    assert config.have("code", ROOT / "bantay" / "config.py") is True
    assert config.status()["code"]["available"] is True
    assert "config.py" in config.status()["code"]["detail"]
    assert config.have("pkg", ROOT / "bantay", pattern="*.py") is True
    assert config.have("nothing", ROOT / "bantay", pattern="*.does-not-exist") is False
    assert config.have("gone", tmp_path / "absent.csv") is False
    assert config.status()["gone"]["available"] is False
    assert "absent.csv not found" in config.status()["gone"]["detail"]
    # every path must exist: one missing path fails the key
    assert config.have("two", ROOT / "bantay" / "config.py", tmp_path / "absent.csv") is False


def test_have_empty_directory_is_missing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert config.have("empty", tmp_path / "empty") is False


def test_have_accepts_an_existing_path_outside_the_repo(tmp_path):
    f = tmp_path / "input.csv"
    f.write_text("x\n1\n")
    assert config.have("outside", f) is True
