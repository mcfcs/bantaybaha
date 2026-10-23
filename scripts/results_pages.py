"""HTML for the evaluation report (A4). Used by scripts/make_results.py; the deck is in scripts/results_slides.py."""

from bantay.config import STORMS
from bantay.scenarios import TIERS

from make_results import (FONT_CSS, REFERENCES, fmt_m, storm_rows, eval_rows, edge_rows, sens_rows, valid_rows,
                          source_rows)

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
h2 { font-family: "Big Shoulders Display"; font-weight: 700; text-transform: uppercase; font-size: 14pt; margin: 5mm 0 1.5mm; color: var(--teal);
     letter-spacing: .03em; }
p, li { font-size: 9.4pt; line-height: 1.42; margin: 0 0 2.2mm; }
ul, ol { padding-left: 5mm; margin: 0 0 2mm; }
table { font-size: 8.2pt; margin: 2mm 0 3mm; }
th { font-size: 6.8pt; color: var(--grey); border-bottom: 1.5px solid var(--ink); }
tr.tot td { font-weight: 700; border-top: 1.5px solid var(--ink); }
tr.pend td { color: var(--grey); font-style: italic; }
figure { margin: 2mm 0 3mm; }
figure img { width: 100%; display: block; }
figcaption { font-size: 7.8pt; color: var(--grey); margin-top: 1mm; font-style: italic; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 3mm 0; }
.kpi { background: var(--mist); border-top: 3px solid var(--teal); padding: 3mm; }
.kpi b { display: block; font-family: "Big Shoulders Display"; font-weight: 800; font-size: 24pt; line-height: 1; }
.kpi span { font-size: 7.4pt; color: var(--grey); }
.kpi.warn { border-top-color: var(--amber); }
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


def _targets(k):
    e = k["ev"]
    return [
        ("Province-week panel, 2016-2020, joined on PSGC", f"{k['n_units']} harmonised units x {k['n_weeks']} weeks; dengue, rain, river, storms, NOAH, Sentinel-1", "ok" if k["s1_ok"] else "part", "" if k["s1_ok"] else "Sentinel-1 flood fraction pending (GEE)"),
        ("Lead-lag graph, sentinels, communities; test sentinel features out of sample", f"PCMCI+ with FDR: {k['ll_edges']} links; ablation run", "ok", f"result is null (graph / no-graph {k['relwis_graph']:.3f})"),
        ("Relative WIS below 1.0 vs seasonal-naive, 2018-2019", f"{k['relwis']:.3f} overall, {e.iloc[3]['relWIS xgb/naive']:.2f} at 4 weeks", "ok", ""),
        ("90% interval coverage of 80-95%", f"{k['cov90']:.3f} overall; {e.iloc[3]['cov90 xgb']:.2f}-{e.iloc[0]['cov90 xgb']:.2f} by horizon", "ok", ""),
        ("Access loss per municipality, two methods, four typhoons", f"network method, {k['n_adm3']:,} municipalities, 4 storms", "part", "raster (friction) method not wired in yet"),
        ("Sensitivity bounds; Metro Manila benchmark", f"9 variants, &tau; &ge; {k['tau_min']:.2f}; NCR {k['bench']:.0%} vs ~22%", "ok", ""),
        ("Dashboard for any historical or shifted track in under a minute", f"{k['n_scen']} pre-computed scenarios; loads in about 6 s", "ok", ""),
        ("System Usability Scale from three target users", "not done", "no", "needs the user sessions"),
        ("Foundation-model benchmarks (Chronos-2, TabPFN-TS)", "Chronos-2 script written, not run", "no", "needs the torch install"),
    ]


