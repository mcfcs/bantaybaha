"""Bantay-Baha dashboard. Reads only pre-computed files in data/processed/app/ (built by scripts/build.py).

Run:  streamlit run app/streamlit_app.py      (or run_app.bat)

Layout: sidebar = the scenario (typhoon, then track shift); main = situation header and caveats, then KPIs, then tabs.
Tabs are a registry (TABS at the bottom): each is a function, and optional ones appear only when their files exist, so
new build outputs slot in without touching the rest. Optional outputs this file already looks for:
  scenarios_catalog*.parquet  (more storms, same columns as scenarios.parquet; observed track only)
  scenario columns A_raster, A_lo, A_hi, P_lo, P_hi, pop_cut_u5, pop_cut_60, R_raw
  access_methods.csv, eval_models.csv, s1_adm3.parquet, lepto_*.csv
Env overrides (tests): BANTAY_APP_DATA (folder of build outputs), BANTAY_SUS_PATH (SUS responses CSV).
"""

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from shapely import wkt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from bantay.config import APP_DATA, STORMS  # noqa: E402
from bantay.scenarios import TIER_LABELS, TIERS, tier as tier_rule  # noqa: E402

import lepto_tab  # noqa: E402
import sus  # noqa: E402
import ui  # noqa: E402
from ui import HELP, TIER_SHORT  # noqa: E402

st.set_page_config(page_title="Bantay-Baha", page_icon=":material/flood:", layout="wide",
                   initial_sidebar_state="expanded")
ui.css()

APP = Path(os.environ.get("BANTAY_APP_DATA") or APP_DATA)
STATUS_FILE = APP.parent / "status.json"
DRIVERS = ["recent cases", "season", "rain", "river", "storm / flood", "outbreak graph", "unit"]
BASE = ["pop", "R", "A", "P", "tier", "cases4_med", "cases4_lo90", "cases4_hi90", "pop_cut", "pop_no_access_base",
        "base_hours", "is_sentinel", "sentinel_rank", "community", "flood_source", "ferries_cancelled", "origin",
        "train_end", "hospital_source", "flag_2020"]


# ================================================================ data (cached; reloads when any build output changes)
def stamp():
    files = [*APP.glob("*"), STATUS_FILE] if APP.exists() else [STATUS_FILE]
    return tuple(sorted((p.name, p.stat().st_mtime) for p in files if p.exists()))


def _read(p):
    if not p.exists():
        return None
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    if p.suffix == ".csv":
        return pd.read_csv(p)
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Loading the scenario outputs…")
def load(folder, outputs_stamp):  # no leading underscore: Streamlit only hashes named args without one
    f = {k: APP / v for k, v in dict(
        scen="scenarios.parquet", adm3="scenarios_adm3.parquet", tracks="tracks.parquet", swaths="swaths.parquet",
        ferries="ferries.parquet", fstat="ferries_status.parquet", edges="leadlag_edges_pcmciplus.parquet",
        nodes="leadlag_nodes_pcmciplus.parquet", xedges="leadlag_edges_xcorr.parquet", evalf="eval_forecasts.parquet",
        hosp="hospitals.parquet", evals="eval_summary.csv", valid="validation.csv", sens="sensitivity.csv",
        bench="benchmark_ncr.csv", rel="surge_reliability.csv", cal="surge_calibration.json",
        meta="leadlag_meta.json", geo="units_simplified.geojson",
        # optional outputs; each section renders only when its file is present
        access_methods="access_methods.csv", access_methods_cat="access_methods_catalog.csv",
        eval_models="eval_models.csv", evalf_models="eval_forecasts_models.parquet", s1_adm3="s1_adm3.parquet",
        catalog="scenarios_catalog.parquet", adm3_cat="scenarios_catalog_adm3.parquet",
        tracks_cat="tracks_catalog.parquet", swaths_cat="swaths_catalog.parquet",
        fstat_cat="ferries_status_catalog.parquet", catalog_storms="catalog_storms.csv",
        lepto_weekly="lepto_weekly.parquet", bench_summary="bench_summary.csv").items()}
    d = {k: _read(p) for k, p in f.items()}
    d["status"] = json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}
    # catalogue storms share the frames of the backtest storms (storm = IBTrACS SID, observed track dlat = dlon = 0)
    for main, extra in (("tracks", "tracks_cat"), ("swaths", "swaths_cat"), ("fstat", "fstat_cat"), ("adm3", "adm3_cat")):
        if d[main] is not None and d[extra] is not None:
            d[main] = pd.concat([d[main], d[extra]], ignore_index=True)
    d["lepto"] = {p.stem: pd.read_csv(p) for p in sorted(APP.glob("lepto_*.csv"))}
    return d


@st.cache_data
def swath_xy(sw, storm, dlat, dlon):
    lon, lat = [], []
    if sw is None:
        return lon, lat
    for w in sw[(sw.storm == storm) & (sw.dlat == dlat) & (sw.dlon == dlon)].wkt:
        g = wkt.loads(w)
        for poly in getattr(g, "geoms", [g]):
            x, y = poly.exterior.xy
            lon += [*x, None]
            lat += [*y, None]
    return lon, lat


D = load(str(APP), stamp())
if D["scen"] is None:
    st.title("Bantay-Baha")
    st.error("No scenario outputs found in `data/processed/app/`. Build them with `build.bat` "
             "(or `python scripts/build.py`), then refresh this page.")
    st.stop()

hook_notes = []  # problems with optional outputs, shown on the Data & caveats tab instead of breaking the app
S = D["scen"].assign(catalog=False)
if D["catalog"] is not None:
    need = {"storm", "dlat", "dlon", "unit_id", "R"}
    if need <= set(D["catalog"].columns):
        extra = D["catalog"][~D["catalog"].storm.isin(S.storm.unique())].assign(catalog=True)
        S = pd.concat([S, extra], ignore_index=True)
    else:
        hook_notes.append(f"scenarios_catalog.parquet is missing columns {sorted(need - set(D['catalog'].columns))}; "
                          "its storms are not listed.")
CAT = {}  # catalogue storm -> name, season, closest approach
if "name" in S:
    for k_, r_ in S[S.catalog].groupby("storm").first().iterrows():
        CAT[k_] = dict(name=str(r_.get("name", "")), season=r_.get("season"), when=r_.get("closest_time"),
                       km=r_.get("closest_km"))

names = {f["properties"]["unit_id"]: f["properties"]["unit_name"] for f in D["geo"]["features"]} if D["geo"] else {}
PAL = ui.palette()


def storm_label(k):
    if k in STORMS:
        m = STORMS[k]
        return f"{m['local']} ({m['name'].title()}, {m['season']})"
    m = CAT.get(k, {})
    name, season = m.get("name") or "", m.get("season")
    yr = f" {int(season)}" if season is not None and not ui.nan(season) else ""
    if not name or name.upper() in ("UNNAMED", "NAN"):
        return f"Unnamed{yr} ({k})"
    return name.title() + yr


# ================================================================ sidebar: the scenario
main_storms = [k for k in STORMS if k in set(S.storm)]
other_storms = sorted(set(S.storm) - set(main_storms),
                      key=lambda k: (pd.Timestamp(CAT.get(k, {}).get("when") or "2100-01-01"), str(k)))
with st.sidebar:
    st.markdown('<p class="bb-brand" translate="no">Bantay-Baha</p>', unsafe_allow_html=True)  # brand, not a second h1
    st.caption("Where will flood-linked dengue surge after a typhoon, and who loses the road or ferry to a hospital? "
               "Per province, for a historical or shifted track.")
    storm = st.selectbox("Typhoon", main_storms + other_storms, format_func=storm_label, key="storm",
                         bind="query-params", placeholder="Type a storm name…",
                         help="The four backtest typhoons come first; their track can be shifted. The rest are the "
                              "other 2017-2020 storms whose gale swath reached land (catalogue, by date): observed "
                              "track only, NOAH flood proxy. Type to search.")
    if other_storms:
        st.caption(f"{len(main_storms)} backtest typhoons, then {len(other_storms)} catalogue storms by date.")
    have = S[S.storm == storm]
    lat_opts = sorted(have.dlat.unique().tolist())
    lon_opts = sorted(have.dlon.unique().tolist())
    for k, opts in (("dlat", lat_opts), ("dlon", lon_opts)):
        if st.session_state.get(k) not in opts:
            st.session_state[k] = 0.0 if 0.0 in opts else opts[0]
    if len(lat_opts) > 1 or len(lon_opts) > 1:
        st.markdown("**Track**")
        dlat = st.select_slider("Move track north or south", lat_opts, key="dlat", bind="query-params",
                                format_func=lambda v: ui.shift_label(v, "lat"), help=HELP["shift"])
        dlon = st.select_slider("Move track east or west", lon_opts, key="dlon", bind="query-params",
                                format_func=lambda v: ui.shift_label(v, "lon"), help=HELP["shift"])

        def _reset():
            st.session_state.dlat = st.session_state.dlon = 0.0

        st.button("Back to observed track", on_click=_reset, disabled=(dlat, dlon) == (0.0, 0.0),
                  icon=":material/undo:")
    else:
        dlat, dlon = st.session_state.dlat, st.session_state.dlon
        st.caption("Observed track only for this storm.")
    st.divider()
    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(f"- **Surge risk R**: {HELP['R'].split(': ', 1)[1]}\n"
                    f"- **Access loss A**: {HELP['A'].split(': ', 1)[1]}\n"
                    "- **Priority P = R x A**: ranks provinces where both are high.\n"
                    f"- **Action tier**: {HELP['tier'].split(': ', 1)[1]}\n"
                    "- Ranges are 90% intervals: 9 times in 10 the real count falls inside.")
    st.caption("Decision support only. Tier thresholds are provisional; check local reports before acting.")
    ui.watch_theme()

