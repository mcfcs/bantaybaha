"""Build docs/results/: the evaluation report and the 20-slide deck (both PDF) from the pipeline outputs.

Usage:
    python scripts/make_results.py            # needs a finished `python scripts/build.py`
    python scripts/make_results.py --no-pdf   # figures + HTML only

Reads data/processed/ (panel, app/*) and data/raw/MANIFEST.csv, plus three small raw tables read-only with pandas for
data-finding numbers (the DOH dengue CSV, the 2020 census age table, IBTrACS gale radii). Figures are drawn with matplotlib
in the vendored fonts (Big Shoulders Display, Barlow, Space Mono; docs/results/src/fonts, SIL OFL) and a palette checked with the dataviz validator (light surface:
teal #0A86B5, amber #C77700, red #C8323F; grey #6B7A88 = baseline / context only). HTML is printed to PDF with headless
Chrome or Edge. docs/results/figures/dashboard.png is a screenshot of the running app (see README in that folder).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import geopandas as gpd  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from shapely import wkt  # noqa: E402

from bantay.config import APP_DATA, PROCESSED, RAW, STORMS  # noqa: E402
from bantay.scenarios import TIERS  # noqa: E402

OUT = ROOT / "docs" / "results"
FIG = OUT / "figures"
SRC = OUT / "src"
FONTS = SRC / "fonts"

INK, TEAL, AMBER, RED, GREY, GRID, PAPER = "#0F1E28", "#0A86B5", "#C77700", "#C8323F", "#6B7A88", "#DDE3E8", "#FFFFFF"
SEQ = LinearSegmentedColormap.from_list("tide", ["#E6F2F7", "#7FC3DC", TEAL, "#08364A"])


# ---------------------------------------------------------------- data

def _opt_csv(p, **kw):
    return pd.read_csv(p, **kw) if p.exists() else None


def _opt_pq(p):
    return pd.read_parquet(p) if p.exists() else None


def load():
    d = dict(
        methods=_opt_csv(APP_DATA / "access_methods.csv"),
        methods_cat=_opt_csv(APP_DATA / "access_methods_catalog.csv"),
        models=_opt_csv(APP_DATA / "eval_models.csv"),
        models_meta=json.loads((APP_DATA / "eval_models.json").read_text()) if (APP_DATA / "eval_models.json").exists() else {},
        bench_summary=_opt_csv(APP_DATA / "bench_summary.csv"),
        scen_cat=_opt_pq(APP_DATA / "scenarios_catalog.parquet"),
        cat_storms=_opt_csv(APP_DATA / "catalog_storms.csv"),
        s1_adm3=_opt_pq(APP_DATA / "s1_adm3.parquet"),
        lepto_city=_opt_csv(APP_DATA / "lepto_city_lag.csv"),
        lepto_nat=_opt_csv(APP_DATA / "lepto_national_lag.csv"),
        lepto_did=_opt_csv(APP_DATA / "lepto_events_did.csv"),
        lepto_events=_opt_csv(APP_DATA / "lepto_events.csv"),
        panel=pd.read_parquet(PROCESSED / "panel.parquet"),
        s1_storm=(pd.read_parquet(PROCESSED / "s1_unit_storm.parquet") if (PROCESSED / "s1_unit_storm.parquet").exists()
                  else pd.DataFrame(columns=["unit_id", "s1_flood_frac", "s1_flood_pop", "storm"])),
        scen=pd.read_parquet(APP_DATA / "scenarios.parquet"),
        adm3=pd.read_parquet(APP_DATA / "scenarios_adm3.parquet"),
        tracks=pd.read_parquet(APP_DATA / "tracks.parquet"),
        swaths=pd.read_parquet(APP_DATA / "swaths.parquet"),
        evals=pd.read_csv(APP_DATA / "eval_summary.csv", index_col=0),
        evalf=pd.read_parquet(APP_DATA / "eval_forecasts.parquet"),
        rel=pd.read_csv(APP_DATA / "surge_reliability.csv"),
        cal=json.loads((APP_DATA / "surge_calibration.json").read_text()),
        valid=pd.read_csv(APP_DATA / "validation.csv"),
        sens=pd.read_csv(APP_DATA / "sensitivity.csv"),
        bench=pd.read_csv(APP_DATA / "benchmark_ncr.csv"),
        edges=pd.read_parquet(APP_DATA / "leadlag_edges_pcmciplus.parquet"),
        xedges=pd.read_parquet(APP_DATA / "leadlag_edges_xcorr.parquet"),
        nodes=pd.read_parquet(APP_DATA / "leadlag_nodes_pcmciplus.parquet"),
        llmeta=json.loads((APP_DATA / "leadlag_meta.json").read_text()),
        graphs=pd.read_csv(APP_DATA / "eval_graphs.csv"),
        hosp=pd.read_parquet(APP_DATA / "hospitals.parquet"),
        units=gpd.read_file(APP_DATA / "units_simplified.geojson"),
        manifest=pd.read_csv(RAW / "MANIFEST.csv"),
        status=json.loads((PROCESSED / "status.json").read_text()),
    )
    d["names"] = dict(zip(d["units"].unit_id, d["units"].unit_name))
    return d


def stats(d):
    """Every number quoted in the text, computed from the outputs."""
    k = {}
    m = d["manifest"]
    k["n_files"], k["gb"], k["n_sources"] = len(m), m.bytes.sum() / 1e9, m.source.nunique()
    p = d["panel"]
    k["n_units"], k["n_weeks"] = p.unit_id.nunique(), p.week.nunique()
    k["cases_nonnull"] = p.cases.notna().mean()
    k["pop"] = p.drop_duplicates("unit_id")["pop"].sum()
    h = p.drop_duplicates("unit_id")
    k["haz_units"] = int(h.hazard_any_25yr.notna().sum())
    k["haz_nomap"] = sorted(h[h.hazard_any_25yr.isna()].unit_name)
    k["haz_median"] = h.hazard_any_25yr.median()
    k["rain_r"] = p[["chirps_7d", "imerg_7d"]].corr().iloc[0, 1]
    e = d["evals"]
    k["ev"] = e
    k["relwis"], k["cov90"], k["cov50"] = e.loc["all", "relWIS xgb/naive"], e.loc["all", "cov90 xgb"], e.loc["all", "cov50 xgb"]
    k["relwis_graph"] = e.loc["all", "relWIS xgb/nograph"]
    k["relwis_noenv"], k["relwis_env"] = e.loc["all", "relWIS noenv/naive"], e.loc["all", "relWIS xgb/noenv"]
    k["n_scored"] = int(e.loc["all", "n"])
    c = d["cal"]["xgb"]
    k["brier"], k["brier_clim"], k["base_rate"] = c["brier"], c["brier_climatology"], c["base_rate"]
    fin = [x for x in d["llmeta"] if x["method"] == "pcmciplus"][0]
    k["ll_edges"], k["ll_T"], k["ll_N"] = fin["n_edges"], fin["T"], fin["n_series"]
    k["xc_edges"] = len(d["xedges"])
    a = d["adm3"]
    a0 = a[(a.storm == "ompong") & (a.dlat == 0) & (a.dlon == 0)]
    fin_pop = a0["pop"].sum() - a0.pop_no_access_base.sum()
    k["route_share"] = fin_pop / a0["pop"].sum()
    k["mean_hours"] = (a0.base_hours * (a0["pop"] - a0.pop_no_access_base)).sum() / fin_pop
    k["cells_pop"] = a0["pop"].sum()
    k["n_hosp"] = len(d["hosp"])
    k["n_adm3"] = a0.adm3_pcode.nunique()
    k["n_scen"] = len(d["scen"][["storm", "dlat", "dlon"]].drop_duplicates())
    s = d["scen"]
    # columns from optional build parts (raster method, HRSL, calibration): NaN when that part did not run, so the
    # guarded sections below say "not available" instead of failing
    for c in ("A_lo", "A_hi", "A_raster", "R_raw", "pop_cut_raster", "pop_cut_u5", "pop_cut_60", "pop_cells"):
        if c not in s:
            s = s.assign(**{c: np.nan})
    d["scen"] = s
    b = s[(s.dlat == 0) & (s.dlon == 0)]
    b = b.assign(cut_lo=b.pop_cells * b.A_lo, cut_hi=b.pop_cells * b.A_hi)
    k["storm_tab"] = b.groupby("storm").agg(cut=("pop_cut", "sum"), A=("A", "mean"), ferries=("ferries_cancelled", "first"),
                                            t3=("tier", lambda t: int((t == 3).sum())), t2=("tier", lambda t: int((t == 2).sum())),
                                            src=("flood_source", "first"), R=("R", "mean"), R_raw=("R_raw", "mean"),
                                            cutr=("pop_cut_raster", "sum"), Ar=("A_raster", "mean"), cut_lo=("cut_lo", "sum"),
                                            cut_hi=("cut_hi", "sum"), u5=("pop_cut_u5", "sum"), o60=("pop_cut_60", "sum"))
    k["top"] = {st: d["names"][g.sort_values("P", ascending=False).unit_id.iloc[0]] for st, g in b.groupby("storm")}
    k["bench"] = d["bench"].share_cut.iloc[0]
    k["tau_min"] = d["sens"].kendall_tau.min()
    k["missing"] = {kk: v["detail"] for kk, v in d["status"].items() if not v["available"]}
    s1 = p.dropna(subset=["s1_flood_frac"])
    k["s1_ok"] = len(s1) > 0
    if k["s1_ok"]:
        by = d["s1_storm"]  # per storm: panel weeks hold the max of overlapping storms (Rolly / Ulysses)
        lw = {key: by[by.storm == key] for key in STORMS}
        k["s1_tab"] = {key: dict(pop=float(g.s1_flood_pop.sum()), units=int((g.s1_flood_frac > 0.01).sum()),
                                 frac_max=float(g.s1_flood_frac.max()), top=d["names"][g.loc[g.s1_flood_pop.idxmax(), "unit_id"]])
                       for key, g in lw.items() if len(g)}
        k["ems"] = s1_ems_agreement()
    k["src_obs"] = "Sentinel-1 observed flood" if b.flood_source.isin(["sentinel1", "observed"]).any() else "the NOAH 25-yr hazard proxy"
    k["names_of"] = d["names"]
    k["n_ferry"] = len(pd.read_parquet(APP_DATA / "ferries.parquet"))
    stats_access(d, k, s, b)
    stats_calibration(d, k)
    stats_models(d, k)
    stats_catalog(d, k, b)
    stats_lepto(d, k)
    stats_data(d, k)
    k["n_edges_windows"] = d["graphs"][d["graphs"].method == "pcmciplus"].assign(y=lambda g: pd.to_datetime(g.end).dt.year)
    gw = k["n_edges_windows"].groupby("y").n_edges.agg(["min", "max"])
    k["edges_by_year"] = {int(y): (int(r["min"]), int(r["max"])) for y, r in gw.iterrows()}
    return k


def _rng(lo, hi, f="{:.0f}"):
    return f.format(lo) if f.format(lo) == f.format(hi) else f"{f.format(lo)}-{f.format(hi)}"


def stats_access(d, k, s, b):
    """Network vs MAP friction raster, the method range, Meta HRSL vulnerable groups, Sentinel-1 per municipality."""
    from scipy import stats as ss

    m = d["methods"]
    k["raster_ok"] = m is not None and b.A_raster.notna().any()
    if not k["raster_ok"]:
        return
    k["mbase"] = m[m.kind == "baseline"].iloc[0].to_dict()
    sc = m[m.kind == "scenario"]
    obs = sc[(sc.dlat == 0) & (sc.dlon == 0)].set_index("storm")
    k["rho_A_obs"] = obs.spearman_A_units.to_dict()
    sh = s[(s.dlat != 0) | (s.dlon != 0)]
    g = sh.groupby(["storm", "dlat", "dlon"]).agg(cut=("pop_cut", "sum"), cutr=("pop_cut_raster", "sum"), A=("A", "mean"),
                                                 Ar=("A_raster", "mean"), t3=("tier", lambda t: int((t == 3).sum())))
    k["proxy"] = dict(cut=(g.cut.min(), g.cut.max()), cutr=(g.cutr.min(), g.cutr.max()),
                      ratio=float((g.cutr / g.cut).median()), n=len(g),
                      rho=(sc[(sc.dlat != 0) | (sc.dlon != 0)].spearman_A_units.min(), sc[(sc.dlat != 0) | (sc.dlon != 0)].spearman_A_units.max()),
                      t3=(int(g.t3.min()), int(g.t3.max())))
    k["proxy_storm"] = g.groupby(level=0).agg(cut_min=("cut", "min"), cut_max=("cut", "max"), t3_min=("t3", "min"), t3_max=("t3", "max"))
    tau, ov = {}, {}
    for st, gg in b.groupby("storm"):
        pr = gg.R * gg.A_raster
        tau[st] = ss.kendalltau(gg.P, pr).statistic
        ov[st] = len(set(gg.nlargest(10, "P").unit_id) & set(gg.assign(pr=pr).nlargest(10, "pr").unit_id))
    k["tau_methods"], k["top10_methods"] = tau, ov
    sens = d["sens"]
    k["tau_min_raster"] = sens.kendall_tau_raster.min() if "kendall_tau_raster" in sens else np.nan
    # vulnerable groups (Meta HRSL) against the 2020 census age table
    u = b.drop_duplicates("unit_id")
    k["hrsl_ok"] = u.pop_u5.notna().any()
    if k["hrsl_ok"]:
        k["u5_share"], k["o60_share"] = u.pop_u5.sum() / u.pop_cells.sum(), u.pop_60.sum() / u.pop_cells.sum()
        age = census_age()
        if age is not None:
            k["census_u5"], k["census_60"] = age
        st = k["storm_tab"]
        k["u5_cut_share"] = (st.u5 / st.cut).to_dict()
        k["o60_cut_share"] = (st.o60 / st.cut).to_dict()
    # Sentinel-1 per municipality
    s3 = d["s1_adm3"]
    if s3 is not None and len(s3):
        a3 = d["adm3"]
        a3 = a3[(a3.dlat == 0) & (a3.dlon == 0)].merge(s3[["storm", "adm3_pcode", "s1_flood_frac"]], on=["storm", "adm3_pcode"], how="left")
        tab = {}
        for key, gg in s3.groupby("storm"):
            top = gg.nlargest(3, "s1_flood_pop")
            aa = a3[(a3.storm == key) & a3.s1_flood_frac.notna()]
            tab[key] = dict(n_seen=int((gg.seen_frac > 0.2).sum()), n_fl=int((gg.s1_flood_frac > 0.01).sum()), n=len(gg),
                            top=[(r.adm3_name.replace(" (Capital)", ""), d["names"][r.unit_id], r.s1_flood_pop, r.s1_flood_frac) for r in top.itertuples()],
                            rho=ss.spearmanr(aa.A, aa.s1_flood_frac).statistic if len(aa) > 5 else np.nan,
                            n_A10=int((a3[a3.storm == key].A > 0.1).sum()))
        k["s1_muni"] = tab


def census_age():
    """Under-5 and 60+ shares of the 2020 census (PSA CPH, HDX age-group sheet), read-only."""
    p = RAW / "census2020" / "2020_CPH_SexAge_Popn_Mun_Admin3.xlsx"
    if not p.exists():
        return None
    a = pd.read_excel(p, sheet_name="AgeGroup").groupby("Age_Group")["Popn Total"].sum()
    old = [g for g in a.index if g.startswith(("60", "65", "70", "75", "80"))]
    return float(a["0 - 4"] / a.sum()), float(a[old].sum() / a.sum())


def stats_calibration(d, k):
    c = d["cal"].get("calibrated")
    k["cal_ok"] = c is not None and "observed_cal" in d["rel"]
    if k["cal_ok"]:
        k["calib"] = c
        sc = d["scen"]
        o = sc[(sc.storm == "ompong") & (sc.dlat == 0) & (sc.dlon == 0)]
        top = o.R.round(6).value_counts()
        top = top[top.index == o.R.round(6).max()] if len(top) else top
        k["ties"] = (int(top.iloc[0]), float(top.index[0])) if len(top) else (1, float("nan"))
        k["n_distinct_R"] = int(o.R.round(6).nunique())


BENCH_LABEL = {"chronos2": "Chronos-2", "tabpfn_ts": "TabPFN-TS", "mpnn_lstm": "MPNN-LSTM", "ens_median": "median ensemble"}
MODEL_LABEL = {"xgb": "XGBoost + graph (ours)", "xgb_nograph": "XGBoost, no graph", "xgb_noenv": "XGBoost, no rain/river/storm/flood",
               "naive": "seasonal naive", "chronos2": "Chronos-2, zero-shot", "tabpfn_ts": "TabPFN-TS, zero-shot",
               "mpnn_lstm": "MPNN-LSTM, graph neural net", "ens_median": "median ensemble"}


def stats_models(d, k):
    """Model comparison from eval_models.csv: whatever models are present; names the expected benchmarks that are not."""
    m = d["models"]
    k["models_ok"] = m is not None
    k["bench_only"] = []
    if m is None:
        k["bench_present"], k["bench_missing"] = [], list(BENCH_LABEL)
        return
    m = m.assign(horizon=m.horizon.astype(str))
    k["mtab"] = m
    present = list(dict.fromkeys(m.model))
    k["bench_present"] = [x for x in BENCH_LABEL if x in present]
    k["bench_missing"] = [x for x in BENCH_LABEL if x not in present]
    al = m[m.horizon == "all"].set_index("model")
    k["mall"] = al
    k["n_common"] = int(al.n.iloc[0])
    bench = [x for x in k["bench_present"] if x != "ens_median"]
    k["bench_only"] = bench
    if bench:
        k["best_mean"] = al.relWIS_vs_naive.idxmin()
        k["mw"], k["split"] = median_wis_split(bench)
        meta = d["models_meta"].get("benchmarks", {})
        k["bench_meta"] = {x: meta.get(x, {}).get("meta", {}) for x in bench}
        bs = d["bench_summary"]
        k["variants"] = ({r.model: r["relWIS vs naive"] for _, r in bs[bs.horizon.astype(str) == "all"].iterrows()} if bs is not None else {})


def median_wis_split(bench):
    """Median WIS per model and the mean-WIS ratio to XGBoost below / above the 90th percentile of weekly cases, re-scored
    from eval_quantiles.parquet and the bench files exactly as forecast.evaluate_models does (same rows)."""
    from bantay import forecast as Fc

    q = pd.read_parquet(APP_DATA / "eval_quantiles.parquet")
    mats_b, _ = Fc.load_bench(q, log=lambda *a: None)
    mats = {x: np.vstack(q[x].to_numpy()) for x in Fc.MODELS}
    mats.update(mats_b)
    if mats_b:
        mats[Fc.ENSEMBLE] = np.sort(np.median(np.stack([mats[x] for x in ["xgb"] + list(mats_b)]), axis=0), axis=1)
    keep = q.target.notna().to_numpy()
    y, rows = Fc.score_rows({x: v[keep] for x, v in mats.items()}, q.target[keep].to_numpy(), q["pop"][keep].to_numpy())
    s = pd.DataFrame(rows).assign(y=y)
    s = s[s[[f"wis_{x}" for x in mats]].notna().all(axis=1)]
    thr = s.y.quantile(0.9)
    lo, hi = s.y < thr, s.y >= thr
    split = dict(thr=float(thr), lo={x: s[f"wis_{x}"][lo].mean() / s.wis_xgb[lo].mean() for x in mats},
                 hi={x: s[f"wis_{x}"][hi].mean() / s.wis_xgb[hi].mean() for x in mats})
    return {x: float(s[f"wis_{x}"].median()) for x in mats}, split


def stats_catalog(d, k, b):
    """All storms with a scenario: the 4 backtests (observed track, Sentinel-1 flood) + the catalogue (NOAH proxy)."""
    c = d["scen_cat"]
    k["cat_ok"] = c is not None and len(c) > 0
    if not k["cat_ok"]:
        return

    def agg(g):
        return g.groupby("storm").agg(name=("name", "first"), season=("season", "first"), origin=("origin", "first"), R=("R", "mean"),
                                      cal=("R_calibrated", "all"), cut=("pop_cut", "sum"), cutr=("pop_cut_raster", "sum"),
                                      rcut=("Rcut", "sum"), ferries=("ferries_cancelled", "first"), src=("flood_source", "first"),
                                      t3=("tier", lambda t: int((t == 3).sum())), t2=("tier", lambda t: int((t == 2).sum())),
                                      flag=("flag_2020", "first"))

    cat = agg(c.assign(Rcut=c.R * c.pop_cut))
    bb = b.assign(Rcut=b.R * b.pop_cut, name=b.storm.map(lambda x: STORMS[x]["local"]), season=b.storm.map(lambda x: STORMS[x]["season"]))
    back = agg(bb)
    allst = pd.concat([cat.assign(kind="catalogue"), back.assign(kind="backtest")]).sort_values("origin")
    allst["label"] = [f"{n.title() if k_ == 'catalogue' else n} {s_}" for n, s_, k_ in zip(allst.name, allst.season, allst.kind)]
    k["allst"] = allst
    k["n_cat"] = len(cat)
    k["n_cal_cat"] = int(cat.cal.sum())
    cs = d["cat_storms"]
    if cs is not None:
        sk = cs[(cs.status == "skipped") & cs.reason.str.contains("history", na=False)]
        k["cat_skipped"] = sk
        k["cat_n_land"] = int(cs.swath_hits_land.sum())
    mc = d["methods_cat"]
    k["cat_rho"] = None  # set below only when the catalogue method table exists
    if mc is not None:
        r = mc.spearman_A_units.dropna()
        k["cat_rho"] = (r.min(), r.median(), len(r))


def _irr(df, variant, exposure, model="joint"):
    g = df[(df.variant == variant) & (df.exposure == exposure) & (df.model == model)]
    lags = g[g.lag.notna()].sort_values("lag")
    cum = g[g.term.str.startswith("cum")]
    return lags, (cum.iloc[0] if len(cum) else None)


def stats_lepto(d, k):
    c, n = d["lepto_city"], d["lepto_nat"]
    k["lepto_ok"] = c is not None and n is not None
    if not k["lepto_ok"]:
        return
    L = {}
    lags, cum = _irr(c, "12 cities", "rain_7d")
    pk = lags.loc[lags.irr.idxmax()]
    L["city"] = dict(lags=lags, cum=cum, peak=pk, n_cases=int(lags.n_cases.iloc[0]), n_obs=int(lags.n_obs.iloc[0]),
                     sig=lags[lags.ci_lo > 1].lag.astype(int).tolist())
    hl, hc = _irr(c, "12 cities", "heavy")
    L["heavy_peak"] = hl.loc[hl.irr.idxmax()]
    lags, cum = _irr(n, "2019-2020", "rain_7d")
    L["nat"] = dict(lags=lags, cum=cum, peak=lags.loc[lags.irr.idxmax()], n_obs=int(lags.n_obs.iloc[0]), n_cases=int(lags.n_cases.iloc[0]))
    _, c19 = _irr(n, "2019 only", "rain_7d")
    L["nat19_cum"] = c19
    did = d["lepto_did"]
    if did is not None:
        def row(storms, term):
            r = did[(did.storms == storms) & (did.term == term)]
            return r.iloc[0] if len(r) else None
        L["ru_post"], L["ru_pre"] = row("rolly+ulysses", "inside_x_post1_4"), row("rolly+ulysses", "inside_x_pre")
        L["ot_post"], L["ot_pre"] = row("ompong+tisoy", "inside_x_post1_4"), row("ompong+tisoy", "inside_x_pre")
    ev = d["lepto_events"]
    if ev is not None:
        pairs = ev.drop_duplicates(["storm", "city"])
        seen = pairs[pairs.s1_seen_frac > 0.2]
        L["s1_pairs"] = (len(pairs), len(seen), int((pairs.s1_flood_frac > 0).sum()), float(pairs.s1_flood_frac.max()))
        L["n_cities"] = pairs.city.nunique()
    k["lepto"] = L


def stats_data(d, k):
    """Data-finding numbers from the raw DOH file, the panel and IBTrACS (read-only), and the SUS responses if any."""
    p = RAW / "dengue_hdx" / "doh-epi-dengue-data-2016-2021.csv"
    if p.exists():
        dg = pd.read_csv(p, skiprows=[1])
        dg["loc"] = dg["loc"].str.strip()
        dg["year"] = pd.to_datetime(dg["date"], format="%m/%d/%Y").dt.year
        y = dg.groupby("year")[["cases", "deaths"]].sum()
        k["dg_units"] = dg["loc"].nunique()
        k["cfr16"] = y.loc[2016, "deaths"] / y.loc[2016, "cases"]
        k["cases_by_year"] = y.cases.to_dict()
    try:
        from bantay.storms import IBTRACS, R34

        ib = pd.read_csv(IBTRACS, skiprows=[1], usecols=["SEASON", "NAME", "USA_WIND", "WMO_WIND", "TOKYO_WIND", *R34], low_memory=False,
                         na_values=[" ", ""])
        out = {}
        for key, s_ in STORMS.items():
            t = ib[(ib.NAME == s_["name"]) & (ib.SEASON == s_["season"])]
            w = t.USA_WIND.fillna(t.WMO_WIND).fillna(t.TOKYO_WIND)
            t = t[w >= 34]
            usa = t[R34].max(axis=1)
            out[key] = float((usa.isna() | (usa <= 0)).mean())
        k["r34_missing"] = out
    except Exception as e:  # noqa: BLE001 - a data-finding number, never fatal
        print(f"  WARNING IBTrACS radius check skipped: {e}")
    sp = PROCESSED / "sus" / "sus_responses.csv"
    sus = pd.read_csv(sp) if sp.exists() else pd.DataFrame(columns=["sus"])
    k["sus_n"], k["sus_mean"] = len(sus), (sus.sus.mean() if len(sus) else np.nan)
    p = d["panel"]
    k["unit_weeks"] = len(p)


def s1_ems_agreement():
    """Sentinel-1 (Ompong) vs Copernicus EMSR312 observed flood, inside each EMS AOI's extent, on the S1 100 m grid."""
    import rasterio
    from rasterio import features
    from bantay import flood

    ems = flood.ems_observed_flood("EMSR312", record_status=False)
    tiles = flood.s1_tiles("ompong")
    if ems is None or not tiles:
        return None
    ems_px = s1_px = both = 0
    for t in tiles:
        with rasterio.open(t) as r:
            b = r.bounds
            e = ems.cx[b.left:b.right, b.bottom:b.top]
            if e.empty:
                continue
            a = r.read(1)
            em = features.rasterize(((g, 1) for g in e.geometry), out_shape=a.shape, transform=r.transform, fill=0, dtype="uint8") == 1
            # AOI extent = bounding box of the EMS polygons in this tile
            x0, y0, x1, y1 = e.total_bounds
            r0, c0 = r.index(max(x0, b.left), min(y1, b.top))
            r1, c1 = r.index(min(x1, b.right - 1e-9), max(y0, b.bottom + 1e-9))
            box = (slice(r0, r1 + 1), slice(c0, c1 + 1))
            sa, ea, va = a[box] == 1, em[box], a[box] != 255
            ems_px += int((ea & va).sum())
            s1_px += int(sa.sum())
            both += int((sa & ea).sum())
    if not ems_px:
        return None
    return dict(ems_km2=ems_px * 0.01, s1_km2=s1_px * 0.01, both_km2=both * 0.01, recall=both / ems_px, precision=both / max(s1_px, 1))


