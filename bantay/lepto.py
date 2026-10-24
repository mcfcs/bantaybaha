"""Leptospirosis stretch goal: lagged rain / typhoon association, national (weekly) and city-week (12 CCHAIN cities).

Retrospective association analysis, not a forecast: every model is fit on the whole overlap with the rain data, and
the heavy-rain threshold is an in-sample percentile (descriptive only; a forecasting use would have to refit both inside
each training window).

Data
  national  Mendeley Parreno `Diseases_Data_for_NBL.xlsx`, columns "Leptospirosis - YYYY", morbidity weeks 1-52.
            Week w of year Y is labelled firstSunday(Y) + 7(w-1) days (Mon-Sun week ending that Sunday): the same
            file's dengue column matches the HDX national dengue sum best on that labelling (2019 r = 0.956, check in
            `alignment()`). Overlap with CHIRPS: 2019 (52 weeks) + 2020 (28 weeks, COVID reporting collapse).
  city      Project CCHAIN `disease_pidsr_totals.csv` (PIDSR-DOH city-weekly 2008-2022, 12 cities, old 9-digit PSGC
            `PH015518000` -> COD-AB `PH0105518`). CCHAIN dates are Mondays; the CCHAIN dengue counts match the HDX
            city dengue best when a CCHAIN week dated D is the DOH week ending D + 13 days (7 of 10 matched cities on
            levels and on week-to-week differences; `alignment()`), so that is the label used (CCHAIN_LABEL_DAYS);
            the literal reading D + 6 is a sensitivity fit (it shortens every lag by one week). Only these 12 cities: never read as provincial or national.
  rain      CHIRPS v2.0 daily -> week (Mon-Sun) sum. National = area-weighted mean of the panel's unit-week chirps_7d
            (85 units = PHL land); city = mean over CHIRPS cells in the COD-AB ADM3 polygon (nearest land cell if none).
  typhoon   national: population share of units in any IBTrACS gale swath that week (panel storm_gale_hit);
            city: city polygon inside any gale circle that week (`storms.unit_week_exposure`, every WP storm).

Models (statsmodels NegativeBinomial, NB2, alpha by ML)
  national  y_t ~ const + covid_t + sum_k (sin, cos)(2 pi k doy/365.25), k = 1, 2 + exposure lag(s);
            HAC (Newey-West, 4 lags) standard errors.
  city      y_ct ~ city FE + year FE + covid + 2 harmonics + exposure lag(s); Driscoll-Kraay (hac-groupsum over weeks,
            4 lags) standard errors, robust to cross-city and serial correlation.
  Each exposure is fit one lag at a time ("single", lags 0-6) and with lags 0-6 together ("joint", a distributed-lag
  model; "cum" = sum of the joint lags). IRR per 50 mm of weekly rain, per heavy-rain week (>= own 90th percentile
  2016-2020) or per gale week / full population share in a gale swath.
  events    stacked windows -4..+8 weeks around each backtest landfall week; cities inside the storm's whole-lifetime
            gale swath vs outside. Expected = the city's mean in the same 3 calendar weeks of the other 2014-2019 CCHAIN
            years (floor 0.1). Quasi-Poisson GLM with offset log(expected), FE storm x event week, inside x period
            (pre -4..-1 as a placebo, 0, +1..+4, +5..+8): IRR = inside obs/exp over outside obs/exp. Plus the
            Sentinel-1 flooded share of each city (descriptive).
"""

import numpy as np
import pandas as pd
import geopandas as gpd

from .config import RAW, INTERIM, PROCESSED, APP_DATA, STORMS, CRS_M, week_ending, missing, record

MENDELEY = RAW / "mendeley_parreno" / "Diseases_Data_for_NBL.xlsx"
CCHAIN = RAW / "cchain"
DENGUE = RAW / "dengue_hdx" / "doh-epi-dengue-data-2016-2021.csv"
SUMMARY = PROCESSED / "lepto_summary.md"
CITY_RAIN = INTERIM / "lepto_city_chirps_week.parquet"

LAGS = list(range(7))
RAIN_PER = 50.0  # mm per week: one IRR unit
HEAVY_Q = 0.90
HARM_K = 2
HAC_LAGS = 4
COVID_START = pd.Timestamp("2020-03-15")  # Luzon enhanced community quarantine from 16 Mar 2020
CCHAIN_LABEL_DAYS = 13  # CCHAIN Monday date -> DOH week-ending Sunday (see module docstring); literal = 6
EVENT_K = list(range(-4, 9))
PERIODS = {"pre": range(-4, 0), "k0": [0], "post1_4": range(1, 5), "late5_8": range(5, 9)}
BASE_YEARS = range(2014, 2020)  # CCHAIN years for the seasonal expectation: recent, pre-COVID, storm year left out (2008-2013 had much larger outbreaks, e.g. Iloilo 2011, Cagayan de Oro 2012)
EXP_FLOOR = 0.1  # cases/week: floor for a zero seasonal expectation (small cities), used as a Poisson offset
# HDX dengue `loc` of the same city, for the CCHAIN date check (Palayan and Legazpi have no city row in HDX)
HDX_CITY = {"Iloilo City": "ILOILO CITY", "Davao City": "DAVAO CITY", "Cagayan de Oro City": "CAGAYAN DE ORO CITY",
            "Zamboanga City": "ZAMBOANGA CITY", "City of Mandaluyong": "MANDALUYONG CITY", "Mandaue City": "MANDAUE CITY",
            "City of Muntinlupa": "MUNTINLUPA CITY", "City of Navotas": "NAVOTAS CITY", "Dagupan City": "DAGUPAN CITY",
            "Tacloban City": "TACLOBAN"}


# ---------------------------------------------------------------- data

def first_sunday(year):
    d = pd.Timestamp(f"{year}-01-01")
    return d + pd.Timedelta(days=(6 - d.weekday()) % 7)


def mendeley_weekly(disease="Leptospirosis"):
    """National weekly counts: year, mw, week (DOH week-ending Sunday), cases (NaN = not reported). None if missing."""
    if not MENDELEY.exists():
        return missing("mendeley_parreno", f"{MENDELEY.relative_to(RAW.parent.parent)} not found")
    mx = pd.read_excel(MENDELEY)
    long = mx.melt(id_vars="Week", var_name="col", value_name="cases")
    long[["disease", "year"]] = long.col.str.rsplit(" - ", n=1, expand=True)
    long = long[long.disease == disease].copy()
    long["year"] = long.year.astype(int)
    long["mw"] = long.Week.astype(int)
    long["week"] = [first_sunday(y) + pd.Timedelta(weeks=w - 1) for y, w in zip(long.year, long.mw)]
    return long[["year", "mw", "week", "cases"]].sort_values("week").reset_index(drop=True)


