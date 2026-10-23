"""Bantay-Baha dashboard. Reads only pre-computed files in data/processed/app/ (built by scripts/build.py).

Run:  streamlit run app/streamlit_app.py      (or run_app.bat)
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from shapely import wkt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bantay.config import APP_DATA, PROCESSED, STORMS  # noqa: E402
from bantay.scenarios import TIER_LABELS  # noqa: E402

st.set_page_config(page_title="Bantay-Baha", layout="wide")

# reference palette (dataviz skill): sequential blue for magnitude, ordinal blue steps for tiers (always with labels)
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
TIER_COLOR = {1: "#86b6ef", 2: "#2a78d6", 3: "#0d366b"}
TIER_SHORT = {1: "Monitor", 2: "Pre-position", 3: "Deploy"}
TRACK, SWATH, CANCEL = "#eb6834", "#eb6834", "#e34948"
FLOOD_LABEL = {"sentinel1": "Sentinel-1 observed flood", "observed": "Sentinel-1 observed flood",
               "noah_25yr_proxy": "NOAH 25-yr hazard inside the gale swath (proxy)",
               "noah_25yr_proxy+ems_aoi": "NOAH 25-yr hazard proxy + Copernicus EMS", "none": "none"}
DRIVERS = ["recent cases", "season", "rain", "river", "storm / flood", "outbreak graph", "unit"]


def read(name, kind="parquet"):
    p = APP_DATA / name
    if not p.exists():
        return None
    if kind == "parquet":
        return pd.read_parquet(p)
    if kind == "csv":
        return pd.read_csv(p)
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data
def load():
    d = {k: read(f) for k, f in [("scen", "scenarios.parquet"), ("adm3", "scenarios_adm3.parquet"), ("tracks", "tracks.parquet"),
                                 ("swaths", "swaths.parquet"), ("ferries", "ferries.parquet"), ("fstat", "ferries_status.parquet"),
                                 ("edges", "leadlag_edges_pcmciplus.parquet"), ("nodes", "leadlag_nodes_pcmciplus.parquet"),
                                 ("xedges", "leadlag_edges_xcorr.parquet"), ("evalf", "eval_forecasts.parquet"),
                                 ("hosp", "hospitals.parquet")]}
    for k, f in [("evals", "eval_summary.csv"), ("valid", "validation.csv"), ("sens", "sensitivity.csv"),
                 ("bench", "benchmark_ncr.csv"), ("rel", "surge_reliability.csv")]:
        d[k] = read(f, "csv")
    d["cal"] = read("surge_calibration.json", "json")
    d["meta"] = read("leadlag_meta.json", "json")
    gj = APP_DATA / "units_simplified.geojson"
    d["geo"] = json.loads(gj.read_text(encoding="utf-8")) if gj.exists() else None
    stp = PROCESSED / "status.json"
    d["status"] = json.loads(stp.read_text(encoding="utf-8")) if stp.exists() else {}
    return d


D = load()
if D["scen"] is None:
    st.error("No scenarios yet. Build them with `python scripts/build.py` (see README).")
    st.stop()

names = {}
if D["geo"]:
    names = {f["properties"]["unit_id"]: f["properties"]["unit_name"] for f in D["geo"]["features"]}

# ---------------------------------------------------------------- sidebar: the scenario
st.sidebar.title("Bantay-Baha")
st.sidebar.caption("Flood-linked dengue surge risk x loss of hospital access, per province, for a typhoon track.")
storm = st.sidebar.selectbox("Typhoon", list(STORMS), format_func=lambda k: f"{STORMS[k]['local']} ({STORMS[k]['name'].title()} {STORMS[k]['season']})")
c1, c2 = st.sidebar.columns(2)
dlat = c1.select_slider("Shift north (deg)", [-1.0, -0.5, 0.0, 0.5, 1.0], value=0.0)
dlon = c2.select_slider("Shift east (deg)", [-1.0, 0.0, 1.0], value=0.0)
color_by = st.sidebar.radio("Map colour", ["Priority P = R x A", "Surge risk R", "Access loss A"])

S = D["scen"]
s = S[(S.storm == storm) & (S.dlat == dlat) & (S.dlon == dlon)].copy()
s["unit_name"] = s.unit_id.map(names).fillna(s.unit_id)
shifted = (dlat, dlon) != (0.0, 0.0)
meta = s.iloc[0]

# ---------------------------------------------------------------- header + caveats
st.title(f"Typhoon {STORMS[storm]['local']}" + (f", track shifted {dlat:+g} deg N / {dlon:+g} deg E" if shifted else ""))
st.caption(f"Forecast origin: week ending {pd.Timestamp(meta.origin).date()} (data to the landfall week). "
           f"Models trained on data up to {pd.Timestamp(meta.train_end).date()}. Flood on roads: **{FLOOD_LABEL.get(meta.flood_source, meta.flood_source)}**. "
           f"Ferry routes cancelled: **{int(meta.ferries_cancelled)}**. Hospitals: **{meta.hospital_source}**.")
notes = []
if meta.flag_2020:
    notes.append("2020 storm: dengue reporting collapsed under COVID-19, so R is indicative only (the proposal uses 2020 for access scenarios).")
if s.A.isna().all():
    notes.append("Access loss A is missing (road graph, population or hospitals not built yet), so P is undefined and tiers use R only.")
if "proxy" in str(meta.flood_source):
    notes.append("No observed flood map for this run: roads are cut/slowed where NOAH 25-yr hazard (high / medium) lies inside the gale swath. "
                 "Sentinel-1 flood replaces this once the GEE download has run.")
if meta.flood_source in ("sentinel1", "observed"):
    notes.append("Roads are cut only where Sentinel-1 radar saw new water after landfall. Radar misses floods under trees, in towns and "
                 "between passes, so the people cut off here are a lower bound.")
if shifted:
    notes.append("Shifted track: storm exposure features are recomputed for the new track; observed rainfall is unchanged.")
notes.append("Ferry links: roroph 2024-2026 routes, a proxy for 2018-2020 operations.")
for n in notes:
    st.info(n)

# ---------------------------------------------------------------- KPIs
k = st.columns(4)
k[0].metric("Deploy mobile clinics", int((s.tier == 3).sum()), help=TIER_LABELS[3])
k[1].metric("Pre-position supplies", int((s.tier == 2).sum()), help=TIER_LABELS[2])
k[2].metric("People cut off from a hospital", f"{s.pop_cut.sum():,.0f}" if s.pop_cut.notna().any() else "n/a")
top = s.sort_values("P" if s.P.notna().any() else "R", ascending=False).iloc[0]
k[3].metric("Top priority", top.unit_name)

tabs = st.tabs(["Priority map", "Risk vs access", "Ranked provinces", "Municipalities", "Outbreak graph", "Forecast skill",
                "Validation", "Data status"])

# ---------------------------------------------------------------- map
with tabs[0]:
    col = {"Priority P = R x A": "P", "Surge risk R": "R", "Access loss A": "A"}[color_by]
    if s[col].isna().all():
        st.warning(f"{col} is not available for this run; showing R.")
        col = "R"
    if D["geo"] is None:
        st.warning("units_simplified.geojson missing: run `python scripts/build.py app`.")
    else:
        # SVG geo map (no WebGL, no tile server): renders in any browser and offline
        fig = px.choropleth(s, geojson=D["geo"], locations="unit_id", featureidkey="properties.unit_id", color=col,
                            color_continuous_scale=SEQ, range_color=(0, max(float(s[col].max()), 1e-3)),
                            hover_name="unit_name", hover_data={"unit_id": False, "R": ":.2f", "A": ":.1%", "P": ":.3f"},
                            height=720)
        fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[116.5, 127], lataxis_range=[4.5, 21.2])
        sw = D["swaths"]
        if sw is not None:
            g = sw[(sw.storm == storm) & (sw.dlat == dlat) & (sw.dlon == dlon)]
            for w in g.wkt:
                geom = wkt.loads(w)
                for poly in getattr(geom, "geoms", [geom]):
                    x, y = poly.exterior.xy
                    fig.add_trace(go.Scattergeo(lon=list(x), lat=list(y), mode="lines", line=dict(color=SWATH, width=1),
                                                name="gale swath", hoverinfo="skip", showlegend=False))
        tr = D["tracks"]
        t = tr[(tr.storm == storm) & (tr.dlat == dlat) & (tr.dlon == dlon)]
        fig.add_trace(go.Scattergeo(lon=t.LON, lat=t.LAT, mode="lines+markers", line=dict(color=TRACK, width=2),
                                    marker=dict(size=8, color=TRACK), name="track",
                                    text=[f"{a:%d %b %H:%M} UTC, {w:.0f} kt" for a, w in zip(pd.to_datetime(t.time), t.wind_kt.fillna(0))],
                                    hoverinfo="text"))
        if D["ferries"] is not None and D["fstat"] is not None:
            fs = D["fstat"][(D["fstat"].storm == storm) & (D["fstat"].dlat == dlat) & (D["fstat"].dlon == dlon) & D["fstat"].cancelled]
            fr = D["ferries"][D["ferries"].route_name.isin(fs.route)]
            lon, lat = [], []
            for a, b, c, dd in zip(fr.from_lon, fr.from_lat, fr.to_lon, fr.to_lat):
                lon += [a, c, None]
                lat += [b, dd, None]
            if lon:
                fig.add_trace(go.Scattergeo(lon=lon, lat=lat, mode="lines", line=dict(color=CANCEL, width=2),
                                            name="ferry route cancelled", hoverinfo="skip"))
        fig.update_traces(marker_line_width=0.4, marker_line_color="#ffffff", selector=dict(type="choropleth"))
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=0.01, x=0.01),
                          coloraxis_colorbar=dict(title=col))
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- 2x2
with tabs[1]:
    if s.A.isna().all():
        st.warning("Access loss is not available for this run.")
    else:
        d = s.assign(tier_label=s.tier.map(TIER_SHORT))
        fig = px.scatter(d, x="R", y="A", size="pop", size_max=40, color="tier_label",
                         color_discrete_map={TIER_SHORT[i]: c for i, c in TIER_COLOR.items()},
                         category_orders={"tier_label": [TIER_SHORT[3], TIER_SHORT[2], TIER_SHORT[1]]},
                         hover_name="unit_name", hover_data={"R": ":.2f", "A": ":.1%", "pop": ":,.0f", "tier_label": False},
                         labels={"R": "Surge risk R = P(next 4 weeks > unit's 90th pct)", "A": "Access loss A (share cut off)",
                                 "tier_label": "Action tier"}, height=560)
        fig.add_vline(x=0.3, line=dict(color="#c3c2b7", width=1, dash="dot"))
        fig.add_hline(y=0.10, line=dict(color="#c3c2b7", width=1, dash="dot"))
        for _, r in d.nlargest(6, "P").iterrows():
            fig.add_annotation(x=r.R, y=r.A, text=r.unit_name, showarrow=False, yshift=14, font=dict(size=11))
        fig.update_layout(yaxis_tickformat=".0%", xaxis_range=[0, 1], plot_bgcolor="rgba(0,0,0,0)")
        fig.update_xaxes(gridcolor="rgba(128,128,128,.15)")
        fig.update_yaxes(gridcolor="rgba(128,128,128,.15)")
        st.plotly_chart(fig, width="stretch")
        st.caption("Top-right: high surge risk and many people cut off: act first. Dotted lines are the provisional tier thresholds.")

# ---------------------------------------------------------------- ranked table
with tabs[2]:
    t = s.copy()

    def drivers(r):
        v = {g: r.get(f"shap_{g}", 0.0) for g in DRIVERS}
        up = [g for g, x in sorted(v.items(), key=lambda kv: -kv[1]) if x > 0.02][:2]
        return ", ".join(up) or "-"

    t["drivers (push R up)"] = t.apply(drivers, axis=1)
    t["cases next 4 wk (90% range)"] = [f"{m:,.0f} ({lo:,.0f}-{hi:,.0f})" for m, lo, hi in zip(t.cases4_med, t.cases4_lo90, t.cases4_hi90)]
    t["action"] = t.tier.map(TIER_LABELS)
    t["sentinel"] = np.where(t.is_sentinel.fillna(False), "sentinel #" + t.sentinel_rank.astype("Int64").astype(str), "")
    sort = "P" if t.P.notna().any() else "R"
    t = t.sort_values(sort, ascending=False)
    show = t[["unit_name", "action", "P", "R", "A", "cases next 4 wk (90% range)", "pop_cut", "sentinel", "community", "drivers (push R up)"]]
    st.dataframe(show, hide_index=True, width="stretch", height=640,
                 column_config={"P": st.column_config.NumberColumn(format="%.3f"), "R": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                                "A": st.column_config.NumberColumn(format="percent"), "pop_cut": st.column_config.NumberColumn("people cut off", format="%,.0f"),
                                "unit_name": "province / unit"})
    st.download_button("Download CSV", show.to_csv(index=False).encode(), f"bantay_baha_{storm}_{dlat:+g}_{dlon:+g}.csv")

# ---------------------------------------------------------------- municipalities
with tabs[3]:
    a3 = D["adm3"]
    if a3 is None:
        st.warning("Municipal access results are not available (access model not built).")
    else:
        unit = st.selectbox("Province / unit", t.unit_id.tolist(), format_func=lambda u: names.get(u, u))
        m = a3[(a3.storm == storm) & (a3.dlat == dlat) & (a3.dlon == dlon) & (a3.unit_id == unit)].sort_values("A", ascending=False)
        st.dataframe(m[["adm3_name", "pop", "pop_cut", "A", "base_hours", "pop_no_access_base"]], hide_index=True, width="stretch",
                     column_config={"A": st.column_config.NumberColumn("share cut off", format="percent"),
                                    "base_hours": st.column_config.NumberColumn("normal trip to hospital (h)", format="%.2f"),
                                    "pop_no_access_base": st.column_config.NumberColumn("no road route even normally", format="%,.0f"),
                                    "pop": st.column_config.NumberColumn(format="%,.0f"), "pop_cut": st.column_config.NumberColumn("cut off", format="%,.0f")})

# ---------------------------------------------------------------- outbreak graph
with tabs[4]:
    st.markdown("Lead-lag graph learned with **PCMCI+** on seasonally differenced log incidence, 2016-2019 "
                "(lagged edges 1-3 weeks, Benjamini-Hochberg q < 0.05). Links are statistical dependencies, not proof of transmission.")
    if D["meta"]:
        st.dataframe(pd.DataFrame(D["meta"]), hide_index=True)
    e = D["edges"]
    if e is not None and len(e):
        e = e.assign(source=e.source.map(names), target=e.target.map(names))
        st.dataframe(e[["source", "target", "lag", "weight", "q", "confidence"]], hide_index=True, width="stretch")
    else:
        st.warning("PCMCI+ found no lead-lag links between provinces at q < 0.05.")
    n = D["nodes"]
    if n is not None:
        st.subheader("Sentinels and communities")
        st.dataframe(n.assign(unit=n.unit_id.map(names)).sort_values("sentinel_rank")[["unit", "sentinel_rank", "out_degree", "in_degree", "community", "is_sentinel"]].head(20),
                     hide_index=True, width="stretch")
    if D["xedges"] is not None:
        st.caption(f"Baseline (lagged cross-correlation, same FDR): {len(D['xedges']):,} edges. Plain correlation links almost every "
                   "province because they share the 2019 epidemic; PCMCI+ conditions that away.")

# ---------------------------------------------------------------- forecast skill
with tabs[5]:
    ev = D["evals"]
    if ev is None:
        st.warning("Forecast evaluation not built (`python scripts/build.py forecast`).")
    else:
        st.markdown("Rolling-origin evaluation over 2018-2019 (refit every 13 weeks, never a random split), scored on case counts with "
                    "the Weighted Interval Score at the 23 FluSight quantiles. Relative WIS < 1 beats the seasonal-naive baseline; "
                    "the proposal target is 90% coverage of 80-95%.")
        ev = ev.rename(columns={"Unnamed: 0": "horizon"})
        st.dataframe(ev[["horizon", "n", "WIS xgb", "WIS xgb_nograph", "WIS naive", "relWIS xgb/naive", "relWIS xgb/nograph",
                         "cov50 xgb", "cov90 xgb", "cov90 naive", "cov90 conformal", "MAE xgb", "MAE naive"]].round(3), hide_index=True, width="stretch")
        if D["cal"]:
            c = D["cal"]["xgb"]
            st.caption(f"Surge probability R: Brier {c['brier']:.3f} vs {c['brier_climatology']:.3f} for always predicting the base rate "
                       f"({c['base_rate']:.0%} of unit-weeks surged).")
        if D["rel"] is not None:
            rl = D["rel"]
            fig = go.Figure([go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color="#c3c2b7", dash="dot"), name="perfect"),
                             go.Scatter(x=rl.mean_R, y=rl.observed, mode="lines+markers", marker=dict(size=9, color=SEQ[4]),
                                        line=dict(color=SEQ[4], width=2), name="R", text=rl.n, hovertemplate="R %{x:.2f}<br>observed %{y:.2f}<br>n %{text}")])
            fig.update_layout(title="Reliability of R", xaxis_title="mean predicted R", yaxis_title="observed surge rate", height=360,
                              xaxis_range=[0, 1], yaxis_range=[0, 1], plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch")
        f = D["evalf"]
        if f is not None:
            u = st.selectbox("Unit", sorted(f.unit_id.unique()), format_func=lambda x: names.get(x, x), key="evalunit")
            h = st.radio("Horizon (weeks ahead)", [1, 2, 3, 4], horizontal=True)
            d = f[(f.unit_id == u) & (f.horizon == h)].sort_values("target_week")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=d.target_week, y=d.xgb_q95, line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d.xgb_q05, fill="tonexty", fillcolor="rgba(57,135,229,.18)", line=dict(width=0), name="90% interval"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d.xgb_q50, line=dict(color=SEQ[4], width=2), name="median forecast"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d.naive_q50, line=dict(color="#898781", width=1.5, dash="dot"), name="seasonal naive"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d.cases, mode="markers", marker=dict(size=8, color="#0b0b0b"), name="reported cases"))
            fig.update_layout(height=380, yaxis_title="cases / week", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
            st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- validation
with tabs[6]:
    st.subheader("Backtest: did high-priority units see more cases in the next 4 weeks?")
    if D["valid"] is not None:
        st.dataframe(D["valid"].round(3), hide_index=True, width="stretch")
    st.subheader("Sensitivity of the ranking (Kendall's tau vs base settings)")
    if D["sens"] is not None:
        st.dataframe(D["sens"].pivot_table(index="variant", columns="storm", values="kendall_tau").round(2), width="stretch")
    else:
        st.info("Not available until the access model is built.")
    st.subheader("Metro Manila benchmark")
    if D["bench"] is not None:
        st.dataframe(D["bench"], hide_index=True, width="stretch")
    else:
        st.info("Not available until the access model and NOAH hazard raster are built.")

# ---------------------------------------------------------------- data status
with tabs[7]:
    stt = pd.DataFrame([dict(input=k, available=v["available"], detail=v["detail"], checked=v["checked"]) for k, v in D["status"].items()])
    if len(stt):
        st.dataframe(stt.sort_values(["available", "input"]), hide_index=True, width="stretch")
    st.caption("Missing inputs are skipped and their outputs are NaN; re-running `python scripts/build.py` after the files arrive picks them up.")
