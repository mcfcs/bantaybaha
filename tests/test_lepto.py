"""bantay.lepto: week labels, lag helpers, the seasonal expectation, the event-study ratios, and the key-findings text
whose every qualitative word must follow the numbers (hand-built lag and event tables)."""

import numpy as np
import pandas as pd
import pytest

from bantay import lepto as L

pytestmark = pytest.mark.usefixtures("isolated_status")


# ---------------------------------------------------------------- week labels and helpers

def test_first_sunday_and_pcode():
    assert L.first_sunday(2019) == pd.Timestamp("2019-01-06")
    assert L.first_sunday(2017) == pd.Timestamp("2017-01-01")  # already a Sunday
    assert L._new_pcode("PH015518000") == "PH0105518"  # Dagupan: old 9-digit PSGC -> COD-AB ADM3


def test_mendeley_weeks_end_on_the_first_sunday(tmp_path, monkeypatch):
    f = tmp_path / "m.xlsx"
    pd.DataFrame({"Week": [1, 2, 52], "Leptospirosis - 2019": [3, 4, 5], "Dengue - 2019": [100, 120, 90],
                  "Leptospirosis - 2020": [6, np.nan, 7]}).to_excel(f, index=False)
    monkeypatch.setattr(L, "MENDELEY", f)
    m = L.mendeley_weekly()
    assert m.week.iloc[0] == pd.Timestamp("2019-01-06") and m.week.iloc[1] == pd.Timestamp("2019-01-13")
    assert m[m.year == 2019].week.iloc[-1] == pd.Timestamp("2019-01-06") + pd.Timedelta(weeks=51)
    assert m[m.year == 2020].week.iloc[0] == pd.Timestamp("2020-01-05")
    assert (m.week.dt.weekday == 6).all() and m.cases.isna().sum() == 1  # not reported stays NaN
    assert L.mendeley_weekly("Dengue").cases.tolist() == [100, 120, 90]


def test_add_lags_never_shifts_across_a_gap():
    """A gap in the weekly grid gives NaN lags (the guard), never the value of a row at the wrong distance."""
    df = pd.DataFrame({"week": pd.to_datetime(["2019-01-06", "2019-01-13", "2019-01-27", "2019-02-03"]), "x": [1.0, 2.0, 3.0, 4.0]})
    out = L.add_lags(df, "x", lags=[0, 1, 2])
    assert out.x_l0.tolist() == [1, 2, 3, 4]
    assert np.isnan(out.x_l1.iloc[2]) and out.x_l1.iloc[3] == 3.0  # 01-27's previous row is 2 weeks back: no lag 1
    assert np.isnan(out.x_l2.iloc[2]) and np.isnan(out.x_l2.iloc[3])  # rows 2 back are 3 weeks back
    full = L.add_lags(pd.DataFrame({"week": pd.date_range("2019-01-06", periods=5, freq="W-SUN"), "x": np.arange(5.0)}), "x", lags=[2])
    assert full.x_l2.tolist()[2:] == [0.0, 1.0, 2.0]
    g = pd.concat([df.assign(c="a"), df.assign(c="b", x=df.x * 10)])
    og = L.add_lags(g, "x", lags=[1], by="c")
    assert np.isnan(og[og.c == "b"].x_l1.iloc[0])  # never borrows from another city
    assert og[og.c == "b"].x_l1.iloc[1] == 10.0


def test_harmonics():
    h = L.harmonics(pd.to_datetime(["2019-01-01", "2019-07-02"]))
    assert list(h.columns) == ["sin1", "cos1", "sin2", "cos2"]
    assert h.cos1.iloc[0] == pytest.approx(np.cos(2 * np.pi / 365.25))


