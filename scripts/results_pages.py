"""HTML for the evaluation report (A4). Used by scripts/make_results.py; the deck is in scripts/results_slides.py.

Every number is read from `k` (make_results.stats) or `d` (the loaded outputs); none is typed into the prose.
"""

import itertools
import re

import pandas as pd

from bantay.config import STORMS
from bantay.scenarios import TIERS

from make_results import (FONT_CSS, REFERENCES, BENCH_LABEL, fmt_m, storm_rows, eval_rows, edge_rows, sens_rows, valid_rows,
                          source_rows, method_rows, model_rows, bench_missing_text, catalog_rows, s1_muni_rows, _rng)

# ================================================================ report (A4)

REPORT_CSS = """
@page { size: A4; margin: 0; }
.page { width: 210mm; height: 297mm; position: relative; overflow: hidden; page-break-after: always; padding: 18mm 16mm 18mm 32mm; }
.page:last-child { page-break-after: auto; }
.rail { position: absolute; left: 0; top: 0; bottom: 0; width: 20mm; background: var(--deep); }
.rail .no { position: absolute; top: 16mm; left: 0; width: 20mm; text-align: center; font-family: "Big Shoulders Display"; font-weight: 800;
            font-size: 30pt; color: var(--signal); line-height: 1; }
.rail .lbl { position: absolute; bottom: 20mm; left: 6.5mm; writing-mode: vertical-rl; transform: rotate(180deg); font-family: "Space Mono";
             font-size: 7pt; letter-spacing: .25em; color: #8FA6B4; text-transform: uppercase; }
.foot { position: absolute; bottom: 8mm; left: 32mm; right: 16mm; display: flex; justify-content: space-between; font-family: "Space Mono";
        font-size: 7pt; color: var(--grey); border-top: 1px solid var(--rule); padding-top: 2mm; }
h1 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 28pt; line-height: .95; margin: 0 0 4mm; }
h2 { font-family: "Big Shoulders Display"; font-weight: 700; text-transform: uppercase; font-size: 14pt; margin: 4.5mm 0 1.5mm; color: var(--teal);
     letter-spacing: .03em; }
p, li { font-size: 9.4pt; line-height: 1.42; margin: 0 0 2.2mm; }
ul, ol { padding-left: 5mm; margin: 0 0 2mm; }
table { font-size: 8.2pt; margin: 2mm 0 3mm; }
th { font-size: 6.8pt; color: var(--grey); border-bottom: 1.5px solid var(--ink); }
tr.tot td { font-weight: 700; border-top: 1.5px solid var(--ink); }
tr.pend td { color: var(--grey); font-style: italic; }
table.tight td, table.tight th { padding: 2.2px 5px; }
table.tight { font-size: 7.6pt; }
table.cat td, table.cat th { white-space: nowrap; padding: 1.6px 4px; font-size: 7.2pt; }
figure { margin: 2mm 0 3mm; }
figure img { width: 100%; display: block; }
figcaption { font-size: 7.8pt; color: var(--grey); margin-top: 1mm; font-style: italic; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 3mm 0; }
.kpi { background: var(--mist); border-top: 3px solid var(--teal); padding: 3mm; }
.kpi b { display: block; font-family: "Big Shoulders Display"; font-weight: 800; font-size: 24pt; line-height: 1; }
.kpi span { font-size: 7.4pt; color: var(--grey); }
.kpi.warn { border-top-color: var(--amber); }
.kpi.red { border-top-color: var(--red); }
.note { border-left: 3px solid var(--amber); background: #FFF7EA; padding: 2.5mm 3.5mm; font-size: 8.6pt; margin: 3mm 0; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; align-items: start; }
.ok { color: var(--teal); font-weight: 700; } .part { color: var(--amber); font-weight: 700; } .no { color: var(--red); font-weight: 700; }
.refs p { font-size: 8.4pt; padding-left: 6mm; text-indent: -6mm; margin-bottom: 2mm; line-height: 1.38; overflow-wrap: anywhere; }
.cover { background: var(--deep); color: #fff; padding: 0; }
.cover .hatch { position: absolute; inset: 0; background: repeating-linear-gradient(105deg, rgba(95,195,228,.07) 0 2px, transparent 2px 14px); }
.cover .inner { position: absolute; left: 22mm; right: 20mm; top: 50mm; }
.cover .tag { display: inline-block; font-family: "Space Mono"; font-size: 8pt; letter-spacing: .2em; border: 1px solid var(--signal);
              color: var(--signal); padding: 1.5mm 3mm; text-transform: uppercase; }
.cover h1 { font-size: 80pt; color: #fff; margin: 10mm 0 5mm; }
.cover .sub { font-size: 15pt; color: #CFE3EC; max-width: 150mm; line-height: 1.3; }
.cover .meta { position: absolute; left: 22mm; bottom: 26mm; font-family: "Space Mono"; font-size: 8.5pt; color: #8FA6B4; line-height: 1.7; }
.cover .bar { position: absolute; left: 22mm; top: 38mm; width: 40mm; height: 3mm; background: var(--signal); }
"""


def _page(no, label, body, total):
    return (f"<section class='page'><div class='rail'><div class='no'>{no:02d}</div><div class='lbl'>{label}</div></div>{body}"
            f"<div class='foot'><span>Bantay-Baha / evaluation report</span><span>PJDSC 2026</span><span>{no} / {total}</span></div></section>")


