"""bantay.storms: the gale-radius fallback chain, shifted tracks and the forecast-origin exposure window, on hand-built
IBTrACS-like fixes and two square units."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from bantay import storms as S
from bantay.config import STORMS

pytestmark = pytest.mark.usefixtures("isolated_status")
NAN = np.nan


def fixes(rows):
    """rows: (R34 NE, SE, SW, NW, TOKYO_R30_LONG, wind_kt)."""
    return pd.DataFrame(rows, columns=S.R34 + ["TOKYO_R30_LONG", "wind_kt"])


def test_gale_radius_fallback_chain():
    tr = fixes([
        (50, 60, NAN, 40, 100, 80),  # USA R34: max of the quadrants (nm)
        (NAN, NAN, NAN, NAN, 80, 50),  # no R34 -> JMA 30-kt long axis
        (0, 0, 0, 0, NAN, 50),  # R34 all zero and no JMA -> fixed
        (NAN, NAN, NAN, NAN, 0, 40),  # JMA zero -> fixed
        (30, 30, 30, 30, 50, 30),  # below gale: no swath whatever the radii
        (NAN, NAN, NAN, NAN, NAN, NAN),  # unknown wind keeps the fallback
    ])
    out = S.gale_radius(tr)
    assert out.radius_km.tolist() == pytest.approx([60 * 1.852, 80 * 1.852, 150, 150, 0, 150])
    assert out.r_source.tolist() == ["USA_R34", "TOKYO_R30", "fixed_150km", "fixed_150km", "below_gale", "fixed_150km"]
    assert "radius_km" not in tr  # input left alone
    alt = S.gale_radius(tr, fixed_km=100.0)
    assert alt.radius_km.iloc[2] == 100 and alt.r_source.iloc[2] == "fixed_100km"
    assert alt.radius_km.iloc[0] == pytest.approx(60 * 1.852)  # the fixed value only matters as a fallback


def test_gale_threshold_is_34_kt():
    out = S.gale_radius(fixes([(NAN,) * 5 + (34,), (NAN,) * 5 + (33.9,)]))
    assert out.r_source.tolist() == ["fixed_150km", "below_gale"]


def track(lat, lon, times, name="MANGKHUT", season=2018, sid="S1", wind=80.0):
    n = len(times)
    df = pd.DataFrame({"SID": sid, "NAME": name, "SEASON": season, "LAT": lat, "LON": lon,
                       "time": pd.to_datetime(times), "wind_kt": wind, "TOKYO_R30_LONG": NAN})
    for c in S.R34:
        df[c] = 50.0  # 50 nm = 92.6 km
    return df.iloc[:n]


def test_shift_track_moves_space_and_time_only():
    tr = track([14.0, 15.0], [122.0, 121.0], ["2018-09-14 00:00", "2018-09-14 03:00"])
    out = S.shift_track(tr, dlat=-0.5, dlon=1.0, dhours=6)
    assert out.LAT.tolist() == [13.5, 14.5] and out.LON.tolist() == [123.0, 122.0]
    assert (out.time - tr.time == pd.Timedelta(hours=6)).all()
    pd.testing.assert_frame_equal(out.drop(columns=["LAT", "LON", "time"]), tr.drop(columns=["LAT", "LON", "time"]))
    assert tr.LAT.tolist() == [14.0, 15.0]  # a copy


def test_shift_storm_moves_only_that_storm():
    a = track([14.0, 15.0], [122.0, 121.0], ["2018-09-14", "2018-09-15"], sid="OMPONG")
    b = track([10.0], [125.0], ["2018-09-14"], name="OTHER", sid="OTHER")
    c = track([12.0], [124.0], ["2016-09-14"], season=2016, sid="MANGKHUT2016")  # same name, another season
    ib = pd.concat([a, b, c], ignore_index=True)
    assert STORMS["ompong"]["name"] == "MANGKHUT" and STORMS["ompong"]["season"] == 2018
    out = S.shift_storm(ib, "ompong", dlat=1.0, dlon=-1.0)
    m = out.SID == "OMPONG"
    assert out.loc[m, "LAT"].tolist() == [15.0, 16.0] and out.loc[m, "LON"].tolist() == [121.0, 120.0]
    pd.testing.assert_frame_equal(out[~m], ib[~m])
    assert ib.loc[m, "LAT"].tolist() == [14.0, 15.0]


def test_interpolate_is_hourly_and_linear():
    tr = S.gale_radius(track([14.0, 14.3], [122.0, 122.3], ["2018-09-14 00:00", "2018-09-14 03:00"]))
    it = S.interpolate(tr)
    assert len(it) == 4 and (it.time.diff().dropna() == pd.Timedelta(hours=1)).all()
    assert it.LAT.tolist() == pytest.approx([14.0, 14.1, 14.2, 14.3])


def test_swath_none_below_gale_and_covers_the_track():
    from pyproj import Transformer
    from shapely.geometry import Point

    tr = track([14.0, 14.0], [122.0, 122.5], ["2018-09-14 00:00", "2018-09-14 06:00"])
    sw = S.swath(tr)
    x, y = Transformer.from_crs(4326, S.CRS_M, always_xy=True).transform(122.25, 14.0)
    assert sw.contains(Point(x, y))
    assert S.swath(tr.assign(wind_kt=20.0)) is None


@pytest.fixture
def units():
    return gpd.GeoDataFrame({"unit_id": ["NEAR", "FAR"]},
                            geometry=[box(121.9, 13.9, 122.1, 14.1), box(124.9, 7.9, 125.1, 8.1)], crs=4326)


ORIGIN = pd.Timestamp("2018-09-16")  # a Sunday: the week Mon 09-10 .. Sun 09-16


def test_origin_exposure_window(units):
    ib = pd.concat([
        track([14.0], [122.0], ["2018-09-15 12:00"], sid="IN"),  # origin week, over NEAR
        track([8.0], [125.0], ["2018-09-17 00:00"], sid="AFTER", wind=150.0),  # after the origin week: ignored
        track([8.0], [125.0], ["2018-08-12 00:00"], sid="OLD", wind=150.0),  # 5 weeks before: outside the 4-week window
    ], ignore_index=True)
    out = S.origin_exposure(units, ib, ORIGIN).set_index("unit_id")
    assert out.loc["NEAR"].tolist() == [1.0, 80.0, 0.0]  # gale hit, wind, distance 0 (inside)
    assert out.loc["FAR", "storm_gale_4w"] == 0 and out.loc["FAR", "storm_wind_4w"] == 0
    assert out.loc["FAR", "storm_dist_4w"] > 600  # only the IN fix counts, ~700 km away
    assert list(out.columns) == ["storm_gale_4w", "storm_wind_4w", "storm_dist_4w"]


def test_origin_exposure_includes_the_three_earlier_weeks(units):
    ib = track([8.0], [125.0], ["2018-08-21 00:00"], sid="EARLY", wind=60.0)  # week ending 08-26: 3 weeks before
    out = S.origin_exposure(units, ib, ORIGIN).set_index("unit_id")
    assert out.loc["FAR", "storm_gale_4w"] == 1.0 and out.loc["FAR", "storm_wind_4w"] == 60.0
    assert out.loc["NEAR", "storm_gale_4w"] == 0.0


def test_origin_exposure_without_fixes(units):
    ib = track([14.0], [122.0], ["2018-10-01"], sid="LATER")  # only fixes after the origin
    out = S.origin_exposure(units, ib, ORIGIN)
    assert out.storm_gale_4w.tolist() == [0.0, 0.0]
    assert out.storm_wind_4w.tolist() == [0.0, 0.0]
    assert out.storm_dist_4w.tolist() == [2000.0, 2000.0]


def test_origin_exposure_shift_only_changes_the_moved_storm(units):
    ib = pd.concat([track([14.0], [122.0], ["2018-09-15"], sid="OMPONG"),
                    track([8.0], [125.0], ["2018-09-15"], name="OTHER", sid="OTHER", wind=40.0)], ignore_index=True)
    base = S.origin_exposure(units, ib, ORIGIN).set_index("unit_id")
    moved = S.origin_exposure(units, S.shift_storm(ib, "ompong", dlat=3.0), ORIGIN).set_index("unit_id")
    assert base.loc["NEAR", "storm_gale_4w"] == 1 and moved.loc["NEAR", "storm_gale_4w"] == 0  # moved 330 km north
    pd.testing.assert_series_equal(base.loc["FAR"], moved.loc["FAR"])  # the other storm still hits FAR