def cchain_weekly(disease="LEPTOSPIROSIS", label_days=CCHAIN_LABEL_DAYS):
    """CCHAIN city-week counts: adm3_pcode (COD-AB), pcode_old, city, week, cases. None if missing."""
    f = CCHAIN / "disease_pidsr_totals.csv"
    if not f.exists():
        return missing("cchain", f"{f.name} not found in {CCHAIN}")
    cc = pd.read_csv(f, parse_dates=["date"])
    cc = cc[cc.disease_common_name == disease]
    loc = pd.read_csv(CCHAIN / "location.csv").drop_duplicates("adm3_pcode")[["adm3_pcode", "adm3_en"]]
    cc = cc.merge(loc, on="adm3_pcode", how="left")
    out = pd.DataFrame({
        "pcode_old": cc.adm3_pcode.values,
        "adm3_pcode": [_new_pcode(p) for p in cc.adm3_pcode],
        "city": cc.adm3_en.values,
        "week": (cc.date + pd.Timedelta(days=label_days)).values,
        "cases": cc.case_total.astype(float).values,
    })
    return out.sort_values(["adm3_pcode", "week"]).reset_index(drop=True)


def _new_pcode(old):
    """Old 9-digit PSGC (PH RR PP MM 000) -> COD-AB ADM3 pcode (PH RR 0PP MM); checked by name for all 12 cities."""
    return f"PH{old[2:4]}0{old[4:6]}{old[6:8]}"


def hdx_dengue():
    if not DENGUE.exists():
        return None
    dg = pd.read_csv(DENGUE, skiprows=[1])
    dg["loc"] = dg["loc"].str.strip()
    dg["date"] = pd.to_datetime(dg.date)
    return dg


def alignment():
    """Week-label checks against the HDX dengue file: correlation of the dengue counts under each candidate shift."""
    dg = hdx_dengue()
    if dg is None:
        return None
    rows = []
    nat = dg.groupby("date").cases.sum()
    mx = mendeley_weekly("Dengue")
    if mx is not None:
        for y in sorted(set(mx.year) & {2019, 2020}):
            m = mx[mx.year == y]
            for k in (-1, 0, 1):
                j = pd.DataFrame({"c": m.cases.values, "h": nat.reindex(m.week + pd.Timedelta(weeks=k)).values})
                rows.append(dict(check=f"mendeley_dengue_{y}_vs_hdx_national", shift=f"{k:+d} wk", **_r(j)))
    cc = cchain_weekly("DENGUE FEVER", label_days=0)
    if cc is not None:
        for city, loc in HDX_CITY.items():
            c = cc[cc.city == city].set_index("week").cases
            h = dg[dg["loc"] == loc].set_index("date").cases
            for d in (-1, 6, 13, 20):
                j = pd.concat([c.set_axis(c.index + pd.Timedelta(days=d)), h], axis=1, join="inner")
                rows.append(dict(check=f"cchain_dengue_{city}_vs_hdx", shift=f"+{d} d" if d >= 0 else f"{d} d", **_r(j)))
    return pd.DataFrame(rows)


def _r(j):
    """Correlation of two weekly count columns (levels, and week-to-week differences: the sharper timing test)."""
    j = j.set_axis(["c", "h"], axis=1)
    dj = j.diff()
    j, dj = j.dropna(), dj.dropna()
    return dict(n=len(j), r=j.c.corr(j.h), r_diff=dj.c.corr(dj.h))


def city_polygons():
    """COD-AB ADM3 polygons of the 12 CCHAIN cities (unit_id = COD-AB pcode, as rain.zonal_weights expects)."""
    from .units import read_adm

    a3 = read_adm(3)
    if a3 is None:
        return None
    cc = cchain_weekly()
    if cc is None:
        return None
    pc = cc[["adm3_pcode", "city"]].drop_duplicates()
    g = a3[["adm3_pcode", "adm3_name", "adm2_name", "geometry"]].merge(pc, on="adm3_pcode")
    if len(g) != len(pc):
        missing("lepto_city_polygons", f"only {len(g)}/{len(pc)} CCHAIN cities found in COD-AB ADM3")
    return g.rename(columns={"adm3_pcode": "unit_id"}).reset_index(drop=True)


def city_rain(cities):
    """CHIRPS week (Mon-Sun) rain per city: week, adm3_pcode, chirps_7d, chirps_3d, chirps_max1d. Cached in interim."""
    from . import rain
    from .panel import cached
    from .units import COD_ZIP

    def build():
        d = rain.chirps_daily_units(cities)
        return None if d is None else rain.weekly(d, "chirps").rename(columns={"unit_id": "adm3_pcode"})

    files = sorted(rain.CHIRPS_DIR.glob("*.nc"))
    if not files:
        return missing("chirps", f"no CHIRPS files in {rain.CHIRPS_DIR}")
    return cached(CITY_RAIN, files + [COD_ZIP, CCHAIN / "disease_pidsr_totals.csv"], build)


def city_storms(cities, ib):
    """Weekly gale exposure of each city from every WP storm (unit_week_exposure on the city polygons)."""
    from .storms import unit_week_exposure

    ex = unit_week_exposure(cities[["unit_id", "geometry"]], ib)
    if ex is None:
        return None
    return ex.rename(columns={"unit_id": "adm3_pcode"})[["adm3_pcode", "week", "storm_gale_hit", "storm_min_dist_km"]]


def national_exposure(panel, units):
    """National weekly rain (area-weighted CHIRPS / IMERG over the 85 units) and population share in a gale swath."""
    area = units.to_crs(6933).set_index("unit_id").geometry.area  # equal-area CRS
    p = panel[["unit_id", "week", "chirps_7d", "imerg_7d", "storm_gale_hit", "pop"]].copy()
    p["pop"] = p["pop"].fillna(0)
    p["area"] = p.unit_id.map(area)
    p["storm_gale_hit"] = p.storm_gale_hit.fillna(0)

    def wmean(g, col, w):
        ok = g[col].notna()
        return np.average(g.loc[ok, col], weights=g.loc[ok, w]) if ok.any() else np.nan

    rows = []
    for wk, g in p.groupby("week"):
        rows.append(dict(week=wk, rain_7d=wmean(g, "chirps_7d", "area"), imerg_7d=wmean(g, "imerg_7d", "area"),
                         rain_pop_7d=wmean(g, "chirps_7d", "pop"),
                         gale_pop_share=np.average(g.storm_gale_hit, weights=g["pop"]) if g["pop"].sum() > 0 else np.nan,
                         rain_cover=g.loc[g.chirps_7d.notna(), "area"].sum() / g.area.sum()))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- models

def harmonics(week, k=HARM_K):
    doy = pd.DatetimeIndex(week).dayofyear.values / 365.25
    return pd.DataFrame({f"{f}{i}": fn(2 * np.pi * i * doy) for i in range(1, k + 1) for f, fn in (("sin", np.sin), ("cos", np.cos))})


