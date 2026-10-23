"""Build docs/results/: the evaluation report and the 20-slide deck (both PDF) from the pipeline outputs.

Usage:
    python scripts/make_results.py            # needs a finished `python scripts/build.py`
    python scripts/make_results.py --no-pdf   # figures + HTML only

Reads data/processed/ (panel, app/*) and data/raw/MANIFEST.csv; never the raw data. Figures are drawn with matplotlib
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

OUT = ROOT / "docs" / "results"
FIG = OUT / "figures"
SRC = OUT / "src"
FONTS = SRC / "fonts"

INK, TEAL, AMBER, RED, GREY, GRID, PAPER = "#0F1E28", "#0A86B5", "#C77700", "#C8323F", "#6B7A88", "#DDE3E8", "#FFFFFF"
SEQ = LinearSegmentedColormap.from_list("tide", ["#E6F2F7", "#7FC3DC", TEAL, "#08364A"])


# ---------------------------------------------------------------- data

def load():
    d = dict(
        panel=pd.read_parquet(PROCESSED / "panel.parquet"),
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
    b = s[(s.dlat == 0) & (s.dlon == 0)]
    k["storm_tab"] = b.groupby("storm").agg(cut=("pop_cut", "sum"), A=("A", "mean"), ferries=("ferries_cancelled", "first"),
                                            t3=("tier", lambda t: int((t == 3).sum())), t2=("tier", lambda t: int((t == 2).sum())),
                                            src=("flood_source", "first"), R=("R", "mean"))
    k["top"] = {st: d["names"][g.sort_values("P", ascending=False).unit_id.iloc[0]] for st, g in b.groupby("storm")}
    k["bench"] = d["bench"].share_cut.iloc[0]
    k["tau_min"] = d["sens"].kendall_tau.min()
    k["missing"] = {kk: v["detail"] for kk, v in d["status"].items() if not v["available"]}
    s1 = p.dropna(subset=["s1_flood_frac"])
    k["s1_ok"] = len(s1) > 0
    if k["s1_ok"]:
        w = {key: pd.Timestamp(v["landfall"]) for key, v in STORMS.items()}
        lw = {key: s1[s1.week == s1[s1.week >= t].week.min()] for key, t in w.items()}
        k["s1_tab"] = {key: dict(pop=float(g.s1_flood_pop.sum()), units=int((g.s1_flood_frac > 0.01).sum()),
                                 frac_max=float(g.s1_flood_frac.max()), top=d["names"][g.loc[g.s1_flood_pop.idxmax(), "unit_id"]])
                       for key, g in lw.items() if len(g)}
        k["ems"] = s1_ems_agreement()
    k["src_obs"] = "Sentinel-1 observed flood" if b.flood_source.isin(["sentinel1", "observed"]).any() else "the NOAH 25-yr hazard proxy"
    return k


def s1_ems_agreement():
    """Sentinel-1 (Ompong) vs Copernicus EMSR312 observed flood, inside each EMS AOI's extent, on the S1 100 m grid."""
    import rasterio
    from rasterio import features
    from bantay import flood

    ems = flood.ems_observed_flood("EMSR312")
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


def fig_wis(d):
    e = d["evals"].drop(index="all")
    h = e.index.astype(int)
    fig, ax = plt.subplots(1, 2, figsize=(8.4, 2.9), gridspec_kw={"width_ratios": [1.25, 1]})
    a = ax[0]
    a.plot(h, e["WIS naive"], color=GREY, marker="o", ms=7, label="seasonal naive", ls=(0, (3, 2)))
    a.plot(h, e["WIS xgb_nograph"], color=AMBER, marker="s", ms=7, label="XGBoost, no graph")
    a.plot(h, e["WIS xgb"], color=TEAL, marker="o", ms=7, label="XGBoost + graph")
    for x, y, r in zip(h, e["WIS xgb"], e["relWIS xgb/naive"]):
        a.annotate(f"rel {r:.2f}", (x, y), textcoords="offset points", xytext=(0, -16), ha="center", fontsize=8, fontfamily="Space Mono", color=TEAL)
    a.set_xticks(h)
    a.set_xlim(0.6, 4.4)
    a.set_xlabel("weeks ahead")
    a.set_ylabel("mean WIS (cases)")
    a.set_ylim(0, e["WIS naive"].max() * 1.15)
    a.set_title("Weighted interval score (lower is better)")
    a.legend(fontsize=8, loc="lower right")
    b = ax[1]
    b.axhspan(0.80, 0.95, color=TEAL, alpha=0.08, lw=0)
    b.text(1.0, 0.955, "proposal target 80-95%", fontsize=7.5, color=TEAL)
    b.plot(h, e["cov90 xgb"], color=TEAL, marker="o", ms=7, label="90% interval")
    b.plot(h, e["cov90 conformal"], color=AMBER, marker="D", ms=6, label="90% online conformal")
    b.plot(h, e["cov50 xgb"], color=TEAL, marker="o", ms=7, ls=(0, (1, 1.5)), label="50% interval")
    b.axhline(0.9, color=GREY, lw=0.8)
    b.axhline(0.5, color=GREY, lw=0.8)
    b.set_ylim(0.3, 1.0)
    b.set_xticks(h)
    b.set_xlabel("weeks ahead")
    b.set_title("Empirical coverage")
    b.legend(fontsize=7.5, loc="center right")
    for x in ax:
        mono(x)
    fig.tight_layout()
    return save(fig, "f03_wis")


