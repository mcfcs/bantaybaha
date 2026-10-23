"""Leptospirosis tab: lag profile, weekly cases and rain, typhoon event study (files from `build.py lepto`).

Reads only what the build wrote: lepto_city_lag.csv, lepto_national_lag.csv, lepto_weekly.parquet, lepto_events*.csv.
Every number on screen, including the findings line, comes from those files.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

CAPTION = "12 cities (CCHAIN), not provincial; association, not forecast."
# exposure toggle -> (city exposure, national exposure); main variants of each analysis
EXPOSURES = {"Rain": ("rain_7d", "rain_7d"), "Heavy-rain week": ("heavy", "heavy"),
             "Gale": ("storm_gale_hit", "gale_pop_share")}
CITY_VARIANT, NAT_VARIANT = "12 cities", "2019-2020"
PERIODS = {"pre": "Before landfall\n(placebo)", "k0": "Landfall week", "post1_4": "Weeks +1 to +4",
           "late5_8": "Weeks +5 to +8"}
POOLS = {"ompong+tisoy": "Ompong + Tisoy", "rolly+ulysses": "Rolly + Ulysses", "ompong+rolly+tisoy+ulysses": "All four"}


def _profile(lag, variant, exposure):
    d = lag[(lag.model == "joint") & (lag.variant == variant) & (lag.exposure == exposure)]
    return d[d.lag.notna()].sort_values("lag"), d[d.term.astype(str).str.startswith("cum")]


def _ci(r):
    return f"{r.irr:.2f} ({r.ci_lo:.2f}-{r.ci_hi:.2f})"


def findings(L):
    """One plain sentence per analysis, read from the files."""
    out = []
    for key, variant, who in (("lepto_city_lag", CITY_VARIANT, "In the 12 cities (2016-2020)"),
                              ("lepto_national_lag", NAT_VARIANT, "Nationally (2019-2020)")):
        lag = L.get(key)
        if lag is None:
            continue
        prof, cum = _profile(lag, variant, "rain_7d")
        if len(prof):
            p = prof.loc[prof.irr.idxmax()]
            out.append(f"{who}, cases rise most {int(p.lag)} weeks after rain: IRR {_ci(p)} per +50 mm/week"
                       + (f", {_ci(cum.iloc[0])} over lags 0-6" if len(cum) else "") + ".")
    did = L.get("lepto_events_did")
    if did is not None:
        g = did.set_index(["storms", "term"])
        try:
            ru, ot = g.loc[("rolly+ulysses", "inside_x_post1_4")], g.loc[("ompong+tisoy", "inside_x_post1_4")]
            otp = g.loc[("ompong+tisoy", "inside_x_pre")]
            out.append(f"Typhoon event study is mixed: 1-4 weeks after Rolly + Ulysses, cities inside the gale swath "
                       f"had {_ci(ru)} times the outside cities' excess; after Ompong + Tisoy {_ci(ot)}, but there the "
                       f"placebo before landfall already shows {_ci(otp)}.")
        except KeyError:
            pass
    return out


def render(L, weekly, pal):
    st.info(CAPTION + " Rates are incidence-rate ratios (IRR): 1 = no change.", icon=":material/info:")
    for line in findings(L):
        st.markdown(f"- {line}")
    lag_profile(L, pal)
    weekly_chart(weekly, L.get("lepto_events"), pal)
    event_study(L, pal)


def lag_profile(L, pal):
    st.header("How many weeks after rain do cases rise?")
    pick = st.radio("Exposure", list(EXPOSURES), horizontal=True, key="lepto_exposure",
                    help="Rain: per +50 mm/week. Heavy-rain week: a week at or above the place's 90th percentile. "
                         "Gale: city inside a gale circle that week (cities); share of people in a gale swath (national).")
    ce, ne = EXPOSURES[pick]
    fig = go.Figure()
    fig.add_hline(y=1, line=dict(color=pal["rule"], width=1, dash="dot"))
    sums = []
    for i, (key, variant, exp, name) in enumerate((("lepto_city_lag", CITY_VARIANT, ce, "12 cities"),
                                                   ("lepto_national_lag", NAT_VARIANT, ne, "National"))):
        lag = L.get(key)
        if lag is None:
            continue
        prof, cum = _profile(lag, variant, exp)
        if not len(prof):
            continue
        unit = prof.irr_unit.iloc[0]
        fig.add_trace(go.Scatter(
            x=prof.lag + (i - 0.5) * 0.16, y=prof.irr, mode="markers+lines", name=f"{name} (per {unit})",
            line=dict(color=pal["cat"][i], width=2), marker=dict(size=9, color=pal["cat"][i],
                                                                 line=dict(width=1.5, color=pal["unit_line"])),
            error_y=dict(type="data", symmetric=False, array=prof.ci_hi - prof.irr, arrayminus=prof.irr - prof.ci_lo,
                         thickness=1.5, width=4, color=pal["cat"][i]),
            customdata=np.stack([prof.lag, prof.ci_lo, prof.ci_hi], axis=1),
            hovertemplate=f"{name}<br>lag %{{customdata[0]:.0f}} wk: IRR %{{y:.2f}} "
                          "(%{customdata[1]:.2f}-%{customdata[2]:.2f})<extra></extra>"))
        if len(cum):
            sums.append(f"{name}: {_ci(cum.iloc[0])} over lags 0-6")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.12, x=0),
                      xaxis=dict(title="Weeks after the exposure", dtick=1, gridcolor="rgba(128,128,128,.15)"),
                      yaxis=dict(title="IRR (log scale, 95% CI)", type="log", gridcolor="rgba(128,128,128,.15)"))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="lepto_lag")
    st.caption("Joint distributed-lag model (lags 0-6 fitted together). Lags are collinear: read the shape and the "
               "cumulative effect, not single bars. " + "; ".join(sums) + ".")


def weekly_chart(w, events, pal):
    st.header("Weekly cases and rain")
    if w is None or not len(w):
        st.info("Weekly series not built (`build.bat lepto`).")
        return
    places = w[["level", "id", "name"]].drop_duplicates()
    places = pd.concat([places[places.level == "national"], places[places.level != "national"].sort_values("name")])
    labels = {r.id: ("Philippines (national, 2019-2020)" if r.level == "national" else r.name)
              for r in places.itertuples()}
    pid = st.selectbox("Place", list(labels), format_func=labels.get, key="lepto_place")
    d = w[w.id == pid].sort_values("week")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.06)
    inc = d.incomplete.astype("boolean").fillna(False).to_numpy(dtype=bool) if "incomplete" in d else np.zeros(len(d), bool)
    fig.add_trace(go.Bar(x=d.week, y=d.cases, name="Cases per week", marker_color=np.where(inc, pal["seq"][1], pal["seq"][4]),
                         hovertemplate="%{x|%d %b %Y}: %{y:.0f} cases<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.week, y=d.rain_7d, name="Rain (mm/week)", mode="lines",
                             line=dict(color=pal["cat"][2], width=1.5),
                             hovertemplate="%{x|%d %b %Y}: %{y:.0f} mm<extra></extra>"), row=2, col=1)
    if events is not None and len(events):
        lf = events[["storm_name", "landfall"]].drop_duplicates()
        lf = lf.assign(landfall=pd.to_datetime(lf.landfall))
        lf = lf[(lf.landfall >= d.week.min()) & (lf.landfall <= d.week.max())]
        for i, r in enumerate(lf.itertuples()):
            for row in (1, 2):
                fig.add_vline(x=r.landfall, line=dict(color=pal["track"], width=1, dash="dash"), row=row, col=1)
            fig.add_annotation(x=r.landfall, y=1, yref="paper", text=r.storm_name, showarrow=False, yanchor="bottom",
                               xanchor="left" if i % 2 == 0 else "right", font=dict(size=11))
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=24, b=10), plot_bgcolor="rgba(0,0,0,0)", bargap=0.1,
                      legend=dict(orientation="h", y=-0.12, x=0), hovermode="x unified")
    fig.update_yaxes(title_text="Cases", row=1, col=1, gridcolor="rgba(128,128,128,.15)", rangemode="tozero")
    fig.update_yaxes(title_text="mm/week", row=2, col=1, gridcolor="rgba(128,128,128,.15)", rangemode="tozero")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="lepto_weekly")
    note = "Dashed lines: landfall of the four backtest typhoons."
    if inc.any():
        note += " Lighter bars: weeks that look incompletely reported."
    st.caption(note)


def event_study(L, pal):
    st.header("Did cities inside a typhoon's gale swath see more cases?")
    did = L.get("lepto_events_did")
    if did is None or not len(did):
        st.info("Event study not built.")
        return
    d = did.assign(period=did.term.str.replace("inside_x_", "", regex=False))
    order = list(PERIODS)
    fig = go.Figure()
    fig.add_vrect(x0=-0.5, x1=0.5, fillcolor=pal["band"], line_width=0, layer="below")
    fig.add_annotation(x=0, y=1, yref="paper", yanchor="bottom", showarrow=False, font=dict(size=11),
                       text="Placebo: before landfall, should be about 1")
    fig.add_hline(y=1, line=dict(color=pal["rule"], width=1, dash="dot"))
    for i, (key, name) in enumerate(POOLS.items()):
        g = d[d.storms == key].set_index("period").reindex(order).dropna(subset=["irr"])
        if not len(g):
            continue
        x = np.array([order.index(p) for p in g.index]) + (i - 1) * 0.18
        fig.add_trace(go.Scatter(
            x=x, y=g.irr, mode="markers", name=name,
            marker=dict(size=10, color=pal["cat"][i], symbol=["circle-open" if p == "pre" else "circle" for p in g.index],
                        line=dict(width=2, color=pal["cat"][i])),
            error_y=dict(type="data", symmetric=False, array=g.ci_hi - g.irr, arrayminus=g.irr - g.ci_lo,
                         thickness=1.5, width=4, color=pal["cat"][i]),
            customdata=np.stack([g.ci_lo, g.ci_hi, [PERIODS[p].replace("\n", " ") for p in g.index]], axis=1),
            hovertemplate=f"{name}, %{{customdata[2]}}<br>ratio %{{y:.2f}} (%{{customdata[0]:.2f}}-"
                          "%{customdata[1]:.2f})<extra></extra>"))
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=-0.18, x=0),
                      xaxis=dict(tickmode="array", tickvals=list(range(len(order))),
                                 ticktext=[PERIODS[p].replace("\n", "<br>") for p in order], range=[-0.6, len(order) - 0.4]),
                      yaxis=dict(title="Inside / outside, obs/exp (log, 95% CI)", type="log",
                                 tickvals=[0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200],
                                 ticktext=["0.1", "0.2", "0.5", "1", "2", "5", "10", "20", "50", "100", "200"],
                                 gridcolor="rgba(128,128,128,.15)"))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key="lepto_events")
    st.caption("Ratio of observed to expected cases in cities inside the gale swath, over the same ratio outside "
               "(quasi-Poisson, storm x week effects). Hollow markers are the placebo period. Rolly and Ulysses landed "
               "10 days apart, so their windows overlap.")
    r = L.get("lepto_events_ratio")
    if r is not None and len(r):
        with st.expander("Per-storm ratios"):
            t = r.assign(period=r.period.map(lambda p: PERIODS.get(p, p).replace("\n", " ")),
                         storm=r.storm.str.title())
            st.dataframe(t[["storm", "period", "ratio", "ci_lo", "ci_hi"]], hide_index=True, width="stretch",
                         key="lepto_ratio", column_config={
                             "storm": "Typhoon", "period": "Period",
                             "ratio": st.column_config.NumberColumn("Inside / outside", format="%.2f"),
                             "ci_lo": st.column_config.NumberColumn("95% CI low", format="%.2f"),
                             "ci_hi": st.column_config.NumberColumn("95% CI high", format="%.2f")})