def add_lags(df, col, lags=LAGS, by=None):
    """Lagged copies {col}_l{k}: the value k weeks earlier (same group). Needs a complete weekly grid per group."""
    df = df.sort_values(([by] if by else []) + ["week"]).copy()
    for k in lags:
        s = df.groupby(by)[col].shift(k) if by else df[col].shift(k)
        # guard: the shifted row must be exactly k weeks earlier
        wk = df.groupby(by)["week"].shift(k) if by else df["week"].shift(k)
        df[f"{col}_l{k}"] = np.where(df.week - wk == pd.Timedelta(weeks=k), s, np.nan)
    return df


def fit_nb(y, X, cov="HAC", time=None):
    import statsmodels.api as sm

    m = sm.NegativeBinomial(np.asarray(y, float), X.astype(float), loglike_method="nb2")
    kw = dict(disp=0, maxiter=2000)
    start = None
    try:  # Poisson start values help with many fixed effects
        start = np.append(sm.GLM(np.asarray(y, float), X.astype(float), family=sm.families.Poisson()).fit().params.values, 0.5)
    except Exception:  # noqa: BLE001
        pass
    if cov == "HAC":
        return m.fit(start_params=start, cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, **kw)
    if cov == "DK":
        return m.fit(start_params=start, cov_type="hac-groupsum", cov_kwds={"time": np.asarray(time), "maxlags": HAC_LAGS}, **kw)
    return m.fit(start_params=start, **kw)


def _irr_rows(res, names, scale, **meta):
    rows = []
    ci = res.conf_int()
    for n in names:
        b, lo, hi = res.params[n], ci.loc[n, 0], ci.loc[n, 1]
        rows.append(dict(meta, term=n, irr=np.exp(b * scale), ci_lo=np.exp(lo * scale), ci_hi=np.exp(hi * scale),
                         p=res.pvalues[n], converged=bool(res.mle_retvals.get("converged", False))))
    return rows


def _cum_row(res, names, scale, **meta):
    import scipy.stats as st

    v = np.zeros(len(res.params))
    idx = [list(res.params.index).index(n) for n in names]
    v[idx] = 1
    b = float(v @ res.params.values)
    se = float(np.sqrt(v @ np.asarray(res.cov_params()) @ v))
    z = st.norm.ppf(0.975)
    return dict(meta, term="cum_0_6", irr=np.exp(b * scale), ci_lo=np.exp((b - z * se) * scale),
                ci_hi=np.exp((b + z * se) * scale), p=2 * st.norm.sf(abs(b / se)),
                converged=bool(res.mle_retvals.get("converged", False)))


def lag_profile(df, base_cols, exposure, scale, cov, time_col=None, **meta):
    """Single-lag fits (lags 0-6 one at a time) + one joint distributed-lag fit. Rows with any lag missing are dropped
    from every fit, so all fits use the same weeks."""
    lagc = [f"{exposure}_l{k}" for k in LAGS]
    d = df.dropna(subset=lagc + ["cases"]).reset_index(drop=True)
    base = d[base_cols]
    base = base[[c for c in base_cols if c == "const" or base[c].std() > 0]]  # e.g. a year dummy left with no rows
    t = d[time_col].values if time_col else None
    rows = []
    common = dict(meta, exposure=exposure, n_obs=len(d), n_cases=int(d.cases.sum()))
    for k, c in zip(LAGS, lagc):
        r = fit_nb(d.cases, pd.concat([base, d[[c]]], axis=1), cov, t)
        rows += _irr_rows(r, [c], scale, model="single", lag=k, alpha=r.params.get("alpha", np.nan), **common)
    r = fit_nb(d.cases, pd.concat([base, d[lagc]], axis=1), cov, t)
    rows += _irr_rows(r, lagc, scale, model="joint", alpha=r.params.get("alpha", np.nan), **common)
    for row, k in zip(rows[-len(LAGS):], LAGS):
        row["lag"] = k
    rows.append(_cum_row(r, lagc, scale, model="joint", lag=np.nan, alpha=r.params.get("alpha", np.nan), **common))
    return rows


# ---------------------------------------------------------------- 1. national

def national(panel, units):
    """National weekly lag table + the weekly series (cases, rain, gale share) for 2019-2020."""
    lep = mendeley_weekly()
    if lep is None:
        return None, None
    ex = national_exposure(panel, units).sort_values("week")
    for c in ("rain_7d", "rain_pop_7d", "gale_pop_share"):
        ex = add_lags(ex, c)
    q = ex.loc[ex.week.dt.year.between(2016, 2020), "rain_7d"].quantile(HEAVY_Q)
    ex["heavy"] = (ex.rain_7d >= q).astype(float).where(ex.rain_7d.notna())
    ex = add_lags(ex, "heavy")
    # same-file dengue against the HDX national sum: flags weeks whose reporting looks incomplete (ratio < 0.5)
    dgm = mendeley_weekly("Dengue")
    dg = hdx_dengue()
    lep = lep.merge(dgm[["week", "cases"]].rename(columns={"cases": "dengue_mendeley"}), on="week", how="left")
    if dg is not None:
        lep["dengue_hdx"] = lep.week.map(dg.groupby("date").cases.sum())
        lep["incomplete"] = (lep.dengue_mendeley / lep.dengue_hdx) < 0.5
    else:
        lep["dengue_hdx"], lep["incomplete"] = np.nan, False
    d = lep.merge(ex, on="week", how="left")
    d = d[d.year.isin([2019, 2020])]  # overlap with the rain data (CHIRPS ends 2020-12-31)
    d["covid"] = (d.week >= COVID_START).astype(float)
    d = pd.concat([d.reset_index(drop=True), harmonics(d.week)], axis=1)
    d["const"] = 1.0
    hcols = [c for c in d.columns if c[:3] in ("sin", "cos")]
    rows = []
    variants = {
        "2019-2020": (d.cases.notna(), ["const", "covid"] + hcols),
        "2019 only": (d.cases.notna() & (d.year == 2019), ["const"] + hcols),
        "2019-2020, complete weeks": (d.cases.notna() & ~d.incomplete.fillna(False).astype(bool), ["const", "covid"] + hcols),
        "2019-2020, no seasonality": (d.cases.notna(), ["const", "covid"]),
    }
    for vname, (m, base) in variants.items():
        dd = d[m].reset_index(drop=True)
        for exp, scale in (("rain_7d", RAIN_PER), ("rain_pop_7d", RAIN_PER), ("heavy", 1.0), ("gale_pop_share", 1.0)):
            if exp != "rain_7d" and vname != "2019-2020":
                continue
            try:
                rows += lag_profile(dd, base, exp, scale, "HAC", variant=vname, analysis="national")
            except Exception as e:  # noqa: BLE001
                print(f"  national {vname} {exp}: fit failed ({e})")
    tab = pd.DataFrame(rows)
    tab["irr_unit"] = tab.exposure.map({"rain_7d": f"+{RAIN_PER:g} mm/week national rain", "rain_pop_7d": f"+{RAIN_PER:g} mm/week population-weighted rain", "heavy": f"heavy-rain week (>= p{HEAVY_Q * 100:g} = {q:.0f} mm)",
                                        "gale_pop_share": "whole population in a gale swath (share 0 -> 1)"})
    tab["spec"] = "NB2; const + covid(>=2020-03-15) + 2 harmonics (doy) + exposure lag(s); HAC(4) SE"
    tab.loc[tab.variant == "2019 only", "spec"] = "NB2; const + 2 harmonics + rain lag(s); 2019 only; HAC(4) SE"
    tab.loc[tab.variant.str.contains("no seasonality"), "spec"] = "NB2; const + covid + rain lag(s); no harmonics; HAC(4) SE"
    series = d[["week", "year", "mw", "cases", "incomplete", "rain_7d", "rain_pop_7d", "imerg_7d", "gale_pop_share"]].assign(level="national", id="PH", name="Philippines")
    return tab, series