# ---------------------------------------------------------------- figure style

def style():
    for f in FONTS.glob("*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams.update({
        "font.family": "Barlow", "font.size": 10, "axes.edgecolor": INK, "axes.labelcolor": INK,
        "text.color": INK, "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "axes.titleweight": "semibold",
        "axes.titlesize": 11, "axes.titlelocation": "left", "figure.facecolor": PAPER, "axes.facecolor": PAPER,
        "svg.fonttype": "none", "legend.frameon": False, "lines.linewidth": 2,
    })


def mono(ax):
    for t in ax.get_xticklabels() + ax.get_yticklabels():
        t.set_fontfamily("Space Mono")
        t.set_fontsize(8.5)


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight", dpi=220)  # PNG: fonts baked in (an <img> SVG can't use page fonts)
    plt.close(fig)
    return f"../figures/{name}.png"


# ---------------------------------------------------------------- figures

def fig_timeline(d):
    p = d["panel"]
    nat = p.groupby("week").cases.sum(min_count=1)
    fig, ax = plt.subplots(figsize=(8.2, 2.6))
    ax.fill_between(nat.index, nat.values, color=TEAL, alpha=0.15, lw=0)
    ax.plot(nat.index, nat.values, color=TEAL, lw=1.6)
    for i, (k, s) in enumerate(STORMS.items()):
        t = pd.Timestamp(s["landfall"])
        ax.axvline(t, color=AMBER, lw=1, ls=(0, (2, 2)))
        ax.text(t, nat.max() * (0.97 - 0.12 * (k == "ulysses")), f" {s['local']}", color=AMBER, fontsize=8.5, va="top", fontweight="semibold")
    ax.axvspan(pd.Timestamp("2020-01-01"), nat.index.max(), color=GREY, alpha=0.08, lw=0)
    ax.text(pd.Timestamp("2020-03-01"), nat.max() * 0.6, "2020: COVID\nreporting collapse\n(access scenarios only)", fontsize=8, color=GREY)
    ax.set_ylabel("dengue cases / week")
    ax.set_title("National weekly dengue (sum of 85 units), DOH-Epi 2016 to Jan 2021")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    mono(ax)
    return save(fig, "f01_timeline")


