"""Look and formatting for the dashboard: palette (light/dark), number formats, plain-language labels, minimal CSS.

Data colours follow the dataviz reference palette and were checked with its validator:
- tiers: ordinal blue ramp (light steps 250/450/700, dark steps 600/400/150), always shown with a text label;
- map overlays: track orange, cancelled ferries aqua (all-pairs CVD and normal-vision checks pass with the blue
  choropleth in both modes; the old orange/red pair failed), gale swath = dashed orange.
"""

import math

import streamlit as st

LIGHT = dict(
    seq=["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    tier={1: "#86b6ef", 2: "#2a78d6", 3: "#0d366b"},
    track="#eb6834", ferry="#1baf7a", ink="#1d2433", muted="#6b7280", rule="#c3c2b7",
    band="rgba(42,120,214,.16)", unit_line="#ffffff", land="#eef0f2",
    cat=["#2a78d6", "#eb6834", "#1baf7a"],  # first 3 categorical slots: pass all-pairs CVD checks
)
DARK = dict(
    seq=["#1b3354", "#1c4778", "#1f5ca3", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],  # low end recedes
    tier={1: "#184f95", 2: "#3987e5", 3: "#b7d3f6"},
    track="#d95926", ferry="#199e70", ink="#e6e9ee", muted="#9aa3af", rule="#4b5563",
    band="rgba(57,135,229,.24)", unit_line="#13171d", land="#1d232c",
    cat=["#3987e5", "#d95926", "#199e70"],
)

TIER_SHORT = {3: "Deploy mobile clinics", 2: "Pre-position supplies", 1: "Monitor"}
TIER_TINY = {3: "Deploy", 2: "Pre-position", 1: "Monitor"}

FLOOD_LABEL = {"sentinel1": "Sentinel-1 observed flood", "observed": "Sentinel-1 observed flood",
               "noah_25yr_proxy": "NOAH 25-yr hazard proxy",
               "noah_25yr_proxy+ems_aoi": "NOAH 25-yr hazard proxy + Copernicus EMS", "none": "no flood layer"}
HOSPITAL_LABEL = {"osm+noah_fallback": "OpenStreetMap + UP NOAH facilities (fallback list)",
                  "nhfr": "DOH National Health Facility Registry"}

# plain-language help for every term an officer meets on screen
HELP = dict(
    R="Surge risk R: the model’s probability that dengue cases in the next 4 weeks exceed this province’s usual "
      "high level (its 90th percentile). 0 = no chance, 1 = certain.",
    A="Access loss A: share of the province’s people whose trip to the nearest hospital is cut, or at least doubles "
      "and grows by an hour or more, because of flooded roads and cancelled ferries.",
    P="Priority P = R x A: high only when a surge is likely AND people are cut off. Used to rank provinces.",
    tier="Action tier from provisional rules: deploy if R ≥ 0.5 and A ≥ 10%; pre-position if R ≥ 0.3, or if "
         "A ≥ 10% and R ≥ 0.15; otherwise monitor. Thresholds are to be reviewed with health officers.",
    cases="Expected dengue cases over the next 4 weeks (median forecast), with the 90% range: 9 times in 10 the "
          "real count should fall inside it.",
    pop_cut="People who lose their route to a hospital (see access loss A).",
    sentinel="Sentinel: a province whose case changes tend to come before its neighbours’ in the outbreak graph "
             "(rank 1 = strongest). The graph is sparse, so treat this as a weak signal.",
    community="Outbreak community: provinces grouped by the outbreak graph. Same number = same group.",
    drivers="Inputs that pushed this province’s surge risk up the most (SHAP contributions above 0.02).",
    flood="Where roads are cut. Sentinel-1 = radar saw new water after landfall (misses flood under trees and in "
          "towns, so a lower bound). NOAH proxy = mapped 25-year flood hazard inside the gale swath (no image of "
          "that flood, so likely an upper bound).",
    shift="Move the observed track to test a near miss. Shifted tracks use the NOAH hazard proxy for flooding.",
    wis="Weighted Interval Score: forecast error that also rewards honest ranges. Lower is better.",
    relwis="Relative WIS: the model’s WIS divided by a seasonal-naive forecast’s. Below 1 beats the baseline.",
    cov90="Share of real outcomes that fell inside the 90% range. Target 80-95%.",
    methods="Lowest to highest across the two access methods: the road and ferry network (main) and the travel-time "
            "raster. A wide range means the methods disagree, so treat the number as uncertain.",
)


# Reruns the script when the viewer switches light/dark (Streamlit restyles the page itself but not our chart colours).
_THEME_JS = r"""
export default function(component) {
  const { data, setTriggerValue, parentElement } = component;
  const host = (parentElement && parentElement.host) || parentElement;
  const lum = (c) => {
    c = (c || "").trim();
    let r, g, b;
    if (c.startsWith("#")) {
      const h = c.length === 4 ? c.slice(1).split("").map((x) => x + x).join("") : c.slice(1, 7);
      [r, g, b] = [0, 2, 4].map((k) => parseInt(h.slice(k, k + 2), 16));
    } else {
      const m = c.match(/\d+(\.\d+)?/g);
      if (!m) return null;
      [r, g, b] = m.map(Number);
    }
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  };
  const id = setInterval(() => {
    const v = lum(getComputedStyle(host).getPropertyValue("--st-background-color"));
    if (v === null || Number.isNaN(v)) return;
    const k = v < 0.5 ? "dark" : "light";
    if (k !== data.kind && window.__bbTheme !== k) { window.__bbTheme = k; setTriggerValue("theme", k); }
  }, 700);
  return () => clearInterval(id);
}
"""
_watcher = None


def palette():
    """Light or dark data colours, following the viewer's theme (default light when unknown, e.g. in tests)."""
    try:
        kind = st.context.theme.type
    except Exception:  # noqa: BLE001 - older Streamlit or no browser session
        kind = None
    kind = st.session_state.get("_theme_seen") or kind
    return DARK if kind == "dark" else LIGHT


def watch_theme():
    """Mount the invisible theme watcher (call once per run, anywhere)."""
    global _watcher
    if _watcher is None:
        _watcher = st.components.v2.component("bb_theme_watch", js=_THEME_JS)

    def seen():
        v = st.session_state.get("_theme_watch")
        k = getattr(v, "theme", None) if v is not None else None
        if k in ("light", "dark"):
            st.session_state["_theme_seen"] = k

    _watcher(data={"kind": "dark" if palette() is DARK else "light"}, key="_theme_watch", on_theme_change=seen)


def css():
    """A few rules only, all on stable selectors, so a Streamlit update can't break the layout."""
    st.markdown(
        """<style>
        html { touch-action: manipulation; }
        h1, h2, h3 { text-wrap: balance; letter-spacing: -0.01em; }
        [data-testid="stMainBlockContainer"] { padding-top: 2.75rem; }
        [data-testid="stMetricValue"] { font-weight: 650; font-size: 2rem; }
        [data-testid="stMetricLabel"] p { font-size: 0.86rem; }
        [data-testid="stCaptionContainer"] { max-width: 92ch; }
        [data-testid="stMarkdownContainer"] p.bb-brand { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 0.2rem 0; }
        .bb-lede { font-size: 1.02rem; margin: -0.35rem 0 0.4rem 0; max-width: 90ch; }
        @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
        </style>""",
        unsafe_allow_html=True,
    )


def nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def people(x):
    """Rounded people count for headline numbers: 342,801 -> 343K; 7,473,210 -> 7.47M."""
    if nan(x):
        return "n/a"
    x = float(x)
    if x >= 1e6:
        return f"{x / 1e6:.2f}M"
    if x >= 1e4:
        return f"{x / 1e3:,.0f}K"
    return f"{x:,.0f}"


def rng(lo, hi, fmt="{:,.0f}"):
    return "n/a" if nan(lo) or nan(hi) else f"{fmt.format(lo)}-{fmt.format(hi)}"


def date(ts):
    """2018-09-16 -> 16 Sep 2018 (day-month order, as written in PH health bulletins)."""
    import pandas as pd

    return pd.Timestamp(ts).strftime("%d %b %Y").lstrip("0")


def shift_label(v, axis):
    if v == 0:
        return "no shift"
    pos, neg = ("north", "south") if axis == "lat" else ("east", "west")
    return f"{abs(v):g}° {pos if v > 0 else neg}"