def fig_reliability(d):
    r = d["rel"]
    fig, ax = plt.subplots(figsize=(3.6, 3.3))
    ax.plot([0, 1], [0, 1], color=GREY, lw=1, ls=(0, (3, 2)))
    ax.plot(r.mean_R, r.observed, color=TEAL, marker="o", ms=7)
    for x, y, n in zip(r.mean_R, r.observed, r.n):
        ax.annotate(f"n={n:,}", (x, y), textcoords="offset points", xytext=(6, -10), fontsize=7.5, fontfamily="Space Mono", color=GREY)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("mean predicted R")
    ax.set_ylabel("observed surge rate")
    ax.set_title("Surge probability R: reliability")
    mono(ax)
    return save(fig, "f04_reliability")


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
    ax.axvline(0.3, color=GREY, lw=0.8, ls=(0, (2, 2)))
    ax.axhline(0.10, color=GREY, lw=0.8, ls=(0, (2, 2)))
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
    """Observed new flood share per unit, landfall week, one map per typhoon (Sentinel-1)."""
    p = d["panel"].dropna(subset=["s1_flood_frac"])
    if p.empty:
        return None
    fig, axs = plt.subplots(1, 4, figsize=(9.6, 3.0))
    vmax = p.s1_flood_frac.quantile(0.99)
    for ax, (k, st) in zip(axs, STORMS.items()):
        t = pd.Timestamp(st["landfall"])
        g = p[p.week == p[p.week >= t].week.min()]
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
    ems = flood.ems_observed_flood("EMSR312")
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