def fig_coverage(d):
    p = d["panel"]
    groups = [("Dengue cases", "cases"), ("Population", "pop"), ("IBTrACS storm exposure", "storm_gale_hit"),
              ("CHIRPS rainfall", "chirps_7d"), ("IMERG rainfall (GEE)", "imerg_7d"), ("River-routed rain", "river_up_7d"),
              ("NOAH 25-yr hazard share", "hazard_any_25yr"), ("NOAH 5-yr hazard share", "hazard_any_5yr"),
              ("Sentinel-1 flood fraction", "s1_flood_frac")]
    v = [p[c].notna().mean() for _, c in groups][::-1]
    lab = [g for g, _ in groups][::-1]
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    cols = [RED if x == 0 else (AMBER if x < 0.95 else TEAL) for x in v]
    ax.barh(lab, v, color=cols, height=0.62)
    for i, x in enumerate(v):
        ax.text(max(x, 0) + 0.015, i, "pending (GEE)" if x == 0 else f"{x:.0%}", va="center", fontsize=8.5, fontfamily="Space Mono")
    ax.set_xlim(0, 1.18)
    ax.set_xticks([0, .5, 1])
    ax.set_xticklabels(["0%", "50%", "100%"])
    ax.grid(axis="y", visible=False)
    ax.set_title("Panel coverage: share of unit-weeks with a value")
    mono(ax)
    return save(fig, "f02_coverage")


KIND_COLOR = {"model": TEAL, "ablation": "#7FC3DC", "baseline": GREY, "benchmark": AMBER, "ensemble": RED}


def fig_wis(d):
    """Left: relative WIS vs seasonal naive for every model in eval_models.csv (same rows). Right: coverage by horizon."""
    m = d["models"]
    e = d["evals"].drop(index="all")
    h = e.index.astype(int)
    fig, ax = plt.subplots(1, 2, figsize=(8.6, 3.0), gridspec_kw={"width_ratios": [1.3, 1]})
    a = ax[0]
    if m is not None:
        al = m[m.horizon.astype(str) == "all"].sort_values("relWIS_vs_naive", ascending=False)
        h1 = m[m.horizon.astype(str) == "1"].set_index("model").relWIS_vs_naive
        h4 = m[m.horizon.astype(str) == "4"].set_index("model").relWIS_vs_naive
        y = np.arange(len(al))
        a.barh(y, al.relWIS_vs_naive, color=[KIND_COLOR.get(x, INK) for x in al.kind], height=0.62)
        a.scatter(h1.reindex(al.model), y, marker="|", s=90, color=INK, lw=1.4, zorder=3)
        a.scatter(h4.reindex(al.model), y, marker="x", s=22, color=INK, lw=1.1, zorder=3)
        for yy, v in zip(y, al.relWIS_vs_naive):
            a.text(1.06, yy, f"{v:.3f}", va="center", fontsize=7.8, fontfamily="Space Mono")
        a.set_yticks(y)
        a.set_yticklabels([MODEL_LABEL.get(x, x) for x in al.model], fontsize=8)
        a.axvline(1, color=GREY, lw=0.8)
        a.set_xlim(0, 1.24)
        a.set_xticks([0, 0.25, 0.5, 0.75, 1])
        a.set_xlabel("relative WIS vs seasonal naive (bar: 1-4 wk; | 1 wk; x 4 wk)")
        a.grid(axis="y", visible=False)
        a.set_title("Every model, same rows (lower is better)")
    b = ax[1]
    b.axhspan(0.80, 0.95, color=TEAL, alpha=0.08, lw=0)
    b.text(1.0, 0.955, "proposal target 80-95%", fontsize=7.5, color=TEAL)
    b.plot(h, e["cov90 xgb"], color=TEAL, marker="o", ms=6, label="XGBoost 90%")
    if m is not None and "ens_median" in set(m.model):
        en = m[(m.model == "ens_median") & (m.horizon.astype(str) != "all")]
        b.plot(en.horizon.astype(int), en.cov90, color=RED, marker="s", ms=5, label="ensemble 90%")
    b.plot(h, e["cov90 conformal"], color=AMBER, marker="D", ms=5, label="online conformal 90%")
    b.plot(h, e["cov50 xgb"], color=TEAL, marker="o", ms=6, ls=(0, (1, 1.5)), label="XGBoost 50%")
    b.axhline(0.9, color=GREY, lw=0.8)
    b.axhline(0.5, color=GREY, lw=0.8)
    b.set_ylim(0.3, 1.0)
    b.set_xticks(h)
    b.set_xlabel("weeks ahead")
    b.set_title("Empirical coverage")
    b.legend(fontsize=7, loc="center right")
    for x in ax:
        mono(x)
    ax[0].tick_params(axis="y", labelsize=8)
    for t in ax[0].get_yticklabels():
        t.set_fontfamily("Barlow")
    fig.tight_layout()
    return save(fig, "f03_wis")