s = S[(S.storm == storm) & (S.dlat == dlat) & (S.dlon == dlon)].copy()
for c in BASE:
    if c not in s:
        s[c] = np.nan
if s.tier.isna().all():
    s["tier"] = tier_rule(s.R, s.A)
s["tier"] = s.tier.fillna(1).astype(int)
s["unit_name"] = s.unit_id.map(names).fillna(s.unit_id)
RANK = "P" if s.P.notna().any() else "R"
s = s.sort_values(RANK, ascending=False).reset_index(drop=True)
shifted = (dlat, dlon) != (0.0, 0.0)
meta = s.iloc[0]
flood = str(meta.flood_source)
radar = flood in ("sentinel1", "observed")
proxy = "proxy" in flood
bound = "lower bound" if radar else "upper bound" if proxy else ""
top = s.iloc[0]


def flag(v):
    return False if ui.nan(v) else bool(v)


# ================================================================ header + caveats
def headline():
    m = STORMS.get(storm)
    name = f"Typhoon {m['local']}" if m else storm_label(storm)
    track = (ui.shift_label(dlat, "lat") if dlat else "") + (" and " if dlat and dlon else "") + \
        (ui.shift_label(dlon, "lon") if dlon else "")
    st.title(name + (f", track moved {track}" if shifted else ""))
    c = CAT.get(storm, {})
    when = c.get("when")
    if m:
        sub = f"{m['name'].title()}, {m['season']}. "
    elif when is not None and not ui.nan(when):
        sub = f"Catalogue storm (IBTrACS {storm}), closest to the Philippines on {ui.date(when)}. "
    else:
        sub = "Catalogue storm. "
    origin = f"Forecast made in the week ending {ui.date(meta.origin)}" if not ui.nan(meta.origin) else "Forecast"
    st.markdown(f'<p class="bb-lede">{sub}{"Shifted" if shifted else "Observed"} track. {origin}, '
                "with data up to the landfall week.</p>", unsafe_allow_html=True)
    badges = [f":blue-badge[:material/water: Flood on roads: {ui.FLOOD_LABEL.get(flood, flood)}"
              + (f", {bound}" if bound else "") + "]"]
    hs = str(meta.hospital_source)
    badges.append(":gray-badge[:material/local_hospital: Hospitals: "
                  f"{'fallback list' if 'fallback' in hs else ui.HOSPITAL_LABEL.get(hs, hs)}]")
    if not ui.nan(meta.train_end):
        badges.append(f":gray-badge[:material/model_training: Models trained to {ui.date(meta.train_end)}]")
    if flag(meta.flag_2020):
        badges.append(":orange-badge[:material/warning: 2020: COVID-depressed reporting]")
    if s.catalog.any():
        badges.append(":gray-badge[Catalogue storm: observed track only]")
    if "R_calibrated" in s:
        badges.append(":gray-badge[Surge risk: calibrated]" if s.R_calibrated.astype(bool).all()
                      else ":orange-badge[Surge risk: not calibrated]")
    st.markdown(" ".join(badges))


def caveats():
    """Every caveat that applies to this scenario, most decision-relevant first."""
    out = []
    if flag(meta.flag_2020):
        out.append(("warning", "2020 storm: dengue reporting collapsed under COVID-19, so surge risk R and case "
                               "forecasts are indicative only. Use this storm for the access picture."))
    if s.A.isna().all():
        out.append(("warning", "Access loss A is missing for this run (road graph, population or hospitals not built), "
                               "so priority P is undefined and tiers use surge risk R only."))
    if radar:
        out.append(("info", "Roads are cut only where Sentinel-1 radar saw new water in the 10 days after landfall: "
                            "a retrospective view of what radar later saw. Radar misses flood under trees, in towns "
                            "and between passes, so people cut off is a lower bound."))
    elif proxy:
        out.append(("info", "No flood image for this track: roads are cut or slowed where the NOAH 25-year flood "
                            "hazard (high or medium) lies inside the gale swath. People cut off is likely an upper "
                            "bound." + (" Copernicus EMS flood areas are added where mapped." if "ems" in flood else "")))
    if shifted:
        out.append(("info", "Shifted track: storm exposure is recomputed for the new track; observed rainfall is "
                            "unchanged."))
    out.append(("info", "Ferry links come from 2024-2026 RoRo routes, used as a proxy for 2018-2020 operations."))
    if "fallback" in str(meta.hospital_source):
        out.append(("info", "Hospitals: OpenStreetMap and UP NOAH facilities (fallback until the DOH registry is "
                            "loaded). Small clinics may count as hospitals, so travel times can look better than "
                            "they are."))
    rel, cal = D["rel"], (D["cal"] or {}).get("calibrated")
    if "R_calibrated" in s and s.R_calibrated.astype(bool).all():
        extra = (f" Over past forecasts this lowers the Brier score from {cal['all_rows']['brier_raw']:.3f} to "
                 f"{cal['all_rows']['brier_cal']:.3f}." if cal and "all_rows" in cal else "")
        out.append(("info", "Surge risk R is calibrated: an isotonic fit of what actually happened on the raw model "
                            "output, using past forecasts only. The raw value is shown as R raw." + extra))
    elif "R_calibrated" in s:
        n_min = f" ({cal['min_rows']} needed)" if cal and "min_rows" in cal else ""
        out.append(("warning", "Surge risk R is not calibrated for this storm: too few past outcomes before its "
                               f"forecast week{n_min}. R is the raw model output, which ran low in past tests."))
    elif "R_raw" in s and s.R_raw.notna().any():
        out.append(("info", "Surge risk R is recalibrated on past forecasts; the uncalibrated value is shown as R raw."))
    elif rel is not None and len(rel):
        gap = rel.observed - rel.mean_R
        out.append(("info", f"Surge risk R runs low: in past tests, forecasts of 0.1-0.7 came true up to "
                            f"{gap.max():.0%} more often than stated. Treat mid-range R as an underestimate."))
    if "A_raster" in s and s.A_raster.notna().any():
        out.append(("info", "Access is computed two ways: the road and ferry network (main) and a travel-time "
                            "raster. Where they disagree, A, P and people cut off are shown as a range."))
    out.append(("info", "Action tiers use provisional thresholds, to be reviewed with health officers."))
    return out


headline()
CAVEATS = caveats()
lead = [c for c in CAVEATS if c[0] == "warning"] or CAVEATS[:1]
for kind, msg in lead:
    if kind == "warning":
        st.warning(msg, icon=":material/warning:")
    else:
        st.info(msg, icon=":material/info:")
rest = [c for c in CAVEATS if c not in lead]
with st.expander(f"Other caveats for this scenario ({len(rest)})"):
    st.markdown("\n".join(f"- {m}" for _, m in rest))

# ================================================================ KPIs
k = st.columns([1, 1, 1.15, 1, 1.25])
n3, n2 = int((s.tier == 3).sum()), int((s.tier == 2).sum())
k[0].metric("Deploy mobile clinics", n3, delta="province" if n3 == 1 else "provinces", delta_color="off",
            delta_arrow="off", help=f"{TIER_LABELS[3]}. {HELP['tier']}", border=True)
k[1].metric("Pre-position supplies", n2, delta="province" if n2 == 1 else "provinces", delta_color="off",
            delta_arrow="off", help=f"{TIER_LABELS[2]}. {HELP['tier']}", border=True)
cut = s.pop_cut.sum() if s.pop_cut.notna().any() else np.nan
k[2].metric("Cut off from a hospital", ui.people(cut), delta=bound.capitalize() or None, delta_color="off",
            delta_arrow="off", help=f"{HELP['pop_cut']} {HELP['flood']}", border=True)
fc = meta.ferries_cancelled
n_routes = len(D["ferries"]) if D["ferries"] is not None else None
k[3].metric("Ferries cancelled", "n/a" if ui.nan(fc) else int(fc), delta=f"of {n_routes} routes" if n_routes else None,
            delta_color="off", delta_arrow="off", help="RoRo routes with a port or crossing inside the gale swath (2024-2026 routes as a proxy).", border=True)
k[4].metric("Top priority", top.unit_name, delta=TIER_SHORT[int(top.tier)], delta_color="off", delta_arrow="off",
            help=f"Highest {'priority P' if RANK == 'P' else 'surge risk R'} for this scenario.", border=True)
_bits = []
if "pop_cut_raster" in s and s.pop_cut_raster.notna().any() and not ui.nan(cut):
    _bits.append(f"People cut off: {ui.people(cut)} by the road network, {ui.people(s.pop_cut_raster.sum())} by the "
                 "travel-time raster (the gap is method uncertainty)")
if {"pop_cut_u5", "pop_cut_60"} <= set(s.columns) and s.pop_cut_u5.notna().any():
    _bits.append(f"{ui.people(s.pop_cut_u5.sum())} of the road-network count are under 5 and "
                 f"{ui.people(s.pop_cut_60.sum())} are aged 60+")