# ---------------------------------------------------------------- 2. cities

def city_panel(cities, ib, label_days=CCHAIN_LABEL_DAYS):
    lep = cchain_weekly(label_days=label_days)
    rn = city_rain(cities)
    if lep is None or rn is None:
        return None
    rn = rn[["adm3_pcode", "week", "chirps_7d", "chirps_max1d"]].rename(columns={"chirps_7d": "rain_7d", "chirps_max1d": "rain_max1d"})
    weeks = pd.date_range(rn.week.min(), rn.week.max(), freq="W-SUN")
    grid = pd.MultiIndex.from_product([cities.unit_id, weeks], names=["adm3_pcode", "week"]).to_frame(index=False)
    d = grid.merge(rn, on=["adm3_pcode", "week"], how="left")
    st = city_storms(cities, ib) if ib is not None else None
    if st is not None:
        d = d.merge(st, on=["adm3_pcode", "week"], how="left")
        d["storm_gale_hit"] = d.storm_gale_hit.fillna(0).astype(float)
    else:
        d["storm_gale_hit"] = np.nan
    q = d.groupby("adm3_pcode").rain_7d.quantile(HEAVY_Q)
    d["heavy"] = (d.rain_7d >= d.adm3_pcode.map(q)).astype(float).where(d.rain_7d.notna())
    for c in ("rain_7d", "heavy", "storm_gale_hit"):
        d = add_lags(d, c, by="adm3_pcode")
    d = d.merge(lep[["adm3_pcode", "week", "cases", "city"]], on=["adm3_pcode", "week"], how="left")
    d["city"] = d.adm3_pcode.map(cities.set_index("unit_id").city)
    return d, q


def city_lags(d, cities, city_season=False):
    """Design: const, city FE, year FE, covid, 2 common harmonics (city_season: one set of 2 harmonics per city)."""
    d = d[d.cases.notna()].reset_index(drop=True).copy()
    d["covid"] = (d.week >= COVID_START).astype(float)
    d["year"] = d.week.dt.year
    fe = pd.get_dummies(d.adm3_pcode, prefix="c", drop_first=True, dtype=float)
    yr = pd.get_dummies(d.year, prefix="y", drop_first=True, dtype=float)
    h = harmonics(d.week)
    if city_season:
        h = pd.concat([h.mul(d.adm3_pcode.eq(c).astype(float), axis=0).add_suffix(f"_{c}") for c in sorted(d.adm3_pcode.unique())], axis=1)
    X = pd.concat([pd.Series(1.0, index=d.index, name="const"), fe, yr, d[["covid"]], h], axis=1)
    d = pd.concat([d, X.drop(columns=[c for c in X.columns if c in d.columns])], axis=1)
    base = list(X.columns)
    d["t"] = (d.week - d.week.min()).dt.days // 7
    return d, base


def cities_analysis(cities, ib):
    out = city_panel(cities, ib)
    if out is None:
        return None, None, None
    d, q = out
    dm, base = city_lags(d, cities)
    rows = []
    spec = "NB2; city FE + year FE + covid + 2 harmonics + exposure lag(s); Driscoll-Kraay (hac-groupsum, 4 lags) SE"
    for exp, scale in (("rain_7d", RAIN_PER), ("heavy", 1.0), ("storm_gale_hit", 1.0)):
        rows += lag_profile(dm, base, exp, scale, "DK", time_col="t", variant="12 cities", analysis="city")
    # sensitivity: without Iloilo City (about half of all cases), and the literal CCHAIN week label (date + 6)
    ilo = cities.loc[cities.city == "Iloilo City", "unit_id"]
    if len(ilo):
        sub = d[d.adm3_pcode != ilo.iloc[0]]
        dm2, base2 = city_lags(sub, cities)
        rows += lag_profile(dm2, base2, "rain_7d", RAIN_PER, "DK", time_col="t", variant="11 cities (no Iloilo)", analysis="city")
    dm4, base4 = city_lags(d, cities, city_season=True)
    rows += lag_profile(dm4, base4, "rain_7d", RAIN_PER, "DK", time_col="t", variant="city-specific seasonality", analysis="city")
    alt = city_panel(cities, ib, label_days=6)
    if alt is not None:
        dm3, base3 = city_lags(alt[0], cities)
        rows += lag_profile(dm3, base3, "rain_7d", RAIN_PER, "DK", time_col="t", variant="literal CCHAIN week (date+6)", analysis="city")
    tab = pd.DataFrame(rows)
    tab["irr_unit"] = tab.exposure.map({"rain_7d": f"+{RAIN_PER:g} mm/week city rain", "heavy": f"heavy-rain week (>= city p{HEAVY_Q * 100:g})",
                                        "storm_gale_hit": "city inside a gale circle that week"})
    tab["spec"] = spec
    tab.loc[tab.variant == "city-specific seasonality", "spec"] = spec.replace("2 harmonics", "2 harmonics per city")
    series = d[["adm3_pcode", "city", "week", "cases", "rain_7d", "storm_gale_hit"]].rename(columns={"adm3_pcode": "id", "city": "name"}).assign(level="city")
    return tab, series, d


# ---------------------------------------------------------------- 3. typhoon events

def s1_city(cities, storm):
    """Sentinel-1 new-flood share of each city's observed land for one storm (read-only use of the tiles)."""
    import rasterio
    from rasterio import features
    from .flood import s1_tiles

    tiles = s1_tiles(storm)
    out = {u: [0, 0, 0] for u in cities.unit_id}  # observed px, flooded px, total px
    if not tiles:
        return None
    for t in tiles:
        with rasterio.open(t) as r:
            b = r.bounds
            sel = cities.cx[b.left:b.right, b.bottom:b.top]
            if sel.empty:
                continue
            a = r.read(1)
            for u, g in zip(sel.unit_id, sel.geometry):
                m = features.rasterize([(g, 1)], out_shape=a.shape, transform=r.transform, fill=0, dtype="uint8").astype(bool)
                out[u][0] += int((m & (a != 255)).sum())
                out[u][1] += int((m & (a == 1)).sum())
                out[u][2] += int(m.sum())
    df = pd.DataFrame([(u, *v) for u, v in out.items()], columns=["adm3_pcode", "s1_seen_px", "s1_flood_px", "s1_px"])
    with np.errstate(invalid="ignore", divide="ignore"):
        df["s1_flood_frac"] = np.where(df.s1_seen_px > 0, df.s1_flood_px / df.s1_seen_px, np.nan)
        df["s1_seen_frac"] = np.where(df.s1_px > 0, df.s1_seen_px / df.s1_px, 0.0)
    df["storm"] = storm
    return df