def fig_reliability(d):
    """Reliability of R before (model) and after isotonic recalibration on past rolling-origin forecasts only."""
    r = d["rel"]
    fig, ax = plt.subplots(figsize=(3.7, 3.4))
    ax.plot([0, 1], [0, 1], color=GREY, lw=1, ls=(0, (3, 2)))
    ax.plot(r.mean_R, r.observed, color=AMBER, marker="o", ms=6, label="model R (raw)")
    if "observed_cal" in r:
        ax.plot(r.mean_R_cal, r.observed_cal, color=TEAL, marker="s", ms=6, label="recalibrated R")
        for x, y, n in zip(r.mean_R_cal, r.observed_cal, r.n_cal):
            ax.annotate(f"{n:,}", (x, y), textcoords="offset points", xytext=(6, -10), fontsize=7, fontfamily="Space Mono", color=GREY)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("mean predicted R")
    ax.set_ylabel("observed surge rate")
    ax.set_title("Surge probability R: reliability")
    ax.legend(fontsize=7.5, loc="upper left")
    mono(ax)
    return save(fig, "f04_reliability")


def fig_methods(d, k):
    """People cut off, road+ferry network vs MAP friction raster: observed tracks (Sentinel-1) and every proxy track."""
    if not k.get("raster_ok"):
        return None
    st = k["storm_tab"]
    fig, ax = plt.subplots(1, 2, figsize=(8.6, 3.0), gridspec_kw={"width_ratios": [1, 1.15]})
    a = ax[0]
    keys = list(STORMS)
    x = np.arange(len(keys))
    a.bar(x - 0.19, st.loc[keys, "cut"] / 1e6, 0.36, color=TEAL, label="network")
    a.bar(x + 0.19, st.loc[keys, "cutr"] / 1e6, 0.36, color=AMBER, label="friction raster")
    a.set_xticks(x)
    a.set_xticklabels([STORMS[s]["local"] for s in keys])
    a.set_ylabel("people cut off (M)")
    a.set_title("Observed tracks, Sentinel-1 flood")
    a.legend(fontsize=7.5, loc="upper left")
    a.grid(axis="x", visible=False)
    b = ax[1]
    m = d["methods"]
    sc = m[(m.kind == "scenario") & ((m.dlat != 0) | (m.dlon != 0))]
    b.scatter(sc.pop_cut_network / 1e6, sc.pop_cut_raster / 1e6, s=16, color=TEAL, alpha=0.75, lw=0, label=f"shifted backtest tracks ({len(sc)})")
    mc = d["methods_cat"]
    if mc is not None:
        b.scatter(mc.pop_cut_network / 1e6, mc.pop_cut_raster / 1e6, s=16, facecolor="none", edgecolor=GREY, lw=0.9, label=f"catalogue storms ({len(mc)})")
    ob = m[(m.kind == "scenario") & (m.dlat == 0) & (m.dlon == 0)]
    b.scatter(ob.pop_cut_network / 1e6, ob.pop_cut_raster / 1e6, s=34, marker="D", color=AMBER, label="observed tracks (Sentinel-1)")
    hi = max(sc.pop_cut_network.max(), sc.pop_cut_raster.max()) / 1e6 * 1.05
    b.plot([0, hi], [0, hi], color=GREY, lw=0.8, ls=(0, (3, 2)))
    b.text(hi * 0.62, hi * 0.70, "1:1", color=GREY, fontsize=8)
    b.set_xlim(0, hi)
    b.set_ylim(0, hi)
    b.set_xlabel("network: people cut off (M)")
    b.set_ylabel("raster: people cut off (M)")
    b.set_title("Every track: NOAH proxy flood")
    b.legend(fontsize=7, loc="upper left")
    for z in ax:
        mono(z)
    fig.tight_layout()
    return save(fig, "f15_methods")


def fig_catalog(d, k):  # noqa: C901
    """Surge risk vs people cut off for every scored storm 2017-2020; the line spans the two access methods."""
    if not k.get("cat_ok"):
        return None
    a = k["allst"]
    fig, ax = plt.subplots(figsize=(8.6, 3.1))
    for r in a.itertuples():
        ax.plot([r.R, r.R], [min(r.cut, r.cutr) / 1e6, max(r.cut, r.cutr) / 1e6], color=GREY, lw=1, alpha=0.7, zorder=1)
    cat = a[a.kind == "catalogue"]
    first = pd.Timestamp(k["calib"]["first_calibrated_origin"]).strftime("%b %Y") if k.get("calib") else "calibration"
    for cal, face in ((True, TEAL), (False, "none")):
        g = cat[cat.cal == cal]
        ax.scatter(g.R, g.cut / 1e6, s=30, facecolor=face, edgecolor=TEAL, lw=1.1, zorder=3,
                   label=f"catalogue, NOAH proxy flood{'' if cal else ', raw R (before ' + first + ')'}: {len(g)}")
    bt = a[a.kind == "backtest"]
    ax.scatter(bt.R, bt.cut / 1e6, s=48, marker="D", color=AMBER, zorder=4, label=f"backtest, Sentinel-1 flood: {len(bt)}")
    lab = pd.concat([a.nlargest(5, "cut"), a.nlargest(3, "R"), bt]).drop_duplicates("label").sort_values("R")
    last = {}
    for r in lab.itertuples():  # nudge labels that would sit on top of each other
        y = r.cut / 1e6
        key = round(r.R / 0.08)
        dy = 3 + 9 * last.get(key, 0) * (1 if y > 1 else -1)
        last[key] = last.get(key, 0) + 1
        ax.annotate(r.label, (r.R, y), textcoords="offset points", xytext=(5, dy), fontsize=7.2)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, a[["cut", "cutr"]].max().max() / 1e6 * 1.12)
    ax.set_xlabel("mean surge probability R over 85 units (forecast at the storm's week)")
    ax.set_ylabel("people cut off (M, network)")
    ax.set_title(f"{len(a)} storms, {pd.Timestamp(a.origin.min()).year}-{pd.Timestamp(a.origin.max()).year}: risk vs access (vertical line = network-to-raster range)")
    ax.legend(fontsize=7.3, loc="upper right")
    mono(ax)
    return save(fig, "f16_catalog")


def fig_lepto(d, k):
    """Leptospirosis vs rain l weeks earlier: joint distributed-lag IRR per +50 mm/week, cities and national."""
    if not k.get("lepto_ok"):
        return None
    L = k["lepto"]
    fig, ax = plt.subplots(figsize=(5.2, 2.9))
    for lab, key, col, off in ((f"{L.get('n_cities', 12)} cities (CCHAIN), 2016-2020", "city", TEAL, -0.1),
                               ("national (PIDSR), 2019-2020", "nat", AMBER, 0.1)):
        g = L[key]["lags"]
        ax.errorbar(g.lag + off, g.irr, yerr=[g.irr - g.ci_lo, g.ci_hi - g.irr], fmt="o", ms=5, color=col, capsize=2, lw=1.2, label=lab)
    ax.axhline(1, color=GREY, lw=0.8)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_yticks([0.8, 1, 1.25, 1.5, 2])
    ax.set_xlabel("lag (weeks after the rain)")
    ax.set_ylabel("incidence rate ratio")
    ax.set_title("Leptospirosis vs rain: joint lag model, per +50 mm/week")
    ax.legend(fontsize=7.5, loc="upper left")
    mono(ax)
    return save(fig, "f17_lepto")


def fig_fan(d, unit_name="Cagayan"):
    f = d["evalf"]
    uid = {v: k for k, v in d["names"].items()}[unit_name]
    fig, ax = plt.subplots(1, 2, figsize=(8.4, 2.7), sharey=True)
    for a, h in zip(ax, (1, 4)):
        g = f[(f.unit_id == uid) & (f.horizon == h)].sort_values("target_week")
        a.fill_between(g.target_week, g.xgb_q05, g.xgb_q95, color=TEAL, alpha=0.16, lw=0, label="90% interval")
        a.fill_between(g.target_week, g.xgb_q25, g.xgb_q75, color=TEAL, alpha=0.28, lw=0, label="50% interval")
        a.plot(g.target_week, g.xgb_q50, color=TEAL, lw=1.6, label="median")
        a.plot(g.target_week, g.naive_q50, color=GREY, lw=1.1, ls=(0, (3, 2)), label="seasonal naive")
        a.scatter(g.target_week, g.cases, s=9, color=INK, zorder=3, label="reported")
        a.axvline(pd.Timestamp(STORMS["ompong"]["landfall"]), color=AMBER, lw=1, ls=(0, (2, 2)))
        a.set_title(f"{unit_name}, {h} week{'s' if h > 1 else ''} ahead")
        a.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=(1, 7)))
        a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
        mono(a)
    ax[0].set_ylabel("cases / week")
    ax[1].legend(fontsize=7.5, loc="upper left")
    fig.tight_layout()
    return save(fig, "f05_fan")


def _basemap(ax, units, color="#D5DEE4", edge="#FFFFFF"):
    units.plot(ax=ax, color=color, edgecolor=edge, linewidth=0.4)
    ax.set_xlim(116.6, 127)
    ax.set_ylim(4.5, 21.2)
    ax.set_axis_off()


def fig_leadlag(d):
    u = d["units"].copy()
    pts = u.set_index("unit_id").geometry.representative_point()
    fig, ax = plt.subplots(figsize=(4.2, 5.6))
    _basemap(ax, u)
    e = d["edges"]
    for s, t, lag, w in zip(e.source, e.target, e.lag, e.weight):
        a, b = pts[s], pts[t]
        ax.annotate("", xy=(b.x, b.y), xytext=(a.x, a.y),
                    arrowprops=dict(arrowstyle="-|>", color=AMBER, lw=1.6, shrinkA=3, shrinkB=3, connectionstyle="arc3,rad=0.18"))
    srcs = set(e.source)
    ncr = [u for u in set(e.source) | set(e.target) if d["names"][u].startswith("Metropolitan Manila")]
    for uid in set(e.source) | set(e.target):
        p = pts[uid]
        ax.scatter(p.x, p.y, s=26, color=TEAL if uid in srcs else INK, zorder=3)
        if uid not in ncr:  # NCR districts sit on top of each other: one label for all
            ax.text(p.x + 0.15, p.y + 0.05, d["names"][uid].split(" (")[0], fontsize=7, color=INK)
    if ncr:
        c = pts[ncr[0]]
        ax.text(c.x - 0.25, c.y, f"NCR ({len(ncr)} districts)", fontsize=7, color=INK, ha="right")
    ax.set_title(f"PCMCI+ lead-lag links (q < 0.05): {len(e)}", fontsize=10)
    return save(fig, "f06_leadlag")


def fig_priority(d, storm="ompong"):
    u = d["units"].merge(d["scen"][(d["scen"].storm == storm) & (d["scen"].dlat == 0) & (d["scen"].dlon == 0)][["unit_id", "P", "tier"]], on="unit_id")
    fig, ax = plt.subplots(figsize=(4.4, 5.6))
    u.plot(ax=ax, column="P", cmap=SEQ, edgecolor="#FFFFFF", linewidth=0.4, vmin=0, legend=True,
           legend_kwds=dict(shrink=0.5, label="priority P = R x A", orientation="vertical"))
    _basemap(ax, u.iloc[0:0])
    tr = d["tracks"][(d["tracks"].storm == storm) & (d["tracks"].dlat == 0) & (d["tracks"].dlon == 0)]
    ax.plot(tr.LON, tr.LAT, color=AMBER, lw=1.8, marker="o", ms=2.5)
    sw = d["swaths"][(d["swaths"].storm == storm) & (d["swaths"].dlat == 0) & (d["swaths"].dlon == 0)]
    if len(sw):
        geom = wkt.loads(sw.wkt.iloc[0])
        for poly in getattr(geom, "geoms", [geom]):
            ax.plot(*poly.exterior.xy, color=AMBER, lw=0.8, ls=(0, (2, 2)))
    top = u.nlargest(5, "P")
    for _, r in top.iterrows():
        c = r.geometry.representative_point()
        ax.text(c.x + 0.15, c.y, r.unit_name, fontsize=7.2, color=INK, fontweight="semibold")
    ax.set_xlim(116.6, 127)
    ax.set_ylim(4.5, 21.2)
    ax.set_title(f"{STORMS[storm]['local']} ({STORMS[storm]['season']}): priority", fontsize=10)
    return save(fig, f"f07_priority_{storm}")