if _bits:
    st.caption("; ".join(_bits) + ".")


# ================================================================ tabs
def act_table(d, n=10):
    t = d.head(n)
    return pd.DataFrame({"Province": t.unit_name, "Action": t.tier.map(ui.TIER_TINY), "R": t.R, "A %": 100 * t.A,
                         "People cut off": t.pop_cut.round(0)})


ACT_COLS = {"R": st.column_config.NumberColumn("Surge risk R", format="%.2f", help=HELP["R"]),
            "A %": st.column_config.NumberColumn("Access loss A", format="%.1f%%", help=HELP["A"]),
            "People cut off": st.column_config.NumberColumn(format="localized", help=HELP["pop_cut"]),
            "Cases next 4 wk": st.column_config.NumberColumn(format="localized", help=HELP["cases"]),
            "90% range": st.column_config.TextColumn(help=HELP["cases"]),
            "Action": st.column_config.TextColumn(help=HELP["tier"])}


def tab_map():
    left, right = st.columns([10, 9], gap="medium")
    with right:
        st.header("Act first")
        st.caption(f"Top 10 by {'priority P = R x A' if RANK == 'P' else 'surge risk R'}. "
                   "The full list is on Provinces; where to send a clinic is on Municipalities.")
        st.dataframe(act_table(s), hide_index=True, width="stretch", height=388, column_config=ACT_COLS,
                     key="act_first")
        tiers = s.tier.value_counts()
        st.markdown("\n".join(f"- **{int(tiers.get(t, 0))}** {'province' if tiers.get(t, 0) == 1 else 'provinces'}: "
                              f"{TIER_LABELS[t].lower()}" for t in (3, 2, 1)))
    with left:
        opts = {"Priority P": "P", "Surge risk R": "R", "Access loss A": "A"}
        pick = st.radio("Colour provinces by", list(opts), horizontal=True, key="color_by", bind="query-params",
                        help=f"{HELP['P']} {HELP['R']} {HELP['A']}")
        col = opts[pick]
        if s[col].isna().all():
            st.warning(f"{pick} is not available for this run, so the map shows surge risk R.")
            col = "R"
        if D["geo"] is None:
            st.warning("The province outlines are missing: run `build.bat app`.")
            return
        st.plotly_chart(map_figure(col), width="stretch", config={"displaylogo": False, "scrollZoom": False},
                        key="map")
        st.caption("Grey provinces have no value for this layer. Hover a province for its numbers.")


def map_figure(col):
    vmax = 1.0 if col == "R" else max(float(np.nanmax(s[col])), 1e-3)
    fmt = {"R": ".2f", "A": ".1%", "P": ".3f"}[col]
    title = {"R": "Surge risk R", "A": "Access loss A", "P": "Priority P"}[col]
    fig = go.Figure()
    fig.add_trace(go.Choropleth(geojson=D["geo"], locations=list(names), featureidkey="properties.unit_id",
                                z=[0] * len(names), colorscale=[[0, PAL["land"]], [1, PAL["land"]]], showscale=False,
                                hoverinfo="skip", marker_line_color=PAL["unit_line"], marker_line_width=0.4,
                                name="no data", showlegend=False))
    v = s[s[col].notna()]
    has_rng = {"A_lo", "A_hi"} <= set(v.columns)
    a_rng = [f" (methods {ui.rng(lo, hi, '{:.1%}')})" if has_rng and not ui.nan(lo) and abs(hi - lo) > 5e-4 else ""
             for lo, hi in zip(v.get("A_lo", v.A), v.get("A_hi", v.A))]
    cd = np.stack([v.R, v.A, v.P, v.pop_cut.fillna(0), v.tier.map(TIER_SHORT), a_rng], axis=1)
    fig.add_trace(go.Choropleth(
        geojson=D["geo"], locations=v.unit_id, featureidkey="properties.unit_id", z=v[col], zmin=0, zmax=vmax,
        colorscale=[[i / (len(PAL["seq"]) - 1), c] for i, c in enumerate(PAL["seq"])],
        marker_line_color=PAL["unit_line"], marker_line_width=0.4, text=v.unit_name, customdata=cd,
        hovertemplate="<b>%{text}</b><br>Surge risk R %{customdata[0]:.2f}<br>Access loss A %{customdata[1]:.1%}"
                      "%{customdata[5]}"
                      "<br>Priority P %{customdata[2]:.3f}<br>People cut off %{customdata[3]:,.0f}"
                      "<br>%{customdata[4]}<extra></extra>",
        colorbar=dict(title=dict(text=title, side="top"), tickformat=fmt, thickness=12, len=0.45, x=0.99, y=0.72,
                      outlinewidth=0),
        name=title, showlegend=False))
    lon, lat = swath_xy(D["swaths"], storm, dlat, dlon)
    if lon:
        fig.add_trace(go.Scattergeo(lon=lon, lat=lat, mode="lines", name="Gale-force swath",
                                    line=dict(color=PAL["track"], width=1.3, dash="dash"), hoverinfo="skip"))
    if D["ferries"] is not None and D["fstat"] is not None:
        fs = D["fstat"]
        fs = fs[(fs.storm == storm) & (fs.dlat == dlat) & (fs.dlon == dlon) & fs.cancelled]
        fr = D["ferries"][D["ferries"].route_name.isin(fs.route)]
        flon, flat, ftxt = [], [], []
        for a, b, c, e, nm in zip(fr.from_lon, fr.from_lat, fr.to_lon, fr.to_lat, fr.route_name):
            flon += [a, c, None]
            flat += [b, e, None]
            ftxt += [nm, nm, None]
        if flon:
            fig.add_trace(go.Scattergeo(lon=flon, lat=flat, mode="lines", name=f"Ferry route cancelled ({len(fr)})",
                                        line=dict(color=PAL["ferry"], width=2), text=ftxt,
                                        hovertemplate="%{text}<extra>ferry cancelled</extra>"))
    tr = D["tracks"]
    if tr is not None:
        t = tr[(tr.storm == storm) & (tr.dlat == dlat) & (tr.dlon == dlon)]
        if len(t):
            fig.add_trace(go.Scattergeo(
                lon=t.LON, lat=t.LAT, mode="lines+markers", name="Typhoon track" if storm in STORMS else "Storm track",
                line=dict(color=PAL["track"], width=2.5),
                marker=dict(size=8, color=PAL["track"], line=dict(width=1.5, color=PAL["unit_line"])),
                text=[f"{a:%d %b %H:%M} UTC, {w:.0f} kt" for a, w in zip(pd.to_datetime(t.time), t.wind_kt.fillna(0))],
                hovertemplate="%{text}<extra>track</extra>"))
    fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[116.5, 127.2], lataxis_range=[4.5, 21.2],
                    bgcolor="rgba(0,0,0,0)")
    fig.update_layout(height=760, margin=dict(l=0, r=0, t=28, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", x=0.0, y=1.0, yanchor="bottom", bgcolor="rgba(0,0,0,0)", title=None),
                      hoverlabel=dict(align="left"))
    return fig


def tab_quadrant():
    if s.A.isna().all():
        st.warning("Access loss A is not available for this run, so the risk-versus-access view is empty.")
        return
    st.caption("Each dot is a province, sized by population. Top right = likely surge and many people cut off: act "
               "first. Dotted lines are the provisional tier thresholds.")
    has_err = {"A_lo", "A_hi"} <= set(s.columns) and s.A_lo.notna().any()
    amax = float(np.nanmax(s.A_hi if has_err else s.A))
    a_thr, r_dep = TIERS["deploy"][1], TIERS["deploy"][0]
    ymax = max(amax * 1.2, 0.01) if amax < a_thr * 0.6 else max(amax, a_thr) * 1.15  # zoom in when A is small
    fig = go.Figure()
    dot = dict(color=PAL["rule"], width=1, dash="dot")
    fig.add_shape(type="line", x0=TIERS["preposition_R"], x1=TIERS["preposition_R"], y0=0, y1=ymax, line=dot)
    fig.add_annotation(x=TIERS["preposition_R"], y=ymax, yanchor="top", xanchor="left", showarrow=False,
                       text=f" Pre-position from R = {TIERS['preposition_R']}", font=dict(size=11))
    if ymax > a_thr:
        fig.add_shape(type="rect", x0=r_dep, x1=1, y0=a_thr, y1=ymax, line_width=0, fillcolor=PAL["band"],
                      layer="below")
        fig.add_annotation(x=1, y=ymax, xanchor="right", yanchor="top", showarrow=False, text="Deploy zone",
                           font=dict(size=12))
        fig.add_shape(type="line", x0=0, x1=1, y0=a_thr, y1=a_thr, line=dot)
        fig.add_shape(type="line", x0=r_dep, x1=r_dep, y0=a_thr, y1=ymax, line=dot)
    else:
        fig.add_annotation(x=1, y=ymax, xanchor="right", yanchor="top", showarrow=False, font=dict(size=11),
                           text=f"Deploy zone (R ≥ {r_dep}, A ≥ {a_thr:.0%}) is above this view")
    smax = float(s["pop"].max()) if s["pop"].notna().any() else 1.0
    size = 8 + 32 * np.sqrt(s["pop"].fillna(0) / smax)
    for t in (1, 2, 3):
        d = s[s.tier == t]
        if not len(d):
            continue
        err = dict(type="data", symmetric=False, array=(d.A_hi - d.A).clip(lower=0),
                   arrayminus=(d.A - d.A_lo).clip(lower=0), thickness=1, width=0, color=PAL["rule"]) if has_err else None
        fig.add_trace(go.Scatter(
            x=d.R, y=d.A, mode="markers", name=TIER_SHORT[t], error_y=err,
            marker=dict(size=size[d.index], color=PAL["tier"][t], opacity=0.9,
                        line=dict(width=1.5, color=PAL["unit_line"])),
            text=d.unit_name, customdata=np.stack([d["pop"].fillna(0), d.pop_cut.fillna(0)], axis=1),
            hovertemplate="<b>%{text}</b><br>Surge risk R %{x:.2f}<br>Access loss A %{y:.1%}"
                          "<br>Population %{customdata[0]:,.0f}<br>People cut off %{customdata[1]:,.0f}<extra></extra>"))
    for i, (j, r) in enumerate(s.head(6).iterrows()):
        off = size[j] / 2 + 8
        fig.add_annotation(x=r.R, y=r.A, text=r.unit_name, showarrow=False, yshift=off if i % 2 == 0 else -off,
                           font=dict(size=11))
    fig.update_layout(height=580, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(title="Action tier", orientation="h", y=1.08, x=0, traceorder="reversed"),
                      xaxis=dict(title="Surge risk R (chance of a dengue surge in the next 4 weeks)", range=[-0.03, 1.03],
                                 gridcolor="rgba(128,128,128,.15)", zeroline=False),
                      yaxis=dict(title="Access loss A (share of people cut off)", tickformat=".0%",
                                 range=[-0.04 * ymax, ymax],
                                 gridcolor="rgba(128,128,128,.15)", zeroline=False))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="quadrant")
    if has_err:
        st.caption("Vertical whiskers: access loss by the road network and by the travel-time raster. The gap is "
                   "method uncertainty, not a confidence interval.")
    if radar and amax < a_thr:
        st.caption(f"With radar-observed flood no province reaches {TIERS['deploy'][1]:.0%} access loss, so none is "
                   "in the deploy zone. Radar is a lower bound; try a shifted track for the hazard-map upper bound.")