def _expected(s, wk, pc, years=BASE_YEARS):
    """Mean cases of the same city in the same 3 calendar weeks (52-week multiples) of the other pre-COVID years.
    `s`: cases Series indexed by (adm3_pcode, week), the full CCHAIN series."""
    vals = []
    for j in range(-15, 16):
        if j == 0:
            continue
        for dw in (-1, 0, 1):
            w = wk + pd.Timedelta(weeks=52 * j + dw)
            if w.year in years and w.year != wk.year:
                v = s.get((pc, w), np.nan)
                if not np.isnan(v):
                    vals.append(v)
    return np.mean(vals) if vals else np.nan


def events(d, cities, ib):
    """City x storm x event-week table and the pooled inside-vs-outside estimates."""
    from .storms import storm_track, swath

    cm = cities.to_crs(CRS_M).set_index("unit_id")
    full = cchain_weekly().set_index(["adm3_pcode", "week"]).cases  # 2008-2022, for the seasonal expectation
    rows, s1 = [], []
    for key, s in STORMS.items():
        tr = storm_track(key, ib=ib)
        sw = swath(tr) if tr is not None and len(tr) else None
        if sw is None:
            missing(f"lepto_swath_{key}", "no IBTrACS gale swath")
            continue
        pts = gpd.GeoSeries(gpd.points_from_xy(tr.LON, tr.LAT), crs=4326).to_crs(CRS_M)
        w0 = week_ending(pd.Timestamp(s["landfall"]))
        f = s1_city(cities, key)
        if f is not None:
            s1.append(f)
        for pc, g in cm.geometry.items():
            inside = bool(g.intersects(sw))
            dist = float(pts.distance(g).min() / 1000)
            for k in EVENT_K:
                wk = w0 + pd.Timedelta(weeks=k)
                v = d.loc[(d.adm3_pcode == pc) & (d.week == wk), ["cases", "rain_7d"]]
                rows.append(dict(storm=key, storm_name=s["local"], landfall=s["landfall"], adm3_pcode=pc, city=cm.loc[pc, "city"],
                                 inside_gale=inside, track_dist_km=dist, k=k, week=wk,
                                 cases=v.cases.iloc[0] if len(v) else np.nan, rain_7d=v.rain_7d.iloc[0] if len(v) else np.nan,
                                 expected=_expected(full, wk, pc)))
    ev = pd.DataFrame(rows)
    if s1:
        ev = ev.merge(pd.concat(s1)[["storm", "adm3_pcode", "s1_flood_frac", "s1_seen_frac"]], on=["storm", "adm3_pcode"], how="left")
    ev["period"] = ev.k.map({k: p for p, ks in PERIODS.items() for k in ks})
    return ev


def event_did(ev, storms=None):
    """Quasi-Poisson, offset log(expected): cases ~ FE(storm x event week) + inside x {pre, k0, post1_4, late5_8}.

    Each inside x period IRR is (inside obs/exp) / (outside obs/exp) in that period, net of anything common to all
    cities in the same storm week (national reporting, COVID). `pre` is a placebo: it should be ~1."""
    import statsmodels.api as sm

    e = ev[ev.cases.notna()].copy()
    if storms:
        e = e[e.storm.isin(storms)]
    n_floor = int((e.expected.fillna(0) < EXP_FLOOR).sum())
    e["expected"] = e.expected.fillna(0).clip(lower=EXP_FLOOR)
    e = e[e.groupby(["storm", "k"]).cases.transform("sum") > 0]  # all-zero storm weeks: FE is -inf, no information
    if e.empty or not e.inside_gale.any() or e.inside_gale.all():
        return []
    X = pd.get_dummies(e.storm + "_" + e.k.astype(str), prefix="sk", dtype=float)
    terms = []
    for per in PERIODS:
        X[f"inside_x_{per}"] = (e.inside_gale & (e.period == per)).astype(float)
        terms.append(f"inside_x_{per}")
    r = sm.GLM(e.cases.values, X.values, family=sm.families.Poisson(), offset=np.log(e.expected.values)).fit(scale="X2")
    names = list(X.columns)
    ci = r.conf_int()
    out = []
    for t in terms:
        i = names.index(t)
        per = t.replace("inside_x_", "")
        a, b = e[e.inside_gale & (e.period == per)], e[~e.inside_gale & (e.period == per)]
        out.append(dict(storms="+".join(storms or sorted(e.storm.unique())), term=t, irr=np.exp(r.params[i]),
                        ci_lo=np.exp(ci[i, 0]), ci_hi=np.exp(ci[i, 1]), p=r.pvalues[i], dispersion=r.scale, n_obs=len(e),
                        n_inside_city_storms=int(e[e.inside_gale].groupby(["storm", "adm3_pcode"]).ngroups),
                        cases_inside=float(a.cases.sum()), expected_inside=float(a.expected.sum()),
                        cases_outside=float(b.cases.sum()), expected_outside=float(b.expected.sum()), n_expected_floored=n_floor))
    return out


def event_summary(ev):
    """Per storm x group x period: observed and expected; per storm the inside/outside ratio of obs/exp (Poisson CI,
    expected treated as known, no overdispersion) for each period."""
    import scipy.stats as st

    g = ev.groupby(["storm", "inside_gale", "period"], as_index=False).agg(
        n_cities=("adm3_pcode", "nunique"), cases=("cases", "sum"), expected=("expected", "sum"))
    g["obs_exp"] = g.cases / g.expected
    rows = []
    z = st.norm.ppf(0.975)
    for (s, per), h in g.groupby(["storm", "period"]):
        i, o = h[h.inside_gale], h[~h.inside_gale]
        if i.empty or o.empty:
            continue
        A, EA, C, EC = float(i.cases.iloc[0]), float(i.expected.iloc[0]), float(o.cases.iloc[0]), float(o.expected.iloc[0])
        cc = 0.5 if min(A, C) == 0 else 0.0  # continuity correction for a zero cell
        lr = np.log(((A + cc) / EA) / ((C + cc) / EC))
        se = np.sqrt(1 / (A + cc) + 1 / (C + cc))
        rows.append(dict(storm=s, period=per, ratio=np.exp(lr), ci_lo=np.exp(lr - z * se), ci_hi=np.exp(lr + z * se), continuity=cc))
    return g, pd.DataFrame(rows)


# ---------------------------------------------------------------- run

def _fmt(r):
    return f"{r.irr:.2f} ({r.ci_lo:.2f}-{r.ci_hi:.2f})"