def fig_access_multiples(d):
    fig, axs = plt.subplots(1, 4, figsize=(9.6, 3.0))
    s = d["scen"]
    vmax = s[(s.dlat == 0) & (s.dlon == 0)].A.max()
    for ax, (k, st) in zip(axs, STORMS.items()):
        u = d["units"].merge(s[(s.storm == k) & (s.dlat == 0) & (s.dlon == 0)][["unit_id", "A"]], on="unit_id")
        u.plot(ax=ax, column="A", cmap=SEQ, edgecolor="#FFFFFF", linewidth=0.3, vmin=0, vmax=vmax)
        tr = d["tracks"][(d["tracks"].storm == k) & (d["tracks"].dlat == 0) & (d["tracks"].dlon == 0)]
        ax.plot(tr.LON, tr.LAT, color=AMBER, lw=1.4)
        ax.set_xlim(116.6, 127)
        ax.set_ylim(4.5, 21.2)
        ax.set_axis_off()
        ax.set_title(f"{st['local']} {st['season']}", fontsize=10)
    sm = plt.cm.ScalarMappable(cmap=SEQ, norm=plt.Normalize(0, vmax))
    cb = fig.colorbar(sm, ax=axs, shrink=0.6, label="access loss A (share cut off)", format=matplotlib.ticker.PercentFormatter(1.0))
    cb.ax.tick_params(labelsize=8)
    return save(fig, "f08_access")


def fig_scatter(d, storm="ompong"):
    s = d["scen"]
    s = s[(s.storm == storm) & (s.dlat == 0) & (s.dlon == 0)].copy()
    s["name"] = s.unit_id.map(d["names"])
    fig, ax = plt.subplots(figsize=(5.0, 3.1))
    mk = {1: ("o", "#9FBFCC", "monitor"), 2: ("s", TEAL, "pre-position"), 3: ("D", INK, "deploy")}
    for t, (m, c, lab) in mk.items():
        g = s[s.tier == t]
        ax.scatter(g.R, g.A, s=np.sqrt(g["pop"]) / 18, marker=m, color=c, edgecolor="#FFFFFF", lw=0.6, label=f"{lab} ({len(g)})", zorder=3)
    ax.axvline(TIERS["preposition_R"], color=GREY, lw=0.8, ls=(0, (2, 2)))
    ax.axhline(TIERS["deploy"][1], color=GREY, lw=0.8, ls=(0, (2, 2)))
    for _, r in s.nlargest(5, "P").iterrows():
        ax.annotate(r["name"], (r.R, r.A), textcoords="offset points", xytext=(5, 4), fontsize=7.2)
    ax.set_xlim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("surge probability R")
    ax.set_ylabel("access loss A")
    ax.set_title(f"{STORMS[storm]['local']}: risk vs access (size = population)")
    ax.legend(fontsize=7.5, loc="upper left", markerscale=0.6)
    mono(ax)
    return save(fig, "f09_scatter")


def fig_validation(d):
    v = d["valid"]
    x = np.arange(len(v))
    fig, ax = plt.subplots(figsize=(5.0, 2.8))
    ax.bar(x - 0.19, v.spearman_R_obs, 0.36, color=TEAL, label="Spearman(R, observed)")
    ax.bar(x + 0.19, v.spearman_P_obs, 0.36, color=AMBER, label="Spearman(P, observed)")
    for i, (a, b) in enumerate(zip(v.spearman_R_obs, v.spearman_P_obs)):
        ax.text(i - 0.19, a + 0.02, f"{a:.2f}", ha="center", fontsize=7.8, fontfamily="Space Mono")
        ax.text(i + 0.19, b + 0.02, f"{b:.2f}", ha="center", fontsize=7.8, fontfamily="Space Mono")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s}*" if isinstance(n, str) and n else s for s, n in zip(v.storm, v.note)])
    ax.set_ylim(0, 1)
    ax.set_title("Backtest: rank vs next-4-week incidence (* 2020, indicative)")
    ax.legend(fontsize=7.5, loc="upper right")
    ax.grid(axis="x", visible=False)
    mono(ax)
    return save(fig, "f10_validation")


def fig_s1(d):
    """Observed new flood share per unit, one map per typhoon (Sentinel-1; per-storm values, not the merged panel)."""
    p = d["panel"].dropna(subset=["s1_flood_frac"])
    if p.empty:
        return None
    fig, axs = plt.subplots(1, 4, figsize=(9.6, 3.0))
    vmax = p.s1_flood_frac.quantile(0.99)
    for ax, (k, st) in zip(axs, STORMS.items()):
        g = d["s1_storm"][d["s1_storm"].storm == k]
        u = d["units"].merge(g[["unit_id", "s1_flood_frac"]], on="unit_id", how="left")
        u[u.s1_flood_frac.isna()].plot(ax=ax, color="#EEF1F3", edgecolor="#FFFFFF", linewidth=0.3)
        u[u.s1_flood_frac.notna()].plot(ax=ax, column="s1_flood_frac", cmap=SEQ, vmin=0, vmax=vmax, edgecolor="#FFFFFF", linewidth=0.3)
        tr = d["tracks"][(d["tracks"].storm == k) & (d["tracks"].dlat == 0) & (d["tracks"].dlon == 0)]
        ax.plot(tr.LON, tr.LAT, color=AMBER, lw=1.4)
        ax.set_xlim(116.6, 127)
        ax.set_ylim(4.5, 21.2)
        ax.set_axis_off()
        ax.set_title(f"{st['local']} {st['season']}", fontsize=10)
    sm = plt.cm.ScalarMappable(cmap=SEQ, norm=plt.Normalize(0, vmax))
    fig.colorbar(sm, ax=axs, shrink=0.6, label="new flood (share of land seen)", format=matplotlib.ticker.PercentFormatter(1.0, decimals=1))
    return save(fig, "f11_s1_flood")


def fig_s1_ems(d):
    """Sentinel-1 new flood vs Copernicus EMS observed flood at Tuguegarao (Ompong)."""
    import rasterio
    from bantay import flood

    t = [x for x in flood.s1_tiles("ompong") if x.name == "s1flood_121E_17N.tif"]
    ems = flood.ems_observed_flood("EMSR312", record_status=False)
    if not t or ems is None:
        return None
    with rasterio.open(t[0]) as r:
        a, b = r.read(1), r.bounds
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.imshow(np.where(a == 1, 1.0, np.nan), extent=[b.left, b.right, b.bottom, b.top], cmap=LinearSegmentedColormap.from_list("w", [TEAL, TEAL]), interpolation="nearest")
    e = ems.cx[b.left:b.right, b.bottom:b.top]
    e.boundary.plot(ax=ax, color=RED, lw=0.35)
    ax.set_xlim(121.3, 122.0)
    ax.set_ylim(17.0, 17.95)
    ax.set_title("Ompong, Cagayan Valley: Sentinel-1 (teal) vs EMS (red outline)", fontsize=9.5)
    ax.tick_params(labelsize=7.5)
    mono(ax)
    return save(fig, "f12_s1_ems")


def fig_network(d):
    """The access problem: RoRo ferry links and hospitals over the islands."""
    f = pd.read_parquet(APP_DATA / "ferries.parquet")
    h = d["hosp"]
    fig, ax = plt.subplots(figsize=(4.2, 5.4))
    _basemap(ax, d["units"])
    for a, b, c, e in zip(f.from_lon, f.from_lat, f.to_lon, f.to_lat):
        ax.plot([a, c], [b, e], color=AMBER, lw=0.9, alpha=0.9)
    ax.scatter(h.lon, h.lat, s=2.2, color=TEAL, lw=0, label=f"hospitals ({len(h):,})")
    ax.plot([], [], color=AMBER, lw=1.5, label=f"RoRo ferry routes ({len(f)})")
    ax.legend(loc="lower left", fontsize=8, markerscale=4)
    ax.set_title("Getting to care in an archipelago", fontsize=10)
    return save(fig, "f13_network")


def fig_rolling(d):
    """Rolling-origin schematic: training data grows, each block is forecast only from the past."""
    refits = pd.date_range("2018-01-07", "2019-12-29", freq="13W-SUN")
    fig, ax = plt.subplots(figsize=(8.6, 2.2))
    t0 = pd.Timestamp("2016-01-10")
    for i, r in enumerate(refits):
        nxt = refits[i + 1] if i + 1 < len(refits) else pd.Timestamp("2019-12-29")
        ax.barh(i, (r - t0).days, left=matplotlib.dates.date2num(t0), color=TEAL, alpha=0.35, height=0.62)
        ax.barh(i, max((nxt - r).days, 7), left=matplotlib.dates.date2num(r), color=AMBER, height=0.62)
    ax.xaxis_date()
    ax.invert_yaxis()
    ax.set_yticks([])
    ax.grid(axis="y", visible=False)
    ax.barh([], [], color=TEAL, alpha=0.35, label="train (past only)")
    ax.barh([], [], color=AMBER, label="forecast, scored")
    ax.legend(fontsize=8, loc="lower left", ncol=2)
    ax.set_title("Rolling origin: 8 refits, never a random split")
    mono(ax)
    return save(fig, "f14_rolling")


def make_figures(d, k):
    style()
    return dict(timeline=fig_timeline(d), coverage=fig_coverage(d), wis=fig_wis(d), rel=fig_reliability(d), fan=fig_fan(d),
                leadlag=fig_leadlag(d), priority=fig_priority(d), access=fig_access_multiples(d), scatter=fig_scatter(d),
                valid=fig_validation(d), s1=fig_s1(d), s1ems=fig_s1_ems(d), network=fig_network(d), rolling=fig_rolling(d),
                methods=fig_methods(d, k), catalog=fig_catalog(d, k), lepto=fig_lepto(d, k))


# ---------------------------------------------------------------- shared HTML pieces

FONT_CSS = """
@font-face { font-family: "Big Shoulders Display"; src: url("fonts/BigShouldersDisplay-VF.ttf"); font-weight: 100 900; }
@font-face { font-family: "Barlow"; src: url("fonts/Barlow-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Barlow"; src: url("fonts/Barlow-SemiBold.ttf"); font-weight: 600 700; }
@font-face { font-family: "Barlow"; src: url("fonts/Barlow-Italic.ttf"); font-style: italic; }
@font-face { font-family: "Space Mono"; src: url("fonts/SpaceMono-Regular.ttf"); font-weight: 400; }
@font-face { font-family: "Space Mono"; src: url("fonts/SpaceMono-Bold.ttf"); font-weight: 600 700; }
:root { --ink: #0F1E28; --deep: #0B1720; --teal: #0A86B5; --teal-lt: #5FC3E4; --amber: #C77700; --signal: #F2A93B;
        --red: #C8323F; --grey: #6B7A88; --rule: #DDE3E8; --paper: #FFFFFF; --mist: #F2F5F7; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Barlow", sans-serif; color: var(--ink); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.mono { font-family: "Space Mono", monospace; }
table { border-collapse: collapse; width: 100%; }
th { font-family: "Space Mono", monospace; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; text-align: left; }
td, th { padding: 4px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
td.n, th.n { text-align: right; font-family: "Space Mono", monospace; }
"""

