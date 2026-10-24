"""bantay.panel: Sentinel-1 timing (the map is placed from the week its last after-image is known, never at an origin
week) and the interim cache rule; bantay.rain / rivers / grids helpers on tiny arrays."""

import os

import numpy as np
import pandas as pd
import pytest

from bantay import config, grids, panel, rain, rivers
from bantay.config import STORMS, S1_AFTER_DAYS, week_ending

pytestmark = pytest.mark.usefixtures("isolated_status")

FLOOD = {"ompong": ("A", 0.1), "tisoy": ("B", 0.2), "rolly": ("C", 0.3), "ulysses": ("C", 0.5)}


@pytest.fixture
def fake_s1(tmp_path, monkeypatch):
    def s1_unit_flood(u, key):
        unit, frac = FLOOD[key]
        return pd.DataFrame({"unit_id": [unit], "s1_flood_frac": [frac], "s1_flood_pop": [frac * 1000], "storm": key})

    monkeypatch.setattr(panel.flood, "s1_unit_flood", s1_unit_flood)
    monkeypatch.setattr(panel, "S1_BY_STORM", tmp_path / "s1_unit_storm.parquet")
    return tmp_path / "s1_unit_storm.parquet"


def known_week(key):
    return week_ending(pd.Timestamp(STORMS[key]["landfall"]) + pd.Timedelta(days=S1_AFTER_DAYS))


def test_s1_weeks_start_when_the_map_is_known(fake_s1):
    s1 = panel.s1_layers(None, None)
    a = s1[s1.unit_id == "A"]
    assert list(a.week) == [known_week("ompong") + pd.Timedelta(weeks=k) for k in range(4)]
    assert a.week.min() > week_ending(STORMS["ompong"]["landfall"])  # never the origin (landfall) week
    assert (a.s1_flood_frac == 0.1).all()
    for key in STORMS:
        origin = week_ending(STORMS[key]["landfall"])
        w0 = known_week(key)
        assert w0 > origin  # landfall + 10 days is always in a later DOH week
        unit, frac = FLOOD[key]
        own = s1[(s1.unit_id == unit) & (s1.s1_flood_frac == frac)]
        assert own.week.min() >= w0
    assert pd.read_parquet(fake_s1).storm.tolist() == list(STORMS)  # per-storm table kept for the report


def test_s1_absent_at_every_origin_week_of_its_own_storm(fake_s1):
    s1 = panel.s1_layers(None, None).set_index(["unit_id", "week"]).s1_flood_frac
    for key, (unit, frac) in FLOOD.items():
        origin = week_ending(STORMS[key]["landfall"])
        v = s1.get((unit, origin), np.nan)
        assert not v == frac, f"{key}: its own flood map sits on its origin week"


def test_s1_overlapping_storms_take_the_max(fake_s1):
    s1 = panel.s1_layers(None, None)
    c = s1[s1.unit_id == "C"].set_index("week").s1_flood_frac
    r0, u0 = known_week("rolly"), known_week("ulysses")  # Rolly (0.3) and Ulysses (0.5) both flood unit C
    rolly, uly = {r0 + pd.Timedelta(weeks=k) for k in range(4)}, {u0 + pd.Timedelta(weeks=k) for k in range(4)}
    assert set(c.index) == rolly | uly
    for w, v in c.items():
        assert v == (0.5 if w in uly else 0.3)  # the larger observed flood where the windows overlap
    assert not s1.duplicated(["unit_id", "week"]).any()


def test_s1_follows_the_after_window_constant(fake_s1, monkeypatch):
    monkeypatch.setattr(panel, "S1_AFTER_DAYS", 0)
    s1 = panel.s1_layers(None, None)
    assert s1[s1.unit_id == "A"].week.min() == week_ending(STORMS["ompong"]["landfall"])


def test_s1_none_without_maps(tmp_path, monkeypatch):
    monkeypatch.setattr(panel.flood, "s1_unit_flood", lambda u, key: None)
    monkeypatch.setattr(panel, "S1_BY_STORM", tmp_path / "s1.parquet")
    assert panel.s1_layers(None, None) is None
    assert not (tmp_path / "s1.parquet").exists()


def test_cached_rebuilds_only_when_inputs_are_newer(tmp_path):
    inp, out = tmp_path / "raw.txt", tmp_path / "cache.parquet"
    inp.write_text("x")
    calls = []

    def build():
        calls.append(1)
        return pd.DataFrame({"v": [len(calls)]})

    os.utime(inp, (1_000_000, 1_000_000))
    assert panel.cached(out, [inp], build).v.iloc[0] == 1
    assert panel.cached(out, [inp], build).v.iloc[0] == 1 and len(calls) == 1  # reused
    os.utime(inp, (out.stat().st_mtime + 10,) * 2)
    assert panel.cached(out, [inp], build).v.iloc[0] == 2  # input newer -> rebuilt
    assert panel.cached(out, [tmp_path / "absent"], build).v.iloc[0] == 2  # a missing input does not force a rebuild
    assert panel.cached(tmp_path / "none.parquet", [inp], lambda: None) is None
    assert not (tmp_path / "none.parquet").exists()  # a missing layer is never cached


