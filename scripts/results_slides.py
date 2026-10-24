"""HTML for the 20-slide deck (16:9). Used by scripts/make_results.py.

Shape (team feedback, 2026-10-24): more on the problem, results-led, and a future framed as deployment in the loop;
no repository-detail, null-result or to-do slides (the evaluation report keeps that detail). Revision of 2026-10-24: the
fan-chart slide and the second deployment slide made room for the storm catalogue and leptospirosis; the model
comparison, calibration, two access methods and vulnerable groups are folded into the result slides.
Every number comes from `k` (make_results.stats) or `d`; literature figures on the problem slides are cited.
"""

import pandas as pd

from bantay.config import STORMS

from make_results import FONT_CSS, REFERENCES, BENCH_LABEL, MODEL_LABEL, fmt_m, storm_rows, model_rows, bench_missing_text, _rng

SLIDE_CSS = """
@page { size: 13.333in 7.5in; margin: 0; }
.s { width: 13.333in; height: 7.5in; position: relative; overflow: hidden; page-break-after: always; background: var(--deep); color: #E6EEF2;
     padding: .62in .7in .55in .7in; }
.s:last-child { page-break-after: auto; }
.s::before { content: ""; position: absolute; inset: 0; background: repeating-linear-gradient(105deg, rgba(95,195,228,.05) 0 2px, transparent 2px 16px); }
.s > * { position: relative; }
.top { display: flex; justify-content: space-between; align-items: center; margin-bottom: .18in; }
.sig { font-family: "Space Mono"; font-size: 10pt; letter-spacing: .18em; color: var(--deep); background: var(--signal); padding: 3px 9px;
       font-weight: 600; text-transform: uppercase; }
.crit { font-family: "Space Mono"; font-size: 8.5pt; letter-spacing: .12em; color: #8FA6B4; text-transform: uppercase; border: 1px solid #2C4352;
        padding: 3px 8px; }
h1 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 46pt; line-height: .92; margin: 0 0 .16in;
     color: #FFFFFF; letter-spacing: .005em; }
h1 em { font-style: normal; color: var(--signal); }
h3 { font-family: "Big Shoulders Display"; font-weight: 700; text-transform: uppercase; font-size: 18pt; color: var(--teal-lt); margin: 0 0 .06in;
     letter-spacing: .03em; }
p, li { font-size: 16pt; line-height: 1.36; margin: 0 0 .09in; color: #DCE8EE; }
li { margin-bottom: .07in; }
ul { padding-left: .22in; margin: 0; }
b { color: #FFFFFF; }
.dim { color: #8FA6B4; }
.num { font-family: "Big Shoulders Display"; font-weight: 800; color: var(--signal); line-height: .9; }
.card { background: #FFFFFF; padding: .12in; border-top: 4px solid var(--signal); }
.card img { display: block; margin: auto; max-width: 100%; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: .35in; align-items: start; }
.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: .25in; }
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: .22in; }
.g64 { display: grid; grid-template-columns: 1.55fr 1fr; gap: .35in; align-items: start; }
.g46 { display: grid; grid-template-columns: 1fr 1.45fr; gap: .35in; align-items: start; }
.stat { border-left: 3px solid var(--signal); padding-left: .14in; }
.stat .num { font-size: 50pt; }
.stat p { font-size: 13pt; color: #AFC3CE; }
.box { border: 1px solid #2C4352; padding: .16in .2in; background: rgba(15,30,40,.6); }
.box h3 { margin-bottom: .08in; }
.box p, .box li { font-size: 14pt; }
table { font-size: 12.5pt; color: #DCE8EE; }
th { color: #8FA6B4; font-size: 8.5pt; border-bottom: 1.5px solid #5B7385; }
td { border-bottom: 1px solid #22394A; padding: 4px 8px; }
td.n { color: #FFFFFF; }
.pn { position: absolute; right: .7in; bottom: .28in; font-family: "Space Mono"; font-size: 9pt; color: #5B7385; }
.brand { position: absolute; left: .7in; bottom: .28in; font-family: "Space Mono"; font-size: 9pt; color: #5B7385; letter-spacing: .12em; }
.flow { display: grid; grid-template-columns: 1fr .5in 1fr .5in 1fr; grid-template-rows: auto auto auto; row-gap: .2in; }
.flow .node { align-self: stretch; }
.arr { position: relative; align-self: center; height: 3px; background: var(--signal); }
.arr::after { content: ""; position: absolute; right: -1px; top: -6px; border-left: 11px solid var(--signal); border-top: 7.5px solid transparent;
              border-bottom: 7.5px solid transparent; }
.down { position: relative; justify-self: center; width: 3px; background: var(--signal); margin: -.2in 0; }
.down::after { content: ""; position: absolute; bottom: -1px; left: -6px; border-top: 11px solid var(--signal); border-left: 7.5px solid transparent;
               border-right: 7.5px solid transparent; }
.flow .node { border: 1.5px solid var(--teal-lt); padding: .12in .16in; min-height: 1.12in; }
.flow .node h3 { font-size: 15pt; }
.flow .node p { font-size: 12.5pt; margin: 0; color: #AFC3CE; }
.flow .node.hot { border-color: var(--signal); background: rgba(242,169,59,.08); }
.time { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; margin-top: .2in; }
.time div { border-top: 4px solid var(--teal-lt); padding: .12in .14in 0 0; }
.time div.hot { border-top-color: var(--signal); }
.time .when { font-family: "Space Mono"; font-size: 10pt; color: var(--signal); letter-spacing: .08em; }
.time h3 { font-size: 16pt; margin: .04in 0; }
.time p { font-size: 12.5pt; color: #AFC3CE; margin: 0; }
.loop { display: grid; grid-template-columns: repeat(4, 1fr); gap: .18in; }
.loop .step { border: 1.5px solid #2C4352; padding: .16in; position: relative; min-height: 2.2in; }
.loop .step .k { font-family: "Big Shoulders Display"; font-weight: 800; font-size: 34pt; color: var(--signal); line-height: 1; }
.loop .step h3 { font-size: 16pt; }
.loop .step p { font-size: 13.5pt; color: #AFC3CE; }
.refs p { font-size: 6.3pt; line-height: 1.2; margin: 0 0 .035in; padding-left: .18in; text-indent: -.18in; color: #C9D8E0; overflow-wrap: anywhere; }
.refs { column-count: 2; column-gap: .35in; }
.title h1 { font-size: 118pt; margin-top: .7in; }
.title .sub { font-size: 21pt; color: #CFE3EC; max-width: 9in; line-height: 1.25; }
.title .who { position: absolute; left: .7in; bottom: .7in; font-family: "Space Mono"; font-size: 11pt; color: #8FA6B4; line-height: 1.7; }
.title .bar { width: 1.6in; height: .12in; background: var(--signal); margin-top: .35in; }
.shot { border: 1px solid #2C4352; width: 100%; display: block; }
.small td, .small th { padding: 3px 6px; }
"""

