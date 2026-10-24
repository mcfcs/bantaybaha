"""bantay.scenarios: the provisional action tiers, case columns, access tables of the two methods, priority P, the
catalogue's training ends and the rank-change helpers."""

import numpy as np
import pandas as pd
import pytest

from bantay import forecast as F, scenarios as SC
from bantay.config import MODEL_END, QUANTILES

pytestmark = pytest.mark.usefixtures("isolated_status")
T = SC.TIERS


def test_tier_thresholds_are_inclusive():
    dR, dA = T["deploy"]
    pR = T["preposition_R"]
    aA, aR = T["preposition_A"]
    eps = 1e-9
    R = [dR, dR - eps, pR, pR - eps, aR, aR - eps, 0.99, 0.99, 0.0]
    A = [dA, dA, 0.0, aA - eps, aA, aA, dA - eps, np.nan, 1.0]
    # high R with NaN A (access missing) is never "deploy": A counts as 0
    assert SC.tier(R, A).tolist() == [3, 2, 2, 1, 2, 1, 2, 2, 1]


def test_tier_rule_shape():
    """The documented ordering: deploy needs both high R and high A; pre-position needs R alone or A with some R."""
    dR, dA = T["deploy"]
    assert T["preposition_R"] <= dR and T["preposition_A"][1] <= T["preposition_R"]
    assert SC.tier([1.0, 1.0, 0.0], [1.0, 0.0, 1.0]).tolist() == [3, 2, 1]
    assert set(SC.TIER_LABELS) == {1, 2, 3}


def test_tier_reads_the_constants_at_call_time(monkeypatch):
    monkeypatch.setitem(SC.TIERS, "deploy", (0.9, 0.5))
    assert SC.tier([0.6], [0.2]).tolist() == [2]


def test_shifts_include_the_observed_track_once():
    assert (0.0, 0.0) in SC.SHIFTS and len(set(SC.SHIFTS)) == len(SC.SHIFTS)


def test_case_columns():
    Q = np.array(QUANTILES)
    assert Q[2] == 0.05 and Q[-3] == 0.95  # lo90 / hi90 are the 90% interval
    q = np.log1p(np.tile(100 * Q, (2, 1)))
    fc = pd.DataFrame({"unit_id": ["a", "b"], "pop": [1e5, 2e5], "q_cum4": list(q), "q_1": list(q), "R": [0.1, 0.2]})
    out = SC.case_columns(fc)
    assert out.cases4_med.tolist() == pytest.approx([50.0, 100.0])
    assert out.cases4_lo90.tolist() == pytest.approx([5.0, 10.0]) and out.cases4_hi90.tolist() == pytest.approx([95.0, 190.0])
    assert not [c for c in out.columns if c.startswith("q_")]


def cells():
    return pd.DataFrame({"unit_id": ["A", "A", "B", "B"], "adm3_pcode": ["a1", "a2", "b1", "b1"], "adm3_name": ["x", "y", "z", "z"],
                         "pop": [100.0, 100.0, 50.0, 150.0], "pop_u5": [10.0, 20.0, 5.0, 15.0], "pop_60": [7.0, 8.0, 1.0, 2.0]})


NET = (np.array([1.0, 1.0, 1.0, 1.0]), np.array([np.inf, 1.0, 1.0, 9.0]), np.array([True, False, False, True]))
RAS = (np.array([1.0, 1.0, 1.0, 1.0]), np.array([np.inf, np.inf, 1.0, 1.0]), np.array([True, True, False, False]))