def test_expected_uses_same_calendar_weeks_of_other_base_years():
    wk = pd.Timestamp("2018-09-16")
    idx, vals = [], []
    for j in range(-6, 3):
        for dw in (-1, 0, 1):
            w = wk + pd.Timedelta(weeks=52 * j + dw)
            idx.append(("PC", w))
            vals.append(100.0 if w.year == 2018 else float(w.year - 2000))  # the storm year itself must be left out
    s = pd.Series(vals, index=pd.MultiIndex.from_tuples(idx))
    used = [w.year for (_, w) in s.index if w.year in L.BASE_YEARS and w.year != 2018]
    assert L._expected(s, wk, "PC") == pytest.approx(np.mean([y - 2000 for y in used]))
    assert np.isnan(L._expected(s, wk, "OTHER"))


def test_event_summary_ratio_and_continuity():
    ev = pd.DataFrame({"storm": "s", "adm3_pcode": ["a", "b", "a", "b"], "inside_gale": [True, False, True, False],
                       "period": ["pre", "pre", "post1_4", "post1_4"], "cases": [10.0, 5.0, 0.0, 4.0],
                       "expected": [5.0, 5.0, 2.0, 4.0]})
    g, rr = L.event_summary(ev)
    r = rr.set_index("period")
    assert r.loc["pre", "ratio"] == pytest.approx((10 / 5) / (5 / 5)) and r.loc["pre", "continuity"] == 0
    assert r.loc["post1_4", "continuity"] == 0.5  # a zero cell
    assert r.loc["post1_4", "ratio"] == pytest.approx((0.5 / 2) / (4.5 / 4))
    assert r.loc["pre", "ci_lo"] < r.loc["pre", "ratio"] < r.loc["pre", "ci_hi"]


# ---------------------------------------------------------------- the key-findings wording

def lagtab(variant, exposure, peak_lag=4, sig=(3, 4), cum=(2.0, 1.5, 2.6), peak=1.4):
    rows = []
    for k in L.LAGS:
        irr = peak if k == peak_lag else 1.05
        lo = 1.1 if k in sig else 0.9
        rows.append(dict(variant=variant, exposure=exposure, model="joint", term=f"{exposure}_l{k}", lag=k, irr=irr,
                         ci_lo=lo, ci_hi=irr + 0.3, p=0.01, n_obs=100, n_cases=50, alpha=0.5))
        rows.append(dict(variant=variant, exposure=exposure, model="single", term=f"{exposure}_l{k}", lag=k, irr=3.0,
                         ci_lo=2.0, ci_hi=4.0, p=0.01, n_obs=100, n_cases=50, alpha=0.5))  # single fits must be ignored
    rows.append(dict(variant=variant, exposure=exposure, model="joint", term="cum_0_6", lag=np.nan, irr=cum[0], ci_lo=cum[1],
                     ci_hi=cum[2], p=0.01, n_obs=100, n_cases=50, alpha=0.5))
    return rows


def city_tab(peak_lag=4, sig=(3, 4)):
    return pd.DataFrame(lagtab("12 cities", "rain_7d", peak_lag, sig) + lagtab("12 cities", "heavy", 3)
                        + lagtab("literal CCHAIN week (date+6)", "rain_7d", peak_lag - 1)
                        + lagtab("city-specific seasonality", "rain_7d", peak_lag))


def nat_tab(cum=(1.5, 1.2, 1.9), cum19=(1.2, 0.8, 1.7)):
    return pd.DataFrame(lagtab("2019-2020", "rain_7d", 5, (5,), cum) + lagtab("2019 only", "rain_7d", 5, (), cum19))


def did_tab(ru_pre=(0.6, 2.0), ot_pre=(1.5, 3.7), ru_post=(4.3, 1.7, 10.9), ot_post=(0.8, 0.5, 1.3), pooled=(1.3, 0.9, 1.9)):
    rows = [("rolly+ulysses", "inside_x_post1_4", *ru_post), ("rolly+ulysses", "inside_x_pre", 1.2, *ru_pre),
            ("ompong+tisoy", "inside_x_post1_4", *ot_post), ("ompong+tisoy", "inside_x_pre", 2.4, *ot_pre),
            ("ompong+rolly+tisoy+ulysses", "inside_x_post1_4", *pooled)]
    return pd.DataFrame(rows, columns=["storms", "term", "irr", "ci_lo", "ci_hi"])