N = 20


def _slide(n, sig, crit, body):
    sig = f"Signal {n:02d} / {sig.split(' / ', 1)[-1]}"  # tags count with the slides
    return (f"<section class='s'><div class='top'><span class='sig'>{sig}</span><span class='crit'>{crit}</span></div>{body}"
            f"<div class='brand'>BANTAY-BAHA / PJDSC 2026</div><div class='pn'>{n:02d} / {N}</div></section>")


def _img(src, h):
    return f"<div class='card'><img src='{src}' style='height:{h}in;width:auto'></div>" if src else ""


def slides_html(d, k, F):
    e, st, v = k["ev"], k["storm_tab"], d["valid"]
    s1, ems = k["s1_ok"], k.get("ems")
    al = k.get("mall")
    bp = k["bench_present"]
    cal = k.get("calib")
    L = k.get("lepto")
    S = []

    # ---------------------------------------------------------------- problem
    S.append(f"""<section class='s title'><div class='top'><span class='sig'>Signal 01</span><span class='crit'>PJDSC 2026</span></div>
<div class='bar'></div><h1>Bantay-<em>Baha</em></h1>
<div class='sub'>Early warning for flood-linked disease: which provinces will see a surge after a typhoon, and which of them will be cut off
from a hospital.</div>
<div class='grid3' style='margin-top:.55in;max-width:10.5in'>
<div class='stat'><div class='num' style='font-size:44pt'>{1 - k['relwis']:.0%}</div><p>lower forecast error than the seasonal baseline</p></div>
<div class='stat'><div class='num' style='font-size:44pt'>{v.top10_surge_rate.iloc[0] * 10:.0f} / 10</div><p>top-ranked provinces surged after Typhoon Ompong</p></div>
<div class='stat'><div class='num' style='font-size:44pt'>{int(st.ferries.max())}</div><p>ferry routes a single typhoon can close, out of {k['n_ferry']}</p></div></div>
<div class='who'>PJDSC 2026</div>
<div class='pn'>01 / {N}</div></section>""")

    S.append(_slide(2, "Signal 01 / Problem", "Rationale: problem statement", f"""<h1>Typhoons bring floods.<br>Floods bring <em>disease</em>.</h1>
<div class='grid3' style='margin-top:.1in'>
<div class='stat'><div class='num'>8-9</div><p>tropical cyclones cross the Philippines every year, mostly from July to October (PAGASA)</p></div>
<div class='stat'><div class='num'>2,089</div><p>leptospirosis cases and 162 deaths after Typhoon Ondoy in 2009, five times the national lepto deaths of 2008
(Balbuena et al., 2010)</p></div>
<div class='stat'><div class='num'>146k</div><p>dengue cases from January to July 2019, when DOH declared a national epidemic</p></div></div>
<div class='g64' style='margin-top:.18in'>{_img(F['timeline'], 2.3)}
<div class='box'><h3>Who is hit hardest</h3><p>Floodwater spreads leptospirosis within days; standing water breeds the mosquitoes behind dengue for weeks after.
The same storm closes roads and grounds ferries, so the most exposed communities are often the ones that <b>cannot reach a hospital</b>.</p></div></div>"""))

    S.append(_slide(3, "Signal 01 / The cascade", "Rationale: problem and motivation", """<h1>The response arrives <em>after</em> the surge</h1>
<p>A typhoon sets off a sequence. Each step is predictable from data that already exist, yet today's response starts only at the last one.</p>
<div class='time'>
<div><span class='when'>DAY 0</span><h3>Landfall</h3><p>Gale-force winds; ferries suspended; roads blocked by landslides and debris</p></div>
<div><span class='when'>DAYS 1-7</span><h3>Flooding</h3><p>Rivers carry upstream rain to the lowlands; towns at river mouths flood after the rain stops</p></div>
<div><span class='when'>WEEKS 1-2</span><h3>Leptospirosis</h3><p>Risk from rainfall peaks about two weeks later and runs through flooding (Matsushita et al., 2018)</p></div>
<div><span class='when'>WEEKS 2-8</span><h3>Dengue</h3><p>Breeding sites multiply; cases rise province by province</p></div>
<div class='hot'><span class='when'>TODAY</span><h3>Response</h3><p>Prophylaxis, vector control and medical teams go out after cases rise; isolated places are reached last</p></div></div>
<p style='margin-top:.16in;font-size:17pt'>What is missing is a tool that looks at <b>this</b> storm and says, before the roads close, <b>where</b> disease
will rise and <b>who</b> will be cut off.</p>
<div class='grid3' style='margin-top:.1in'>
<div class='box'><h3>Dengue forecasts exist</h3><p>Climate-driven, province-level (Buczak et al., 2014), but not for a specific storm and without honest ranges</p></div>
<div class='box'><h3>Access studies exist</h3><p>Flood access loss for one city, Metro Manila (Tariverdi et al., 2023), with no health forecast and no ferries</p></div>
<div class='box'><h3>Outbreak waves are known</h3><p>Dengue travels between regions (van Panhuis et al., 2015), but this is unused for storm response</p></div></div>"""))

    S.append(_slide(4, "Signal 01 / Access", "Rationale: problem and motivation", f"""<h1>An archipelago makes <em>access</em> the problem</h1>
<div class='g64'><div><ul>
<li><b>An island nation.</b> Many provinces reach the nearest hospital only by RoRo ferry; a gale warning cancels the crossing</li>
<li><b>Roads in floodplains.</b> The road to the provincial hospital often runs exactly where the river overflows</li>
<li><b>Measured once, for one city.</b> A 15 cm flood leaves about 22% of Metro Manila without access to higher-level care (Tariverdi et al., 2023);
nothing comparable exists nationwide, or with ferries</li></ul>
<div class='box' style='margin-top:.2in'><h3>Guiding question</h3><p>Can flood exposure, a graph of outbreak spread and a storm-disrupted transport network, combined
with calibrated forecasts, rank the provinces that need help first, early enough to act?</p></div></div>
{_img(F['network'], 4.55)}</div>"""))

    # ---------------------------------------------------------------- approach and data
    S.append(_slide(5, "Signal 02 / Design", "Methodology and approach", """<h1>Three graphs, <em>one ranking</em></h1>
<div class='flow'>
<div class='node' style='grid-area:1/1'><h3>1 / Flood exposure</h3><p>Sentinel-1 observed flood, CHIRPS + IMERG rain, rain routed down rivers, UP NOAH hazard, typhoon gale swaths</p></div>
<div class='arr' style='grid-area:1/2'></div>
<div class='node' style='grid-area:2/1'><h3>2 / Lead-lag graph</h3><p>PCMCI+ finds which provinces rise first; their recent rise feeds every follower's forecast</p></div>
<div class='arr' style='grid-area:2/2'></div>
<div class='node' style='grid-area:1/3/3/4;display:flex;flex-direction:column;justify-content:center'><h3>Quantile forecast</h3>
<p>XGBoost, 23 quantiles, 1-4 weeks ahead, tested by rolling origin against zero-shot foundation models and a graph network</p></div>
<div class='arr' style='grid-area:1/4'></div>
<div class='node hot' style='grid-area:1/5'><h3>R / surge risk</h3><p>calibrated chance the next 4 weeks beat the province's usual bad month</p></div>
<div class='down' style='grid-area:2/5'></div>
<div class='node' style='grid-area:3/1'><h3>3 / Access graph</h3><p>OSM roads + RoRo ferries + hospitals, and a friction raster as a second method; a storm cuts both</p></div>
<div class='arr' style='grid-area:3/2'></div>
<div class='node' style='grid-area:3/3'><h3>A / access loss</h3><p>share of people who lose their route to a hospital, with the range between methods</p></div>
<div class='arr' style='grid-area:3/4'></div>
<div class='node hot' style='grid-area:3/5'><h3>P = R &times; A</h3><p>ranked provinces, drivers and an action tier for a real or shifted track</p></div></div>
<p class='dim' style='margin-top:.14in;font-size:13pt'>Each half is validated on its own: forecast vs a seasonal baseline and benchmarks; access vs Metro Manila and Copernicus.</p>"""))

    mb = k.get("mbase", {})
    S.append(_slide(6, "Signal 03 / Data", "Data sources and acquisition", f"""<h1>{k['n_files']} open files, <em>{k['n_sources']} sources</em></h1>
<div class='g64'><div><table><tr><th>layer</th><th>sources</th></tr>
<tr><td>Disease</td><td>DOH-Epi dengue, province/city x week, 2016-2021 (HDX); Project CCHAIN city leptospirosis; national PIDSR; OpenDengue</td></tr>
<tr><td>People and places</td><td>2020 census; COD-AB boundaries; WorldPop 2020 100 m; Meta HRSL under-5 / 60+</td></tr>
<tr><td>Rain and rivers</td><td>CHIRPS v2.0; GPM IMERG V07; HydroRIVERS</td></tr>
<tr><td>Storms and flood</td><td>IBTrACS; Sentinel-1 radar (Google Earth Engine); UP NOAH hazard maps; Copernicus EMS</td></tr>
<tr><td>Getting to care</td><td>OpenStreetMap roads; MARINA RoRo routes (roroph); OSM and NOAH health facilities; MAP friction surface</td></tr></table>
<div class='grid3' style='margin-top:.22in'>
<div class='stat'><div class='num' style='font-size:34pt'>{k['unit_weeks']:,}</div><p>province-weeks ({k['n_units']} x {k['n_weeks']})</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>{k['n_hosp']:,}</div><p>hospitals and {k['n_ferry']} ferry routes in the access graph</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>{mb.get('cells', 0) / 1e3:,.0f}k</div><p>1 km population cells, {k['cells_pop'] / 1e6:.0f} M people</p></div></div></div>
<div>{_img(F['coverage'], 3.3)}<p class='dim' style='margin-top:.12in;font-size:13pt'>Only aggregated, non-identifiable health data.</p></div></div>"""))

    S.append(_slide(7, "Signal 03 / Challenges", "Execution: challenges and mitigation", f"""<h1>The data fought back. <em>How we handled it</em></h1>
<table style='font-size:12pt'><tr><th>what we found</th><th>what we did</th></tr>
<tr><td>{k.get('dg_units', 126)} dengue reporting units, not 81 provinces: cities mixed in, misspellings, boundaries changed since 2020</td><td>A reviewed crosswalk to {k['n_units']} harmonised 2016-2020 provinces; a week counts only if every member reported</td></tr>
<tr><td>2020 reporting collapsed under COVID-19 ({k['cases_by_year'].get(2020, 0) / 1e3:.0f}k vs {k['cases_by_year'].get(2019, 0) / 1e3:.0f}k cases)</td><td>2020 is never a forecast target; it is used for access scenarios only</td></tr>
<tr><td>Flood-hazard maps missing for {len(k['haz_nomap'])} provinces</td><td>Carried as missing, never as zero hazard</td></tr>
<tr><td>Satellite flood maps disagreed with Copernicus at first</td><td>Same-orbit change detection with a dB-difference rule, validated against Copernicus EMS</td></tr>
<tr><td>Short series make causal-discovery algorithms over-confident</td><td>False discovery rate control, tested on pure noise first</td></tr>
<tr><td>Surge probability was under-confident in the middle range</td><td>Isotonic recalibration, fitted only on forecasts whose outcome was already known</td></tr>
<tr><td>Road network and friction raster disagree once a storm hits</td><td>Both are run on every track; the gap is shown as a range, not hidden in one number</td></tr></table>"""))

    bench_li = (f"<li>Benchmarks on the same rows: {', '.join(BENCH_LABEL[x] for x in bp if x != 'ens_median')}{', and their median ensemble' if 'ens_median' in bp else ''}</li>"
                if bp else "<li>Bar to beat: \"same week last year\" (seasonal naive)</li>")
    S.append(_slide(8, "Signal 04 / Method", "Technical rigor: validity of techniques", f"""<h1><em>Honest ranges</em>, tested like real time</h1>
<div class='grid2'><div class='box'><h3>Model</h3><ul><li>One pooled XGBoost per horizon, 1-4 weeks ahead</li>
<li>23 quantiles (the CDC FluSight standard), so every forecast is a range</li><li>Inputs: recent cases, season, rain, river, storm, flood, leader provinces</li>
<li>A direct 4-week model gives the surge probability R, recalibrated on past forecasts only; SHAP explains it</li></ul></div>
<div class='box'><h3>Evaluation without leakage</h3><ul><li>Rolling origin over 2018-2019: refit every 13 weeks on past data only</li>
<li>Graph, thresholds and calibration are re-learned inside each window</li><li>Weighted interval score on case counts (Bracher et al., 2021) vs "same week last year"</li>
{bench_li}</ul></div></div>
<div class='g64' style='margin-top:.18in;align-items:center'>{_img(F['rolling'], 1.5)}
<div class='stat'><div class='num' style='font-size:44pt'>{k['n_scored']:,}</div><p>out-of-sample forecasts scored: {k['n_units']} provinces, 4 horizons, 2018-2019</p></div></div>"""))

    # ---------------------------------------------------------------- results
    if "ens_median" in bp:
        bo = k["bench_only"]
        ens = al.loc["ens_median"]
        right = f"""<table class='small' style='font-size:11pt'><tr><th>model</th><th class='n'>rel WIS</th><th class='n'>vs xgb</th><th class='n'>median WIS</th><th class='n'>cov 90</th></tr>
{model_rows(k, compact=True)}</table>
<ul style='margin-top:.12in'><li style='font-size:13pt'>The <b>ensemble</b> is best on average ({ens.relWIS_vs_naive:.2f}); the benchmarks win on epidemic peaks</li>
<li style='font-size:13pt'>On the <b>typical</b> province-week XGBoost is best (median WIS {k['mw']['xgb']:.2f} vs {_rng(min(k['mw'][x] for x in bo), max(k['mw'][x] for x in bo), '{:.2f}')})</li>
<li style='font-size:13pt'>Storm scenarios use XGBoost: the only model that reads the storm track</li></ul>"""
        title = f"Beats the bar by {1 - k['relwis']:.0%}; <em>an ensemble</em> by {1 - ens.relWIS_vs_naive:.0%}"
    else:
        right = f"""<div class='stat'><div class='num'>{k['relwis']:.2f}</div><p>relative WIS vs seasonal naive (target below 1): {e.iloc[0]['relWIS xgb/naive']:.2f} one week ahead, {e.iloc[3]['relWIS xgb/naive']:.2f} four weeks ahead</p></div>
<div class='stat' style='margin-top:.2in'><div class='num'>{k['cov90']:.0%}</div><p>of outcomes fall inside the 90% range (target 80-95%)</p></div>
<p class='dim' style='font-size:12pt;margin-top:.15in'>{bench_missing_text(k)}</p>"""
        title = f"{1 - k['relwis']:.0%} better than the bar: <em>relative WIS {k['relwis']:.2f}</em>"
    S.append(_slide(9, "Signal 05 / Result 1", "Execution: findings", f"""<h1>{title}</h1>
<div class='g64' style='grid-template-columns:1.25fr 1fr'>{_img(F['wis'], 3.55)}<div>{right}</div></div>
<p class='dim' style='margin-top:.1in;font-size:12.5pt'>{k['n_common'] if k['models_ok'] else k['n_scored']:,} forecasts, every model on the same rows; XGBoost 90% coverage {k['cov90']:.0%} (target 80-95%).</p>"""))

    if cal:
        a_ = cal["all_rows"]
        r = d["rel"]
        S.append(_slide(10, "Signal 05 / Result 2", "Technical rigor: analytical depth", f"""<h1>Surge risk R, <em>calibrated</em> on the past</h1>
<div class='g46'><div><div class='grid2' style='gap:.2in'>
<div class='stat'><div class='num' style='font-size:42pt'>{a_['brier_raw']:.3f}</div><p>Brier score of the model's R</p></div>
<div class='stat'><div class='num' style='font-size:42pt'>{a_['brier_cal']:.3f}</div><p>after recalibration ({a_['brier_climatology']:.3f} if always predicting the base rate)</p></div></div>
<ul style='margin-top:.2in'><li>The model under-stated mid-range risk; an isotonic map fitted only on <b>past</b> forecasts with known outcomes fixes it</li>
<li>When R says high, surges follow: above 0.7, {r.observed_cal.iloc[-1]:.0%} of province-weeks surged</li>
<li>2019's epidemic made surges common ({a_['base_rate']:.0%} of province-weeks)</li></ul></div>
{_img(F['rel'], 4.0)}</div>"""))
    else:
        S.append(_slide(10, "Signal 05 / Result 2", "Technical rigor: analytical depth", f"""<h1>Surge probability R: <em>it ranks provinces well</em></h1>
<div class='g46'><div><div class='stat'><div class='num'>{k['brier']:.3f}</div><p>Brier score of R, against {k['brier_clim']:.3f} for the base rate</p></div></div>
{_img(F['rel'], 4.0)}</div>"""))

    ed = d["edges"].sort_values("weight", key=abs, ascending=False).head(5)
    short = lambda u: d["names"][u].replace("Metropolitan Manila ", "NCR ").replace(" District", "").split(" (")[0]  # noqa: E731
    link_rows = "".join(f"<tr><td>{short(a)}</td><td>{short(b)}</td><td class='n'>{l} wk</td><td class='n'>{c:.0%}</td></tr>"
                        for a, b, l, c in zip(ed.source, ed.target, ed.lag, ed.confidence))
    S.append(_slide(11, "Signal 05 / Result 3", "Technical rigor: novelty and validity", f"""<h1>How outbreaks <em>travel</em> between provinces</h1>
<div class='g46'><div><ul><li>PCMCI+ separates "A rises, then B" from "both rise in the rainy season" (Runge, 2020)</li>
<li><b>{k['ll_edges']} lead-lag links</b> survive false-discovery control; plain correlation would have drawn {k['xc_edges']:,}</li>
<li>Leaders are marked as <b>sentinel sites</b> on the dashboard: places to watch first</li></ul>
<table style='margin-top:.1in;font-size:11.5pt'><tr><th>leader</th><th>follower</th><th class='n'>lead</th><th class='n'>bootstrap</th></tr>{link_rows}</table></div>
{_img(F['leadlag'], 4.5)}</div>"""))

    if s1 and F.get("s1"):
        mu = k.get("s1_muni", {})
        rows = "".join(f"<tr><td>{STORMS[kk]['local']}</td><td class='n'>{fmt_m(t['pop'])}</td><td class='n'>{mu[kk]['n_fl'] if kk in mu else '–'}</td>"
                       f"<td>{(mu[kk]['top'][0][0] + ', ' + mu[kk]['top'][0][1]) if kk in mu else t['top']}</td></tr>" for kk, t in k["s1_tab"].items())
        agree = (f"<p class='dim' style='font-size:12pt;margin-top:.1in'>Checked against Copernicus EMS (Ompong): {ems['precision']:.0%} of Sentinel-1 flood inside the EMS areas "
                 f"matches EMS polygons; Sentinel-1 recovers {ems['recall']:.0%} of the EMS-mapped area (one radar pass every 6-12 days misses short floods).</p>") if ems else ""
        S.append(_slide(12, "Signal 05 / Result 4", "Data: observed flood exposure", f"""<h1>Flood seen from <em>space</em>, town by town</h1>
<div class='g64'><div>{_img(F['s1'], 2.45)}
<table style='margin-top:.12in;font-size:11.5pt'><tr><th>typhoon</th><th class='n'>people in new flood</th><th class='n'>municipalities &gt;1% flooded</th><th>most people flooded</th></tr>{rows}</table></div>
<div>{_img(F.get('s1ems'), 3.0)}{agree}</div></div>"""))
    else:
        S.append(_slide(12, "Signal 05 / Result 4", "Data: flood exposure", "<h1>Observed flood</h1><p>Sentinel-1 flood masks not available in this build.</p>"))

    if k["raster_ok"]:
        pr = k["proxy"]
        mrows = "".join(f"<tr><td>{STORMS[kk]['local']}</td><td class='n'>{int(st.loc[kk, 'ferries'])}</td><td class='n'>{fmt_m(st.loc[kk, 'cut'])}</td>"
                        f"<td class='n'>{fmt_m(st.loc[kk, 'cutr'])}</td><td class='n'>{st.loc[kk, 'u5'] / 1e3:,.0f}k</td><td class='n'>{st.loc[kk, 'o60'] / 1e3:,.0f}k</td></tr>"
                        for kk in STORMS)
        S.append(_slide(13, "Signal 06 / Result 5", "Execution: findings", f"""<h1>Who gets <em>cut off</em>: two methods, four typhoons</h1>
<div class='g64' style='grid-template-columns:1.3fr 1fr'><div>{_img(F['access'], 2.15)}
<table style='margin-top:.1in;font-size:11pt' class='small'><tr><th>typhoon</th><th class='n'>ferries cut</th><th class='n'>cut off: network</th><th class='n'>raster</th><th class='n'>under-5</th><th class='n'>60+</th></tr>{mrows}</table></div>
<div>{_img(F['methods'], 2.0)}
<ul style='margin-top:.12in'><li style='font-size:12.5pt'>Road network and friction raster agree on a normal day (&rho; {k['mbase']['spearman_unit_base_hours']:.2f} across provinces) but not on the size of a storm's cut: the range is the uncertainty</li>
<li style='font-size:12.5pt'>Radar flood: a <b>lower bound</b>. Hazard maps on the shifted tracks: {fmt_m(pr['cut'][0])}-{fmt_m(pr['cut'][1])}, an <b>upper bound</b></li>
<li style='font-size:12.5pt'>Older people are under-counted in the population map ({k['o60_share']:.1%} vs {k.get('census_60', float('nan')):.1%} in the census)</li></ul></div></div>"""))
    else:
        S.append(_slide(13, "Signal 06 / Result 5", "Execution: findings", f"""<h1>Who gets <em>cut off</em>: four typhoons</h1>{_img(F['access'], 2.5)}
<table style='margin-top:.1in;font-size:10.5pt'><tr><th>typhoon</th><th class='n'>ferry routes cut</th><th class='n'>people cut off</th><th class='n'>mean A</th><th class='n'>mean R</th><th class='n'>deploy / pre-position</th><th>top priority</th></tr>{storm_rows(k)}</table>"""))

    S.append(_slide(14, "Signal 06 / Result 6", "Real-world application", f"""<h1>Ompong 2018: <em>{k['top']['ompong']}</em> first</h1>
<div class='grid2'>{_img(F['priority'], 4.25)}
<div>{_img(F['scatter'], 2.95)}
<p style='margin-top:.15in'>Using data up to the landfall week only: {st.loc['ompong', 't2']} provinces flagged to <b>pre-position supplies</b>
{f"and {st.loc['ompong', 't3']} to <b>deploy mobile clinics</b>" if st.loc['ompong', 't3'] else "before the surge"}. In the next four weeks,
<b>{v.top10_surge_rate.iloc[0] * 10:.0f} of the top 10</b> really surged.</p></div></div>"""))

    if k.get("cat_ok"):
        a = k["allst"]
        cat = a[a.kind == "catalogue"]
        big = cat.nlargest(1, "cut").iloc[0]
        hiR = cat.nlargest(1, "R").iloc[0]
        S.append(_slide(15, "Signal 06 / Result 7", "Real-world application: scale", f"""<h1>Every storm {pd.Timestamp(a.origin.min()).year}-{pd.Timestamp(a.origin.max()).year}, <em>not just four</em></h1>
{_img(F['catalog'], 3.35)}
<div class='grid3' style='margin-top:.2in'>
<div class='stat'><div class='num' style='font-size:38pt'>{len(a)}</div><p>storms scored: {k['n_cat']} more beyond the four backtests, each with the model of its own week</p></div>
<div class='stat'><div class='num' style='font-size:38pt'>{fmt_m(big.cut)}</div><p>most people cut off: {big.label}, flood from hazard maps (an upper bound)</p></div>
<div class='stat'><div class='num' style='font-size:38pt'>{hiR.R:.2f}</div><p>highest mean surge risk: {hiR.label}{', in the 2019 epidemic season' if pd.Timestamp(hiR.origin).year == 2019 else ''}</p></div></div>"""))
    else:  # keep 20 slides when the catalogue stage has not run
        S.append(_slide(15, "Signal 06 / Result 7", "Real-world application: scale", "<h1>Every storm, <em>not just four</em></h1>"
                        "<p>The storm catalogue is not in this build: run <code>build.bat catalog</code> and regenerate.</p>"))

    S.append(_slide(16, "Signal 06 / Result 8", "Technical rigor: validity", f"""<h1>It points at the <em>right places</em></h1>
<div class='grid2'><div>{_img(F['valid'], 2.9)}
<div class='grid3' style='margin-top:.2in'>
<div class='stat'><div class='num' style='font-size:34pt'>{v.spearman_R_obs.iloc[1]:.2f}</div><p>rank correlation, Tisoy</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>&ge;{min(k['tau_min'], k.get('tau_min_raster', 1)):.2f}</div><p>ranking stability (Kendall's &tau;)</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>{k['bench']:.0%}</div><p>NCR cut off vs ~22% published</p></div></div></div>
<div><ul><li><b>Backtest</b>: R's ranking matches the next four weeks' incidence, &rho; = {v.spearman_R_obs.iloc[0]:.2f} (Ompong) and {v.spearman_R_obs.iloc[1]:.2f} (Tisoy)</li>
<li><b>Ompong</b>: {v.top10_surge_rate.iloc[0] * 10:.0f} of the 10 highest-priority provinces surged, against a {v.surge_rate.iloc[0]:.0%} base rate</li>
<li><b>Robust</b>: nine changes to travel speeds, ferry rules, cut-off rules and storm radius leave the ranking in place on both access methods (Kendall's &tau; &ge; {min(k['tau_min'], k.get('tau_min_raster', 1)):.2f})</li>
<li><b>Benchmark</b>: {k['bench']:.0%} of Metro Manila cut off when hazard-zone roads close; Tariverdi et al. (2023) found ~22% for a 15 cm flood, the same order</li></ul></div></div>"""))

    if L:
        c, n = L["city"], L["nat"]
        ru = L.get("ru_post")
        S.append(_slide(17, "Signal 06 / Result 9", "Technical rigor: analytical depth", f"""<h1>Leptospirosis: rain now, <em>cases in a month</em></h1>
<div class='g64' style='grid-template-columns:1.2fr 1fr'>{_img(F['lepto'], 3.6)}
<div><div class='stat'><div class='num' style='font-size:44pt'>{c['peak'].irr:.2f}&times;</div><p>leptospirosis cases {int(c['peak'].lag)} weeks after an extra 50 mm of weekly rain, in {L.get('n_cities', 12)} cities ({c['peak'].ci_lo:.2f}-{c['peak'].ci_hi:.2f})</p></div>
<ul style='margin-top:.15in'><li style='font-size:13pt'>An open city-level series exists (Project CCHAIN): the proposal had assumed none</li>
<li style='font-size:13pt'>Nationally the same pattern, but mostly from 2020</li>
{f"<li style='font-size:13pt'>After Rolly and Ulysses, cities in the gale swath had {ru.irr:.1f}&times; the expected cases; not after Ompong or Tisoy</li>" if ru is not None else ""}
<li style='font-size:13pt'>An association in 12 cities: not extrapolated to provinces, not yet in the ranking</li></ul></div></div>"""))
    else:
        S.append(_slide(17, "Signal 06 / Result 9", "Technical rigor", "<h1>Leptospirosis</h1><p>Not run in this build.</p>"))

    S.append(f"""<section class='s'><div class='top'><span class='sig'>Signal 18 / Demo</span><span class='crit'>Demonstration video: functional showcase</span></div>
<div class='g64'><img class='shot' src='../figures/dashboard.png'>
<div><h3>What a health officer sees</h3><ul style='font-size:12.5pt'><li>Pick a typhoon, or move its track 0.5-1&deg; south or north, or 1&deg; east or west</li>
<li><b>Action map</b>: priority, track, gale swath and cancelled ferries</li><li><b>Risk vs access</b>, with the action tier for every province</li>
<li><b>Provinces</b>: expected cases for 4 weeks with a 90% range, people cut off (both methods), drivers</li>
<li><b>Municipalities</b>, <b>Outbreak graph</b>, <b>Forecast skill</b>, <b>Leptospirosis</b>, <b>Validation</b>,
<b>Data &amp; caveats</b>, and a built-in <b>Usability test</b></li>
<li>{k['n_scen'] + k.get('n_cat', 0)} scenarios pre-computed: answers in seconds</li></ul></div></div>
<div class='brand'>BANTAY-BAHA / PJDSC 2026</div><div class='pn'>18 / {N}</div></section>""")

    # ---------------------------------------------------------------- deployment
    S.append(_slide(19, "Signal 08 / Deploy", "Future directions: real-world application and deployment", f"""<h1>Putting it <em>in the loop</em></h1>
<div class='loop'>
<div class='step'><div class='k'>1</div><h3>Storm watch</h3><p>A PAGASA tropical cyclone bulletin goes in: its forecast track and shifted tracks for the cone of uncertainty.</p></div>
<div class='step'><div class='k'>2</div><h3>Pre-landfall bulletin</h3><p>A ranked province list with action tiers to DOH regional offices, provincial health offices and DRRMOs, 48-72 h ahead.</p></div>
<div class='step'><div class='k'>3</div><h3>Post-landfall update</h3><p>Days 1-7: Sentinel-1 flood maps replace the hazard estimate; ferry and road status update who is cut off.</p></div>
<div class='step'><div class='k'>4</div><h3>Learn every week</h3><p>Weeks 1-8: each PIDSR report is scored against the forecast; R is recalibrated and tiers are reviewed with users.</p></div></div>
<p style='margin-top:.18in;font-size:17pt'>The output is an <b>action</b>, not a chart: monitor sentinel sites, pre-position doxycycline and vector control, or send mobile clinics
<b>before</b> the roads and ferries close.</p>
<div class='grid4' style='margin-top:.12in'>
<div class='stat'><div class='num' style='font-size:34pt'>{k['n_adm3']:,}</div><p>municipalities with access loss for every scenario</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>{k['n_scen'] + k.get('n_cat', 0)}</div><p>storm scenarios ready on the dashboard</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>100%</div><p>open data and open code; no maps need a tile server</p></div>
<div class='stat'><div class='num' style='font-size:34pt'>1</div><p>command rebuilds everything when new data arrive</p></div></div>
<p style='margin-top:.06in;font-size:15pt'>The novelty is the join: <b>storm-specific</b> disease risk &times; <b>storm-specific</b> loss of access, ferries included, in one
ranking a health officer can act on.</p>"""))

    refs = "".join(f"<p>{r}</p>" for r in REFERENCES)
    S.append(_slide(20, "Signal 09 / Sources", "Sources: APA 7th edition", f"<div class='refs'>{refs}</div>"))
    assert len(S) == N, len(S)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Bantay-Baha slides</title>"
            f"<style>{FONT_CSS}{SLIDE_CSS}</style></head><body>{''.join(S)}</body></html>")