REFERENCES = [
    "Ansari, A. F., Shchur, O., Küken, J., Auer, A., Han, B., Mercado, P., Rangapuram, S. S., Shen, H., Stella, L., Shen, X., Turkmen, C., Bohlke-Schneider, M., Erickson, N., Kapoor, S., Li, Z., Wang, B., Williams, A. R., Ahmed, A., Weber, S., ... Wang, Y. (2025). <i>Chronos-2: From univariate to universal forecasting</i>. arXiv. https://arxiv.org/abs/2510.15821",
    "Balbuena, A., Herbosa, T., & Gundran, C. P. (2010). Cases of leptospirosis after Typhoon Ondoy (international name: Ketsana) seen at the emergency department: The Philippine General Hospital experience. <i>WIT Transactions on Information and Communication Technologies, 43</i>, 605–612. https://doi.org/10.2495/RISK100501",
    "Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. <i>Journal of the Royal Statistical Society: Series B (Methodological), 57</i>(1), 289–300. https://doi.org/10.1111/j.2517-6161.1995.tb02031.x",
    "Blondel, V. D., Guillaume, J.-L., Lambiotte, R., & Lefebvre, E. (2008). Fast unfolding of communities in large networks. <i>Journal of Statistical Mechanics: Theory and Experiment, 2008</i>(10), P10008. https://doi.org/10.1088/1742-5468/2008/10/P10008",
    "Bracher, J., Ray, E. L., Gneiting, T., & Reich, N. G. (2021). Evaluating epidemic forecasts in an interval format. <i>PLoS Computational Biology, 17</i>(2), e1008618. https://doi.org/10.1371/journal.pcbi.1008618",
    "Brooke, J. (1996). SUS: A \"quick and dirty\" usability scale. In P. W. Jordan, B. Thomas, B. A. Weerdmeester, &amp; I. L. McClelland (Eds.), <i>Usability evaluation in industry</i> (pp. 189–194). Taylor &amp; Francis.",
    "Buczak, A. L., Baugher, B., Babin, S. M., Ramac-Thomas, L. C., Guven, E., Elbert, Y., Koshute, P. T., Velasco, J. M. S., Roque, V. G., Jr., Tayag, E. A., Yoon, I.-K., & Lewis, S. H. (2014). Prediction of high incidence of dengue in the Philippines. <i>PLoS Neglected Tropical Diseases, 8</i>(4), e2771. https://doi.org/10.1371/journal.pntd.0002771",
    "Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. In <i>Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining</i> (pp. 785–794). https://doi.org/10.1145/2939672.2939785",
    "Copernicus Emergency Management Service. (2018). <i>EMSR312: Typhoon Mangkhut in the Philippines</i> [Rapid mapping activation]. European Commission. https://mapping.emergency.copernicus.eu/activations/EMSR312/",
    "Department of Health Epidemiology Bureau. (2021). <i>DOH-Epi dengue data 2016–2021</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/ac63a95e-7296-42fb-802b-7f7541c73e45",
    "Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., & Michaelsen, J. (2015). The climate hazards infrared precipitation with stations—A new environmental record for monitoring extremes. <i>Scientific Data, 2</i>, 150066. https://doi.org/10.1038/sdata.2015.66",
    "Gibbs, I., & Candès, E. (2021). Adaptive conformal inference under distribution shift. <i>Advances in Neural Information Processing Systems, 34</i>, 1660–1672.",
    "Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. <i>Remote Sensing of Environment, 202</i>, 18–27. https://doi.org/10.1016/j.rse.2017.06.031",
    "Hoo, S. B., Müller, S., Salinas, D., &amp; Hutter, F. (2025). <i>From tables to time: Extending TabPFN-v2 to time series forecasting</i>. arXiv. https://arxiv.org/abs/2501.02945",
    "Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2023). <i>GPM IMERG final precipitation L3 half hourly 0.1 degree x 0.1 degree V07</i> [Data set]. NASA Goddard Earth Sciences Data and Information Services Center. https://doi.org/10.5067/GPM/IMERG/3B-HH/07",
    "Knapp, K. R., Kruk, M. C., Levinson, D. H., Diamond, H. J., & Neumann, C. J. (2010). The International Best Track Archive for Climate Stewardship (IBTrACS): Unifying tropical cyclone data. <i>Bulletin of the American Meteorological Society, 91</i>(3), 363–376. https://doi.org/10.1175/2009BAMS2755.1",
    "Lehner, B., & Grill, G. (2013). Global river hydrography and network routing: Baseline data and new approaches to study the world's large river systems. <i>Hydrological Processes, 27</i>(15), 2171–2186. https://doi.org/10.1002/hyp.9740",
    "Lundberg, S. M., & Lee, S.-I. (2017). A unified approach to interpreting model predictions. <i>Advances in Neural Information Processing Systems, 30</i>, 4765–4774.",
    "Matsushita, N., Ng, C. F. S., Kim, Y., Suzuki, M., Saito, N., Ariyoshi, K., Salva, E. P., Dimaano, E. M., Villarama, J. B., Go, W. S., & Hashizume, M. (2018). The non-linear and lagged short-term relationship between rainfall and leptospirosis and the intermediate role of floods in the Philippines. <i>PLoS Neglected Tropical Diseases, 12</i>(4), e0006331. https://doi.org/10.1371/journal.pntd.0006331",
    "OpenStreetMap contributors. (2026). <i>OpenStreetMap data extract: Philippines</i> [Data set]. Geofabrik. https://download.geofabrik.de/asia/philippines.html",
    "Page, L., Brin, S., Motwani, R., & Winograd, T. (1999). <i>The PageRank citation ranking: Bringing order to the web</i> (Technical Report 1999-66). Stanford InfoLab.",
    "Panagopoulos, G., Nikolentzos, G., &amp; Vazirgiannis, M. (2021). Transfer graph neural networks for pandemic forecasting. <i>Proceedings of the AAAI Conference on Artificial Intelligence, 35</i>(6), 4838–4845. https://doi.org/10.1609/aaai.v35i6.16616",
    "Petricola, S., Reinmuth, M., Lautenbach, S., Hatfield, C., & Zipf, A. (2022). Assessing road criticality and loss of healthcare accessibility during floods: The case of Cyclone Idai, Mozambique 2019. <i>International Journal of Health Geographics, 21</i>, 14. https://doi.org/10.1186/s12942-022-00315-2",
    "Philippine Statistics Authority. (2021). <i>Philippines: 2020 census of population and housing, population by municipality</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/c1edf0c5-58c8-4d39-b566-937b1ad7907f",
    "Philippine Statistics Authority & National Mapping and Resource Information Authority. (2025). <i>Philippines: Subnational administrative boundaries (COD-AB)</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/caf116df-f984-4deb-85ca-41b349d3f313",
    "Runge, J. (2020). Discovering contemporaneous and lagged causal relations in autocorrelated nonlinear time series datasets. In <i>Proceedings of the 36th Conference on Uncertainty in Artificial Intelligence</i> (PMLR 124, pp. 1388–1397). https://arxiv.org/abs/2003.03685",
    "Runge, J., Nowack, P., Kretschmer, M., Flaxman, S., & Sejdinovic, D. (2019). Detecting and quantifying causal associations in large nonlinear time series datasets. <i>Science Advances, 5</i>(11), eaau4996. https://doi.org/10.1126/sciadv.aau4996",
    "Tariverdi, M., Nunez-del-Prado, M., Leonova, N., & Rentschler, J. (2023). Measuring accessibility to public services and infrastructure criticality for disasters risk management. <i>Scientific Reports, 13</i>, 1569. https://doi.org/10.1038/s41598-023-28460-z",
    "Tatem, A. J. (2017). WorldPop, open data for spatial demography. <i>Scientific Data, 4</i>, 170004. https://doi.org/10.1038/sdata.2017.4",
    "Tellman, B., Sullivan, J. A., Kuhn, C., Kettner, A. J., Doyle, C. S., Brakenridge, G. R., Erickson, T. A., & Slayback, D. A. (2021). Satellite imaging reveals increased proportion of population exposed to floods. <i>Nature, 596</i>, 80–86. https://doi.org/10.1038/s41586-021-03695-w",
    "Tiecke, T. G., Liu, X., Zhang, A., Gros, A., Li, N., Yetman, G., Kilic, T., Murray, S., Blankespoor, B., Prydz, E. B., &amp; Dang, H.-A. H. (2017). <i>Mapping the world population one building at a time</i>. arXiv. https://arxiv.org/abs/1712.05839",
    "UN-SPIDER. (n.d.). <i>Recommended practice: Flood mapping and damage assessment using Sentinel-1 SAR data in Google Earth Engine</i>. United Nations Office for Outer Space Affairs. https://www.un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping",
    "van Panhuis, W. G., Choisy, M., Xiong, X., Chok, N. S., Akarasewi, P., Iamsirithaworn, S., Lam, S. K., Chong, C. K., Lam, F. C., Phommasak, B., Vongphrachanh, P., Bouaphanh, K., Rekol, H., Hien, N. T., Thai, P. Q., Duong, T. N., Chuang, J.-H., Liu, Y.-L., Ng, L.-C., ... Burke, D. S. (2015). Region-wide synchrony and traveling waves of dengue across eight countries in Southeast Asia. <i>Proceedings of the National Academy of Sciences, 112</i>(42), 13069–13074. https://doi.org/10.1073/pnas.1501375112",
    "Weiss, D. J., Nelson, A., Vargas-Ruiz, C. A., Gligorić, K., Bavadekar, S., Gabrilovich, E., Bertozzi-Villa, A., Rozier, J., Gibson, H. S., Shekel, T., Kamath, C., Lieber, A., Schulman, K., Shao, Y., Qarkaxhija, V., Nandi, A. K., Keddie, S. H., Rumisha, S., Amratia, P., ... Gething, P. W. (2020). Global maps of travel time to healthcare facilities. <i>Nature Medicine, 26</i>, 1835–1838. https://doi.org/10.1038/s41591-020-0931-3",
    "Zadrozny, B., &amp; Elkan, C. (2002). Transforming classifier scores into accurate multiclass probability estimates. In <i>Proceedings of the 8th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining</i> (pp. 694–699). https://doi.org/10.1145/775047.775151",
]


def fmt_m(x):
    return f"{x / 1e6:.1f} M"


def storm_rows(k):
    t = k["storm_tab"]
    rows = []
    for key, s in STORMS.items():
        r = t.loc[key]
        rows.append(f"<tr><td>{s['local']} <span class='mono' style='color:var(--grey)'>{s['name'].title()} {s['season']}</span></td>"
                    f"<td class='n'>{int(r.ferries)}</td><td class='n'>{fmt_m(r.cut)}</td><td class='n'>{r.A:.1%}</td>"
                    f"<td class='n'>{r.R:.2f}</td><td class='n'>{r.t3} / {r.t2}</td><td>{k['top'][key]}</td></tr>")
    return "\n".join(rows)


def method_rows(k):
    """Per observed track: people cut off by each access method, the per-unit range, agreement, vulnerable groups."""
    t = k["storm_tab"]
    out = []
    for key, s in STORMS.items():
        r = t.loc[key]
        out.append(f"<tr><td>{s['local']}</td><td class='n'>{fmt_m(r.cut)}</td><td class='n'>{fmt_m(r.cutr)}</td>"
                   f"<td class='n'>{r.cut_lo / 1e6:.1f}-{fmt_m(r.cut_hi)}</td><td class='n'>{k['rho_A_obs'][key]:.2f}</td>"
                   f"<td class='n'>{k['tau_methods'][key]:.2f}</td><td class='n'>{k['top10_methods'][key]}/10</td>"
                   f"<td class='n'>{r.u5 / 1e3:,.0f}k</td><td class='n'>{r.o60 / 1e3:,.0f}k</td></tr>")
    return "\n".join(out)