def make_figures(d):
    style()
    return dict(timeline=fig_timeline(d), coverage=fig_coverage(d), wis=fig_wis(d), rel=fig_reliability(d), fan=fig_fan(d),
                leadlag=fig_leadlag(d), priority=fig_priority(d), access=fig_access_multiples(d), scatter=fig_scatter(d),
                valid=fig_validation(d), s1=fig_s1(d), s1ems=fig_s1_ems(d), network=fig_network(d), rolling=fig_rolling(d))


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
    "Buczak, A. L., Baugher, B., Babin, S. M., Ramac-Thomas, L. C., Guven, E., Elbert, Y., Koshute, P. T., Velasco, J. M. S., Roque, V. G., Jr., Tayag, E. A., Yoon, I.-K., & Lewis, S. H. (2014). Prediction of high incidence of dengue in the Philippines. <i>PLoS Neglected Tropical Diseases, 8</i>(4), e2771. https://doi.org/10.1371/journal.pntd.0002771",
    "Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. In <i>Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining</i> (pp. 785–794). https://doi.org/10.1145/2939672.2939785",
    "Copernicus Emergency Management Service. (2018). <i>EMSR312: Typhoon Mangkhut in the Philippines</i> [Rapid mapping activation]. European Commission. https://mapping.emergency.copernicus.eu/activations/EMSR312/",
    "Department of Health Epidemiology Bureau. (2021). <i>DOH-Epi dengue data 2016–2021</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/ac63a95e-7296-42fb-802b-7f7541c73e45",
    "Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., & Michaelsen, J. (2015). The climate hazards infrared precipitation with stations—A new environmental record for monitoring extremes. <i>Scientific Data, 2</i>, 150066. https://doi.org/10.1038/sdata.2015.66",
    "Gibbs, I., & Candès, E. (2021). Adaptive conformal inference under distribution shift. <i>Advances in Neural Information Processing Systems, 34</i>, 1660–1672.",
    "Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. <i>Remote Sensing of Environment, 202</i>, 18–27. https://doi.org/10.1016/j.rse.2017.06.031",
    "Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2023). <i>GPM IMERG final precipitation L3 half hourly 0.1 degree x 0.1 degree V07</i> [Data set]. NASA Goddard Earth Sciences Data and Information Services Center. https://doi.org/10.5067/GPM/IMERG/3B-HH/07",
    "Knapp, K. R., Kruk, M. C., Levinson, D. H., Diamond, H. J., & Neumann, C. J. (2010). The International Best Track Archive for Climate Stewardship (IBTrACS): Unifying tropical cyclone data. <i>Bulletin of the American Meteorological Society, 91</i>(3), 363–376. https://doi.org/10.1175/2009BAMS2755.1",
    "Lehner, B., & Grill, G. (2013). Global river hydrography and network routing: Baseline data and new approaches to study the world's large river systems. <i>Hydrological Processes, 27</i>(15), 2171–2186. https://doi.org/10.1002/hyp.9740",
    "Lundberg, S. M., & Lee, S.-I. (2017). A unified approach to interpreting model predictions. <i>Advances in Neural Information Processing Systems, 30</i>, 4765–4774.",
    "Matsushita, N., Ng, C. F. S., Kim, Y., Suzuki, M., Saito, N., Ariyoshi, K., Salva, E. P., Dimaano, E. M., Villarama, J. B., Go, W. S., & Hashizume, M. (2018). The non-linear and lagged short-term relationship between rainfall and leptospirosis and the intermediate role of floods in the Philippines. <i>PLoS Neglected Tropical Diseases, 12</i>(4), e0006331. https://doi.org/10.1371/journal.pntd.0006331",
    "OpenStreetMap contributors. (2026). <i>OpenStreetMap data extract: Philippines</i> [Data set]. Geofabrik. https://download.geofabrik.de/asia/philippines.html",
    "Page, L., Brin, S., Motwani, R., & Winograd, T. (1999). <i>The PageRank citation ranking: Bringing order to the web</i> (Technical Report 1999-66). Stanford InfoLab.",
    "Petricola, S., Reinmuth, M., Lautenbach, S., Hatfield, C., & Zipf, A. (2022). Assessing road criticality and loss of healthcare accessibility during floods: The case of Cyclone Idai, Mozambique 2019. <i>International Journal of Health Geographics, 21</i>, 14. https://doi.org/10.1186/s12942-022-00315-2",
    "Philippine Statistics Authority. (2021). <i>Philippines: 2020 census of population and housing, population by municipality</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/c1edf0c5-58c8-4d39-b566-937b1ad7907f",
    "Philippine Statistics Authority & National Mapping and Resource Information Authority. (2025). <i>Philippines: Subnational administrative boundaries (COD-AB)</i> [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/caf116df-f984-4deb-85ca-41b349d3f313",
    "Runge, J. (2020). Discovering contemporaneous and lagged causal relations in autocorrelated nonlinear time series datasets. In <i>Proceedings of the 36th Conference on Uncertainty in Artificial Intelligence</i> (PMLR 124, pp. 1388–1397). https://arxiv.org/abs/2003.03685",
    "Runge, J., Nowack, P., Kretschmer, M., Flaxman, S., & Sejdinovic, D. (2019). Detecting and quantifying causal associations in large nonlinear time series datasets. <i>Science Advances, 5</i>(11), eaau4996. https://doi.org/10.1126/sciadv.aau4996",
    "Tariverdi, M., Nunez-del-Prado, M., Leonova, N., & Rentschler, J. (2023). Measuring accessibility to public services and infrastructure criticality for disasters risk management. <i>Scientific Reports, 13</i>, 1569. https://doi.org/10.1038/s41598-023-28460-z",
    "Tatem, A. J. (2017). WorldPop, open data for spatial demography. <i>Scientific Data, 4</i>, 170004. https://doi.org/10.1038/sdata.2017.4",
    "Tellman, B., Sullivan, J. A., Kuhn, C., Kettner, A. J., Doyle, C. S., Brakenridge, G. R., Erickson, T. A., & Slayback, D. A. (2021). Satellite imaging reveals increased proportion of population exposed to floods. <i>Nature, 596</i>, 80–86. https://doi.org/10.1038/s41586-021-03695-w",
    "UN-SPIDER. (n.d.). <i>Recommended practice: Flood mapping and damage assessment using Sentinel-1 SAR data in Google Earth Engine</i>. United Nations Office for Outer Space Affairs. https://www.un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping",
    "van Panhuis, W. G., Choisy, M., Xiong, X., Chok, N. S., Akarasewi, P., Iamsirithaworn, S., Lam, S. K., Chong, C. K., Lam, F. C., Phommasak, B., Vongphrachanh, P., Bouaphanh, K., Rekol, H., Hien, N. T., Thai, P. Q., Duong, T. N., Chuang, J.-H., Liu, Y.-L., Ng, L.-C., ... Burke, D. S. (2015). Region-wide synchrony and traveling waves of dengue across eight countries in Southeast Asia. <i>Proceedings of the National Academy of Sciences, 112</i>(42), 13069–13074. https://doi.org/10.1073/pnas.1501375112",
    "Weiss, D. J., Nelson, A., Vargas-Ruiz, C. A., Gligorić, K., Bavadekar, S., Gabrilovich, E., Bertozzi-Villa, A., Rozier, J., Gibson, H. S., Shekel, T., Kamath, C., Lieber, A., Schulman, K., Shao, Y., Qarkaxhija, V., Nandi, A. K., Keddie, S. H., Rumisha, S., Amratia, P., ... Gething, P. W. (2020). Global maps of travel time to healthcare facilities. <i>Nature Medicine, 26</i>, 1835–1838. https://doi.org/10.1038/s41591-020-0931-3",
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
        "meta_hrsl": ("Meta HRSL under-5 / 60+", "vulnerability (not yet used)", "HDX"),
        "osm": ("OpenStreetMap Philippines PBF", "road network", "Geofabrik"),
        "roroph": ("roroph RoRo routes (108)", "ferry edges (2024–26 proxy)", "pinasr/roroph"),
        "hotosm_health": ("HOT OSM health facilities", "hospital nodes (fallback)", "HDX"),
        "noah_facilities": ("UP NOAH critical facilities", "hospital nodes (fallback)", "UP NOAH"),
        "map_friction": ("MAP friction surface 2019", "raster access (wired next)", "Earth Engine"),
        "gfd": ("Global Flood Database events", "context (ends 2018)", "Earth Engine"),
        "sentinel1": ("Sentinel-1 scene inventory", "flood-mapping plan", "Earth Engine"),
        "cchain": ("Project CCHAIN PIDSR city-week", "leptospirosis (stretch)", "HDX"),
        "mendeley_parreno": ("Parreño national weekly notifiable diseases", "cross-check", "Mendeley Data"),
        "opendengue": ("OpenDengue V1.3", "national cross-check", "OpenDengue"),
    }
    rows = []
    for src, (desc, role, where) in meta.items():
        if src in m.index:
            rows.append(f"<tr><td class='mono'>{src}</td><td>{desc}</td><td>{role}</td><td>{where}</td>"
                        f"<td class='n'>{int(m.loc[src, 'files'])}</td><td class='n'>{'&lt;1' if m.loc[src, 'mb'] < 1 else f'{m.loc[src, "mb"]:,.0f}'}</td></tr>")
    for src, desc, role, where in [("s1_flood", "Sentinel-1 flood masks per typhoon (UN-SPIDER)", "observed flood", "Earth Engine"),
                                   ("psgc", "PSA PSGC 2Q 2026", "pcode check", "manual"), ("nhfr", "DOH NHFR", "hospital list", "manual")]:
        rows.append(f"<tr class='pend'><td class='mono'>{src}</td><td>{desc}</td><td>{role}</td><td>{where}</td><td class='n'>–</td><td class='n'>pending</td></tr>")
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