def drivers(r):
    v = {g: r.get(f"shap_{g}", 0.0) for g in DRIVERS}
    v = {g: (0.0 if ui.nan(x) else float(x)) for g, x in v.items()}
    up = [g for g, x in sorted(v.items(), key=lambda kv: -kv[1]) if x > 0.02][:2]
    return ", ".join(up) or "-"


def ranked():
    t = s
    out = pd.DataFrame({"Province": t.unit_name, "Action": t.tier.map(ui.TIER_TINY), "P": t.P, "R": t.R})
    if "R_raw" in t:
        out["R raw"] = t.R_raw
    out["A %"] = 100 * t.A
    if {"A_lo", "A_hi"} <= set(t.columns):
        out["A range"] = [ui.rng(lo, hi, "{:.1%}") for lo, hi in zip(t.A_lo, t.A_hi)]
    if "A_raster" in t:
        out["A raster %"] = 100 * t.A_raster
    if {"P_lo", "P_hi"} <= set(t.columns):
        out["P range"] = [ui.rng(lo, hi, "{:.3f}") for lo, hi in zip(t.P_lo, t.P_hi)]
    out["Cases next 4 wk"] = t.cases4_med.round(0)
    out["90% range"] = [ui.rng(lo, hi) for lo, hi in zip(t.cases4_lo90, t.cases4_hi90)]
    out["People cut off"] = t.pop_cut.round(0)
    if "pop_cut_raster" in t:
        out["Cut off, raster"] = t.pop_cut_raster.round(0)
    if "pop_cut_u5" in t:
        out["Under-5 cut off"] = t.pop_cut_u5.round(0)
    if "pop_cut_60" in t:
        out["Aged 60+ cut off"] = t.pop_cut_60.round(0)
    sent = t.is_sentinel.astype("boolean").fillna(False).to_numpy(dtype=bool)
    out["Sentinel"] = np.where(sent, "#" + t.sentinel_rank.astype("Int64").astype(str), "")
    out["Community"] = t.community.astype("Int64")
    out["Main drivers"] = t.apply(drivers, axis=1)
    return out


def tab_table():
    st.caption("Sorted by priority. Click a column header to re-sort; hover it for its definition.")
    show = ranked()
    cfg = dict(ACT_COLS)
    cfg.update({"Province": st.column_config.TextColumn(pinned=True),
                "P": st.column_config.NumberColumn("Priority P", format="%.3f", help=HELP["P"]),
                "R": st.column_config.ProgressColumn("Surge risk R", min_value=0, max_value=1, format="%.2f",
                                                     help=HELP["R"]),
                "R raw": st.column_config.NumberColumn(format="%.2f", help="Surge risk before calibration."),
                "A range": st.column_config.TextColumn("A, method range", help=HELP["methods"]),
                "A raster %": st.column_config.NumberColumn("A, raster", format="%.1f%%",
                                                            help="Access loss from the travel-time raster method."),
                "P range": st.column_config.TextColumn("P, method range", help=HELP["methods"]),
                "Cut off, raster": st.column_config.NumberColumn(format="localized",
                                                                 help="People cut off by the travel-time raster method."),
                "Under-5 cut off": st.column_config.NumberColumn(format="localized", help="Children under 5 cut off."),
                "Aged 60+ cut off": st.column_config.NumberColumn(format="localized", help="People aged 60+ cut off."),
                "Sentinel": st.column_config.TextColumn(help=HELP["sentinel"]),
                "Community": st.column_config.NumberColumn(help=HELP["community"]),
                "Main drivers": st.column_config.TextColumn(help=HELP["drivers"])})
    st.dataframe(show, hide_index=True, width="stretch", height=640, column_config=cfg, key="ranked")
    st.download_button("Download table (CSV)", show.to_csv(index=False).encode("utf-8"),
                       f"bantay_baha_{storm}_{dlat:+g}N_{dlon:+g}E.csv", mime="text/csv", icon=":material/download:")


def tab_muni():
    a3 = D["adm3"]
    if a3 is None:
        st.info("Municipal access results are not built yet (`build.bat scenarios app`).")
        return
    opts = s.unit_id.tolist()
    if st.session_state.get("muni_unit") not in opts:
        st.session_state["muni_unit"] = opts[0]
    unit = st.selectbox("Province", opts, format_func=lambda u: names.get(u, u), key="muni_unit",
                        help="Starts on the top-priority province.")
    m = a3[(a3.storm == storm) & (a3.dlat == dlat) & (a3.dlon == dlon) & (a3.unit_id == unit)].copy()
    if not len(m):
        st.info("No municipal results for this province and track.")
        return
    s1, s1_cols = D["s1_adm3"], []
    if s1 is not None and "adm3_pcode" in s1 and not shifted and storm in set(s1.get("storm", pd.Series(dtype=str))):
        keys = [c for c in ("adm3_pcode", "storm") if c in s1]
        s1_cols = [c for c in s1.columns if c not in m.columns and c not in ("unit_id", "dlat", "dlon")]
        m = m.merge(s1[keys + s1_cols].drop_duplicates(keys), on=keys, how="left")
        for c in ("s1_flood_frac", "seen_frac"):
            if c in m:
                m[c] = 100 * m[c]
    m = m.sort_values("A", ascending=False)
    worst = m.sort_values("pop_cut", ascending=False).iloc[0]
    if worst.pop_cut > 0:
        st.markdown(f"**Send a mobile clinic first to {worst.adm3_name}**: {worst.pop_cut:,.0f} people "
                    f"({worst.A:.0%} of the municipality) lose their route to a hospital.")
    else:
        st.markdown(f"No municipality in {names.get(unit, unit)} loses hospital access on this track.")
    b = m[m.pop_cut > 0].nlargest(10, "pop_cut").iloc[::-1]
    if len(b):
        fig = go.Figure(go.Bar(x=b.pop_cut, y=b.adm3_name, orientation="h", marker_color=PAL["tier"][2],
                               text=[f"{v:,.0f} ({a:.0%})" for v, a in zip(b.pop_cut, b.A)], textposition="outside",
                               cliponaxis=False, width=0.6,
                               hovertemplate="%{y}<br>%{x:,.0f} people cut off<extra></extra>"))
        fig.update_layout(height=80 + 34 * len(b), margin=dict(l=10, r=110, t=36, b=10), plot_bgcolor="rgba(0,0,0,0)",
                          title=dict(text="People cut off, by municipality (share in brackets)", font=dict(size=14)),
                          xaxis=dict(visible=False), yaxis=dict(title=None))
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="muni_bar")
    extra = [c for c in ("A_raster", "pop_cut_raster", "pop_cut_u5", "pop_cut_60") if c in m]
    cols = ["adm3_name", "pop", "pop_cut", "A"] + extra + ["base_hours", "pop_no_access_base"] + s1_cols
    m = m.assign(A=100 * m.A, **({"A_raster": 100 * m.A_raster} if "A_raster" in m else {}))
    st.dataframe(m[cols].round({c: 0 for c in ("pop", "pop_cut", "pop_no_access_base", "pop_cut_raster", "pop_cut_u5",
                                               "pop_cut_60", "s1_flood_pop") if c in cols}),
                 hide_index=True, width="stretch",
                 key="muni_table", column_config={
                     "adm3_name": st.column_config.TextColumn("Municipality / city", pinned=True),
                     "A_raster": st.column_config.NumberColumn("Share cut off, raster", format="%.1f%%",
                                                               help="Travel-time raster method."),
                     "pop_cut_raster": st.column_config.NumberColumn("Cut off, raster", format="localized"),
                     "pop_cut_u5": st.column_config.NumberColumn("Under 5 cut off", format="localized"),
                     "pop_cut_60": st.column_config.NumberColumn("Aged 60+ cut off", format="localized"),
                     "s1_flood_frac": st.column_config.NumberColumn("Radar flood share", format="%.1f%%",
                                                                    help="Share of the area where Sentinel-1 saw new "
                                                                         "water after landfall."),
                     "s1_flood_pop": st.column_config.NumberColumn("People in radar flood", format="localized"),
                     "seen_frac": st.column_config.NumberColumn("Radar coverage", format="%.0f%%",
                                                                help="Share of the area the radar passes covered; low "
                                                                     "coverage means flood may be missed."),
                     "pop": st.column_config.NumberColumn("Population", format="localized"),
                     "pop_cut": st.column_config.NumberColumn("People cut off", format="localized",
                                                              help=HELP["pop_cut"]),
                     "A": st.column_config.NumberColumn("Share cut off", format="%.1f%%", help=HELP["A"]),
                     "base_hours": st.column_config.NumberColumn("Normal trip to hospital (h)", format="%.2f",
                                                                 help="Travel time on a normal day."),
                     "pop_no_access_base": st.column_config.NumberColumn(
                         "No road route even normally", format="localized",
                         help="People with no mapped road route to a hospital, even before the storm.")})
    if s1_cols:
        st.caption("Radar columns: what Sentinel-1 saw for this typhoon (observed track only). Low radar coverage "
                   "means flood there may be missed.")