def model_rows(k, compact=False):
    """eval_models.csv: one row per model present, all scored on the same rows."""
    m, al = k["mtab"], k["mall"]
    order = sorted(al.index, key=lambda x: al.loc[x, "relWIS_vs_naive"])
    out = []
    for x in order:
        r = al.loc[x]
        hh = {h: m[(m.model == x) & (m.horizon == h)].relWIS_vs_naive.iloc[0] for h in ("1", "4")}
        lab = MODEL_LABEL.get(x, x)
        bold = " style='font-weight:700'" if x in ("xgb", k.get("best_mean")) else ""
        mw = f"{k['mw'][x]:.2f}" if k.get("mw") else "–"
        if compact:
            out.append(f"<tr{bold}><td>{lab}</td><td class='n'>{r.relWIS_vs_naive:.3f}</td><td class='n'>{r.relWIS_vs_xgb:.3f}</td>"
                       f"<td class='n'>{mw}</td><td class='n'>{r.cov90:.2f}</td></tr>")
        else:
            out.append(f"<tr{bold}><td>{lab}</td><td class='mono' style='font-size:7pt;color:var(--grey)'>{r.kind}</td><td class='n'>{r.WIS:.1f}</td>"
                       f"<td class='n'>{mw}</td><td class='n'>{hh['1']:.3f}</td><td class='n'>{hh['4']:.3f}</td><td class='n'>{r.relWIS_vs_naive:.3f}</td>"
                       f"<td class='n'>{r.relWIS_vs_xgb:.3f}</td><td class='n'>{r.cov50:.2f}</td><td class='n'>{r.cov90:.2f}</td></tr>")
    return "\n".join(out)


def bench_missing_text(k):
    miss = [BENCH_LABEL[x] for x in k["bench_missing"]]
    return "" if not miss else f"Not in this build: {', '.join(miss)} (no forecast file yet); the table fills in when they are added."


def catalog_rows(k, cols=2):
    """All scored storms in date order, split over `cols` side-by-side tables."""
    a = k["allst"]
    rows = []
    for r in a.itertuples():
        star = "" if r.kind == "catalogue" else " &#9670;"
        raw = "" if r.cal else "&dagger;"
        rows.append(f"<tr><td>{r.label}{star}</td><td class='n'>{r.R:.2f}{raw}</td>"
                    f"<td class='n'>{r.cut / 1e6:.2f}</td><td class='n'>{r.cutr / 1e6:.2f}</td><td class='n'>{r.rcut / 1e3:,.0f}k</td>"
                    f"<td class='n'>{r.ferries}</td><td class='n'>{r.t3}/{r.t2}</td></tr>")
    n = (len(rows) + cols - 1) // cols
    head = ("<tr><th>storm</th><th class='n'>R</th><th class='n'>cut M</th><th class='n'>raster</th>"
            "<th class='n'>R&times;cut</th><th class='n'>ferry</th><th class='n'>D/P</th></tr>")
    return [head + "".join(rows[i * n:(i + 1) * n]) for i in range(cols)]


def s1_muni_rows(k):
    out = []
    for key, s in STORMS.items():
        t = k.get("s1_muni", {}).get(key)
        if not t:
            continue
        top = "; ".join(f"{a} ({p}) {fl / 1e3:.0f}k, {fr:.0%}" for a, p, fl, fr in t["top"])
        out.append(f"<tr><td>{s['local']}</td><td class='n'>{t['n_seen']:,}</td><td class='n'>{t['n_fl']}</td><td>{top}</td>"
                   f"<td class='n'>{t['rho']:.2f}</td></tr>")
    return "\n".join(out)


def eval_rows(k):
    e = k["ev"]
    out = []
    for h in list(e.index):
        r = e.loc[h]
        lab = "all" if h == "all" else f"{int(float(h))} wk"
        out.append(f"<tr{' class=\"tot\"' if h == 'all' else ''}><td>{lab}</td><td class='n'>{int(r.n):,}</td><td class='n'>{r['WIS xgb']:.1f}</td>"
                   f"<td class='n'>{r['WIS xgb_nograph']:.1f}</td><td class='n'>{r['WIS naive']:.1f}</td><td class='n'><b>{r['relWIS xgb/naive']:.2f}</b></td>"
                   f"<td class='n'>{r['relWIS xgb/nograph']:.3f}</td><td class='n'>{r['cov50 xgb']:.2f}</td><td class='n'>{r['cov90 xgb']:.2f}</td>"
                   f"<td class='n'>{r['cov90 conformal']:.2f}</td></tr>")
    return "\n".join(out)


def edge_rows(d):
    e = d["edges"].sort_values("weight", key=abs, ascending=False)
    return "\n".join(f"<tr><td>{d['names'][s]}</td><td>{d['names'][t]}</td><td class='n'>{l}</td><td class='n'>{w:.2f}</td>"
                     f"<td class='n'>{q:.3f}</td><td class='n'>{'' if c != c else f'{c:.2f}'}</td></tr>"
                     for s, t, l, w, q, c in zip(e.source, e.target, e.lag, e.weight, e.q, e.confidence))


def sens_rows(d):
    p = d["sens"].pivot_table(index="variant", columns="storm", values="kendall_tau")
    a = d["sens"].pivot_table(index="variant", columns="storm", values="mean_A")
    cols = [STORMS[k]["local"] for k in STORMS]
    head = "<tr><th>variant</th>" + "".join(f"<th class='n'>{c} &tau;</th>" for c in cols) + "<th class='n'>mean A (Ompong)</th></tr>"
    body = "\n".join("<tr><td>" + v + "</td>" + "".join(f"<td class='n'>{p.loc[v, c]:.3f}</td>" for c in cols)
                     + f"<td class='n'>{a.loc[v, 'Ompong']:.2%}</td></tr>" for v in p.index)
    return head + body


def valid_rows(d):
    v = d["valid"]
    return "\n".join(f"<tr><td>{r.storm}</td><td class='mono'>{r.origin}</td><td class='n'>{r.units}</td><td class='n'>{r.surge_rate:.0%}</td>"
                     f"<td class='n'>{r.spearman_R_obs:.2f}</td><td class='n'>{r.spearman_P_obs:.2f}</td><td class='n'>{r.top10_surge_rate:.0%}</td>"
                     f"<td class='n'>{r.brier_R:.3f}</td><td>{r.note if isinstance(r.note, str) else ''}</td></tr>" for r in v.itertuples())


def source_rows(d):
    m = d["manifest"].groupby("source").agg(files=("path", "size"), mb=("bytes", lambda b: b.sum() / 1e6))
    meta = {
        "dengue_hdx": ("DOH-Epi dengue, province/city x week 2016–Jan 2021", "forecast target", "HDX"),
        "census2020": ("2020 CPH population by municipality", "population", "HDX"),
        "cod_ab": ("COD-AB boundaries ADM0-4 (v03, 2025)", "join keys, geometry", "HDX"),
        "ibtracs": ("IBTrACS v04r01 Western Pacific", "storm exposure, swaths", "NOAA NCEI"),
        "chirps": ("CHIRPS v2.0 daily 0.05°, 2016–2020", "rain features, routing", "IRI Data Library"),
        "imerg": ("GPM IMERG V07 daily 0.1°", "rain features", "Earth Engine"),
        "hydrorivers": ("HydroRIVERS v1.0 Australasia", "river routing", "HydroSHEDS"),
        "noah": ("UP NOAH flood hazard 5/25-yr, 139 provinces", "static susceptibility, road proxy", "UP NOAH (Drive)"),
        "copernicus_ems": ("EMSR312 / EMSR478 vector packages", "observed flood (Ompong AOIs)", "Copernicus EMS"),
        "worldpop": ("WorldPop 2020 100 m UN-adjusted", "population grid", "WorldPop"),
        "meta_hrsl": ("Meta HRSL under-5 / 60+", "vulnerable groups cut off", "HDX"),
        "osm": ("OpenStreetMap Philippines PBF", "road network", "Geofabrik"),
        "roroph": ("roroph RoRo routes (108)", "ferry edges (2024–26 proxy)", "pinasr/roroph"),
        "hotosm_health": ("HOT OSM health facilities", "hospital nodes (fallback)", "HDX"),
        "noah_facilities": ("UP NOAH critical facilities", "hospital nodes (fallback)", "UP NOAH"),
        "map_friction": ("MAP friction surface 2019", "raster access method", "Earth Engine"),
        "gfd": ("Global Flood Database events", "context only (ends 2017)", "Earth Engine"),
        "sentinel1": ("Sentinel-1 scene inventory", "pass dates per storm", "Earth Engine"),
        "s1_flood": ("Sentinel-1 new-flood masks per typhoon", "observed flood", "Earth Engine"),
        "cchain": ("Project CCHAIN PIDSR city-week", "leptospirosis, 12 cities", "HDX"),
        "mendeley_parreno": ("Parreño national weekly notifiable diseases", "leptospirosis, national", "Mendeley Data"),
        "opendengue": ("OpenDengue V1.3", "national cross-check", "OpenDengue"),
    }
    rows = []
    for src, (desc, role, where) in meta.items():
        if src in m.index:
            rows.append(f"<tr><td class='mono'>{src}</td><td>{desc}</td><td>{role}</td><td>{where}</td>"
                        f"<td class='n'>{int(m.loc[src, 'files'])}</td><td class='n'>{'&lt;1' if m.loc[src, 'mb'] < 1 else f'{m.loc[src, "mb"]:,.0f}'}</td></tr>")
    for src, desc, role, where in [("psgc", "PSA PSGC 2Q 2026", "not needed: COD-AB pcodes resolve every unit", "manual"),
                                   ("nhfr", "DOH NHFR facility registry", "not used: OSM + NOAH fallback", "manual")]:
        if src not in m.index:
            rows.append(f"<tr class='pend'><td class='mono'>{src}</td><td>{desc}</td><td>{role}</td><td>{where}</td><td class='n'>–</td><td class='n'>–</td></tr>")
    return "\n".join(rows)


# ---------------------------------------------------------------- render

def browser():
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              shutil.which("chrome"), shutil.which("chromium"), shutil.which("msedge")):
        if p and Path(p).exists():
            return p
    return None


def to_pdf(html_path, pdf_path):
    exe = browser()
    if exe is None:
        print("  WARNING no Chrome / Edge found: HTML written, PDF skipped")
        return
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=10000",
                    f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()], check=True, capture_output=True)
    print(f"  wrote {pdf_path.relative_to(ROOT)} ({pdf_path.stat().st_size / 1e6:.1f} MB)")


SCRIPT_CSS = """
@page { size: A4 landscape; margin: 14mm 16mm; }
body { font-size: 10.5pt; }
.head { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid var(--signal); padding-bottom: 3mm; margin-bottom: 4mm; }
h1 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 30pt; line-height: .95; margin: 0; }
h1 em { font-style: normal; color: var(--amber); }
.tag { font-family: "Space Mono"; font-size: 8pt; letter-spacing: .15em; text-transform: uppercase; color: var(--grey); }
p.intro { font-size: 9.5pt; color: #3A4A55; margin: 0 0 4mm; line-height: 1.4; }
table.script td, table.script th { padding: 2.2mm 3mm; border-bottom: 1px solid var(--rule); vertical-align: top; }
table.script th { font-size: 7.5pt; color: var(--grey); border-bottom: 1.5px solid var(--ink); }
table.script td.t { font-family: "Space Mono"; font-weight: 700; white-space: nowrap; color: var(--amber); width: 24mm; }
table.script td.cue { width: 38%; color: #3A4A55; font-size: 9.5pt; }
table.script td.say { font-size: 10.5pt; line-height: 1.4; }
table.script tr { page-break-inside: avoid; }
h2 { font-family: "Big Shoulders Display"; font-weight: 700; text-transform: uppercase; font-size: 15pt; color: var(--teal); margin: 5mm 0 1.5mm; }
ul { margin: 0; padding-left: 5mm; } li { font-size: 9.5pt; margin-bottom: 1mm; }
code { font-family: "Space Mono"; font-size: 8.5pt; }
"""


def _md_inline(t):
    import html as H
    import re

    t = H.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