def run():
    """Whole stage: writes data/processed/app/lepto_*.csv / .parquet and data/processed/lepto_summary.md."""
    from .panel import load_panel
    from .units import load_units
    from .storms import load_ibtracs

    APP_DATA.mkdir(parents=True, exist_ok=True)
    al = alignment()
    if al is not None:
        al.to_csv(APP_DATA / "lepto_alignment.csv", index=False)
    panel, units = load_panel(), load_units()
    ib = load_ibtracs()
    nat, nat_series = national(panel, units)
    if nat is not None:
        nat.to_csv(APP_DATA / "lepto_national_lag.csv", index=False)
        record("lepto_national", True, f"{int(nat_series.cases.notna().sum())} national weeks with cases and rain")
    cities = city_polygons()
    city, city_series, d, ev = None, None, None, None
    if cities is not None:
        city, city_series, d = cities_analysis(cities, ib)
    if city is not None:
        city.to_csv(APP_DATA / "lepto_city_lag.csv", index=False)
        record("lepto_city", True, f"{d.adm3_pcode.nunique()} CCHAIN cities, {int(d.cases.notna().sum())} city-weeks")
        if ib is not None:
            ev = events(d, cities, ib)
            ev.to_csv(APP_DATA / "lepto_events.csv", index=False)
            record("lepto_events", True, f"{ev.storm.nunique()} storms x {ev.adm3_pcode.nunique()} cities")
        else:
            missing("lepto_events", "IBTrACS needed for the swaths")
    series = [s for s in (nat_series, city_series) if s is not None]
    if series:
        ser = pd.concat(series, ignore_index=True)
        ser["incomplete"] = ser.incomplete.astype("boolean") if "incomplete" in ser else pd.NA
        ser.to_parquet(APP_DATA / "lepto_weekly.parquet")
    did, summ, rr = None, None, None
    if ev is not None:
        did = pd.DataFrame(event_did(ev) + event_did(ev, ["ompong", "tisoy"]) + event_did(ev, ["rolly", "ulysses"]))
        summ, rr = event_summary(ev)
        did.to_csv(APP_DATA / "lepto_events_did.csv", index=False)
        summ.to_csv(APP_DATA / "lepto_events_summary.csv", index=False)
        rr.to_csv(APP_DATA / "lepto_events_ratio.csv", index=False)
    write_summary(nat, nat_series, city, d, ev, did, summ, rr, al, cities)
    return nat, city, ev


def _lag_md(tab, variant, exposure):
    t = tab[(tab.variant == variant) & (tab.exposure == exposure)]
    if t.empty:
        return "_not fitted_"
    s = t[t.model == "single"].set_index("lag")
    j = t[(t.model == "joint") & (t.term != "cum_0_6")].set_index("lag")
    cum = t[t.term == "cum_0_6"].iloc[0]
    lines = ["| lag (weeks) | single-lag IRR (95% CI) | p | joint DLM IRR (95% CI) | p |", "|---|---|---|---|---|"]
    for k in LAGS:
        lines.append(f"| {k} | {_fmt(s.loc[k])} | {s.loc[k].p:.3f} | {_fmt(j.loc[k])} | {j.loc[k].p:.3f} |")
    lines.append(f"| sum 0-6 | | | {_fmt(cum)} | {cum.p:.3f} |")
    n = t.iloc[0]
    return "\n".join(lines) + f"\n\nn = {n.n_obs} weeks, {n.n_cases:,} cases; IRR per {n.irr_unit}; NB alpha (joint) = {j.iloc[0].alpha:.2f}."


def _peak(tab, variant, exposure="rain_7d"):
    t = tab[(tab.variant == variant) & (tab.exposure == exposure) & (tab.model == "joint")]
    lag = t[t.term != "cum_0_6"].sort_values("irr").iloc[-1]
    return lag, t[t.term == "cum_0_6"].iloc[0]


def _sig_lags(tab, variant, exposure="rain_7d"):
    """Lags of the joint rain model whose 95% CI lies above 1."""
    t = tab[(tab.variant == variant) & (tab.exposure == exposure) & (tab.model == "joint") & (tab.term != "cum_0_6")]
    return sorted(int(x) for x in t[t.ci_lo > 1].lag)


def _span(lags):
    if not lags:
        return "no single lag clearly above 1"
    if lags[0] == lags[-1]:
        return f"{lags[0]} week{'' if lags[0] == 1 else 's'} later"
    return f"{lags[0]}-{lags[-1]} weeks later"


def _findings(nat, city, did):
    """Key findings for the summary; every qualitative word (later, same direction, fails, ...) follows the numbers."""
    out = []
    if city is not None:
        pk, cum = _peak(city, "12 cities")
        pk6, _ = _peak(city, "literal CCHAIN week (date+6)")
        pks, _ = _peak(city, "city-specific seasonality")
        hv, hcum = _peak(city, "12 cities", "heavy")
        gap = int(pk.lag) - 2  # Matsushita et al. (2018): risk peaks ~2 weeks after rain
        vs = (f"{abs(gap)} week{'s' if abs(gap) != 1 else ''} {'later' if gap > 0 else 'earlier'} than" if gap else "the same as")
        sig = _sig_lags(city, "12 cities")
        when = f"{_span(sig)}, 95% CI above 1" if sig else "no lag has its 95% CI above 1"
        out.append(f"- **Cities (12, 2016-2020): rain is followed by leptospirosis ({when}).** Joint distributed-lag peak at lag {int(pk.lag)}: IRR {_fmt(pk)} per +50 mm/week; cumulative lags 0-6 "
                   f"{_fmt(cum)}. Peak with city-specific seasonality: lag {int(pks.lag)}, {_fmt(pks)}; with the literal CCHAIN week "
                   f"label: lag {int(pk6.lag)} ({_fmt(pk6)}). A heavy-rain week (>= city p90) peaks at lag {int(hv.lag)}: {_fmt(hv)}. "
                   f"The peak is {vs} the ~2-week peak of Matsushita et al. (2018); the week-label uncertainty (above) and any "
                   "onset-to-report delay in PIDSR (not checked here) bear on that comparison.")
    if nat is not None:
        pk, cum = _peak(nat, "2019-2020")
        p19, c19 = _peak(nat, "2019 only")
        both = cum.ci_lo > 1
        out.append(f"- **National (2019-2020, 80 weeks): {'same direction' if both else 'inconclusive'}.** Joint peak at lag "
                   f"{int(pk.lag)}: {_fmt(pk)} per +50 mm/week, cumulative {_fmt(cum)}; with 2019 alone (52 weeks) the cumulative "
                   f"effect is {_fmt(c19)} (peak lag {int(p19.lag)}: {_fmt(p19)})"
                   + (", so much of the national signal comes from 2020 (COVID-era reporting): treat it as indicative."
                      if c19.ci_lo <= 1 < cum.ci_lo else "."))
    if did is not None and len(did):
        g = did.set_index(["storms", "term"])

        def row(st, t):
            return g.loc[(st, t)] if (st, t) in g.index else None

        def cell(r):
            return _fmt(r) if r is not None else "n/a"

        parts, verdicts = [], []
        for st, label in (("rolly+ulysses", "Rolly + Ulysses (2020)"), ("ompong+tisoy", "Ompong + Tisoy")):
            post, pre = row(st, "inside_x_post1_4"), row(st, "inside_x_pre")
            if post is None:
                continue
            placebo_ok = pre is not None and pre.ci_lo <= 1 <= pre.ci_hi
            effect = post.ci_lo > 1 and placebo_ok
            verdicts.append(effect)
            parts.append(f"{label}: inside-swath cities had {cell(post)} times the outside cities' obs/exp in weeks +1..+4 "
                         f"(pre-landfall placebo {cell(pre)}, {'passes' if placebo_ok else 'fails'})")
            if st == "ompong+tisoy" and not placebo_ok:
                parts[-1] += "; weeks of heavy monsoon rain from late July 2018 had already raised Luzon/NCR cases"
        pooled = row("ompong+rolly+tisoy+ulysses", "inside_x_post1_4")
        head = "mixed" if any(verdicts) and not all(verdicts) else ("consistent effect" if verdicts and all(verdicts) else "no clear effect")
        tail = ("" if pooled is None else f" All four pooled: {cell(pooled)}"
                + ("; no general storm effect can be claimed." if pooled.ci_lo <= 1 else "."))
        out.append(f"- **Typhoon event study: {head}.** " + ". ".join(parts) + "." + tail)
    out.append("- **Sentinel-1 flood vs cases: not estimable.** Few city-storm pairs show any observed flood (see section 3), "
               "so the flood-mediation step stays a literature assumption here.")
    return out