def tab_graph():
    st.markdown("Which provinces’ dengue changes come before others’? Learned with **PCMCI+** on 2016-2019 data "
                "(links lag 1-3 weeks, false-discovery rate q < 0.05). Links are statistical, not proof of "
                "transmission, and the graph is sparse: treat sentinels as a weak signal.")
    e = D["edges"]
    if e is not None and len(e):
        e = e.assign(source=e.source.map(names).fillna(e.source), target=e.target.map(names).fillna(e.target))
        e = e.assign(confidence=100 * e.confidence)
        st.dataframe(e[["source", "target", "lag", "weight", "q", "confidence"]], hide_index=True, width="stretch",
                     key="edges", column_config={
                         "source": "Leads (province)", "target": "Follows (province)",
                         "lag": st.column_config.NumberColumn("Lag (weeks)"),
                         "weight": st.column_config.NumberColumn("Strength", format="%.2f",
                                                                 help="Partial correlation of the link."),
                         "q": st.column_config.NumberColumn("q value", format="%.4f",
                                                            help="False-discovery-rate adjusted p value."),
                         "confidence": st.column_config.NumberColumn(
                             "Bootstrap confidence", format="%.0f%%",
                             help="Share of bootstrap resamples that found this link.")})
    else:
        st.warning("PCMCI+ found no lead-lag links between provinces at q < 0.05.")
    n = D["nodes"]
    if n is not None:
        st.header("Sentinels and communities")
        n = n.assign(unit=n.unit_id.map(names).fillna(n.unit_id)).sort_values("sentinel_rank")
        st.dataframe(n[["unit", "sentinel_rank", "out_degree", "in_degree", "community", "is_sentinel"]].head(20),
                     hide_index=True, width="stretch", key="nodes", column_config={
                         "unit": "Province",
                         "sentinel_rank": st.column_config.NumberColumn("Sentinel rank", help=HELP["sentinel"]),
                         "out_degree": st.column_config.NumberColumn("Leads", help="Links going out."),
                         "in_degree": st.column_config.NumberColumn("Follows", help="Links coming in."),
                         "community": st.column_config.NumberColumn("Community", help=HELP["community"]),
                         "is_sentinel": st.column_config.CheckboxColumn("Sentinel")})
    if D["meta"]:
        with st.expander("Graph fit details"):
            st.dataframe(pd.DataFrame(D["meta"]), hide_index=True)
    if D["xedges"] is not None:
        st.caption(f"Baseline, lagged cross-correlation with the same FDR: {len(D['xedges']):,} links. Plain "
                   "correlation links almost every province because they share the 2019 epidemic; PCMCI+ conditions "
                   "that away.")


MODEL_NAMES = {"xgb": "Bantay-Baha (XGBoost)", "xgb_nograph": "XGBoost without outbreak graph",
               "xgb_noenv": "XGBoost without rain, river and flood", "naive": "Seasonal naive (baseline)",
               "chronos2": "Chronos-2", "tabpfn_ts": "TabPFN-TS", "mpnn_lstm": "MPNN-LSTM",
               "ens_median": "Median ensemble"}
MODEL_ORDER = ["xgb", "ens_median", "chronos2", "tabpfn_ts", "mpnn_lstm", "xgb_nograph", "xgb_noenv"]
KIND_NAMES = {"model": "Main model", "ablation": "Ablation", "baseline": "Baseline", "benchmark": "Benchmark",
              "ensemble": "Ensemble"}


def median_wis(em_all):
    """Median WIS per model from bench_summary.csv (all horizons); NaN where the build has none."""
    bs = D["bench_summary"]
    out = {}
    if bs is not None and {"model", "horizon", "median WIS"} <= set(bs.columns):
        b = bs[bs.horizon.astype(str) == "all"]
        out.update(dict(zip(b.model, b["median WIS"])))
        if len(b) and "median WIS xgb" in b:
            out["xgb"] = b["median WIS xgb"].iloc[0]
        if len(b) and "median WIS naive" in b:
            out["naive"] = b["median WIS naive"].iloc[0]
    return em_all.model.map(out)