def report_html(d, k, F):
    e, st, v = k["ev"], k["storm_tab"], d["valid"]
    s1, ems = k["s1_ok"], k.get("ems")
    pending = ([] if s1 else ["Sentinel-1 observed flood masks (Earth Engine job written, not run)"]) + [
        "the MAP friction raster access method (data on disk, not wired into the scenarios)",
        "the DOH NHFR hospital list and PSA PSGC (manual downloads)", "the Chronos-2 / TabPFN-TS benchmarks"]
    cover = f"""<section class='page cover'><div class='hatch'></div><div class='bar'></div><div class='inner'>
<span class='tag'>Evaluation report / build of 24 Oct 2026</span>
<h1>Bantay-<br>Baha</h1>
<div class='sub'>Flood-linked dengue surge risk and storm-driven loss of hospital access, ranked by province for any typhoon track.
Results of the full pipeline run on {k['n_files']} verified source files.</div></div>
<div class='meta'>PJDSC 2026</div></section>"""

    pages = []
    pages.append(("Summary", f"""<h1>What we built,<br>what the data says</h1>
<p>Bantay-Baha joins three graphs into one ranking: a flood-exposure layer (rain, river routing, flood hazard), a lead-lag outbreak graph
learned with PCMCI+, and a road-plus-ferry access graph that a typhoon cuts. A quantile forecast of dengue gives the probability
<b>R</b> that a province's next four weeks exceed its usual bad month; the access model gives the share <b>A</b> of people cut off from a
hospital; priority is <b>P = R &times; A</b>. Every number below was computed by <span class='mono'>build.bat</span> from the raw files;
nothing is synthetic.</p>
<div class='kpis'>
<div class='kpi'><b>{k['relwis']:.2f}</b><span>relative WIS vs seasonal-naive, 1-4 weeks (target below 1)</span></div>
<div class='kpi'><b>{k['cov90']:.0%}</b><span>90% interval coverage (target 80-95%)</span></div>
<div class='kpi warn'><b>{k['ll_edges']}</b><span>PCMCI+ lead-lag links among {k['ll_N']} provinces (cross-correlation: {k['xc_edges']:,})</span></div>
<div class='kpi'><b>{k['n_scen']}</b><span>pre-computed scenarios (4 typhoons x 15 tracks)</span></div></div>
<h2>Findings</h2>
<ul>
<li><b>The forecast beats the bar.</b> Pooled multi-quantile XGBoost reaches relative WIS {e.iloc[0]['relWIS xgb/naive']:.2f} at one week and
{e.iloc[3]['relWIS xgb/naive']:.2f} at four weeks over {k['n_scored']:,} rolling-origin forecasts in 2018-2019; 90% intervals cover {k['cov90']:.0%}.</li>
<li><b>Two honest null results.</b> Lead-lag graph features do not improve the forecast (relative WIS graph / no-graph = {k['relwis_graph']:.3f}),
and adding rain, river, storm and flood features moves relative WIS from {k['relwis_noenv']:.3f} to {k['relwis']:.3f}
(ratio {k['relwis_env']:.3f}). At 1-4 weeks, recent cases and the season carry the skill.</li>
<li><b>Surge probability is informative but under-confident.</b> Brier {k['brier']:.3f} vs {k['brier_clim']:.3f} for the base rate; forecasts of
0.1-0.7 come true 10-20 points more often. It needs recalibration before the tier thresholds are trusted.</li>
<li><b>The ranking points at the right places.</b> Spearman(R, observed next-4-week incidence) = {v.spearman_R_obs.iloc[0]:.2f} for Ompong and
{v.spearman_R_obs.iloc[1]:.2f} for Tisoy; {v.top10_surge_rate.iloc[0] * 10:.0f} of Ompong's top-10 provinces by priority surged against a
{v.surge_rate.iloc[0]:.0%} base rate.</li>
<li><b>Access loss is large and robust to settings.</b> The typhoons' gale swaths cancel {int(st.ferries.min())}-{int(st.ferries.max())} of 108 RoRo routes
and cut off {fmt_m(st.cut.min())}-{fmt_m(st.cut.max())} people (roads cut by {k['src_obs']}); Kendall's &tau; of the ranking under nine setting
changes is at least {k['tau_min']:.2f}.</li></ul>
<div class='note'><b>Not yet in these results:</b> {'; '.join(pending)}. See the scorecard (page {13 if s1 else 12}).</div>
<figure><img src='{F['timeline']}'><figcaption>Figure 1. The forecast target: DOH-Epi weekly dengue summed over the 85 harmonised units, with the
four backtest typhoons. 2020 is used for access scenarios only.</figcaption></figure>"""))

    pages.append(("Data", f"""<h1>Data and acquisition</h1>
<p>{k['n_files']} files from {k['n_sources']} sources ({k['gb']:.1f} GB) are listed in <span class='mono'>data/raw/MANIFEST.csv</span> with size and
sha256; all were verified on disk before this build. Open sources come from <span class='mono'>scripts/download_data.py</span>, Earth Engine
sources from <span class='mono'>scripts/download_gee.py</span>, and the team shares them through a private bucket (<span class='mono'>setup.bat</span>,
every file checked against the manifest).</p>
<table><tr><th>folder</th><th>dataset</th><th>role</th><th>from</th><th class='n'>files</th><th class='n'>MB</th></tr>
{source_rows(d)}</table>"""))

    pages.append(("Panel", f"""<h1>Step 0: one unit-week table</h1>
<h2>Harmonised units</h2>
<p>The DOH file has <b>126 reporting units, not 81 provinces</b>: provinces mixed with 45 highly urbanised and component cities, plus
misspellings (NUEVA VISCAYA, SISQUIJOR, BASILIG CITY = Bislig). COD-AB uses current boundaries (Maguindanao split in 2022, Special
Geographic Area in 2024). The reviewed crosswalk in <span class='mono'>data/crosswalks/</span> folds cities into their province and undoes
the post-2020 changes, giving <b>{k['n_units']} units</b>; all 126 dengue units resolve and every unit has data. A unit-week counts only if
every member reported (NaN otherwise, never 0).</p>
<h2>Population</h2>
<p>The 2020 census table's municipal codes are old 9-digit PSGC and do not join to COD-AB for 54 municipalities (24.2 M people). Its
own <i>Province</i> column already places cities in their province, so units are summed on it: {k['pop'] / 1e6:.2f} M people.</p>
<div class='two'><figure><img src='{F['coverage']}'><figcaption>Figure 2. Coverage of the {k['n_units']} x {k['n_weeks']} panel. {"Sentinel-1 is filled only for the four landfall windows (4 weeks each), by design." if s1 else "Sentinel-1 is the only empty input."}</figcaption></figure>
<div><h2>Layer 1 inputs</h2><p>Rain: CHIRPS and IMERG agree (weekly r = {k['rain_r']:.2f}). River routing accumulates CHIRPS rain down the
HydroRIVERS network. NOAH 25-yr hazard covers {k['haz_units']} of {k['n_units']} units; the median unit has {k['haz_median']:.0%} of its people in a
hazard zone. Units with no map are <b>missing, not zero</b>: {', '.join(k['haz_nomap'])}.</p>
<p>Storm exposure: every Western Pacific track 2016-2020 from IBTrACS, gale radius from USA R34, else JMA R30, else a fixed 150 km (the
fallback never triggered for the four backtest storms).</p></div></div>"""))

    pages.append(("Methods", f"""<h1>Methods and evaluation protocol</h1>
<h2>Layer 2: lead-lag outbreak graph</h2>
<p>log(1 + incidence), 52-week seasonal difference, standardised inside the training window. PCMCI+ (Runge, 2020) with partial-correlation
tests, lags 1-3 weeks, pc_alpha 0.01; lagged inter-province edges are kept when the Benjamini-Hochberg (1995) q-value is below 0.05. The
FDR step matters: on pure noise with 85 series, PCMCI+ alone returned 60-90 false edges. PageRank (Page et al., 1999) on the reversed graph
scores sentinels; Louvain (Blondel et al., 2008) finds communities; lagged cross-correlation with the same FDR is the baseline graph.</p>
<h2>Forecast</h2>
<p>One pooled XGBoost (Chen &amp; Guestrin, 2016) per horizon (1-4 weeks) with the multi-quantile objective at the 23 CDC FluSight levels, on
log(1 + incidence), back-transformed to cases. Features: lagged incidence and moving averages, same week last year, week of year,
CHIRPS / IMERG / river rain lags, storm exposure, NOAH hazard, and leader signals from the graph. SHAP values (Lundberg &amp; Lee, 2017) from
the median model give the dashboard's "drivers". A second model predicts the 4-week cumulative incidence directly; <b>R</b> is its
probability of exceeding the unit's 90th percentile of 4-week incidence in the training window.</p>
<h2>Evaluation</h2>
<p><b>Rolling origin, never a random split.</b> From January 2018 to December 2019 the model, the lead-lag graph and the surge thresholds
are refit every 13 weeks on data up to the refit date only, then forecast every origin until the next refit. Training targets never pass
the refit date and 2020 is never a target. Scores: weighted interval score on case counts (Bracher et al., 2021), relative WIS against a
seasonal-naive forecast with empirical error quantiles, 50% and 90% coverage, and an online conformal 90% band built from past errors only
(Gibbs &amp; Candès, 2021) as a check on the quantiles.</p>
<h2>Layer 3: access</h2>
<p>OSM highways (motorway to track) become a graph of junctions; RoRo routes are ferry edges (crossing time plus half the headway);
hospitals are HOT OSM plus NOAH name-matched facilities ({k['n_hosp']:,}) until NHFR arrives. WorldPop (Tatem, 2017) is summed to 1 km cells,
each joined to the nearest road node. A multi-source Dijkstra gives hours to the nearest hospital. A storm cancels ferry routes crossing
its gale swath and cuts roads in observed flood (Sentinel-1, observed tracks) or, for shifted tracks, cuts (high hazard) or slows
(medium) roads in NOAH 25-yr hazard inside the swath.
A cell is cut off if it loses its route, or its trip at least doubles and grows by more than an hour (after Petricola et al., 2022).</p>"""))

    pages.append(("Forecast", f"""<h1>Forecast skill</h1>
<table><tr><th>horizon</th><th class='n'>n</th><th class='n'>WIS xgb</th><th class='n'>WIS no-graph</th><th class='n'>WIS naive</th>
<th class='n'>rel WIS</th><th class='n'>graph / no-graph</th><th class='n'>cov 50</th><th class='n'>cov 90</th><th class='n'>cov 90 conformal</th></tr>
{eval_rows(k)}</table>
<figure><img src='{F['wis']}'><figcaption>Figure 3. Left: mean WIS by horizon (labels: relative WIS vs seasonal-naive). Right: coverage against the
nominal 50% and 90% lines and the proposal's 80-95% band.</figcaption></figure>
<p><b>Targets met.</b> Relative WIS is below 1 at every horizon ({e.iloc[0]['relWIS xgb/naive']:.2f} to {e.iloc[3]['relWIS xgb/naive']:.2f}) and 90%
coverage is inside 80-95% at every horizon (four weeks is close to the floor at {e.iloc[3]['cov90 xgb']:.2f}). The 50% intervals are a little narrow
({e.iloc[3]['cov50 xgb']:.2f}-{e.iloc[0]['cov50 xgb']:.2f}). The online conformal band reaches similar coverage, a sign the quantiles are not badly
miscalibrated.</p>
<figure><img src='{F['fan']}'><figcaption>Figure 4. Rolling-origin forecasts for Cagayan (Ompong's landfall province, dashed line), one and four weeks
ahead.</figcaption></figure>"""))

    pages.append(("Ablation", f"""<h1>Ablations and calibration</h1>
<h2>What carries the skill</h2>
<table><tr><th>comparison</th><th class='n'>relative WIS</th><th>reading</th></tr>
<tr><td>XGBoost vs seasonal-naive</td><td class='n'>{k['relwis']:.3f}</td><td>{1 - k['relwis']:.0%} lower WIS than "same week last year"</td></tr>
<tr><td>with vs without graph leader features</td><td class='n'>{k['relwis_graph']:.3f}</td><td>no gain: the graph has 0 links in every 2018 window and 2-6 in 2019</td></tr>
<tr><td>with vs without rain / river / storm / flood features</td><td class='n'>{k['relwis_env']:.3f}</td><td>{k['relwis']:.3f} vs {k['relwis_noenv']:.3f} against seasonal-naive, same rows</td></tr></table>
<p>The graph ablation follows from the graph itself: with so few significant links, leader signals are empty for most provinces. The rain
result has two likely reasons, not yet tested: rain moves with the season in a four-year panel, so the season features already carry it, and
any effect of rain at lags longer than four weeks is outside this forecast horizon. Both are reported as findings rather than tuned away.</p>
<div class='two'><figure><img src='{F['rel']}'><figcaption>Figure 5. Reliability of R over the 2018-2019 unit-weeks. Points above the diagonal:
R is under-confident.</figcaption></figure>
<div><h2>Surge probability R</h2><p>Brier score {k['brier']:.3f} against {k['brier_clim']:.3f} for always predicting the base rate. The base rate is
{k['base_rate']:.0%}, not 10%, because 2019 was an epidemic year and the thresholds come from earlier, quieter years.</p>
<p>R is under-confident in the middle range: forecasts of 0.1-0.7 come true 10-20 points more often. Isotonic recalibration fitted on past
rolling-origin forecasts only is the next step, before the tier thresholds (R &ge; {TIERS['preposition_R']:g}, R &ge; {TIERS['deploy'][0]:g}) are relied on.</p></div></div>"""))

    pages.append(("Graph", f"""<h1>The lead-lag graph</h1>
<div class='two'><figure><img src='{F['leadlag']}'><figcaption>Figure 6. The {k['ll_edges']} PCMCI+ links learned on 2016-2019 (teal = leader).</figcaption></figure>
<div><p>Final window: {k['ll_N']} series, T = {k['ll_T']} weeks after seasonal differencing (Davao Occidental sits out with more than 10% missing
weeks). PCMCI+ keeps <b>{k['ll_edges']}</b> lagged inter-province links at q &lt; 0.05. Plain lagged cross-correlation with the same FDR keeps
<b>{k['xc_edges']:,}</b>, because the 2019 national epidemic makes almost every pair co-move.</p>
<p>The proposal's sentinel idea is therefore <b>weakly supported at province-week level</b>. The links are statistical dependencies, not
evidence of transmission, and several join distant provinces. Likely reasons: weekly province totals average out local waves, four years
is short for 84 series, and reporting artefacts dominate small provinces. Synchrony studies such as van Panhuis et al. (2015) worked at
longer time scales.</p></div></div>
<table><tr><th>leader</th><th>follower</th><th class='n'>lag (wk)</th><th class='n'>partial corr</th><th class='n'>q</th><th class='n'>bootstrap freq</th></tr>
{edge_rows(d)}</table>"""))

    if s1:
        tab = k["s1_tab"]
        rows = "".join(f"<tr><td>{STORMS[kk]['local']}</td><td class='n'>{fmt_m(t['pop'])}</td><td class='n'>{t['units']}</td>"
                       f"<td class='n'>{t['frac_max']:.1%}</td><td>{t['top']}</td></tr>" for kk, t in tab.items())
        agree = (f"Inside the EMS areas of interest, EMS mapped {ems['ems_km2']:.0f} km&sup2; of observed flood and Sentinel-1 flagged "
                 f"{ems['s1_km2']:.0f} km&sup2;; {ems['both_km2']:.0f} km&sup2; overlap. So <b>{ems['precision']:.0%}</b> of Sentinel-1 flood there is confirmed by "
                 f"EMS, and Sentinel-1 recovers <b>{ems['recall']:.0%}</b> of the EMS area.") if ems else "EMS comparison unavailable."
        pages.append(("Flood", f"""<h1>Observed flood: Sentinel-1</h1>
<p>Radar sees through typhoon clouds. For each typhoon, new open water is mapped on Google Earth Engine (Gorelick et al., 2017) by comparing
Sentinel-1 VH backscatter before and after landfall, in 100 m tiles near the track: before = median of days -30 to -3, after = darkest image of
days 0 to +10, <b>both from the same relative orbit</b>, so the viewing geometry matches. A pixel is new flood when VH drops by at least 3 dB and ends
water-dark (at most -18 dB); permanent water (JRC), slopes over 5&deg; and specks under 8 pixels are removed (after UN-SPIDER, n.d.).</p>
<figure><img src='{F['s1']}'><figcaption>Figure 8. New-flood share of the land Sentinel-1 saw, per unit, in the landfall week, with each track.</figcaption></figure>
<table><tr><th>typhoon</th><th class='n'>people in new flood</th><th class='n'>units &gt;1% flooded</th><th class='n'>max unit share</th><th>most people flooded</th></tr>{rows}</table>
<div class='two'><figure><img src='{F['s1ems']}'><figcaption>Figure 9. Ompong around Tuguegarao: Sentinel-1 new flood (teal) and Copernicus EMS
observed flood (red outlines).</figcaption></figure>
<div><h2>Checked against Copernicus EMS</h2><p>{agree}</p>
<p>The first version followed UN-SPIDER's after/before ratio on dB values and recovered almost none of the EMS flood: dividing negative dB
values under-detects surfaces that were already dark, and mixing orbits compared different viewing geometries. Sampling backscatter at EMS flood
points showed drops of 4-10 dB that the ratio missed. Low recall is expected: EMS used other imagery and dates, while one Sentinel-1 orbit passed
here only on 16 and 22 September.</p></div></div>"""))

    pages.append(("Access", f"""<h1>Access loss under four typhoons</h1>
<p><b>Baseline.</b> {k['cells_pop'] / 1e6:.1f} M people in 1 km cells; {k['route_share']:.1%} have a road or ferry route to one of {k['n_hosp']:,} hospitals, with a
population-weighted mean trip of {k['mean_hours']:.2f} h. Results are also written for {k['n_adm3']:,} municipalities.</p>
<table><tr><th>typhoon</th><th class='n'>ferry routes cut</th><th class='n'>people cut off</th><th class='n'>mean A</th><th class='n'>mean R</th>
<th class='n'>deploy / pre-position</th><th>top priority</th></tr>{storm_rows(k)}</table>
<figure><img src='{F['access']}'><figcaption>Figure 7. Access loss A per unit for the observed tracks. Roads are cut by {k['src_obs']}; ferries crossing
the gale swath are cancelled.</figcaption></figure>
<div class='note'>{"Roads are cut only where Sentinel-1 saw new water, so cut-offs are storm-specific; the radar misses floods under dense vegetation and in built-up areas and between passes, so these are lower bounds. With the NOAH 25-yr hazard proxy instead (build of 24 Oct, before Sentinel-1), the same tracks cut off 4.8-10.3 M people: an upper bound. The truth lies between." if s1 else "These cut-off counts are <b>upper bounds</b>: the proxy treats every high-hazard road inside the storm's whole-lifetime gale swath as flooded."}
Ferry routes are 2024-2026 operations used as a proxy for 2018-2020. Shifted tracks always use the NOAH hazard proxy (no image of a storm that did not happen).</div>"""))

    pages.append(("Priority", f"""<h1>Priority: Ompong 2018</h1>
<div class='two'><figure><img src='{F['priority']}'><figcaption>Figure 8. P = R x A for Ompong with its track and gale swath; top 5 labelled.</figcaption></figure>
<figure><img src='{F['scatter']}'><figcaption>Figure 9. Risk vs access. Dotted lines are the provisional tier thresholds (R = {TIERS['preposition_R']:g}, A = {TIERS['deploy'][1]:.0%}); marker
shape encodes the action tier.</figcaption></figure></div>
<p>Ompong made landfall in Cagayan on 15 September 2018. The model, trained on data to the landfall week only, puts <b>{k['top']['ompong']}</b>
first, with {st.loc['ompong', 't3']} provinces in the "deploy mobile clinics" tier and {st.loc['ompong', 't2']} in "pre-position supplies".
Provinces with high R but little observed loss of access fall to "pre-position"; "deploy" needs at least {TIERS['deploy'][1]:.0%} of people cut off, which
observed flood alone did not produce for this storm (the hazard-map upper bound did, for 7 provinces).</p>
<p>The dashboard repeats this for every storm and 14 shifted variants of each track (&plusmn;0.5&deg; and &plusmn;1&deg; north, &plusmn;1&deg; east), so a
health officer can ask "what if it comes in further south?" and get an answer in seconds.</p>"""))

    pages.append(("Validation", f"""<h1>Backtest, sensitivity, benchmark</h1>
<h2>Did high-priority provinces see more cases?</h2>
<table><tr><th>typhoon</th><th>origin</th><th class='n'>units</th><th class='n'>surged</th><th class='n'>&rho;(R, obs)</th><th class='n'>&rho;(P, obs)</th>
<th class='n'>top-10 surged</th><th class='n'>Brier R</th><th>note</th></tr>{valid_rows(d)}</table>
<div class='two'><figure><img src='{F['valid']}'><figcaption>Figure 10. Spearman correlation of each ranking with observed incidence over the next
four weeks (relative to each unit's threshold).</figcaption></figure>
<div><p>R ranks provinces well for both 2018-2019 storms. P correlates less with cases, as it should: A measures access, not disease. After
Ompong, {v.top10_surge_rate.iloc[0] * 10:.0f} of the 10 highest-priority provinces surged against a {v.surge_rate.iloc[0]:.0%} base rate. After
Tisoy almost nothing surged (the 2019 season was over), so the top-10 rate is 0 and the Brier score is low for the right reason.</p></div></div>
<h2>Sensitivity: Kendall's &tau; of P against the base settings</h2>
<table>{sens_rows(d)}</table>
<p>Every variant changes A (speed &plusmn;20% moves mean A by about 4%) but none reorders the ranking: P's spread is dominated by R, which ranges
0.02-0.93 across provinces. The gale fallback never triggers for these storms.</p>
<h2>Metro Manila benchmark</h2>
<p>Cutting every NCR road in NOAH 25-yr medium or high hazard leaves <b>{k['bench']:.1%}</b> of NCR without a route within the cut-off rule.
Tariverdi et al. (2023) report about 22% losing access to higher-level care at a 15 cm flood. The definitions differ, so this is an
order-of-magnitude check, not a replication.</p>"""))

    rows = "\n".join(f"<tr><td>{a}</td><td>{b}</td><td class='{c}'>{ {'ok': 'met', 'part': 'partly', 'no': 'not yet'}[c] }</td><td>{n}</td></tr>"
                     for a, b, c, n in _targets(k))
    pages.append(("Scorecard", f"""<h1>Proposal objectives: scorecard</h1>
<table><tr><th>objective (proposal)</th><th>result</th><th>status</th><th>note</th></tr>{rows}</table>
<h2>Proposal corrections found in the data</h2>
<ul><li>126 dengue reporting units, not 81 provinces; deaths unreliable (2016 case fatality 3.9%); 2020 collapsed under COVID-19.</li>
<li>An open subnational leptospirosis series exists (Project CCHAIN, 12 cities, 2008-2022).</li>
<li>EMSR478 (Rolly) has damage grading only, no flood delineation; the Global Flood Database (Tellman et al., 2021) ends in 2018.</li>
<li>Flood hazard maps come from the UP NOAH archive, not LiPAD; 11 units have no 25-yr map.</li>
<li>HydroRIVERS (Lehner &amp; Grill, 2013) places the Philippines in the Australasia file, not Asia.</li>
<li>IBTrACS (Knapp et al., 2010) USA R34 is missing on up to 58% of fixes of the backtest storms; JMA R30 fills the gaps.</li>
<li>roroph routes describe 2024-2026 operations with partly coarse port coordinates.</li></ul>"""))

    flood_lim = ("<li><b>Observed flood.</b> Sentinel-1 sees each place every 6-12 days and misses flooding under dense vegetation and in "
                 "built-up areas; shifted tracks fall back to static hazard maps.</li>" if s1 else
                 "<li><b>Flood proxy.</b> Until Sentinel-1 runs, storm road cuts come from static hazard maps, so A is an upper bound and similar "
                 "for any storm crossing the same hazard zones.</li>")
    s1_next = ("<li>Add a second radar or optical source between Sentinel-1 passes and compare observed-flood A with the hazard proxy.</li>" if s1 else
               "<li>Run the Sentinel-1 flood puller (code ready; Google Earth Engine, Gorelick et al., 2017) and rebuild.</li>")
    pages.append(("Limits", f"""<h1>Limitations and next steps</h1>
<h2>Threats to validity</h2>
<ul><li><b>Two evaluation years.</b> 2018-2019 contains one epidemic; skill and calibration may differ in quieter or COVID-era years.</li>
<li><b>Surveillance artefacts.</b> Reporting delays and under-reporting are in the target; forecasts predict reported, not true, cases.</li>
{flood_lim}
<li><b>Network gaps.</b> OSM completeness is uneven outside Luzon; ferries are 2024-2026 routes; hospitals are an OSM / NOAH fallback without
facility level or capacity.</li>
<li><b>Provisional rules.</b> Action-tier thresholds, road speeds and the cut-off rule are assumptions, partly addressed by the sensitivity
analysis.</li>
<li><b>Causality.</b> PCMCI+ links are conditional dependencies, not transmission routes.</li></ul>
<h2>Next steps</h2>
<ol>{s1_next}
<li>Wire in the MAP friction raster method (Weiss et al., 2020) and report the network-vs-raster gap per province.</li>
<li>Recalibrate R and review the tiers with DOH and LGU users; run the System Usability Scale test.</li>
<li>Replace the hospital fallback with NHFR; validate pcodes against PSGC 2Q 2026.</li>
<li>Run the Chronos-2 benchmark (Ansari et al., 2025); extend to leptospirosis with the CCHAIN city series.</li></ol>
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
    body = cover + "".join(_page(i + 2, lab, b, total) for i, (lab, b) in enumerate(pages))
    import itertools
    import re

    n = itertools.count(1)
    body = re.sub(r"Figure \d+\.", lambda m: f"Figure {next(n)}.", body)  # number figures in page order
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Bantay-Baha evaluation report</title>"
            f"<style>{FONT_CSS}{REPORT_CSS}</style></head><body>{body}</body></html>")
