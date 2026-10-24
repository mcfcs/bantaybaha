"""bantay.leadlag: series preparation inside the training window, the empty graph below MIN_T, the lagged
cross-correlation baseline on a planted lead, and the sentinel / community metrics."""

import numpy as np
import pandas as pd
import pytest

from bantay import leadlag as LL


def panel(n_units=4, n_weeks=200, seed=0, lead=None):
    rng = np.random.default_rng(seed)
    wk = pd.date_range("2016-01-10", periods=n_weeks, freq="W-SUN")
    x = rng.gamma(2, 2, (n_weeks, n_units))
    if lead:  # unit 1 follows unit 0 by `lead` weeks
        x[lead:, 1] = x[:-lead, 0] + 0.2 * rng.random(n_weeks - lead)
    df = pd.DataFrame(x, index=wk, columns=[f"U{i}" for i in range(n_units)])
    return df.stack().rename("incidence").rename_axis(["week", "unit_id"]).reset_index()


def test_prepare_is_standardised_and_uses_only_the_window():
    p = panel()
    end = pd.Timestamp("2018-06-03")
    d = LL.prepare(p, end)
    assert d.index.max() <= end and len(d) == (p.week <= end).sum() // 4 - 52  # seasonal difference eats a year
    assert d.mean().abs().max() < 1e-9 and (d.std() - 1).abs().max() < 1e-9
    late = p.copy()
    late.loc[late.week > end, "incidence"] *= 50
    pd.testing.assert_frame_equal(d, LL.prepare(late, end))


def test_prepare_drops_gappy_units_and_fills_short_gaps():
    p = panel()
    gappy = (p.unit_id == "U3") & (p.index % 3 == 0)  # a third of U3's weeks missing
    short = (p.unit_id == "U2") & p.week.isin(pd.date_range("2017-06-04", periods=2, freq="W-SUN"))
    p.loc[gappy | short, "incidence"] = np.nan
    d = LL.prepare(p, p.week.max())
    assert "U3" not in d.columns and "U2" in d.columns
    assert not d.isna().any().any()


def test_learn_below_min_t_gives_an_empty_graph():
    p = panel()
    end = pd.Timestamp("2016-01-10") + pd.Timedelta(weeks=52 + LL.MIN_T - 2)  # T = MIN_T - 1 differenced weeks
    edges, nodes, meta = LL.learn(p, end)  # PCMCI+ is never run
    assert meta["T"] == LL.MIN_T - 1 and meta["n_edges"] == 0 and meta["method"] == "pcmciplus"
    assert edges.empty and list(edges.columns) == LL.EDGE_COLS + ["window_end"]
    assert sorted(nodes.unit_id) == ["U0", "U1", "U2", "U3"]
    assert not nodes.is_sentinel.any() and (nodes.out_degree == 0).all()
    assert nodes.sentinel_score.tolist() == pytest.approx([0.25] * 4)


def test_xcorr_finds_a_planted_two_week_lead():
    d = LL.prepare(panel(n_units=5, n_weeks=260, lead=2), pd.Timestamp("2020-12-27"))
    e = LL.xcorr_graph(d)
    top = e.iloc[0]
    assert (top.source, top.target, top.lag) == ("U0", "U1", 2)
    assert (e.q < 0.05).all() and (e.weight > 0).all() and (e.source != e.target).all()
    assert not e.duplicated(["source", "target"]).any()  # best lag per ordered pair
    assert ((e.source == "U1") & (e.target == "U0")).sum() == 0  # the follower does not lead


def test_learn_xcorr_window_and_meta():
    p = panel(n_units=5, n_weeks=260, lead=2)
    edges, nodes, meta = LL.learn(p, pd.Timestamp("2019-12-29"), method="xcorr")
    assert meta["T"] >= LL.MIN_T and meta["n_series"] == 5 and meta["end"] == "2019-12-29"
    assert (edges.window_end == "2019-12-29").all() and (nodes.method == "xcorr").all()
    assert "U0" in set(edges.source)


def test_node_metrics_sentinel_is_the_leader():
    edges = pd.DataFrame({"source": ["A", "A", "A", "B"], "target": ["B", "C", "D", "C"], "weight": [0.5, 0.4, -0.3, 0.2]})
    m = LL.node_metrics(edges, list("ABCDE")).set_index("unit_id")
    assert m.sentinel_rank["A"] == 1 and m.out_degree["A"] == 3 and m.in_degree["C"] == 2
    assert m.is_sentinel["A"] and not m.is_sentinel["C"]  # C ranks high but leads nobody
    assert m.community["E"] != m.community["A"]  # an isolated unit is its own community
    assert m.sentinel_score.sum() == pytest.approx(1.0)