DEMO_SCRIPTS = {  # markdown source in docs/results -> (html in src/, header tag)
    "Bantay-Baha_Demo_Script": ("demo_script.html", "demonstration video"),
    "Bantay-Baha_Tech_Demo_Script": ("tech_demo_script.html", "technical demo"),
}


def demo_script_html(name="Bantay-Baha_Demo_Script", tag="demonstration video"):
    """docs/results/<name>.md (a demo script) -> HTML in the deck's style (the markdown stays the editable source)."""
    md = (OUT / f"{name}.md").read_text(encoding="utf-8").splitlines()
    title = md[0].lstrip("# ").strip()
    intro, rows, extra, i = [], [], [], 1
    while i < len(md) and not md[i].startswith("|"):
        if md[i].strip():
            intro.append(md[i].strip())
        i += 1
    for line in md[i:]:
        if line.startswith("| **"):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            rows.append(f"<tr><td class='t'>{c[0].strip('*')}</td><td class='cue'>{_md_inline(c[1])}</td><td class='say'>{_md_inline(c[2])}</td></tr>")
        elif line.startswith("## "):
            extra.append(("</ul>" if extra else "") + f"<h2>{_md_inline(line[3:])}</h2><ul>")
        elif line.startswith("- "):
            extra.append(f"<li>{_md_inline(line[2:])}</li>")
    if extra:
        extra.append("</ul>")
    head = title.split(":", 1)
    h1 = f"{head[0]}: <em>{head[1].strip()}</em>" if len(head) == 2 else title
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{FONT_CSS}{SCRIPT_CSS}</style></head><body>"
            f"<div class='head'><h1>{h1}</h1><span class='tag'>PJDSC 2026 / {tag}</span></div>"
            f"<p class='intro'>{_md_inline(' '.join(intro))}</p>"
            f"<table class='script'><tr><th>time</th><th>on screen</th><th>narration</th></tr>{''.join(rows)}</table>{''.join(extra)}</body></html>")


GUIDE_CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm;
        @bottom-left { content: "Bantay-Baha / code guide"; font-family: "Space Mono"; font-size: 7pt; color: #6B7A88; }
        @bottom-right { content: counter(page) " / " counter(pages); font-family: "Space Mono"; font-size: 7pt; color: #6B7A88; } }
body { font-size: 9.6pt; line-height: 1.42; }
h1 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 34pt; line-height: .95; margin: 0 0 3mm;
     border-bottom: 3px solid var(--signal); padding-bottom: 2mm; }
h2 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 20pt; margin: 7mm 0 2mm; color: var(--ink);
     break-after: avoid; }
h3 { font-family: "Big Shoulders Display"; font-weight: 700; text-transform: uppercase; font-size: 14pt; margin: 5mm 0 1.5mm; color: var(--teal);
     break-after: avoid; }
h2 code, h3 code { font-family: inherit; font-size: inherit; background: none; padding: 0; text-transform: none; }
p, li { margin: 0 0 2mm; }
ul, ol { padding-left: 5mm; }
hr { border: 0; border-top: 1px solid var(--rule); margin: 4mm 0; }
code { font-family: "Space Mono"; font-size: 7.8pt; background: var(--mist); padding: 0 1mm; }
pre { background: var(--deep); color: #DCE8EE; padding: 3mm 3mm; font-size: 6.6pt; line-height: 1.35; overflow: hidden; break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; font-size: inherit; }
table { font-size: 8.6pt; margin: 2mm 0 4mm; }
th { font-size: 6.8pt; color: var(--grey); border-bottom: 1.5px solid var(--ink); }
td { border-bottom: 1px solid var(--rule); vertical-align: top; padding: 1.6mm 2mm; }
tr { break-inside: avoid; }
table.blocks td:first-child { width: 26%; }
table.blocks td:nth-child(2) { width: 9%; white-space: nowrap; font-family: "Space Mono"; font-size: 7.6pt; color: var(--amber); }
table.files td:first-child { width: 22%; }
a { color: inherit; text-decoration: none; }
a.toc { color: var(--teal); }
"""


LIBRARY_GUIDE_INTRO = """# Bantay-Baha code guide: library and dashboard

Every code block of the `bantay` package (the pipeline: one module per layer) and of the dashboard in `app/`: what it
does, how, and why it was written that way. The data-download scripts, the build entry point, the benchmarks, the
document generators and the tests are in the full code guide. Line numbers refer to the code as of the date of this
PDF; if a function has moved, search for its name.

[TOC]

---

"""


def library_guide_md(md):
    """The `bantay` library and dashboard sections of CODE_GUIDE.md as a stand-alone guide, renumbered 1-3.

    Keeps section 4 (the library), section 6 (the dashboard) without its tests subsection, and the glossary (11); drops
    the big picture, entry points, data downloads, build, documents, benchmarks, notebook and output list."""
    import re

    parts = {int(m.group(1)): p for p in re.split(r"(?m)^(?=## )", md) if (m := re.match(r"## (\d+)\. ", p))}
    if 4 not in parts or 6 not in parts:
        raise ValueError("CODE_GUIDE.md has no '## 4.' (library) or '## 6.' (dashboard) section")
    app = re.split(r"(?m)^### \d+\.\d+ Tests\b", parts[6])[0]

    def renumber(section, old, new):
        section = re.sub(rf"(?m)^## {old}\. ", f"## {new}. ", section)
        return re.sub(rf"(?m)^### {old}\.(\d+) ", rf"### {new}.\1 ", section)

    out = [renumber(parts[4], 4, 1).rstrip(), renumber(app, 6, 2).rstrip()]
    if 11 in parts:
        out.append(renumber(parts[11], 11, 3).rstrip())
    body = "\n\n".join(re.sub(r"\n---\s*$", "", s) for s in out)  # drop trailing section separators
    return LIBRARY_GUIDE_INTRO + body + "\n"


def code_guide_html(md=None, title="Bantay-Baha code guide"):
    """docs/CODE_GUIDE.md (or the given markdown) -> styled HTML. File links become plain text (they point into the
    repo, which a PDF can't open); the contents links stay as in-document links. A `[TOC]` line becomes the contents."""
    import re

    import markdown

    md = (ROOT / "docs" / "CODE_GUIDE.md").read_text(encoding="utf-8") if md is None else md
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
    body = re.sub(r'<a href="\.\./[^"]*">(.*?)</a>', r"\1", body)  # repo file links -> text
    body = re.sub(r'<a href="(#[^"]*)">', r'<a class="toc" href="\1">', body)
    # block tables (Block | Lines | Explanation) get the line-number column style; other tables a plain first column
    body = re.sub(r"<table>(\s*<thead>\s*<tr>\s*<th>[^<]*</th>\s*<th>Lines</th>)", r"<table class='blocks'>\1", body)
    body = body.replace("<table>", "<table class='files'>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
            f"<style>{FONT_CSS}{GUIDE_CSS}</style></head><body>{body}</body></html>")


def write_code_guides(pdf=True):
    """The full code guide and the library + dashboard guide (HTML in src/, PDFs in docs/results/). Needs no build
    outputs, so `--guide-only` can run on any checkout."""
    path = ROOT / "docs" / "CODE_GUIDE.md"
    if not path.exists():
        return
    SRC.mkdir(parents=True, exist_ok=True)
    guides = [("code_guide.html", code_guide_html(), "Bantay-Baha_Code_Guide.pdf"),
              ("code_guide_library_app.html",
               code_guide_html(library_guide_md(path.read_text(encoding="utf-8")), "Bantay-Baha code guide: library and dashboard"),
               "Bantay-Baha_Code_Guide_Library_App.pdf")]
    for html_name, html, pdf_name in guides:
        (SRC / html_name).write_text(html, encoding="utf-8")
        if pdf:
            to_pdf(SRC / html_name, OUT / pdf_name)


OVERFLOW_JS = """<script>
window.addEventListener("load", () => setTimeout(() => {
  const bad = [];
  document.querySelectorAll("section").forEach((sec, i) => {
    const r = sec.getBoundingClientRect(), limit = r.bottom - 0.5 * 96;  // keep clear of the footer band (0.5 in)
    sec.querySelectorAll("*").forEach(el => {
      if (el.closest(".brand, .pn, .foot, .rail, .hatch, .meta")) return;
      const b = el.getBoundingClientRect();
      if (b.height > 0 && (b.bottom > limit + 1 || b.right > r.right - 0.3 * 96 + 1))
        bad.push((i + 1) + ":" + el.tagName + "." + (el.className || "") + ":" + (el.textContent || el.getAttribute("src") || "").trim().slice(0, 40));
    });
  });
  document.body.setAttribute("data-overflow", JSON.stringify(bad));
}, 500));
</script>"""


def check_overflow(html_path):
    """Lay the HTML out in headless Chrome and list elements that run into the footer band or off the right edge."""
    exe = browser()
    if exe is None:
        return None
    tmp = html_path.with_name(html_path.stem + "_check.html")
    tmp.write_text(html_path.read_text(encoding="utf-8").replace("</body>", OVERFLOW_JS + "</body>"), encoding="utf-8")
    try:
        out = subprocess.run([exe, "--headless=new", "--disable-gpu", "--virtual-time-budget=8000", "--dump-dom", tmp.resolve().as_uri()],
                             capture_output=True, text=True, encoding="utf-8").stdout
    finally:
        tmp.unlink(missing_ok=True)
    import html as H
    import re

    m = re.search(r'data-overflow="([^"]*)"', out)
    bad = json.loads(H.unescape(m.group(1))) if m else ["check did not run"]
    # report each page once, with its first offending element
    seen, msgs = set(), []
    for b in bad:
        pg = b.split(":", 1)[0]
        if pg not in seen:
            seen.add(pg)
            msgs.append(b)
    print(f"  overflow check {html_path.name}: " + ("ok" if not msgs else "; ".join(msgs)))
    return msgs


def main(pdf=True):
    import results_pages as RP
    import results_slides as RS

    d = load()
    k = stats(d)
    F = make_figures(d, k)
    SRC.mkdir(parents=True, exist_ok=True)
    report, slides = SRC / "report.html", SRC / "slides.html"
    report.write_text(RP.report_html(d, k, F), encoding="utf-8")
    slides.write_text(RS.slides_html(d, k, F), encoding="utf-8")
    print(f"  wrote {report.relative_to(ROOT)}, {slides.relative_to(ROOT)}, {len(F)} figures")
    check_overflow(report)
    check_overflow(slides)
    if pdf:
        to_pdf(report, OUT / "Bantay-Baha_Evaluation_Report.pdf")
        to_pdf(slides, OUT / "Bantay-Baha_Slides.pdf")
    write_code_guides(pdf)
    write_demo_scripts(pdf)


def write_demo_scripts(pdf=True):
    """Every DEMO_SCRIPTS markdown that exists -> src/*.html (+ PDF). The scripts' numbers are typed, so this needs no
    build outputs and `--scripts-only` can run on any checkout."""
    SRC.mkdir(parents=True, exist_ok=True)
    for name, (html, tag) in DEMO_SCRIPTS.items():
        if not (OUT / f"{name}.md").exists():
            continue
        page = SRC / html
        page.write_text(demo_script_html(name, tag), encoding="utf-8")
        if pdf:
            to_pdf(page, OUT / f"{name}.pdf")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--guide-only", action="store_true", help="only the two code-guide PDFs (no build outputs needed)")
    ap.add_argument("--scripts-only", action="store_true", help="only the demo-script PDFs (no build outputs needed)")
    a = ap.parse_args()
    if a.guide_only:
        write_code_guides(pdf=not a.no_pdf)
    elif a.scripts_only:
        write_demo_scripts(pdf=not a.no_pdf)
    else:
        main(pdf=not a.no_pdf)