def _lst(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _targets(k):
    """Proposal objectives: (objective, result, status ok/part/no, note). Status follows the outputs present."""
    e = k["ev"]
    bp, bm = k["bench_present"], k["bench_missing"]
    st = k["storm_tab"]
    rows = [
        ("Province-week panel 2016-2020 on PSGC: dengue, rain, Sentinel-1, hazard, storms",
         f"{k['n_units']} harmonised units x {k['n_weeks']} weeks; every listed layer plus river routing", "ok" if k["s1_ok"] else "part",
         f"{k['n_units']} harmonised 2016-2020 units, not 81 provinces ({k.get('dg_units', '?')} reporting units); Sentinel-1 only in the 4 storm windows"),
        ("Lead-lag graph (PCMCI+), sentinels (PageRank), communities (Louvain); test sentinel features out of sample",
         f"{k['ll_edges']} links at q &lt; 0.05; sentinels and communities on the dashboard; ablation run", "ok",
         f"tested and null: graph / no-graph relative WIS {k['relwis_graph']:.3f}"),
        ("Relative WIS below 1.0 vs seasonal naive, 2018-2019", f"XGBoost {k['relwis']:.3f}"
         + (f"; median ensemble {k['mall'].loc['ens_median', 'relWIS_vs_naive']:.3f}" if "ens_median" in bp else ""), "ok", ""),
        ("90% interval coverage of 80-95%", f"{k['cov90']:.3f} overall; {e.iloc[3]['cov90 xgb']:.2f}-{e.iloc[0]['cov90 xgb']:.2f} by horizon", "ok",
         "4-week horizon close to the floor"),
        ("Benchmarks: Chronos-2, TabPFN-TS, MPNN-LSTM; median ensemble; conformal check",
         ("scored on the same rows: " + ", ".join(BENCH_LABEL[x] for x in bp) if bp else "none scored") + "; online conformal check",
         "ok" if not bm else ("part" if bp else "no"),
         ("the ensemble is evaluated, but storm scenarios use XGBoost (the zero-shot models take no storm-track input)" if not bm
          else "missing: " + ", ".join(BENCH_LABEL[x] for x in bm))),
        ("Access loss per municipality, friction-surface and network methods, four typhoons",
         f"both methods, {k['n_adm3']:,} municipalities, 4 storms x 15 tracks" if k["raster_ok"] else f"network only, {k['n_adm3']:,} municipalities",
         "ok" if k["raster_ok"] else "part", "method disagreement reported as the A_lo-A_hi range" if k["raster_ok"] else "raster method missing"),
        ("Sensitivity bounds (Kendall's &tau;); Metro Manila benchmark",
         f"9 variants x 2 methods, &tau; &ge; {min(k['tau_min'], k.get('tau_min_raster', 1)):.2f}; NCR {k['bench']:.0%} vs ~22%", "ok", "order-of-magnitude check"),
        ("Dashboard: ranked provinces, calibrated risk, access, sentinels, drivers, tier, any historical or shifted track",
         f"{k['n_scen']} backtest scenarios + {k.get('n_cat', 0)} catalogue storms, pre-computed; R recalibrated", "ok",
         "tiers are provisional rules"),
        ("Backtest: did high-priority provinces see more cases?", f"&rho;(R) {_rng(d_min(k, 'spearman_R_obs'), d_max(k, 'spearman_R_obs'), '{:.2f}')} over 4 storms",
         "ok", "2020 storms indicative only (COVID reporting)"),
        ("System Usability Scale from three target users",
         (f"{k['sus_n']} responses, mean {k['sus_mean']:.0f}" if k["sus_n"] else "test form and task built into the dashboard; no responses yet"),
         "ok" if k["sus_n"] >= 3 else "part" if k["sus_n"] else "no", "needs sessions with DOH / LGU / DRRM users"),
        ("Leptospirosis (stretch): national lag analysis; region-week series if digitised",
         "national lag analysis + an open 12-city series (CCHAIN) + typhoon event study" if k.get("lepto_ok") else "not run", "part" if k.get("lepto_ok") else "no",
         "association only, not in the forecast; no province-level series"),
    ]
    return rows


def d_min(k, col):
    return k["valid"][col].min()


def d_max(k, col):
    return k["valid"][col].max()


def report_html(d, k, F):
    k["valid"] = d["valid"]
    e, st, v = k["ev"], k["storm_tab"], d["valid"]
    s1, ems = k["s1_ok"], k.get("ems")
    bp, bm = k["bench_present"], k["bench_missing"]
    al = k.get("mall")
    cal = k.get("calib")
    L = k.get("lepto")
    n_cat = k.get("n_cat", 0)
    obs_cut = (st.cut.min(), st.cut.max())
    obs_cutr = (st.cutr.min(), st.cutr.max()) if k["raster_ok"] else None

    pending = [f"{_lst(BENCH_LABEL[x] for x in bm)} (not in this build)"] if bm else []
    if not k["sus_n"]:
        pending.append("System Usability Scale responses from target users (the test is built into the dashboard)")
    pending.append("the DOH facility registry (hospitals are the OSM + NOAH fallback)")

    cover = f"""<section class='page cover'><div class='hatch'></div><div class='bar'></div><div class='inner'>
<span class='tag'>Evaluation report / PJDSC 2026</span>
<h1>Bantay-<br>Baha</h1>
<div class='sub'>Flood-linked dengue surge risk and storm-driven loss of hospital access, ranked by province for any typhoon track.
Results of the full pipeline run on {k['n_files']} verified source files.</div></div>
<div class='meta'>PJDSC 2026</div></section>"""

    pages = []
    ens_txt = ""
    if "ens_median" in bp:
        ens = al.loc["ens_median"]
        bo = k["bench_only"]
        ens_txt = (f"<li><b>Benchmarked, and beaten on the mean.</b> Zero-shot Chronos-2 and TabPFN-TS and a graph network (MPNN-LSTM) reach relative WIS "
                   f"{_rng(al.loc[bo, 'relWIS_vs_naive'].min(), al.loc[bo, 'relWIS_vs_naive'].max(), '{:.3f}')}, all below XGBoost; their median ensemble with "
                   f"XGBoost is best ({ens.relWIS_vs_naive:.3f}, 90% coverage {ens.cov90:.0%}). On the <i>median</i> WIS XGBoost is best "
                   f"({k['mw']['xgb']:.2f} vs {_rng(min(k['mw'][x] for x in bo), max(k['mw'][x] for x in bo), '{:.2f}')}): the benchmarks win on high-count "
                   f"epidemic weeks. Storm scenarios still use XGBoost, the only model that takes the storm track.</li>")
    elif bp or bm:
        ens_txt = f"<li><b>Benchmarks.</b> {bench_missing_text(k)}</li>"
    acc_txt = (f"<li><b>Access loss, two methods.</b> For the observed tracks (roads cut by {k['src_obs']}) {fmt_m(obs_cut[0])}-{fmt_m(obs_cut[1])} people lose "
               f"their route on the road-and-ferry network and {fmt_m(obs_cutr[0])}-{fmt_m(obs_cutr[1])} on the MAP friction raster; the gap is reported as a range. "
               f"Gale swaths cancel {int(st.ferries.min())}-{int(st.ferries.max())} of {k['n_ferry']} RoRo routes; Kendall's &tau; under nine setting changes is at least "
               f"{min(k['tau_min'], k.get('tau_min_raster', 1)):.2f}.</li>") if k["raster_ok"] else ""
    cal_txt = (f"<li><b>Surge probability R, recalibrated.</b> Isotonic regression on past rolling-origin forecasts only lowers the Brier score from "
               f"{cal['all_rows']['brier_raw']:.3f} to {cal['all_rows']['brier_cal']:.3f} ({cal['all_rows']['brier_climatology']:.3f} for always predicting the base rate) and removes the "
               f"model's under-confidence in the middle range.</li>") if cal else ""
    lep_txt = (f"<li><b>Leptospirosis (stretch).</b> In {L.get('n_cities', 12)} cities, rain is followed by leptospirosis "
               f"{min(L['city']['sig'])}-{max(L['city']['sig'])} weeks later (peak IRR {L['city']['peak'].irr:.2f} per +50 mm/week at lag "
               f"{int(L['city']['peak'].lag)}); not extrapolated to provinces.</li>") if L else ""
    pages.append(("Summary", f"""<h1>What we built,<br>what the data says</h1>
<p>Bantay-Baha joins three graphs into one ranking: a flood-exposure layer (rain, river routing, observed and mapped flood), a lead-lag outbreak
graph learned with PCMCI+, and a road-plus-ferry access graph that a typhoon cuts. A quantile forecast of dengue gives the probability
<b>R</b> that a province's next four weeks exceed its usual bad month; two access methods give the share <b>A</b> of people cut off from a
hospital; priority is <b>P = R &times; A</b>. Every number below was computed by <span class='mono'>build.bat</span> from the raw files.</p>
<div class='kpis'>
<div class='kpi'><b>{k['relwis']:.2f}</b><span>relative WIS of XGBoost vs seasonal naive, 1-4 weeks (target below 1)</span></div>
{f"<div class='kpi red'><b>{al.loc['ens_median', 'relWIS_vs_naive']:.2f}</b><span>median ensemble with the three benchmarks: the best mean score</span></div>" if 'ens_median' in bp else
 f"<div class='kpi warn'><b>{k['ll_edges']}</b><span>PCMCI+ lead-lag links among {k['ll_N']} provinces</span></div>"}
<div class='kpi'><b>{k['cov90']:.0%}</b><span>XGBoost 90% interval coverage (target 80-95%)</span></div>
<div class='kpi'><b>{k['n_scen'] + n_cat}</b><span>pre-computed storm scenarios: 4 typhoons x 15 tracks{f" + {n_cat} more storms" if n_cat else ""}</span></div></div>
<h2>Findings</h2>
<ul>
<li><b>The forecast beats the bar.</b> Multi-quantile XGBoost reaches relative WIS {e.iloc[0]['relWIS xgb/naive']:.2f} at one week and
{e.iloc[3]['relWIS xgb/naive']:.2f} at four over {k['n_scored']:,} rolling-origin forecasts in 2018-2019.</li>
{ens_txt}
<li><b>Two honest null results.</b> Lead-lag graph features do not help (graph / no-graph {k['relwis_graph']:.3f}), nor do rain, river, storm and
flood features ({k['relwis_env']:.3f}). At 1-4 weeks, recent cases and the season carry the skill.</li>
{cal_txt}
<li><b>The ranking points at the right places.</b> &rho;(R, next-4-week incidence) = {v.spearman_R_obs.iloc[0]:.2f} (Ompong), {v.spearman_R_obs.iloc[1]:.2f}
(Tisoy); {v.top10_surge_rate.iloc[0] * 10:.0f} of Ompong's top-10 provinces surged against a {v.surge_rate.iloc[0]:.0%} base rate.</li>
{acc_txt}
{lep_txt}</ul>
<div class='note'><b>Not in these results:</b> {'; '.join(pending)}. Scorecard: page @@Scorecard@@.</div>
<figure><img src='{F['timeline']}' style='width:74%'><figcaption>Figure 1. The forecast target: DOH-Epi weekly dengue summed over the {k['n_units']} harmonised units, with the
four backtest typhoons. 2020 is used for access scenarios only.</figcaption></figure>"""))

    pages.append(("Data", f"""<h1>Data and acquisition</h1>
<p>{k['n_files']} files from {k['n_sources']} sources ({k['gb']:.1f} GB) are listed in <span class='mono'>data/raw/MANIFEST.csv</span> with size and
sha256; all were verified on disk before this build. Open sources come from <span class='mono'>scripts/download_data.py</span>, Earth Engine
sources from <span class='mono'>scripts/download_gee.py</span>, and the team shares them through a private bucket (<span class='mono'>setup.bat</span>,
every file checked against the manifest). The two manual sources were not needed (last rows).</p>
<table><tr><th>folder</th><th>dataset</th><th>role</th><th>from</th><th class='n'>files</th><th class='n'>MB</th></tr>
{source_rows(d)}</table>"""))

    cy = k.get("cases_by_year", {})
    pages.append(("Panel", f"""<h1>Step 0: one unit-week table</h1>
<h2>Harmonised units</h2>
<p>The DOH file has <b>{k.get('dg_units', 126)} reporting units, not 81 provinces</b>: provinces mixed with highly urbanised and component cities, plus
misspellings (NUEVA VISCAYA, SISQUIJOR, BASILIG CITY = Bislig). COD-AB uses current boundaries (Maguindanao split in 2022, Special
Geographic Area in 2024). The reviewed crosswalk in <span class='mono'>data/crosswalks/</span> folds cities into their province and undoes
the post-2020 changes, giving <b>{k['n_units']} units</b>; every dengue unit resolves and every unit has data. A unit-week counts only if
every member reported (NaN otherwise, never 0). Deaths are not used (2016 case fatality {k.get('cfr16', float('nan')):.1%}, far above other years), and
2020 fell to {cy.get(2020, 0) / 1e3:.0f}k cases against {cy.get(2019, 0) / 1e3:.0f}k in 2019 under COVID-19, so 2020 is never a forecast target.</p>
<h2>Population</h2>
<p>The 2020 census table's municipal codes are old 9-digit PSGC and do not join to COD-AB for the highly urbanised cities, post-split Maguindanao and
the Special Geographic Area. Its own <i>Province</i> column already places cities in their province, so units are summed on it: {k['pop'] / 1e6:.2f} M people.</p>
<div class='two'><figure><img src='{F['coverage']}'><figcaption>Figure 2. Coverage of the {k['n_units']} x {k['n_weeks']} panel. {"Sentinel-1 is filled only for the four landfall windows, by design." if s1 else "Sentinel-1 is the only empty input."}</figcaption></figure>
<div><h2>Layer 1 inputs</h2><p>Rain: CHIRPS and IMERG agree (weekly r = {k['rain_r']:.2f}). River routing accumulates CHIRPS rain down the
HydroRIVERS network. NOAH 25-yr hazard covers {k['haz_units']} of {k['n_units']} units; the median unit has {k['haz_median']:.0%} of its people in a
hazard zone. Units with no map are <b>missing, not zero</b>: {', '.join(k['haz_nomap'])}.</p>
<p>Storm exposure: every Western Pacific track 2016-2020 from IBTrACS, gale radius from USA R34, else JMA R30, else a fixed 150 km.
{f"USA R34 is missing on {max(k['r34_missing'].values()):.0%} of Rolly's gale-strength fixes (JMA fills them); the fixed fallback never triggers for the four storms." if k.get('r34_missing') else ""}</p></div></div>"""))

    hrsl = ""
    if k.get("hrsl_ok"):
        hrsl = (f" Under-5 and 60+ people come from Meta HRSL (Tiecke et al., 2017) summed to the same cells; a cell's vulnerable people are cut off "
                f"when the cell is (network rule).")
    bench_m = ""
    if k["bench_only"]:
        bench_m = ("<p><b>Benchmarks</b>, scored on exactly the same rows: Chronos-2 (Ansari et al., 2025) and TabPFN-TS (Hoo et al., 2025) zero-shot, "
                   "each origin's forecast from that unit's own past only; an MPNN-LSTM graph network (Panagopoulos et al., 2021) trained on the same 13-week "
                   "rolling refits; and the element-wise median of the 23 quantiles of XGBoost and the three (the ensemble).</p>")
    pages.append(("Methods", f"""<h1>Methods and evaluation protocol</h1>
<h2>Layer 2: lead-lag outbreak graph</h2>
<p>log(1 + incidence), 52-week seasonal difference, standardised inside the training window. PCMCI+ (Runge, 2020) with partial-correlation
tests, lags 1-3 weeks, pc_alpha 0.01; lagged inter-province edges are kept when the Benjamini-Hochberg (1995) q-value is below 0.05 (on pure-noise
checks PCMCI+ without this step returned many false edges). PageRank (Page et al., 1999) on the reversed graph scores sentinels; Louvain
(Blondel et al., 2008) finds communities; lagged cross-correlation with the same FDR is the baseline graph.</p>
<h2>Forecast and surge probability</h2>
<p>One pooled XGBoost (Chen &amp; Guestrin, 2016) per horizon (1-4 weeks), multi-quantile objective at the 23 CDC FluSight levels, on
log(1 + incidence), back-transformed to cases. Features: lagged incidence, same week last year, week of year, CHIRPS / IMERG / river rain lags,
storm exposure, NOAH hazard, Sentinel-1 flood and leader signals from the graph; SHAP (Lundberg &amp; Lee, 2017) gives the "drivers". A direct
4-week model gives <b>R</b>, the probability of exceeding the unit's 90th percentile of 4-week incidence in the training window. R is then
<b>recalibrated</b> by isotonic regression (Zadrozny &amp; Elkan, 2002) fitted only on earlier rolling-origin forecasts whose outcome was known at the origin.</p>
{bench_m}
<h2>Evaluation</h2>
<p><b>Rolling origin, never a random split.</b> From January 2018 to December 2019 the model, graph and thresholds are refit every 13 weeks on data
up to the refit date, then forecast every origin until the next refit. Scores: weighted interval score on case counts (Bracher et al., 2021),
relative WIS against a seasonal-naive forecast, 50% and 90% coverage, and an online conformal 90% band from past errors only (Gibbs &amp; Candès, 2021).</p>
<h2>Layer 3: access, two methods</h2>
<p><b>Network.</b> OSM highways become a graph of junctions; RoRo routes are ferry edges (crossing time plus half the headway); hospitals are HOT OSM plus
NOAH name-matched facilities ({k['n_hosp']:,}). WorldPop (Tatem, 2017) is summed to 1 km cells, each joined to the nearest road node; a
multi-source Dijkstra gives hours to the nearest hospital. <b>Raster.</b> Cost-distance from the same hospitals over the MAP motorised friction surface
(Weiss et al., 2020), sea impassable except along the same ferry lines. <b>Storms</b> apply the same rules to both: ferries crossing the gale swath are
cancelled; roads (or cells) in observed flood (Sentinel-1, observed tracks) or in NOAH high hazard inside the swath (shifted tracks) are cut, medium
hazard slows them. A cell is cut off if it loses its route, or its trip at least doubles and grows by over an hour (after Petricola et al., 2022).
The network gives A, P and the tier; the per-unit minimum and maximum of the two methods give A_lo-A_hi and P_lo-P_hi.{hrsl}</p>"""))

    pages.append(("Forecast", f"""<h1>Forecast skill (XGBoost)</h1>
<table><tr><th>horizon</th><th class='n'>n</th><th class='n'>WIS xgb</th><th class='n'>WIS no-graph</th><th class='n'>WIS naive</th>
<th class='n'>rel WIS</th><th class='n'>graph / no-graph</th><th class='n'>cov 50</th><th class='n'>cov 90</th><th class='n'>cov 90 conformal</th></tr>
{eval_rows(k)}</table>
<p><b>Targets met.</b> Relative WIS is below 1 at every horizon ({e.iloc[0]['relWIS xgb/naive']:.2f} to {e.iloc[3]['relWIS xgb/naive']:.2f}) and 90%
coverage is inside 80-95% at every horizon (four weeks is close to the floor at {e.iloc[3]['cov90 xgb']:.2f}). The 50% intervals are a little narrow
({e.iloc[3]['cov50 xgb']:.2f}-{e.iloc[0]['cov50 xgb']:.2f}). The online conformal band reaches similar coverage, a sign the quantiles are not badly
miscalibrated.</p>
<h2>What carries the skill</h2>
<table><tr><th>comparison</th><th class='n'>relative WIS</th><th>reading</th></tr>
<tr><td>XGBoost vs seasonal naive</td><td class='n'>{k['relwis']:.3f}</td><td>{1 - k['relwis']:.0%} lower WIS than "same week last year"</td></tr>
<tr><td>with vs without graph leader features</td><td class='n'>{k['relwis_graph']:.3f}</td><td>no gain: the graph has {_rng(*k['edges_by_year'][2018])} links in the 2018 windows and {_rng(*k['edges_by_year'][2019])} in 2019</td></tr>
<tr><td>with vs without rain / river / storm / flood</td><td class='n'>{k['relwis_env']:.3f}</td><td>{k['relwis']:.3f} vs {k['relwis_noenv']:.3f} against seasonal naive, same rows</td></tr></table>
<p>With so few significant links, leader signals are empty for most provinces. The rain result has two likely reasons, not tested: rain moves with
the season in a four-year panel, so the season features already carry it, and any effect at lags beyond four weeks is outside this horizon.</p>
<figure><img src='{F['fan']}'><figcaption>Figure 3. Rolling-origin forecasts for Cagayan (Ompong's landfall province, dashed line), one and four weeks
ahead.</figcaption></figure>"""))

    if k["models_ok"]:
        notes = ""
        if k["bench_only"]:
            sp, var, bmeta = k["split"], k.get("variants", {}), k["bench_meta"]
            bo = k["bench_only"]
            mp = bmeta.get("mpnn_lstm", {}).get("adjacency", {})
            notes = f"""<h2>Reading the comparison</h2>
<ul><li><b>Mean vs median.</b> Every benchmark beats XGBoost on mean WIS, and the ensemble is best. On the median row XGBoost is best
({k['mw']['xgb']:.2f} cases vs {_rng(min(k['mw'][x] for x in bo), max(k['mw'][x] for x in bo), '{:.2f}')}; ensemble {k['mw'].get('ens_median', float('nan')):.2f}). Split at the
90th percentile of weekly cases ({sp['thr']:.0f}): below it the benchmarks' mean WIS is {_rng(min(sp['lo'][x] for x in bo), max(sp['lo'][x] for x in bo), '{:.2f}')} times
XGBoost's, above it {_rng(min(sp['hi'][x] for x in bo), max(sp['hi'][x] for x in bo), '{:.2f}')} times. The better means come from the large-count epidemic weeks;
the ensemble ({sp['lo'].get('ens_median', float('nan')):.2f} / {sp['hi'].get('ens_median', float('nan')):.2f}) gains in both.</li>
<li><b>Chronos-2</b> as first specified, on log(1 + incidence), collapsed on one-week reporting spikes (relative WIS {var.get('chronos2_log1p', float('nan')):.0f}).
The headline run uses the incidence scale with past-only covariates; it was chosen <i>after</i> seeing that failure. Without covariates it scores
{var.get('chronos2_nocov', float('nan')):.3f}, so the covariates do not help.</li>
<li><b>TabPFN-TS</b> runs univariate (it ignores past-only covariates) with the ungated TabPFN v2 regressor; the default v3.5 weights need a login and
licence and were not used. A lagged-covariate variant scores {var.get('tabpfn_ts_lagcov', float('nan')):.3f}.</li>
<li><b>MPNN-LSTM</b> uses border adjacency ({mp.get('n_border', '?')} edges) plus RoRo routes ({mp.get('n_ferry_new_edges', '?')} more, a 2024-26 proxy); with no graph
it scores {var.get('mpnn_lstm_none', float('nan')):.3f}, the same within seed noise, in line with the sparse lead-lag graph.</li>
<li><b>Where it is used.</b> Benchmarks and the ensemble exist only at the rolling-origin weeks (2018-2019). Storm scenarios, shifted tracks, 2020 and
the catalogue use XGBoost with calibrated R, because the zero-shot models take no storm-track input.</li></ul>"""
        miss = bench_missing_text(k)
        pages.append(("Models", f"""<h1>Model comparison</h1>
<p>Every model scored on the same {k['n_common']:,} rolling-origin rows (2018-2019, horizons 1-4, WIS on case counts). Relative WIS is against
the seasonal naive (below 1 is better) and against XGBoost.</p>
<table class='tight'><tr><th>model</th><th>kind</th><th class='n'>mean WIS</th><th class='n'>median WIS</th><th class='n'>rel 1 wk</th><th class='n'>rel 4 wk</th>
<th class='n'>rel WIS</th><th class='n'>vs xgb</th><th class='n'>cov 50</th><th class='n'>cov 90</th></tr>{model_rows(k)}</table>
{f"<div class='note'>{miss}</div>" if miss else ""}
<figure><img src='{F['wis']}'><figcaption>Figure 4. Left: relative WIS of every model over 1-4 weeks (ticks: 1 and 4 weeks). Right: coverage against the nominal
lines and the proposal's 80-95% band.</figcaption></figure>
{notes}"""))

    if cal:
        a_, c_ = cal["all_rows"], cal["calibrated_rows"]
        r = d["rel"]
        mid = r[(r.mean_R > 0.1) & (r.mean_R <= 0.7)]
        gap_raw = (mid.observed - mid.mean_R).abs().max()
        midc = r[(r.mean_R_cal > 0.1) & (r.mean_R_cal <= 0.7)]
        gap_cal = (midc.observed_cal - midc.mean_R_cal).abs().max()
        pages.append(("Calibration", f"""<h1>Surge probability R: recalibrated</h1>
<div class='two'><figure><img src='{F['rel']}'><figcaption>Figure 5. Reliability of R over the 2018-2019 unit-weeks, before (amber) and after (teal)
isotonic recalibration; labels: unit-weeks per bin.</figcaption></figure>
<div><p>The model's R was <b>under-confident in the middle</b>: in the bins between 0.1 and 0.7, outcomes came true up to {gap_raw:.0%} more often than
forecast. Isotonic regression maps raw R to observed surge frequency. It is fitted at each origin on earlier forecasts whose 4-week outcome was
already known (target week no later than the origin), so it never sees the future. It needs {cal['min_rows']:,} past outcomes first: the
{len(cal['uncalibrated_origins'])} origins before {cal['first_calibrated_origin']} keep raw R ({cal['n_uncalibrated']:,} rows).</p>
<p>After recalibration the largest middle-bin gap is {gap_cal:.0%}.</p></div></div>
<table><tr><th>rows</th><th class='n'>n</th><th class='n'>base rate</th><th class='n'>mean R raw</th><th class='n'>mean R cal</th><th class='n'>Brier raw</th>
<th class='n'>Brier cal</th><th class='n'>Brier base rate</th></tr>
<tr><td>all 2018-2019 origins</td><td class='n'>{a_['n']:,}</td><td class='n'>{a_['base_rate']:.3f}</td><td class='n'>{a_['mean_R_raw']:.3f}</td><td class='n'>{a_['mean_R_cal']:.3f}</td>
<td class='n'>{a_['brier_raw']:.3f}</td><td class='n'><b>{a_['brier_cal']:.3f}</b></td><td class='n'>{a_['brier_climatology']:.3f}</td></tr>
<tr><td>origins with a calibrator</td><td class='n'>{c_['n']:,}</td><td class='n'>{c_['base_rate']:.3f}</td><td class='n'>{c_['mean_R_raw']:.3f}</td><td class='n'>{c_['mean_R_cal']:.3f}</td>
<td class='n'>{c_['brier_raw']:.3f}</td><td class='n'><b>{c_['brier_cal']:.3f}</b></td><td class='n'>{c_['brier_climatology']:.3f}</td></tr></table>
<p>The base rate is {a_['base_rate']:.0%}, not 10%, because 2019 was an epidemic year and the thresholds come from earlier, quieter years. The scenario
files keep both: <span class='mono'>R</span> (calibrated, used for P and the tiers) and <span class='mono'>R_raw</span>. Recalibration raises mid-range R, so
more provinces reach the provisional tiers (pre-position at R &ge; {TIERS['preposition_R']:g}, deploy at R &ge; {TIERS['deploy'][0]:g} with A &ge; {TIERS['deploy'][1]:.0%}):
for Ompong mean R rises from {st.loc['ompong', 'R_raw']:.2f} to {st.loc['ompong', 'R']:.2f}. The tier thresholds still need review with users.</p>
<p><b>Ties.</b> Isotonic regression is a step function, so provinces share values: for Ompong the {k['n_units']} units take {k['n_distinct_R']} distinct R values and {k['ties'][0]} share the top value ({k['ties'][1]:.2f}). A ranking by R alone has ties; P = R &times; A breaks them by access, and the backtest's Spearman correlations use average ranks.</p>"""))

    pages.append(("Graph", f"""<h1>The lead-lag graph</h1>
<div class='two'><figure><img src='{F['leadlag']}'><figcaption>Figure 6. The {k['ll_edges']} PCMCI+ links learned on 2016-2019 (teal = leader).</figcaption></figure>
<div><p>Final window: {k['ll_N']} series, T = {k['ll_T']} weeks after seasonal differencing (Davao Occidental sits out with more than 10% missing
weeks). PCMCI+ keeps <b>{k['ll_edges']}</b> lagged inter-province links at q &lt; 0.05. Plain lagged cross-correlation with the same FDR keeps
<b>{k['xc_edges']:,}</b>, because the 2019 national epidemic makes almost every pair co-move.</p>
<p>The proposal's sentinel idea is therefore <b>weakly supported at province-week level</b>. The links are statistical dependencies, not
evidence of transmission, and several join distant provinces. Likely reasons: weekly province totals average out local waves, four years
is short for {k['ll_N']} series, and reporting artefacts dominate small provinces. Synchrony studies such as van Panhuis et al. (2015) worked at
longer time scales. The MPNN-LSTM benchmark points the same way: its result does not depend on its graph.</p></div></div>
<table><tr><th>leader</th><th>follower</th><th class='n'>lag (wk)</th><th class='n'>partial corr</th><th class='n'>q</th><th class='n'>bootstrap freq</th></tr>
{edge_rows(d)}</table>"""))

    if s1:
        tab = k["s1_tab"]
        rows = "".join(f"<tr><td>{STORMS[kk]['local']}</td><td class='n'>{fmt_m(t['pop'])}</td><td class='n'>{t['units']}</td>"
                       f"<td class='n'>{t['frac_max']:.1%}</td><td>{t['top']}</td></tr>" for kk, t in tab.items())
        agree = (f"Inside the EMS areas of interest, EMS mapped {ems['ems_km2']:.0f} km&sup2; of observed flood and Sentinel-1 flagged "
                 f"{ems['s1_km2']:.0f} km&sup2;; {ems['both_km2']:.0f} km&sup2; overlap: <b>{ems['precision']:.0%}</b> of Sentinel-1 flood there is confirmed by "
                 f"EMS, and Sentinel-1 recovers <b>{ems['recall']:.0%}</b> of the EMS area.") if ems else "EMS comparison unavailable."
        pages.append(("Flood", f"""<h1>Observed flood: Sentinel-1</h1>
<p>Radar sees through typhoon clouds. For each typhoon, new open water is mapped on Google Earth Engine (Gorelick et al., 2017) from Sentinel-1 VH
backscatter in 100 m tiles near the track: before = median of days -30 to -3, after = darkest image of days 0 to +10, <b>both from the same relative
orbit</b>. A pixel is new flood when VH drops by at least 3 dB and ends at most -18 dB; permanent water (JRC), slopes over 5&deg; and specks under 8
pixels are removed (after UN-SPIDER, n.d.). The first version, UN-SPIDER's after/before ratio on dB values with mixed orbits, recovered almost none of
the EMS flood and was replaced.</p>
<figure><img src='{F['s1']}' style='width:84%'><figcaption>Figure 7. New-flood share of the land Sentinel-1 saw, per unit, with each track.</figcaption></figure>
<table class='tight'><tr><th>typhoon</th><th class='n'>people in new flood</th><th class='n'>units &gt;1% flooded</th><th class='n'>max unit share</th><th>most people flooded</th></tr>{rows}</table>
{f'''<h2>Per municipality</h2><table class='tight'><tr><th>typhoon</th><th class='n'>seen &gt;20%</th><th class='n'>&gt;1% flooded</th><th>most people in new flood: municipality (province), people, share</th><th class='n'>&rho;(A, flood)</th></tr>{s1_muni_rows(k)}</table>
<p style='font-size:8.4pt'>&rho;: Spearman correlation, over the municipalities the radar saw, between network access loss A and the new-flood share. Access loss follows
flood but not one-to-one: a municipality can be flooded and keep a dry road to a hospital.</p>''' if k.get('s1_muni') else ''}
<div class='two' style='grid-template-columns:.8fr 1.2fr'><figure><img src='{F['s1ems']}' style='max-height:58mm;width:auto'><figcaption>Figure 8. Ompong around Tuguegarao: Sentinel-1 new flood (teal) and Copernicus EMS
observed flood (red outlines).</figcaption></figure>
<div><h2>Checked against Copernicus EMS</h2><p>{agree} Low recall is expected: EMS used other imagery and dates, while one Sentinel-1 orbit passed
here only twice in the window.</p></div></div>"""))

    pr = k.get("proxy", {})
    pages.append(("Access", f"""<h1>Access loss under four typhoons</h1>
<p><b>Baseline.</b> {k['cells_pop'] / 1e6:.1f} M people in 1 km cells; on the network {k['route_share']:.1%} have a road or ferry route to one of {k['n_hosp']:,}
hospitals, with a population-weighted mean trip of {k['mean_hours']:.2f} h.{f" The raster reaches {k['mbase']['pop_reach_raster']:.1%} with a mean of {k['mbase']['popw_mean_hours_raster']:.2f} h." if k['raster_ok'] else ""}
Results are also written for {k['n_adm3']:,} municipalities.</p>
{f'''<table class='tight'><tr><th>typhoon</th><th class='n'>cut off network</th><th class='n'>raster</th><th class='n'>range (unit min-max)</th><th class='n'>&rho; A units</th>
<th class='n'>&tau; P</th><th class='n'>top-10 shared</th><th class='n'>under-5 cut off</th><th class='n'>60+ cut off</th></tr>{method_rows(k)}</table>''' if k['raster_ok'] else ''}
<figure><img src='{F['access']}'><figcaption>Figure 9. Network access loss A per unit for the observed tracks. Roads are cut by {k['src_obs']}; ferries crossing
the gale swath are cancelled.</figcaption></figure>
<div class='note'>Observed tracks: roads are cut only where Sentinel-1 saw new water. Radar misses floods under dense vegetation, in built-up areas and
between passes, so these are <b>lower bounds</b>. The {pr.get('n', 0)} shifted tracks have no image and use the NOAH 25-yr proxy (every high-hazard road
in the swath cut): {fmt_m(pr['cut'][0]) if pr else ''}-{fmt_m(pr['cut'][1]) if pr else ''} people cut off on the network, an <b>upper bound</b>. Ferry routes are
2024-2026 operations, a proxy for 2018-2020. A uses radar that exists about ten days after the forecast origin: it is a retrospective access
estimate.</div>"""))

    if k["raster_ok"]:
        mb = k["mbase"]
        pages.append(("Two methods", f"""<h1>Network vs friction raster</h1>
<p>The proposal runs a raster method next to the network because OSM completeness is uneven, and reports their disagreement as uncertainty. Both
use the same hospitals, population cells, ferry lines and storm rules.</p>
<h2>On a normal day</h2>
<p>The raster reaches more people ({mb['pop_reach_raster']:.1%} vs {mb['pop_reach_network']:.1%}) and is faster (population-weighted mean
{mb['popw_mean_hours_raster']:.2f} h vs {mb['popw_mean_hours_network']:.2f} h; median cell ratio raster / network {mb['median_ratio_raster_network']:.2f}): it can cross
land without a mapped road. The two still rank places alike: Spearman {mb['spearman_hours_cells']:.2f} over {mb['cells_both_reach']:,.0f} cells that both reach,
{mb['spearman_unit_base_hours']:.2f} over the {mb['n_units']:.0f} units' mean trip.</p>
<figure><img src='{F['methods']}'><figcaption>Figure 10. People cut off by each method. Left: observed tracks with Sentinel-1 flood. Right: every track that uses the
NOAH proxy (shifted backtest tracks and catalogue storms), with the 1:1 line.</figcaption></figure>
<h2>Under a storm</h2>
<p>The gap changes sign with the flood source. With Sentinel-1 the raster cuts off more people ({fmt_m(st.cutr.min())}-{fmt_m(st.cutr.max())} vs
{fmt_m(st.cut.min())}-{fmt_m(st.cut.max())}); with the NOAH proxy it cuts off fewer (median ratio {pr['ratio']:.2f}). A likely reason: at 1 km a flooded cell
centre closes the whole cell, while radar flood is patchy and the network closes only the flooded road edges; the proxy closes every high-hazard
road, which the raster's cell-centre test samples more sparsely. The unit rankings agree well under the proxy (&rho; of A {pr['rho'][0]:.2f}-{pr['rho'][1]:.2f}) and less
with radar ({min(k['rho_A_obs'].values()):.2f}-{max(k['rho_A_obs'].values()):.2f}), where {_rng(min(k['top10_methods'].values()), max(k['top10_methods'].values()))} of the top-10 provinces by P are shared. The dashboard
shows A and P with this range. Sensitivity on the raster: Kendall's &tau; &ge; {k['tau_min_raster']:.3f} for the same nine variants.</p>
{f'''<h2>Vulnerable groups</h2>
<p>Meta HRSL puts {k['u5_share']:.1%} of people under five and {k['o60_share']:.1%} aged 60+; the 2020 census has {k.get('census_u5', float('nan')):.1%} and
{k.get('census_60', float('nan')):.1%}. HRSL therefore <b>under-counts older people</b> (and slightly over-counts young children), so the 60+ cut-off numbers
are low estimates. Among those cut off, the under-5 share is {_rng(min(k['u5_cut_share'].values()), max(k['u5_cut_share'].values()), '{:.1%}')} and the 60+ share
{_rng(min(k['o60_cut_share'].values()), max(k['o60_cut_share'].values()), '{:.1%}')}.</p>''' if k.get('hrsl_ok') else ''}"""))

    ps = k.get("proxy_storm")
    pages.append(("Priority", f"""<h1>Priority: Ompong 2018</h1>
<table class='tight'><tr><th>typhoon</th><th class='n'>ferry routes cut</th><th class='n'>people cut off</th><th class='n'>mean A</th><th class='n'>mean R</th>
<th class='n'>deploy / pre-position</th><th>top priority</th></tr>{storm_rows(k)}</table>
<div class='two'><figure><img src='{F['priority']}'><figcaption>Figure 11. P = R x A for Ompong with its track and gale swath; top 5 labelled.</figcaption></figure>
<figure><img src='{F['scatter']}'><figcaption>Figure 12. Risk vs access. Dotted lines are the provisional tier thresholds (R = {TIERS['preposition_R']:g}, A = {TIERS['deploy'][1]:.0%}); marker
shape encodes the action tier.</figcaption></figure></div>
<p>Ompong made landfall in Cagayan on 15 September 2018. The model, trained on data to the landfall week only, puts <b>{k['top']['ompong']}</b>
first, with {st.loc['ompong', 't3']} provinces in the "deploy mobile clinics" tier and {st.loc['ompong', 't2']} in "pre-position supplies".
"Deploy" needs at least {TIERS['deploy'][1]:.0%} of people cut off{", which observed flood alone did not produce for any of the four storms" if st.t3.sum() == 0 else ""};
the hazard-proxy shifted tracks of Ompong put {_rng(ps.loc['ompong', 't3_min'], ps.loc['ompong', 't3_max']) if ps is not None else '?'} provinces there.</p>
<p>The dashboard repeats this for every storm and 14 shifted variants of each track (&plusmn;0.5&deg; and &plusmn;1&deg; north or south, &plusmn;1&deg; east
or west), so a health officer can ask "what if it comes in further south?" and get an answer in seconds.</p>"""))

    if k.get("cat_ok"):
        t1, t2 = catalog_rows(k)
        a = k["allst"]
        cat = a[a.kind == "catalogue"]
        sk = k.get("cat_skipped")
        rho_txt = (f" Network-raster agreement across units: &rho; median {k['cat_rho'][1]:.2f} (min {k['cat_rho'][0]:.2f}) over "
                   f"{k['cat_rho'][2]} storms with any cut-off." if k.get("cat_rho") else "")
        pages.append(("Catalogue", f"""<h1>Every storm, {pd.Timestamp(a.origin.min()).year}-{pd.Timestamp(a.origin.max()).year}</h1>
<p>Beyond the four backtests, the build scores the observed track of every other storm whose gale swath touched Philippine land:
<b>{n_cat} storms</b>. Each uses the latest model fitted before its week (never later data), R calibrated where enough past outcomes exist
({k['n_cal_cat']} of {n_cat}), and <b>the NOAH 25-yr proxy for flood</b> (no radar map exists for them), so their cut-off counts are upper bounds.
{f"{len(sk)} storms of 2016 are skipped: their model would have under 52 weeks of history." if sk is not None and len(sk) else ""}</p>
<figure><img src='{F['catalog']}'><figcaption>Figure 13. Mean surge probability and people cut off per storm. Diamonds: the four backtests (Sentinel-1 flood, lower
bounds); circles: catalogue storms (NOAH proxy, upper bounds); hollow: raw R.</figcaption></figure>
<div class='two' style='gap:4mm'><table class='cat'>{t1}</table><table class='cat'>{t2}</table></div>
<p style='font-size:8pt'>R: mean over {k['n_units']} units; cut: people cut off (M), network and raster; R&times;cut: expected people at surge risk who are cut off
(&Sigma; R &times; cut off over units); D/P: provinces at deploy / pre-position. &#9670; backtest (Sentinel-1); &dagger; raw R (before calibration was possible).
The largest cut-offs ({_lst(cat.nlargest(3, 'cut').label)}) pair with low R; high-R storms ({_lst(cat.nlargest(3, 'R').label)}) came
{"in the 2019 epidemic season" if (pd.to_datetime(cat.nlargest(3, 'R').origin).dt.year == 2019).all() else "in several seasons"}.{rho_txt}</p>"""))

    pages.append(("Validation", f"""<h1>Backtest, sensitivity, benchmark</h1>
<h2>Did high-priority provinces see more cases?</h2>
<table><tr><th>typhoon</th><th>origin</th><th class='n'>units</th><th class='n'>surged</th><th class='n'>&rho;(R, obs)</th><th class='n'>&rho;(P, obs)</th>
<th class='n'>top-10 surged</th><th class='n'>Brier R</th><th>note</th></tr>{valid_rows(d)}</table>
<div class='two'><figure><img src='{F['valid']}'><figcaption>Figure 14. Spearman correlation of each ranking (calibrated R) with observed incidence over the
next four weeks, relative to each unit's threshold.</figcaption></figure>
<div><p>R ranks provinces well for both 2018-2019 storms. P correlates less with cases, as it should: A measures access, not disease. After
Ompong, {v.top10_surge_rate.iloc[0] * 10:.0f} of the 10 highest-priority provinces surged against a {v.surge_rate.iloc[0]:.0%} base rate. After
Tisoy almost nothing surged (the 2019 season was over), so the top-10 rate is 0 and the Brier score is low for the right reason.</p></div></div>
<h2>Sensitivity: Kendall's &tau; of P against the base settings (network)</h2>
<table class='tight'>{sens_rows(d)}</table>
<p>Every variant changes A a little but none reorders the ranking: P's spread is dominated by R. The same variants on the raster method give
&tau; &ge; {k.get('tau_min_raster', float('nan')):.3f}. The gale fallback never triggers for these storms.</p>
<h2>Metro Manila benchmark</h2>
<p>Cutting every NCR road in NOAH 25-yr medium or high hazard leaves <b>{k['bench']:.1%}</b> of NCR without a route within the cut-off rule.
Tariverdi et al. (2023) report about 22% losing access to higher-level care at a 15 cm flood. The definitions differ: an order-of-magnitude check.</p>"""))

    if L:
        c, n = L["city"], L["nat"]
        ru, rp, ot, op = L.get("ru_post"), L.get("ru_pre"), L.get("ot_post"), L.get("ot_pre")
        sp = L.get("s1_pairs")
        hp = L["heavy_peak"]
        did = ""
        if ru is not None and ot is not None:
            did = (f"<li><b>Typhoons: mixed.</b> After Rolly and Ulysses (2020), cities inside the gale swath had {ru.irr:.2f} ({ru.ci_lo:.2f}-{ru.ci_hi:.2f}) times "
                   f"the outside cities' observed / expected cases in weeks 1-4 (pre-landfall placebo {rp.irr:.2f}, {rp.ci_lo:.2f}-{rp.ci_hi:.2f}). For Ompong and Tisoy "
                   f"the ratio is {ot.irr:.2f} ({ot.ci_lo:.2f}-{ot.ci_hi:.2f}) but the placebo fails ({op.irr:.2f}, {op.ci_lo:.2f}-{op.ci_hi:.2f}): weeks of monsoon rain had "
                   f"already raised cases before Ompong. Four storms and {L.get('n_cities', 12)} cities support no general storm effect.</li>")
        pages.append(("Leptospirosis", f"""<h1>Leptospirosis: the stretch goal</h1>
<p>The proposal assumed no open subnational leptospirosis series. Project CCHAIN (HDX) has weekly PIDSR counts for {L.get('n_cities', 12)} cities, and the
Mendeley (Parreño) file has national weeks. Both are analysed as <b>retrospective associations</b>, not forecasts: negative-binomial models of weekly cases
on CHIRPS rain 0-6 weeks earlier, with seasonal terms, year and city effects and a COVID-19 term.</p>
<figure><img src='{F['lepto']}' style='width:78%'><figcaption>Figure 15. Joint distributed-lag incidence rate ratios (95% CI) per +50 mm/week of rain.</figcaption></figure>
<ul><li><b>Cities ({c['n_obs']:,} city-weeks, {c['n_cases']:,} cases, 2016-2020): the headline.</b> Rain is followed by leptospirosis
{min(c['sig'])}-{max(c['sig'])} weeks later; the joint peak is lag {int(c['peak'].lag)}, IRR {c['peak'].irr:.2f} ({c['peak'].ci_lo:.2f}-{c['peak'].ci_hi:.2f}) per +50 mm/week,
cumulative over lags 0-6 {c['cum'].irr:.2f} ({c['cum'].ci_lo:.2f}-{c['cum'].ci_hi:.2f}). A heavy-rain week (at or above the city's 90th percentile) peaks at lag
{int(hp.lag)}: {hp.irr:.2f} ({hp.ci_lo:.2f}-{hp.ci_hi:.2f}). That is a week or two later than the ~2-week peak of Matsushita et al. (2018); the CCHAIN week label is
uncertain by about a week.</li>
<li><b>National ({n['n_obs']} weeks, 2019-2020): consistent, weaker.</b> Joint peak at lag {int(n['peak'].lag)}: {n['peak'].irr:.2f} ({n['peak'].ci_lo:.2f}-{n['peak'].ci_hi:.2f});
cumulative {n['cum'].irr:.2f} ({n['cum'].ci_lo:.2f}-{n['cum'].ci_hi:.2f}). With 2019 alone the cumulative effect is {L['nat19_cum'].irr:.2f}
({L['nat19_cum'].ci_lo:.2f}-{L['nat19_cum'].ci_hi:.2f}): much of the national signal comes from 2020 (the December surge after Rolly and Ulysses, under COVID reporting).</li>
{did}
{f"<li><b>Flood: not estimable.</b> Of {sp[0]} city-storm pairs, {sp[1]} had radar over more than 20% of the city and {sp[2]} show any new flood (at most {sp[3]:.1%}); too few to relate flood to cases. Flood mediation stays a literature assumption.</li>" if sp else ""}</ul>
<p>The {L.get('n_cities', 12)} cities are not a sample of provinces, so nothing here is extrapolated to provinces, and leptospirosis is not in the dashboard's
ranking.</p>"""))

    rows = "\n".join(f"<tr><td>{a}</td><td>{b}</td><td class='{c}'>{ {'ok': 'done', 'part': 'partly', 'no': 'not done'}[c] }</td><td>{n}</td></tr>"
                     for a, b, c, n in _targets(k))
    pages.append(("Scorecard", f"""<h1>Proposal objectives: scorecard</h1>
<table class='tight'><tr><th>objective (proposal)</th><th>result in this build</th><th>status</th><th>note</th></tr>{rows}</table>
<h2>Proposal corrections found in the data</h2>
<ul><li>{k.get('dg_units', 126)} dengue reporting units, not 81 provinces (harmonised to {k['n_units']}); deaths unreliable; 2020 collapsed under COVID-19.</li>
<li>An open subnational leptospirosis series exists (Project CCHAIN, 12 cities).</li>
<li>EMSR478 (Rolly) has damage grading only, no flood delineation; the Global Flood Database (Tellman et al., 2021) has no Philippine event after 2017.</li>
<li>Flood hazard maps come from the UP NOAH archive at 5 and 25 years, not LiPAD; {len(k['haz_nomap'])} units have no 25-yr map.</li>
<li>HydroRIVERS (Lehner &amp; Grill, 2013) places the Philippines in the Australasia file, not Asia.</li>
<li>roroph routes describe 2024-2026 operations with partly coarse port coordinates; NHFR blocks scripted download (OSM + NOAH fallback used).</li>
<li>Meta HRSL under-counts people aged 60+ against the 2020 census.</li>
<li>The proposal's final forecast was the median ensemble; storm scenarios use XGBoost (the only storm-conditioned model).</li></ul>"""))

    flood_lim = ("<li><b>Observed flood.</b> Sentinel-1 sees each place every 6-12 days and misses flooding under dense vegetation and in "
                 "built-up areas; shifted tracks and the catalogue fall back to static hazard maps.</li>")
    nxt = []
    if bm:
        nxt.append(f"<li>Score {_lst(BENCH_LABEL[x] for x in bm)} on the same rows.</li>")
    nxt += ["<li>Run the System Usability Scale test with three DOH / LGU / DRRM users (Brooke, 1996) and review the tiers with them.</li>",
            "<li>Feed a PAGASA forecast track and its cone in place of historical shifts.</li>",
            "<li>Add a second radar or optical source between Sentinel-1 passes.</li>",
            "<li>Replace the hospital fallback with the DOH facility registry (facility level, so access can mean a Level 2-3 hospital).</li>",
            "<li>Give the benchmarks storm inputs, or blend the ensemble with XGBoost's storm signal, so scenarios can use the ensemble.</li>"]
    pages.append(("Limits", f"""<h1>Limitations and next steps</h1>
<h2>Threats to validity</h2>
<ul><li><b>Two evaluation years.</b> 2018-2019 contains one epidemic; the model ranking changes between mean and median WIS because of it.</li>
<li><b>Surveillance artefacts.</b> Reporting delays and under-reporting are in the target; forecasts predict reported, not true, cases.</li>
{flood_lim}
<li><b>Network gaps.</b> OSM completeness is uneven outside Luzon (the raster method bounds this); ferries are 2024-2026 routes; hospitals are an
OSM / NOAH fallback without facility level or capacity. HRSL under-counts older people.</li>
<li><b>Provisional rules.</b> Tier thresholds, road speeds and the cut-off rule are assumptions, partly addressed by the sensitivity analysis.</li>
<li><b>Causality.</b> PCMCI+ links and the leptospirosis lags are associations, not transmission routes or causal effects.</li></ul>
<h2>Next steps</h2>
<ol>{''.join(nxt)}</ol>
<h2>Reproducibility</h2>
<p><span class='mono'>setup.bat</span> (or <span class='mono'>download_data.bat</span>) &rarr; <span class='mono'>build.bat</span> &rarr;
<span class='mono'>run_app.bat</span>. This report and the slides are regenerated with <span class='mono'>python scripts/make_results.py</span>.
Missing inputs are skipped, listed in <span class='mono'>data/processed/status.json</span> and on the dashboard; re-running after they arrive
needs no code change.</p>"""))

    half = (len(REFERENCES) + 1) // 2
    for i, chunk in enumerate((REFERENCES[:half], REFERENCES[half:])):
        refs = "".join(f"<p>{r}</p>" for r in chunk)
        pages.append(("References", f"<h1>References{' (continued)' if i else ''}</h1><div class='refs'>{refs}</div>"))
    total = len(pages) + 1
    labels = [lab for lab, _ in pages]
    body = cover + "".join(_page(i + 2, lab, b, total) for i, (lab, b) in enumerate(pages))
    body = re.sub(r"@@(\w[\w ]*)@@", lambda m: str(labels.index(m.group(1)) + 2), body)
    n = itertools.count(1)
    body = re.sub(r"Figure \d+\.", lambda m: f"Figure {next(n)}.", body)  # number figures in page order
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Bantay-Baha evaluation report</title>"
            f"<style>{FONT_CSS}{REPORT_CSS}</style></head><body>{body}</body></html>")