def test_access_tables_method_range_and_vulnerable_groups():
    acc = SC.access_tables(cells(), NET, RAS, "unit_id").set_index("unit_id")
    assert acc.A.tolist() == [0.5, 0.75] and acc.A_raster.tolist() == [1.0, 0.0]
    assert acc.A_lo.tolist() == [0.5, 0.0] and acc.A_hi.tolist() == [1.0, 0.75]
    assert acc.pop_cut_u5.tolist() == [10.0, 15.0] and acc.pop_u5.tolist() == [30.0, 20.0]  # network cut-off
    assert acc.pop_cut_60.tolist() == [7.0, 2.0]
    none = SC.access_tables(cells().drop(columns=["pop_u5", "pop_60"]), NET, None, "unit_id")
    assert none.A_raster.isna().all() and none.A_lo.isna().all() and none.A_hi.isna().all()  # no interval from one method
    assert none.pop_cut_u5.isna().all()
    a3 = SC.access_tables(cells(), NET, RAS, "adm3_pcode").set_index("adm3_pcode")
    assert a3.A.to_dict() == {"a1": 1.0, "a2": 0.0, "b1": 0.75}


def test_priority_rows():
    acc = SC.access_tables(cells(), NET, RAS, "unit_id")
    fc = pd.DataFrame({"unit_id": ["A", "B"], "R": [0.6, 0.2], "pop": [200.0, 200.0]})
    nodes = pd.DataFrame({"unit_id": ["A", "B"], "is_sentinel": [True, False], "sentinel_rank": [1, 2], "community": [0, 0]})
    r = SC.scenario_rows(fc, acc, nodes, None, storm="ompong", dlat=0.0).set_index("unit_id")
    assert r.P.tolist() == pytest.approx([0.3, 0.15])
    assert r.P_lo.tolist() == pytest.approx([0.3, 0.0]) and r.P_hi.tolist() == pytest.approx([0.6, 0.15])
    assert r.tier.tolist() == [3, 2] and (r.storm == "ompong").all() and r.is_sentinel.tolist() == [True, False]
    units = pd.DataFrame({"unit_id": ["A", "B"]})
    r0 = SC.scenario_rows(fc, None, nodes, units)
    assert r0.A.isna().all() and r0.P.isna().all() and r0.tier.tolist() == [2, 1]  # access missing: R alone decides
    a3 = SC.access_tables(cells(), NET, RAS, "adm3_pcode").merge(cells()[["adm3_pcode", "unit_id"]].drop_duplicates(), on="adm3_pcode")
    p3 = SC.adm3_priority(a3, fc).set_index("adm3_pcode")
    assert p3.R.tolist() == [0.6, 0.6, 0.2] and p3.P.tolist() == pytest.approx([0.6, 0.0, 0.15])


def test_catalog_train_ends():
    panel = pd.DataFrame({"week": pd.date_range("2016-01-10", "2021-01-10", freq="W-SUN")})
    ends = SC.catalog_train_ends(panel)
    assert ends == sorted(ends) and ends[-1] == pd.Timestamp(MODEL_END)
    assert set(F.refit_dates()) <= set(ends) and ends[0] >= panel.week.min()
    assert ends[0] - pd.Timedelta(weeks=SC.CATALOG_REFIT_WEEKS) < panel.week.min()  # extended back as far as possible
    steps = set(np.diff(ends[:-1]))
    assert steps == {pd.Timedelta(weeks=SC.CATALOG_REFIT_WEEKS)}
    assert all(e.weekday() == 6 for e in ends)


def test_rank_change_and_weighted_median():
    idx = list("abcdefgh")
    R = pd.Series(np.linspace(0.1, 0.8, 8), index=idx)
    A = pd.Series(np.linspace(0.05, 0.4, 8), index=idx)
    P0 = R * A
    same = SC._rank_change(R, P0, A)
    assert same["kendall_tau"] == pytest.approx(1.0) and same["top10_overlap"] == 8
    rev = SC._rank_change(R, P0, pd.Series(1 / R.to_numpy() ** 3, index=idx))
    assert rev["kendall_tau"] == pytest.approx(-1.0)
    assert SC._wmedian(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 10.0])) == 3.0
    assert SC._wmedian(np.array([3.0, 1.0, 2.0]), np.array([1.0, 1.0, 1.0])) == 2.0