def demo_script_html():
    """docs/results/Bantay-Baha_Demo_Script.md -> HTML in the deck's style (the markdown stays the editable source)."""
    md = (OUT / "Bantay-Baha_Demo_Script.md").read_text(encoding="utf-8").splitlines()
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
            extra.append(f"<h2>{_md_inline(line[3:])}</h2><ul>")
        elif line.startswith("- "):
            extra.append(f"<li>{_md_inline(line[2:])}</li>")
    if extra:
        extra.append("</ul>")
    head = title.split(":", 1)
    h1 = f"{head[0]}: <em>{head[1].strip()}</em>" if len(head) == 2 else title
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{FONT_CSS}{SCRIPT_CSS}</style></head><body>"
            f"<div class='head'><h1>{h1}</h1><span class='tag'>PJDSC 2026 / demonstration video</span></div>"
            f"<p class='intro'>{_md_inline(' '.join(intro))}</p>"
            f"<table class='script'><tr><th>time</th><th>on screen</th><th>narration</th></tr>{''.join(rows)}</table>{''.join(extra)}</body></html>")


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
    F = make_figures(d)
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
    if (OUT / "Bantay-Baha_Demo_Script.md").exists():
        demo = SRC / "demo_script.html"
        demo.write_text(demo_script_html(), encoding="utf-8")
        if pdf:
            to_pdf(demo, OUT / "Bantay-Baha_Demo_Script.pdf")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pdf", action="store_true")
    main(pdf=not ap.parse_args().no_pdf)