def write_summary(nat, nat_series, city, d, ev, did, summ, rr, al, cities):
    L = ["# Leptospirosis: lagged rain and typhoon association (stretch goal)", "",
         "_Written by `python scripts/build.py lepto` (`bantay/lepto.py`). Retrospective association, not a forecast; "
         "every number below is from the files in `data/processed/app/lepto_*`._", ""]
    L += ["## Key findings", ""] + _findings(nat, city, did) + ["", "## Data and week labels", ""]
    if nat_series is not None:
        ns = nat_series
        L.append(f"- **National** (Mendeley Parreno, PIDSR national weekly): {int(ns.cases.notna().sum())} weeks with both cases and "
                 f"CHIRPS rain ({int(ns[(ns.year == 2019)].cases.notna().sum())} in 2019, {int(ns[(ns.year == 2020)].cases.notna().sum())} in 2020); "
                 f"{int(ns.cases.sum()):,} cases. 2020 has 24 unreported weeks and the COVID reporting collapse (a `covid` term from 2020-03-15). "
                 f"{int(ns.incomplete.fillna(False).astype(bool).sum())} weeks look incompletely reported (same-file dengue < 50% of the HDX national dengue that week) "
                 f"and are dropped in one sensitivity fit. Rain data stop in 2020, so 2021-2023 cannot be used.")
    if al is not None:
        a = al[al.check.str.startswith("mendeley_dengue_2019")].set_index("shift").r
        c = al[al.check.str.startswith("cchain")].pivot_table(index="check", columns="shift", values="r")
        cd = al[al.check.str.startswith("cchain")].pivot_table(index="check", columns="shift", values="r_diff")
        best = c.idxmax(axis=1).value_counts()
        bestd = cd.idxmax(axis=1).value_counts()
        L.append(f"- **Week labels** (`lepto_alignment.csv`): Mendeley MW w = week ending firstSunday + 7(w-1) days; its dengue column vs the HDX "
                 f"national sum r = {a.get('+0 wk', np.nan):.3f} (vs {a.get('-1 wk', np.nan):.3f} / {a.get('+1 wk', np.nan):.3f} one week off). "
                 f"CCHAIN Monday date D -> DOH week ending D + {CCHAIN_LABEL_DAYS} d: best shift for "
                 + ", ".join(f"{v} {'city' if v == 1 else 'cities'} at {k}" for k, v in best.items())
                 + f" on levels (mean r {c.mean().round(3).to_dict()}; the median favours +6 d), and "
                 + ", ".join(f"{v} {'city' if v == 1 else 'cities'} at {k}" for k, v in bestd.items())
                 + f" on week-to-week differences, the sharper timing test (mean r {cd.mean().round(3).to_dict()}). "
                 "The literal reading (D + 6) is a sensitivity fit; it shortens every lag by one week.")
    if d is not None:
        dc = d[d.cases.notna()]
        tot = dc.groupby("city").cases.sum().sort_values(ascending=False)
        L.append(f"- **Cities** (Project CCHAIN PIDSR city-week, {dc.adm3_pcode.nunique()} cities, weeks {dc.week.min().date()} to {dc.week.max().date()}): "
                 f"{int(dc.cases.sum()):,} cases; " + ", ".join(f"{k} {int(v)}" for k, v in tot.items())
                 + f". {(dc.cases == 0).mean():.0%} of city-weeks are zero. **These 12 cities are not a sample of provinces; nothing here is extrapolated to provinces.**")
    L += ["", "## 1. National weekly lag analysis (2019-2020)", ""]
    if nat is not None:
        L += ["Spec: `cases_t ~ NB2(const + covid_t + sin/cos(2pi k doy/365.25), k=1,2 + rain_{t-l})`, HAC(4) SE. "
              "'single' fits one lag at a time; 'joint' fits lags 0-6 together (distributed lag).", "",
              "**Rain (+50 mm/week national area-mean CHIRPS), 2019-2020:**", "", _lag_md(nat, "2019-2020", "rain_7d"), ""]
        for v in ("2019 only", "2019-2020, complete weeks", "2019-2020, no seasonality"):
            t = nat[(nat.variant == v) & (nat.exposure == "rain_7d") & (nat.model == "single")].set_index("lag")
            if len(t):
                L.append(f"- {v}: single-lag IRR by lag 0-6 = " + ", ".join(f"{k}: {_fmt(t.loc[k])}" for k in LAGS))
        for exp, lab in (("rain_pop_7d", "population-weighted rain (+50 mm/week)"), ("heavy", "heavy-rain week"), ("gale_pop_share", "population share in a gale swath")):
            t = nat[(nat.variant == "2019-2020") & (nat.exposure == exp) & (nat.model == "single")].set_index("lag")
            if len(t):
                L.append(f"- {lab} (single lags): " + ", ".join(f"{k}: {_fmt(t.loc[k])}" for k in LAGS))
        L.append("")
    L += ["## 2. City-week analysis (12 CCHAIN cities, 2016-2020)", ""]
    if city is not None:
        L += ["Spec: `cases_ct ~ NB2(city FE + year FE + covid + 2 harmonics + rain_{c,t-l})`, Driscoll-Kraay SE "
              "(statsmodels `hac-groupsum` over weeks, 4 lags).", "",
              "**Rain (+50 mm/week city CHIRPS):**", "", _lag_md(city, "12 cities", "rain_7d"), "",
              "**Heavy-rain week (>= the city's own 90th percentile):**", "", _lag_md(city, "12 cities", "heavy"), "",
              "**City inside a gale circle (any WP storm) that week:**", "", _lag_md(city, "12 cities", "storm_gale_hit"), ""]
        for v in ("city-specific seasonality", "11 cities (no Iloilo)", "literal CCHAIN week (date+6)"):
            t = city[(city.variant == v) & (city.model == "single")].set_index("lag")
            if len(t):
                L.append(f"- {v}, rain single lags: " + ", ".join(f"{k}: {_fmt(t.loc[k])}" for k in LAGS))
        L.append("")
    L += ["## 3. Typhoon event study (weeks -4..+8 around landfall)", ""]
    if ev is not None:
        ins = ev[ev.k == 0].groupby("storm").apply(lambda g: ", ".join(g[g.inside_gale].city)).to_dict()
        L.append("Cities inside each storm's whole-lifetime gale swath: " + "; ".join(f"{STORMS[k]['local']}: {v or 'none'}" for k, v in ins.items()) + ".")
        L.append("")
        if summ is not None:
            L += ["| storm | group | pre (-4..-1) obs / exp | k0 | +1..+4 | +5..+8 |", "|---|---|---|---|---|---|"]
            for (s, i), h in summ.groupby(["storm", "inside_gale"]):
                h = h.set_index("period")
                cell = lambda p: f"{int(h.loc[p].cases)} / {h.loc[p].expected:.1f}" if p in h.index else ""
                L.append(f"| {STORMS[s]['local']} | {'inside' if i else 'outside'} ({int(h.n_cities.iloc[0])}) | {cell('pre')} | {cell('k0')} | {cell('post1_4')} | {cell('late5_8')} |")
            L += ["", "Expected = the city's mean in the same 3 calendar weeks of the other 2014-2019 CCHAIN years, so in 2020 (COVID) every "
                  "city sits below expectation; the inside/outside ratio removes that common drop.", ""]
        if rr is not None and len(rr):
            L += ["Per storm, inside / outside ratio of obs/exp (Poisson CI, expected treated as known, no overdispersion):", "",
                  "| storm | pre (placebo) | k0 | +1..+4 | +5..+8 |", "|---|---|---|---|---|"]
            for s_, h in rr.groupby("storm"):
                h = h.set_index("period")
                cell = lambda p: (f"{h.loc[p].ratio:.2f} ({h.loc[p].ci_lo:.2f}-{h.loc[p].ci_hi:.2f})" + ("*" if h.loc[p].continuity else "")) if p in h.index else ""
                L.append(f"| {STORMS[s_]['local']} | {cell('pre')} | {cell('k0')} | {cell('post1_4')} | {cell('late5_8')} |")
            L += ["", "(*) 0.5 added to a zero cell.", ""]
        if did is not None and len(did):
            L += ["Pooled (quasi-Poisson, offset log expected, FE storm x event week; IRR = inside obs/exp over outside obs/exp):", "",
                  "| storms | period | IRR (95% CI) | p | dispersion | inside city-storms | inside obs / exp | outside obs / exp |",
                  "|---|---|---|---|---|---|---|---|"]
            for r in did.itertuples():
                L.append(f"| {r.storms} | {r.term.replace('inside_x_', '')} | {r.irr:.2f} ({r.ci_lo:.2f}-{r.ci_hi:.2f}) | {r.p:.3f} | {r.dispersion:.2f} | "
                         f"{r.n_inside_city_storms} | {int(r.cases_inside)} / {r.expected_inside:.1f} | {int(r.cases_outside)} / {r.expected_outside:.1f} |")
            L += ["", "Rolly and Ulysses landed 10 days apart, so their windows share city-weeks: the same weeks enter both storms in the pooled fits, and the two are not independent events."]
            L += ["", f"{int(did.n_expected_floored.iloc[0])} city-weeks had a zero seasonal expectation (floored at {EXP_FLOOR} cases/week)."]
        if "s1_flood_frac" in ev:
            s1 = ev[ev.k == 0][["storm", "city", "inside_gale", "s1_flood_frac", "s1_seen_frac"]]
            post = ev[ev.period == "post1_4"].groupby(["storm", "city"]).agg(cases=("cases", "sum"), expected=("expected", "sum")).reset_index()
            s1 = s1.merge(post, on=["storm", "city"])
            seen = s1[s1.s1_seen_frac > 0.2]
            fl = seen[seen.s1_flood_frac > 0]
            L += ["", f"**Sentinel-1**: {len(seen)} of {len(s1)} city-storm pairs have radar over > 20% of the city; "
                  f"{len(fl)} show any new flood (max {seen.s1_flood_frac.max():.1%}). "
                  + ("Pairs with flood: " + "; ".join(f"{STORMS[r.storm]['local']} {r.city} {r.s1_flood_frac:.1%} flooded, {int(r.cases)} cases in +1..+4 (exp {r.expected:.1f})" for r in fl.itertuples()) + ". " if len(fl) else "")
                  + "Too few flooded city-storm pairs to estimate a flood-case relation; reported descriptively only."]
    L += ["", "## Caveats", "",
          "- Power: the national series is ~80 weeks with a COVID break and gaps (HAC errors treat the observed weeks as consecutive); "
          "the city panel is ~3,000 city-weeks but under 2,000 cases, over a third of them in Iloilo City, mostly zero weeks. Rain is "
          "seasonal, so the harmonics absorb much of its variation and the rain terms identify within-season anomalies; the common "
          "harmonics do not remove city-specific seasons (see the city-specific seasonality row).",
          "- Lags 0-6 are collinear (weekly rain is autocorrelated); read the joint profile and the cumulative sum together, not single "
          "joint coefficients.",
          "- Week labels: the CCHAIN-vs-HDX check fixes the city weeks to within about one week; a one-week label error shifts the lag "
          "profile one week (see the 'literal CCHAIN week' row).",
          "- The heavy-rain threshold is an in-sample percentile and the models are fit on all weeks: fine for a retrospective "
          "association, not for a forecast (that would refit both inside each training window).",
          "- The event study has 4 storms (2 in the COVID year; Rolly and Ulysses 10 days apart, so their windows overlap) and a "
          "handful of inside cities per storm; inside vs outside is mostly Luzon/NCR vs Visayas/Mindanao. Before Ompong, CHIRPS "
          "has heavy-rain weeks (>= the city's p90) in the inside cities from late July to early September 2018 (Dagupan "
          "385 mm in the week ending 22 Jul and 141-275 mm/week from 12 Aug to 2 Sep), so those cities were already far above "
          "expectation before landfall (placebo column). For the same reason the landfall-week (k0) ratios reflect earlier "
          "rain, not the storm: incubation alone is usually 1-2 weeks.",
          "- CCHAIN covers 12 cities only; the national series is Mendeley. Neither says anything about provinces.",
          "- Matsushita et al. (2018) found the rain-leptospirosis risk peaking ~2 weeks after heavy rain, mediated by flooding; "
          "compare the lag profile above with that, not with a significance threshold."]
    SUMMARY.write_text("\n".join(L) + "\n", encoding="utf-8")