def tab_skill():
    ev = D["evals"]
    if ev is None:
        st.info("Forecast evaluation not built yet (`build.bat forecast`).")
    else:
        st.markdown("Tested as if live: every forecast in 2018-2019 used only earlier data (rolling origin, refit "
                    "every 13 weeks, never a random split). Relative WIS below 1 beats the seasonal baseline; the "
                    "target for the 90% range is 80-95% coverage.")
        ev = ev.rename(columns={"Unnamed: 0": "horizon"})
        want = ["horizon", "n", "WIS xgb", "WIS naive", "relWIS xgb/naive", "cov90 xgb", "cov90 conformal",
                "cov90 naive", "cov50 xgb"]
        cols = [c for c in want if c in ev.columns]
        if "horizon" in ev:
            ev["horizon"] = ev.horizon.astype(str)
        full = ev.copy()
        for c in [c for c in ev.columns if c.startswith("cov")]:
            ev[c] = 100 * ev[c]
        cfg = {c: st.column_config.NumberColumn(c, format="%.3f") for c in cols}
        cfg.update({"horizon": st.column_config.TextColumn("Weeks ahead"),
                    "n": st.column_config.NumberColumn("Forecasts", format="localized"),
                    "relWIS xgb/naive": st.column_config.NumberColumn("Relative WIS vs naive", format="%.2f",
                                                                      help=HELP["relwis"]),
                    "relWIS xgb/nograph": st.column_config.NumberColumn(
                        "Relative WIS vs no graph", format="%.3f", help="About 1 = the outbreak graph adds nothing."),
                    "WIS xgb": st.column_config.NumberColumn("WIS model", format="%.1f", help=HELP["wis"]),
                    "WIS naive": st.column_config.NumberColumn("WIS naive", format="%.1f", help=HELP["wis"]),
                    "cov90 xgb": st.column_config.NumberColumn("90% coverage", format="%.0f%%", help=HELP["cov90"]),
                    "cov50 xgb": st.column_config.NumberColumn("50% coverage", format="%.0f%%",
                                                               help="Share inside the 50% range. Target about 50%."),
                    "cov90 naive": st.column_config.NumberColumn("90% cov., naive", format="%.0f%%"),
                    "cov90 conformal": st.column_config.NumberColumn(
                        "90% cov., conformal", format="%.0f%%",
                        help="Coverage after online conformal adjustment of the 90% range."),
                    "MAE xgb": st.column_config.NumberColumn("Mean abs. error, model", format="%.1f"),
                    "MAE naive": st.column_config.NumberColumn("Mean abs. error, naive", format="%.1f")})
        st.dataframe(ev[cols], hide_index=True, width="stretch", column_config=cfg, key="eval_summary")
        with st.expander("All scores, including the ablations (no graph, no rain/river/flood)"):
            st.dataframe(full, hide_index=True, width="stretch", key="eval_full",
                         column_config={c: st.column_config.NumberColumn(format="%.3f")
                                        for c in full.select_dtypes("number").columns if c != "n"})
    em = D["eval_models"]
    if em is not None and len(em) and {"model", "horizon", "WIS"} <= set(em.columns):
        st.header("Model comparison")
        hz = em.horizon.astype(str)
        tab = (em[hz == "all"] if (hz == "all").any() else em).copy()
        tab["median_WIS"] = median_wis(tab)
        main = tab[tab.get("kind", pd.Series("", index=tab.index)) != "ablation"]
        if len(main) > 2:
            best = main.loc[main.WIS.idxmin()]
            xg = main[main.model == "xgb"]
            line = (f"Lowest mean WIS: **{MODEL_NAMES.get(best.model, best.model)}** (relative WIS vs naive "
                    f"{best.relWIS_vs_naive:.3f}")
            line += f", against {xg.relWIS_vs_naive.iloc[0]:.3f} for XGBoost)." if len(xg) and best.model != "xgb" else ")."
            md = main.dropna(subset=["median_WIS"])
            if len(md):
                bm = md.loc[md.median_WIS.idxmin()]
                miss = [MODEL_NAMES.get(m, m) for m in main.model[main.median_WIS.isna()]]
                line += (f" Lowest median WIS: **{MODEL_NAMES.get(bm.model, bm.model)}** ({bm.median_WIS:.2f})"
                         + (f"; no median score in the build for {', '.join(miss)}." if miss else "."))
            st.markdown(line)
        st.info("Storm scenarios use XGBoost: the benchmark models take no storm-track inputs, so they can't score a "
                "shifted or hypothetical track.", icon=":material/info:")
        tab = tab.assign(Model=tab.model.map(lambda m: MODEL_NAMES.get(m, m)),
                         kind=tab.get("kind", pd.Series("", index=tab.index)).map(lambda k: KIND_NAMES.get(k, k)))
        tab = tab.sort_values("WIS")
        tab["median_WIS"] = tab.median_WIS.map(lambda x: "n/a" if ui.nan(x) else f"{x:.2f}")
        for c in ("cov50", "cov90"):
            if c in tab:
                tab[c] = 100 * tab[c]
        cols = [c for c in ("Model", "kind", "WIS", "median_WIS", "relWIS_vs_naive", "relWIS_vs_xgb", "cov90", "cov50",
                            "MAE", "n") if c in tab]
        st.caption("All horizons together; every model scored on the same rolling-origin rows. Mean WIS is pulled up "
                   "by a few outbreak weeks; median WIS shows the typical week.")
        st.dataframe(tab[cols], hide_index=True, width="stretch", key="eval_models", column_config={
            "kind": "Type", "WIS": st.column_config.NumberColumn("Mean WIS", format="%.1f", help=HELP["wis"]),
            "median_WIS": st.column_config.TextColumn("Median WIS", help="Median over forecasts: the typical week. "
                                                                         "n/a: not in the build outputs."),
            "relWIS_vs_naive": st.column_config.NumberColumn("Relative WIS vs naive", format="%.2f",
                                                             help=HELP["relwis"]),
            "relWIS_vs_xgb": st.column_config.NumberColumn("Relative WIS vs Bantay-Baha", format="%.3f",
                                                           help="Below 1 beats the main model."),
            "cov90": st.column_config.NumberColumn("90% coverage", format="%.0f%%", help=HELP["cov90"]),
            "cov50": st.column_config.NumberColumn("50% coverage", format="%.0f%%"),
            "MAE": st.column_config.NumberColumn("Mean abs. error", format="%.1f"),
            "n": st.column_config.NumberColumn("Forecasts", format="localized")})
        bs = D["bench_summary"]
        if bs is not None and "model" in bs:
            var = bs[(bs.horizon.astype(str) == "all") & ~bs.model.isin(em.model)]
            if len(var):
                with st.expander(f"Benchmark variants not used ({len(var)})"):
                    vc = [c for c in ("model", "WIS", "relWIS vs naive", "median WIS",
                                      "relWIS vs naive excl. worst origin", "worst origin") if c in var]
                    st.caption("Other settings tried for the benchmarks; not in the model picker. A very large mean WIS "
                               "means the variant collapsed on a few reporting spikes.")
                    st.dataframe(var[vc], hide_index=True, width="stretch", key="bench_variants",
                                 column_config={c: st.column_config.NumberColumn(format="%.3f")
                                                for c in vc if c not in ("model", "worst origin")})
    c1, c2 = st.columns([2, 3], gap="large")
    with c1:
        cal = (D["cal"] or {}).get("calibrated")
        if cal and "all_rows" in cal:
            a = cal["all_rows"]
            st.markdown(f"**Calibrated surge risk R** (used on the map and in the tables) scores a Brier of "
                        f"**{a['brier_cal']:.3f}**, against {a['brier_raw']:.3f} before calibration and "
                        f"{a['brier_climatology']:.3f} for always forecasting the base rate ({a['base_rate']:.0%} of "
                        "province-weeks surged). Lower is better.")
        elif D["cal"] and "xgb" in D["cal"]:
            c = D["cal"]["xgb"]
            st.markdown(f"**Surge risk R** scores a Brier of **{c['brier']:.3f}**, against {c['brier_climatology']:.3f} "
                        f"for always forecasting the base rate ({c['base_rate']:.0%} of province-weeks surged). "
                        "Lower is better.")
        if D["rel"] is not None:
            rl = D["rel"]
            calibrated = {"mean_R_cal", "observed_cal"} <= set(rl.columns)
            traces = [go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color=PAL["rule"], dash="dot", width=1),
                                 name="Perfectly calibrated", hoverinfo="skip")]
            if calibrated:
                traces.append(go.Scatter(x=rl.mean_R, y=rl.observed, mode="lines+markers", name="Raw R (before calibration)",
                                         marker=dict(size=7, color=PAL["muted"]), line=dict(color=PAL["muted"], width=1.5,
                                                                                            dash="dot"),
                                         customdata=rl.n, hovertemplate="Raw R %{x:.2f}<br>Came true %{y:.0%}<br>"
                                                                        "n = %{customdata:,}<extra></extra>"))
            x, y, n = (rl.mean_R_cal, rl.observed_cal, rl.n_cal) if calibrated else (rl.mean_R, rl.observed, rl.n)
            traces.append(go.Scatter(x=x, y=y, mode="lines+markers",
                                     name="Calibrated R (used on the map)" if calibrated else "Surge risk R",
                                     marker=dict(size=9, color=PAL["seq"][4], line=dict(width=1.5, color=PAL["unit_line"])),
                                     line=dict(color=PAL["seq"][4], width=2), customdata=n,
                                     hovertemplate="Forecast R %{x:.2f}<br>Came true %{y:.0%}<br>n = %{customdata:,}"
                                                   "<extra></extra>"))
            fig = go.Figure(traces)
            fig.update_layout(title=dict(text="Does R mean what it says?", font=dict(size=14)), height=340,
                              margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="rgba(0,0,0,0)",
                              legend=dict(orientation="h", y=-0.25),
                              xaxis=dict(title="Forecast R", range=[0, 1], gridcolor="rgba(128,128,128,.15)"),
                              yaxis=dict(title="Share that surged", range=[0, 1], tickformat=".0%",
                                         gridcolor="rgba(128,128,128,.15)"))
            st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="reliability")
            if calibrated:
                first = f" Forecasts before {ui.date(cal['first_calibrated_origin'])} stay raw (too few past outcomes)." \
                    if cal and cal.get("first_calibrated_origin") else ""
                st.caption("Calibrated R sits close to the dotted line; raw R lay above it (surges came true more often "
                           "than it said). The calibration is fitted only on forecasts whose outcome was already known."
                           + first)
            else:
                st.caption("Above the dotted line = surges happened more often than R said (R is under-confident).")
    with c2:
        f, fb = D["evalf"], D["evalf_models"]
        if f is not None:
            q50 = lambda fr: [m for m in dict.fromkeys(re.sub(r"_q50$", "", c) for c in fr.columns  # noqa: E731
                                                       if c.endswith("_q50")) if m != "naive"]
            models = q50(f)
            bench = [m for m in q50(fb) if m not in models] if fb is not None else []
            models += bench
            models = sorted(models, key=lambda m: (MODEL_ORDER.index(m) if m in MODEL_ORDER else 99, m))
            units = sorted(f.unit_id.unique().tolist(), key=lambda x: names.get(x, x))
            if st.session_state.get("evalunit") not in units:
                st.session_state["evalunit"] = top.unit_id if top.unit_id in units else units[0]
            a, b_ = st.columns(2)
            u = a.selectbox("Province", units, format_func=lambda x: names.get(x, x), key="evalunit")
            mdl = b_.selectbox("Model", models, format_func=lambda m: MODEL_NAMES.get(m, m), key="evalmodel")
            h = st.radio("Weeks ahead", [1, 2, 3, 4], horizontal=True, key="evalh")
            src = fb if mdl in bench else f
            d = src[(src.unit_id == u) & (src.horizon == h)].sort_values("target_week")
            fig = go.Figure()
            if f"{mdl}_q95" in d and f"{mdl}_q05" in d:
                fig.add_trace(go.Scatter(x=d.target_week, y=d[f"{mdl}_q95"], line=dict(width=0), showlegend=False,
                                         hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=d.target_week, y=d[f"{mdl}_q05"], fill="tonexty", fillcolor=PAL["band"],
                                         line=dict(width=0), name="90% range", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d[f"{mdl}_q50"], line=dict(color=PAL["seq"][4], width=2),
                                     name="Median forecast", hovertemplate="%{y:,.0f}"))
            if "naive_q50" in d:
                fig.add_trace(go.Scatter(x=d.target_week, y=d.naive_q50, name="Seasonal naive",
                                         line=dict(color=PAL["muted"], width=1.5, dash="dot"),
                                         hovertemplate="%{y:,.0f}"))
            fig.add_trace(go.Scatter(x=d.target_week, y=d.cases, mode="markers", name="Reported cases",
                                     marker=dict(size=6, color=PAL["ink"]), hovertemplate="%{y:,.0f}"))
            fig.update_layout(title=dict(text=f"{names.get(u, u)}: {MODEL_NAMES.get(mdl, mdl)}, {h} week{'s' if h > 1 else ''} ahead",
                                         font=dict(size=14)),
                              height=400, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="rgba(0,0,0,0)",
                              hovermode="x unified", legend=dict(orientation="h", y=-0.15),
                              yaxis=dict(title="Cases per week", gridcolor="rgba(128,128,128,.15)", rangemode="tozero"),
                              xaxis=dict(gridcolor="rgba(128,128,128,.15)"))
            st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="fan")


