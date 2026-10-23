"""DOH-Epi dengue (HDX): load, fold the 126 reporting units into harmonised units, add population.

Rules (AGENTS.md, findings 1-3): skip CSV row 2 (HXL tags), strip `loc`, never use `deaths`. A unit-week is the sum of
its member reporting units and is NaN (not 0) unless every member reported that week.
"""

import pandas as pd

from .config import RAW, FIRST_WEEK, LAST_WEEK, WEEK_FREQ, have, missing, record
from .units import DENGUE_XW, read_crosswalk

DENGUE = RAW / "dengue_hdx" / "doh-epi-dengue-data-2016-2021.csv"
CENSUS = RAW / "census2020" / "2020_CPH_SexAge_Popn_Mun_Admin3.xlsx"


def weeks():
    return pd.date_range(FIRST_WEEK, LAST_WEEK, freq=WEEK_FREQ)


def load_dengue():
    if not DENGUE.exists():
        return missing("dengue_hdx", f"{DENGUE.name} not found")
    dg = pd.read_csv(DENGUE, skiprows=[1])
    dg["loc"] = dg["loc"].str.strip()
    dg["date"] = pd.to_datetime(dg["date"])
    assert (dg.date.dt.weekday == 6).all(), "DOH weeks should end on Sunday"
    record("dengue_hdx", True, f"{dg['loc'].nunique()} reporting units, {dg.date.nunique()} weeks")
    return dg[["loc", "date", "cases", "Region"]]  # deaths deliberately dropped (finding 2)


def unit_week_cases():
    dg = load_dengue()
    if dg is None or not DENGUE_XW.exists():
        return missing("dengue_unit_week", "dengue file or crosswalk missing")
    xw = read_crosswalk(DENGUE_XW)[["dengue_loc", "unit_id"]]
    w = weeks()
    full = (dg.set_index(["loc", "date"]).cases
            .reindex(pd.MultiIndex.from_product([dg["loc"].unique(), w], names=["loc", "week"])).reset_index())
    full = full.merge(xw, left_on="loc", right_on="dengue_loc", how="left")
    assert full.unit_id.notna().all(), "dengue unit without crosswalk row"
    g = full.groupby(["unit_id", "week"])
    out = pd.DataFrame({"cases_sum": g.cases.sum(min_count=1), "n_reporting": g.cases.count(), "n_members": g.cases.size()})
    out["cases"] = out.cases_sum.where(out.n_reporting == out.n_members)
    record("dengue_unit_week", True, f"{out.cases.isna().sum()} NaN unit-weeks of {len(out)}")
    return out.drop(columns="cases_sum").reset_index()


def unit_population():
    """2020 CPH population per harmonised unit (HDX municipal table, sheet PopnMun).

    The table's `Province` column already places HUCs in their geographic province (Cotabato City under Maguindanao),
    so units are matched on that column by name. Its MunCode is the old 9-digit PSGC and does not join to COD-AB ADM3
    pcodes for HUCs or post-2022 Maguindanao, so it is not used here."""
    if not have("census2020", CENSUS):
        return None
    from .units import ADM2_XW, norm

    cph = pd.read_excel(CENSUS, "PopnMun")
    xw2 = read_crosswalk(ADM2_XW)
    by_name = {norm(n): u for n, u in zip(xw2.unit_name, xw2.unit_id)}
    ordinal = {"FIRST": "First", "SECOND": "Second", "THIRD": "Third", "FOURTH": "Fourth"}
    fix = {"SGA": "Cotabato (North Cotabato)", "CITY OF ISABELA (NOT A PROVINCE)": "Basilan"}

    def unit_of(prov):
        p = str(prov).strip().upper()
        if p.startswith("NCR"):
            o = next(v for k, v in ordinal.items() if k in p)
            return by_name.get(norm(f"Metropolitan Manila {o} District"))
        return by_name.get(norm(fix.get(p, p)))

    cph["unit_id"] = cph.Province.map(unit_of)
    bad = cph[cph.unit_id.isna() & cph.TotalPopn.notna()]
    if len(bad):
        print(f"  WARNING census: provinces with no unit: {sorted(bad.Province.unique())}")
    out = cph.groupby("unit_id", as_index=False).TotalPopn.sum().rename(columns={"TotalPopn": "pop2020"})
    record("census_population", True, f"{out.pop2020.sum() / 1e6:.2f} M people in {len(out)} units")
    return out