def test_panel_columns_documented():
    assert {"cases", "incidence", "storm_gale_hit", "s1_flood_frac", "hazard_any_25yr"} <= set(panel.COLUMNS)
    assert "deaths" not in panel.COLUMNS


# ---------------------------------------------------------------- rain, rivers, grids


def test_rain_weekly_sums_mon_to_sun():
    days = pd.date_range("2018-09-10", "2018-09-23", freq="D")  # two full DOH weeks
    daily = pd.DataFrame({"U1": np.arange(14, dtype=float), "U2": 1.0}, index=days)
    daily.loc["2018-09-20", "U2"] = np.nan  # one missing day -> that week's 7-day sum is NaN
    w = rain.weekly(daily, "chirps").set_index(["week", "unit_id"])
    w1, w2 = pd.Timestamp("2018-09-16"), pd.Timestamp("2018-09-23")
    assert w.loc[(w1, "U1"), "chirps_7d"] == sum(range(7))
    assert w.loc[(w2, "U1"), "chirps_7d"] == sum(range(7, 14))
    assert w.loc[(w1, "U1"), "chirps_3d"] == 4 + 5 + 6  # Fri-Sun
    assert w.loc[(w2, "U1"), "chirps_max1d"] == 13
    assert w.loc[(w1, "U2"), "chirps_7d"] == 7
    assert np.isnan(w.loc[(w2, "U2"), "chirps_7d"])
    assert set(w.columns) == {"chirps_7d", "chirps_3d", "chirps_max1d"}


def test_rain_partial_week_is_nan():
    days = pd.date_range("2018-09-12", "2018-09-16", freq="D")  # Wed-Sun only
    w = rain.weekly(pd.DataFrame({"U": 1.0}, index=days), "imerg")
    assert np.isnan(w.imerg_7d.iloc[0]) and w.imerg_3d.iloc[0] == 3


def test_apply_weights_is_a_nan_aware_mean():
    from scipy import sparse

    cube = np.array([[[1.0, 3.0], [np.nan, 5.0]]])  # T=1, 2x2 grid
    w = sparse.csr_matrix(np.array([[0.5, 0.5, 0, 0], [0, 0, 0.5, 0.5], [0, 0, 1.0, 0]]))
    out = rain.apply_weights(w, cube)
    assert out[0, 0] == 2.0 and out[0, 1] == 5.0 and np.isnan(out[0, 2])


def test_river_accumulation_routes_downstream():
    reaches = pd.DataFrame({"HYRIV_ID": [1, 2, 3], "NEXT_DOWN": [3, 3, 0], "CATCH_SKM": [10.0, 20.0, 30.0],
                            "UPLAND_SKM": [10.0, 20.0, 60.0]})
    up = rivers.accumulate(reaches, np.array([[1.0], [2.0], [3.0]]))
    assert up[:, 0].tolist() == pytest.approx([1.0, 2.0, (10 + 40 + 90) / 60])  # upstream-mean rain at the outlet


def test_grid_helpers(tmp_path):
    assert grids.unit_index(pd.DataFrame({"unit_id": ["b", "a", "c"]})) == {"a": 1, "b": 2, "c": 3}  # 0 = outside
    a = grids.worldpop_clean(np.array([1.0, -99999.0, np.nan, -1.0, 2.5]), -99999.0)
    assert a.tolist() == [1.0, 0.0, 0.0, 0.0, 2.5]
    out, inp = tmp_path / "out.tif", tmp_path / "in.gpkg"
    assert grids.fresh(out, inp) is False
    out.write_text("x")
    assert grids.fresh(out, inp) is True  # missing inputs are ignored
    inp.write_text("x")
    os.utime(inp, (out.stat().st_mtime + 10,) * 2)
    assert grids.fresh(out, inp) is False


def test_s1_after_days_matches_the_gee_window():
    """config.S1_AFTER_DAYS must equal the end of the after-image window in scripts/download_gee.py (read with ast)."""
    import ast

    tree = ast.parse((config.ROOT / "scripts" / "download_gee.py").read_text(encoding="utf-8"))
    after = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "S1_AFTER" for t in n.targets))
    assert config.S1_AFTER_DAYS == after[1]