def test_sig_lags_and_span():
    assert L._sig_lags(city_tab(sig=(3, 4)), "12 cities") == [3, 4]
    assert L._sig_lags(city_tab(sig=()), "12 cities") == []
    assert L._sig_lags(city_tab(sig=(2, 3, 4)), "12 cities", "heavy") == [3, 4]  # its own exposure's rows only
    assert L._span([]) == "no single lag clearly above 1"
    assert L._span([3]) == "3 weeks later"
    assert L._span([2, 3, 4]) == "2-4 weeks later"


def test_span_singular_week():
    assert L._span([1]) == "1 week later"


@pytest.mark.parametrize("peak_lag, phrase", [(4, "2 weeks later than"), (3, "1 week later than"), (2, "the same as"),
                                              (1, "1 week earlier than"),
                                              (0, "2 weeks earlier than")])
def test_city_finding_compares_the_peak_with_two_weeks(peak_lag, phrase):
    out = L._findings(None, city_tab(peak_lag, sig=(peak_lag,)), None)
    city = out[0]
    assert f"Joint distributed-lag peak at lag {peak_lag}: IRR 1.40" in city
    assert f"({L._span([peak_lag])}, 95% CI above 1)" in city
    assert f"The peak is {phrase} the ~2-week peak" in city
    assert out[-1].startswith("- **Sentinel-1 flood vs cases: not estimable.**")


def test_city_finding_without_significant_lags():
    assert "(no lag has its 95% CI above 1)" in L._findings(None, city_tab(sig=()), None)[0]


def test_national_finding_follows_the_intervals():
    out = L._findings(nat_tab(), None, None)[0]
    assert "same direction" in out and "much of the national signal comes from 2020" in out
    out = L._findings(nat_tab(cum19=(1.3, 1.1, 1.6)), None, None)[0]
    assert "same direction" in out and "comes from 2020" not in out  # 2019 alone also above 1
    out = L._findings(nat_tab(cum=(1.1, 0.9, 1.4)), None, None)[0]
    assert "inconclusive" in out and "comes from 2020" not in out


def event_line(did):
    return [x for x in L._findings(None, None, did) if "Typhoon event study" in x][0]


def test_event_study_placebo_wording():
    out = event_line(did_tab())
    assert "Typhoon event study: mixed." in out
    assert "Rolly + Ulysses (2020): inside-swath cities had 4.30 (1.70-10.90) times" in out
    assert "placebo 1.20 (0.60-2.00), passes" in out  # CI contains 1
    assert "placebo 2.40 (1.50-3.70), fails" in out  # CI above 1
    assert "heavy monsoon rain from late July 2018" in out  # explanation only for the failed Ompong + Tisoy placebo
    assert "no general storm effect can be claimed." in out  # pooled CI contains 1


def test_event_study_consistent_and_no_effect():
    both = event_line(did_tab(ot_pre=(0.7, 1.4), ot_post=(2.0, 1.2, 3.0), pooled=(2.0, 1.4, 2.9)))
    assert "Typhoon event study: consistent effect." in both and "fails" not in both
    assert both.endswith("All four pooled: 2.00 (1.40-2.90).")
    none = event_line(did_tab(ru_pre=(1.1, 2.0), ru_post=(1.5, 0.9, 2.5)))
    assert "Typhoon event study: no clear effect." in none
    assert "placebo 1.20 (1.10-2.00), fails" in none  # lower bound above 1, even when barely


def test_event_study_placebo_boundary_counts_as_passing():
    out = event_line(did_tab(ru_pre=(1.0, 1.0)))
    assert "placebo 1.20 (1.00-1.00), passes" in out  # ci_lo <= 1 <= ci_hi, inclusive as coded


def test_event_study_without_placebo_row_fails():
    did = did_tab()
    did = did[~((did.storms == "rolly+ulysses") & (did.term == "inside_x_pre"))]
    out = event_line(did)
    assert "(pre-landfall placebo n/a, fails)" in out