def tab_lepto():
    lepto_tab.render(D["lepto"], D["lepto_weekly"], PAL)


def access_methods():
    """Road network vs travel-time raster: the disagreement is reported as uncertainty (proposal)."""
    am, amc = D["access_methods"], D["access_methods_cat"]
    if am is None or not len(am):
        return
    st.header("Two access methods: road network and travel-time raster")
    st.caption("The road and ferry network is the main method; the travel-time raster (friction surface) is the check. "
               "Their gap is shown as a range on every access number.")
    base = am[am.get("kind", pd.Series(dtype=str)) == "baseline"] if "kind" in am else am.iloc[:0]
    if len(base):
        b = base.iloc[0]
        rows = [("People who can reach a hospital", b.get("pop_reach_network"), b.get("pop_reach_raster"), "%"),
                ("Mean trip to hospital, population-weighted (h)", b.get("popw_mean_hours_network"),
                 b.get("popw_mean_hours_raster"), "h")]
        fmt = lambda x, u: "n/a" if ui.nan(x) else (f"{100 * x:.1f}%" if u == "%" else f"{x:.2f} h")  # noqa: E731
        tb = pd.DataFrame([(lbl, fmt(n, u), fmt(r, u)) for lbl, n, r, u in rows],
                          columns=["Normal day", "Road network", "Travel-time raster"])
        c1, c2 = st.columns([3, 2], gap="large")
        c1.dataframe(tb, hide_index=True, width="stretch", key="access_baseline")
        txt = []
        if not ui.nan(b.get("spearman_hours_cells")):
            txt.append(f"Rank agreement of trip times across 1-km cells: **{b.spearman_hours_cells:.2f}**")
        if not ui.nan(b.get("spearman_unit_base_hours")):
            txt.append(f"across provinces: **{b.spearman_unit_base_hours:.2f}**")
        if not ui.nan(b.get("popw_median_ratio_raster_network")):
            txt.append(f"the raster's trips are typically {b.popw_median_ratio_raster_network:.2f} times the "
                       "network's (population-weighted median)")
        c2.markdown("; ".join(txt) + "." if txt else "")
    sc = [x for x in (am[am.kind == "scenario"] if "kind" in am else am, amc) if x is not None and len(x)]
    sc = pd.concat(sc, ignore_index=True) if sc else None
    if sc is None or not {"pop_cut_network", "pop_cut_raster"} <= set(sc.columns):
        return
    sc = sc.assign(label=sc.storm.map(lambda k: storm_label(k) if k in STORMS or k in CAT else k),
                   group=np.where(sc.storm.isin(list(STORMS)), "Backtest typhoons (all tracks)", "Catalogue storms"))
    fig = go.Figure()
    mx = float(np.nanmax([sc.pop_cut_network.max(), sc.pop_cut_raster.max(), 1]))
    fig.add_trace(go.Scatter(x=[0, mx], y=[0, mx], mode="lines", line=dict(color=PAL["rule"], dash="dot", width=1),
                             name="Methods agree", hoverinfo="skip"))
    for i, (g, d) in enumerate(sc.groupby("group", sort=True)):
        fig.add_trace(go.Scatter(
            x=d.pop_cut_network, y=d.pop_cut_raster, mode="markers", name=g,
            marker=dict(size=8, color=PAL["cat"][i], line=dict(width=1, color=PAL["unit_line"])),
            text=[f"{lbl}" + (f", {ui.shift_label(a, 'lat')}/{ui.shift_label(o, 'lon')}" if (a or o) and not ui.nan(a)
                              else "") for lbl, a, o in zip(d.label, d.dlat.fillna(0), d.dlon.fillna(0))],
            hovertemplate="%{text}<br>network %{x:,.0f}<br>raster %{y:,.0f}<extra></extra>"))
    cur = sc[(sc.storm == storm) & (sc.dlat.fillna(0) == dlat) & (sc.dlon.fillna(0) == dlon)]
    if len(cur):
        fig.add_trace(go.Scatter(x=cur.pop_cut_network, y=cur.pop_cut_raster, mode="markers", name="This scenario",
                                 marker=dict(size=16, color="rgba(0,0,0,0)", line=dict(width=2.5, color=PAL["ink"])),
                                 hoverinfo="skip"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.1, x=0),
                      xaxis=dict(title="People cut off, road network", gridcolor="rgba(128,128,128,.15)", rangemode="tozero"),
                      yaxis=dict(title="People cut off, travel-time raster", gridcolor="rgba(128,128,128,.15)",
                                 rangemode="tozero"))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="access_methods_chart")
    if len(cur):
        r = cur.iloc[0]
        rho = f"; rank agreement of A across provinces {r.spearman_A_units:.2f}" if not ui.nan(r.get("spearman_A_units")) else ""
        st.caption(f"This scenario: {ui.people(r.pop_cut_network)} people cut off by the network, "
                   f"{ui.people(r.pop_cut_raster)} by the raster{rho}. Points below the dotted line: the raster cuts "
                   "off fewer people.")
    with st.expander("All method comparisons"):
        cols = [c for c in ("label", "dlat", "dlon", "flood_source", "mean_A_network", "mean_A_raster",
                            "pop_cut_network", "pop_cut_raster", "spearman_A_units") if c in sc]
        st.dataframe(sc[cols], hide_index=True, width="stretch", key="access_methods", column_config={
            "label": "Storm", "dlat": "Shift N", "dlon": "Shift E", "flood_source": "Flood source",
            "mean_A_network": st.column_config.NumberColumn("Mean A, network", format="%.3f"),
            "mean_A_raster": st.column_config.NumberColumn("Mean A, raster", format="%.3f"),
            "pop_cut_network": st.column_config.NumberColumn("Cut off, network", format="localized"),
            "pop_cut_raster": st.column_config.NumberColumn("Cut off, raster", format="localized"),
            "spearman_A_units": st.column_config.NumberColumn("Rank agreement of A", format="%.2f")})


def tab_validation():
    st.header("Backtest: did high-priority provinces see more cases afterwards?")
    v = D["valid"]
    if v is not None:
        v = v.assign(**{c: 100 * v[c] for c in ("surge_rate", "top10_surge_rate") if c in v})
        if "note" in v:
            v["note"] = v.note.fillna("")
        st.dataframe(v, hide_index=True, width="stretch", key="valid", column_config={
            "storm": "Typhoon", "origin": "Forecast week", "units": "Provinces",
            "surge_rate": st.column_config.NumberColumn("Provinces that surged", format="%.0f%%",
                                                        help="Base rate: share of provinces above their 90th percentile "
                                                             "in the 4 weeks after."),
            "spearman_R_obs": st.column_config.NumberColumn("Rank agreement, R", format="%.2f",
                                                            help="Spearman correlation between R and what happened "
                                                                 "(1 = same order)."),
            "spearman_P_obs": st.column_config.NumberColumn("Rank agreement, P", format="%.2f",
                                                            help="Spearman correlation between P and what happened. "
                                                                 "P adds access, which is not about case counts."),
            "top10_surge_rate": st.column_config.NumberColumn("Top 10 by P that surged", format="%.0f%%"),
            "brier_R": st.column_config.NumberColumn("Brier score, R", format="%.3f", help="Lower is better."),
            "note": "Note"})
    st.header("Does the ranking change if the access settings change?")
    if D["sens"] is not None:
        sv = D["sens"]
        vals = [c for c in ("kendall_tau", "kendall_tau_raster") if c in sv]
        piv = sv.pivot_table(index="variant", columns="storm", values=vals)
        if len(vals) > 1:
            piv.columns = [f"{st_}, {'raster' if v.endswith('raster') else 'network'}" for v, st_ in piv.columns]
            piv = piv[sorted(piv.columns)]
        else:
            piv.columns = [c[-1] if isinstance(c, tuple) else c for c in piv.columns]
        piv.index.name = "Setting changed"
        st.caption("Kendall’s tau between the priority ranking under each setting and the base ranking "
                   "(1 = identical order), for each access method.")
        st.dataframe(piv, width="stretch", key="sens",
                     column_config={c: st.column_config.NumberColumn(format="%.2f") for c in piv.columns})
    else:
        st.info("Not available until the access model is built.")
    access_methods()
    st.header("Metro Manila benchmark")
    if D["bench"] is not None:
        bn = D["bench"].assign(**({"share_cut": 100 * D["bench"].share_cut} if "share_cut" in D["bench"] else {}))
        bn = bn.round({"ncr_pop": 0, "pop_cut": 0})
        st.dataframe(bn, hide_index=True, width="stretch", key="bench", column_config={
            "scenario": "Scenario", "ncr_pop": st.column_config.NumberColumn("NCR population", format="localized"),
            "pop_cut": st.column_config.NumberColumn("People cut off", format="localized"),
            "share_cut": st.column_config.NumberColumn("Share cut off", format="%.1f%%"),
            "tariverdi_2023": "Published estimate (Tariverdi et al., 2023)"})
        st.caption("Different flood and facility definitions from the published study: an order-of-magnitude check.")
    else:
        st.info("Not available until the access model and NOAH hazard raster are built.")


def tab_data():
    st.header("Caveats for this scenario")
    st.markdown("\n".join(f"- {m}" for _, m in CAVEATS))
    for n in hook_notes:
        st.warning(n)
    st.header("Inputs")
    stt = pd.DataFrame([dict(input=k, available=bool(v.get("available")), detail=v.get("detail", ""),
                             checked=v.get("checked", "")) for k, v in D["status"].items()])
    if len(stt):
        st.dataframe(stt.sort_values(["available", "input"]), hide_index=True, width="stretch", key="status",
                     column_config={"input": "Input", "available": st.column_config.CheckboxColumn("On disk"),
                                    "detail": "Detail", "checked": "Last checked"})
    st.caption("Missing inputs are skipped and their outputs left empty; re-running `build.bat` after the files "
               "arrive picks them up. Refresh this page after a rebuild.")
    cs = D["catalog_storms"]
    if cs is not None and len(cs) and "status" in cs:
        st.header("Storm catalogue")
        bt = cs.reason.astype(str).str.startswith("backtest") if "reason" in cs else pd.Series(False, index=cs.index)
        skip = cs[(cs.status == "skipped") & ~bt]
        reasons = skip.reason.value_counts() if "reason" in skip else pd.Series(dtype=int)
        st.markdown(f"{len(cs)} 2016-2020 storms came near the Philippines: **{int(bt.sum())}** are the backtest "
                    f"typhoons, **{int((cs.status == 'included').sum())}** are in the catalogue, and "
                    f"**{len(skip)}** were skipped ("
                    + "; ".join(f"{n}: {r.replace('PHL', 'Philippine')}" for r, n in reasons.items()) + ").")
        with st.expander(f"Skipped storms ({len(skip)})"):
            show = skip.assign(name=skip.name.str.title()).sort_values("closest_time")
            st.dataframe(show[[c for c in ("name", "season", "sid", "closest_time", "closest_km", "max_wind_kt", "reason")
                               if c in show]], hide_index=True, width="stretch", key="skipped_storms", column_config={
                "name": "Storm", "season": st.column_config.NumberColumn("Season", format="%d"), "sid": "IBTrACS ID",
                "closest_time": "Closest approach", "closest_km": st.column_config.NumberColumn("Distance (km)",
                                                                                                format="%.0f"),
                "max_wind_kt": st.column_config.NumberColumn("Max wind (kt)", format="%.0f"), "reason": "Why skipped"})


def answer_key():
    o = S[(S.storm == "ompong") & (S.dlat == 0) & (S.dlon == 0)].copy()
    if not len(o):
        return "Ompong is not in this build."
    rk = "P" if o.P.notna().any() else "R"
    o = o.sort_values(rk, ascending=False)
    o["n"] = o.unit_id.map(names).fillna(o.unit_id)
    top3 = "; ".join(f"{r.n} ({TIER_SHORT[int(r.tier)].lower()})" for r in o.head(3).itertuples())
    t1 = o.iloc[0]
    lines = [f"2. {top3}.", f"4. {t1.n}: {t1.cases4_med:,.0f} cases ({ui.rng(t1.cases4_lo90, t1.cases4_hi90)})."]
    a3 = D["adm3"]
    if a3 is not None:
        m = a3[(a3.storm == "ompong") & (a3.dlat == 0) & (a3.dlon == 0) & (a3.unit_id == t1.unit_id)]
        if len(m):
            w = m.sort_values("pop_cut", ascending=False).iloc[0]
            lines.insert(1, f"3. {w.adm3_name}: {w.pop_cut:,.0f} people cut off ({w.A:.0%}).")
    sh = S[(S.storm == "ompong") & (S.dlat == -1) & (S.dlon == 0)]
    if len(sh):
        sh = sh.sort_values("P" if sh.P.notna().any() else "R", ascending=False)
        lines.append(f"5. {names.get(sh.iloc[0].unit_id, sh.iloc[0].unit_id)}; "
                     f"{int(sh.iloc[0].ferries_cancelled)} ferry routes cancelled.")
    lines.append("6. Observed track: Sentinel-1 radar flood, a lower bound. Shifted track: NOAH hazard proxy, likely "
                 "an upper bound.")
    return "\n".join(f"- {x}" for x in lines)


def sus_form():
    with st.form("sus_form", clear_on_submit=True, enter_to_submit=False):
        role = st.selectbox("Your office", sus.ROLES, index=None, placeholder="Choose one…", key="sus_role")
        outcome = st.radio("Did you finish the scenario task?", sus.TASK_OUTCOMES, index=None, horizontal=True,
                           key="sus_outcome")
        minutes = st.number_input("Minutes taken (optional)", min_value=0, max_value=120, value=None, step=1,
                                  key="sus_minutes", placeholder="e.g. 12")
        st.caption("Rate each statement: 1 = strongly disagree, 5 = strongly agree.")
        ans = [st.radio(f"{i}. {q}", [1, 2, 3, 4, 5], index=None, horizontal=True, key=f"sus_q{i}")
               for i, q in enumerate(sus.ITEMS, 1)]
        sent = st.form_submit_button("Submit answers", type="primary", icon=":material/send:")
    if sent:
        missing = [str(i) for i, a in enumerate(ans, 1) if a is None]
        if role is None or outcome is None or missing:
            parts = (["your office"] if role is None else []) + (["the task question"] if outcome is None else []) + \
                    ([f"statement{'s' if len(missing) > 1 else ''} {', '.join(missing)}"] if missing else [])
            st.error("Not saved. Answer " + ", ".join(parts) + ", then submit again (the form clears on submit).")
        else:
            score = sus.save(role, ans, outcome, minutes)
            st.success(f"Saved. This response scores {score:.1f} out of 100. Thank you.")


def tab_sus():
    st.markdown("For a facilitated test with health and disaster-response staff: about 15 minutes for the task, then "
                "the 10-statement System Usability Scale. **No names or contact details are collected.**")
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.header("Scenario task (15 minutes)")
        st.markdown(
            "You are the duty health officer. Typhoon Ompong is about to make landfall in Northern Luzon.\n\n"
            "1. In the sidebar, choose **Ompong** and keep the **observed track**.\n"
            "2. Name the **three provinces** to act on first, and the action each needs.\n"
            "3. For the top province, find the **municipality where a mobile clinic should go** (most people cut "
            "off from a hospital).\n"
            "4. Read that province’s **expected dengue cases for the next 4 weeks and the 90% range**.\n"
            "5. Move the track **1° south**. Which province is now the top priority, and how many ferry routes "
            "are cancelled?\n"
            "6. Say which flood source the numbers used, and whether the people-cut-off count is a lower or "
            "upper bound.")
        with st.expander("Facilitator answer key (computed from this build)"):
            st.markdown(answer_key())
    with right:
        st.header("System Usability Scale")
        sus_form()
    st.header("Responses so far")
    r = sus.load()
    c = st.columns(3)
    c[0].metric("Responses", len(r), border=True)
    c[1].metric("Mean SUS score", f"{r.sus.mean():.1f}" if len(r) else "n/a", border=True,
                help="0-100. About 68 is average usability; above 80 is good (Bangor et al., 2009).")
    done = (r.task_outcome == "Completed").mean() if len(r) else np.nan
    c[2].metric("Task completed", "n/a" if ui.nan(done) else f"{done:.0%}", border=True)
    if len(r):
        st.dataframe(r.groupby("role").agg(responses=("sus", "size"), mean_sus=("sus", "mean")).reset_index(),
                     hide_index=True, key="sus_by_role", column_config={
                         "role": "Role", "responses": "Responses",
                         "mean_sus": st.column_config.NumberColumn("Mean SUS", format="%.1f")})


TABS = [  # (label, render, show?): add new sections here
    ("Action map", tab_map, True),
    ("Risk vs access", tab_quadrant, True),
    ("Provinces", tab_table, True),
    ("Municipalities", tab_muni, True),
    ("Outbreak graph", tab_graph, True),
    ("Forecast skill", tab_skill, True),
    ("Leptospirosis", tab_lepto, bool(D["lepto"])),
    ("Validation", tab_validation, True),
    ("Data & caveats", tab_data, True),
    ("Usability test", tab_sus, True),
]
shown = [(lbl, fn) for lbl, fn, ok in TABS if ok]
for tab, (lbl, fn) in zip(st.tabs([lbl for lbl, _ in shown], key="tab", bind="query-params"), shown):
    with tab:
        fn()
