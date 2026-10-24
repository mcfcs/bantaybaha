"""Build the LaTeX technical specification (docs/spec/) from the pipeline outputs.

Usage:
    python scripts/make_spec.py            # write docs/spec/generated/*.tex, compile with latexmk, copy the PDF
    python scripts/make_spec.py --no-pdf   # write the generated .tex files only

The prose lives in docs/spec/sections/*.tex and quotes results only through macros. This script computes them with
make_results.stats() (the same numbers as the evaluation report) and writes:
  docs/spec/generated/numbers.tex   one \\newcommand per number or data fact, with a comment naming its source
  docs/spec/generated/tab_*.tex     table bodies (rows only), reusing make_results' row builders
The figures are the PNGs make_results.py draws in docs/results/figures/ (run it first after a rebuild). The compiled PDF
is copied to docs/results/Bantay-Baha_Technical_Spec.pdf. A value whose output is missing prints as "n/a" and is listed
at the end.
"""

import argparse
import html
import inspect
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402

import make_results as MR  # noqa: E402
from bantay import forecast, leadlag, access, lepto, scenarios  # noqa: E402
from bantay.config import STORMS, QUANTILES, S1_AFTER_DAYS  # noqa: E402
from bantay.scenarios import TIERS, SHIFTS  # noqa: E402

SPEC = ROOT / "docs" / "spec"
GEN = SPEC / "generated"
PDF = ROOT / "docs" / "results" / "Bantay-Baha_Technical_Spec.pdf"
NA = r"\textit{n/a}"
NAME = re.compile(r"^[A-Za-z]+$")
STORM_MACRO = {k: s["local"] for k, s in STORMS.items()}  # ompong -> Ompong, used as a macro suffix
GAP_BINS = (0.1, 0.7)  # "middle" reliability bins of R, as in the evaluation report's calibration page
COV_TARGET = (0.80, 0.95)  # the proposal's target band for 90% interval coverage
HELPS = 0.98  # a feature group "helps" when it lowers WIS by more than 2% (relative WIS with / without below this)
SAME = 0.01  # two relative WIS values closer than this are "the same within seed noise"
ALIKE = 0.7  # a Spearman correlation at or above this counts as "ranking alike"
STABLE_TAU = 0.95  # Kendall's tau at or above this: a setting change does not reorder the ranking


# ---------------------------------------------------------------- formatting

def f(x, d=2):
    """Fixed decimals; raises on NaN so the caller prints n/a."""
    x = float(x)
    if math.isnan(x):
        raise ValueError("NaN")
    return re.sub(r"^-", "$-$", f"{x:.{d}f}")


def pct(x, d=0):
    return f(100 * float(x), d) + r"\%"


def thou(n):
    """Integer with a TeX thousands separator: 34{,}050."""
    return f"{int(round(float(n))):,}".replace(",", "{,}")


def mil(x, d=1):
    return f(float(x) / 1e6, d) + "~M"


def kilo(x):
    return thou(float(x) / 1e3) + "k"


def rng(lo, hi, fmt=lambda v: f(v, 2), unit=""):
    """'a' or 'a--b' (en dash), unit appended once."""
    a, b = fmt(lo), fmt(hi)
    return (a if a == b else f"{a}--{b}") + unit


def lst(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def ci(row, d=2):
    """IRR with its 95% interval: 1.40 (1.29--1.52)."""
    return f"{f(row.irr, d)} ({f(row.ci_lo, d)}--{f(row.ci_hi, d)})"


def date(s):
    t = pd.Timestamp(s)
    return f"{t.day} {t.strftime('%B %Y')}"


TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
UNICODE = {"τ": r"$\tau$", "ρ": r"$\rho$", "≥": r"$\geq$", "≤": r"$\leq$", "×": r"$\times$", "Σ": r"$\Sigma$",
           "†": r"\textsuperscript{\dag}", "◆": r"$\blacklozenge$", "–": "--", "—": "---", "²": r"\textsuperscript{2}",
           "°": r"\textdegree{}", "±": r"$\pm$", "→": r"$\rightarrow$"}


def esc(s):
    """Plain text -> LaTeX: escape specials, map the few Unicode symbols the row builders use."""
    s = "".join(TEX_ESC.get(c, c) for c in str(s))
    for a, b in UNICODE.items():
        s = s.replace(a, b)
    return s


def cell(h):
    """One HTML table cell from make_results' row builders -> LaTeX (bold kept, other tags dropped)."""
    h = re.sub(r"<b>(.*?)</b>", "\x01\\1\x02", h)
    h = re.sub(r"<span class='mono'[^>]*>(.*?)</span>", r"(\1)", h)
    h = re.sub(r"<[^>]+>", "", h)
    s = esc(html.unescape(h).strip())
    s = s.replace("\x01", r"\textbf{").replace("\x02", "}")
    # numeric ranges: hyphen -> en dash, but leave ISO dates alone
    s = re.sub(r"(?<![\d-])(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?![\d-])", r"\1--\2", s)
    return re.sub(r"(?<![\w-])-(?=\d)", "$-$", s)  # a leading minus sign, not a hyphen or dash


def html_rows(rows_html, cols=None):
    """<tr><td>...</td></tr> rows -> 'a & b \\\\' lines. Header rows are skipped; bold rows stay bold; a 'tot' row gets a rule."""
    out = []
    for attrs, body in re.findall(r"<tr([^>]*)>(.*?)</tr>", rows_html, re.S):
        if "<th" in body:
            continue
        cells = [cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        if cols:
            cells = [cells[i] for i in cols]
        if "font-weight:700" in attrs or "tot" in attrs:
            cells = [c if c.startswith(r"\textbf{") else rf"\textbf{{{c}}}" for c in cells]
        out.append((r"\midrule" + "\n" if "tot" in attrs else "") + " & ".join(cells) + r" \\")
    return "\n".join(out)


# ---------------------------------------------------------------- macros

class Macros:
    """Ordered {name: (tex, source)}; a value that cannot be computed becomes n/a and is reported."""

    def __init__(self):
        self.m, self.na, self.flags = {}, [], {}

    def flag(self, name, fn, src=""):
        """A TeX conditional \\if<name>: the prose writes \\if<name> ... \\else ... \\fi, so a qualitative claim
        follows the numbers. A condition that cannot be evaluated is false and reported."""
        if not NAME.match(name) or name in self.flags:
            raise ValueError(f"flag name {name!r}: letters only, defined once")
        try:
            v = bool(fn() if callable(fn) else fn)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
            v = False
            self.na.append(f"flag {name} ({type(e).__name__}: {e})")
        self.flags[name] = (v, src)

    def put(self, name, fn, src=""):
        if not NAME.match(name):
            raise ValueError(f"macro name {name!r}: letters only")
        if name in self.m:
            raise ValueError(f"macro {name} defined twice")
        try:
            v = fn() if callable(fn) else fn
            v = str(v)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
            v = NA
            self.na.append(f"{name} ({type(e).__name__}: {e})")
        self.m[name] = (v, src)

    def tex(self):
        lines = ["% Generated by scripts/make_spec.py from data/processed/ -- do not edit by hand; re-run the script.",
                 "% Every result quoted in docs/spec/sections/*.tex is one of these macros.", ""]
        for name, (v, src) in self.m.items():
            lines.append(rf"\newcommand{{\{name}}}{{{v}}}" + (f" % {src}" if src else ""))
        lines += ["", "% Conditions behind qualitative claims: \\if<Name> ... \\else ... \\fi in the prose."]
        for name, (v, src) in self.flags.items():
            lines.append(rf"\newif\if{name}\{name}{'true' if v else 'false'}" + (f" % {src}" if src else ""))
        return "\n".join(lines) + "\n"


def defaults(fn, *names):
    p = inspect.signature(fn).parameters
    return [p[n].default for n in names]


def put_data(M, k, d):
    M.put("nFiles", lambda: thou(k["n_files"]), "data/raw/MANIFEST.csv rows")
    M.put("nSources", lambda: k["n_sources"], "MANIFEST.csv sources")
    M.put("dataGB", lambda: f(k["gb"], 1), "MANIFEST.csv bytes / 1e9")
    M.put("nUnits", lambda: k["n_units"], "panel.parquet units")
    M.put("nWeeks", lambda: k["n_weeks"], "panel.parquet weeks")
    M.put("unitWeeks", lambda: thou(k["unit_weeks"]), "panel.parquet rows")
    M.put("dgUnits", lambda: k["dg_units"], "raw DOH dengue CSV: loc.nunique()")
    M.put("cfrSixteen", lambda: pct(k["cfr16"], 1), "raw DOH dengue CSV: 2016 deaths / cases")
    cy = k.get("cases_by_year", {})
    M.put("casesTwentyNineteen", lambda: kilo(cy[2019]), "raw DOH dengue CSV")
    M.put("casesTwentyTwenty", lambda: kilo(cy[2020]), "raw DOH dengue CSV")
    M.put("popM", lambda: f(k["pop"] / 1e6, 2) + "~M", "panel.parquet pop")
    M.put("rainR", lambda: f(k["rain_r"], 2), "panel: corr(chirps_7d, imerg_7d)")
    M.put("hazUnits", lambda: k["haz_units"], "panel: units with a NOAH 25-yr map")
    M.put("hazMedian", lambda: pct(k["haz_median"]), "panel: median hazard_any_25yr")
    M.put("nHazNoMap", lambda: len(k["haz_nomap"]), "panel: units without a NOAH 25-yr map")
    M.put("hazNoMapList", lambda: lst(esc(x) for x in k["haz_nomap"]), "panel")
    M.put("rThirtyFourMissingRolly", lambda: pct(k["r34_missing"]["rolly"]), "IBTrACS: Rolly gale fixes without USA R34")
    M.put("galeFallbackKm", lambda: f(defaults(scenarios.run_all, "fixed_km")[0], 0), "scenarios.run_all fixed_km")
    M.put("nHosp", lambda: thou(k["n_hosp"]), "hospitals.parquet")
    M.put("nFerry", lambda: k["n_ferry"], "ferries.parquet")
    M.put("nAdmThree", lambda: thou(k["n_adm3"]), "scenarios_adm3.parquet municipalities")
    M.put("susN", lambda: k["sus_n"], "data/processed/sus/sus_responses.csv")


def put_methods(M, k):
    tau, pc_alpha, alpha = defaults(leadlag.pcmci_graph, "tau_max", "pc_alpha", "alpha")
    M.put("tauMax", tau, "leadlag.pcmci_graph tau_max")
    M.put("pcAlpha", pc_alpha, "leadlag.pcmci_graph pc_alpha")
    M.put("fdrQ", alpha, "leadlag.pcmci_graph alpha (BH q)")
    M.put("nQuantiles", len(QUANTILES), "config.QUANTILES")
    M.put("horizons", f"{min(forecast.HORIZONS)}--{max(forecast.HORIZONS)}", "forecast.HORIZONS")
    M.put("surgePctl", f"{forecast.SURGE_PCTL * 100:.0f}th", "forecast.SURGE_PCTL")
    M.put("refitWeeks", defaults(forecast.rolling_origin, "refit_weeks")[0], "forecast.rolling_origin refit_weeks")
    M.put("nRefits", lambda: len(forecast.refit_dates()), "forecast.refit_dates()")
    M.put("calMinRows", thou(forecast.CAL_MIN_ROWS), "forecast.CAL_MIN_ROWS")
    ratio, extra = defaults(access.cut_off, "ratio", "extra_h")
    M.put("cutRatio", f(ratio, 0), "access.cut_off ratio")
    M.put("cutExtraH", f(extra, 0), "access.cut_off extra_h")
    M.put("sOneAfterDays", S1_AFTER_DAYS, "config.S1_AFTER_DAYS")
    lat = sorted({abs(a) for a, _ in SHIFTS if a})
    lon = sorted({abs(b) for _, b in SHIFTS if b})
    M.put("nTracks", len(SHIFTS), "scenarios.SHIFTS")
    M.put("nShifted", len(SHIFTS) - 1, "scenarios.SHIFTS without (0, 0)")
    M.put("shiftLat", lst([f"{x:g}" for x in lat]), "scenarios.SHIFTS latitude steps (degrees)")
    M.put("shiftLon", lst([f"{x:g}" for x in lon]), "scenarios.SHIFTS longitude steps (degrees)")
    M.put("tierPreR", f"{TIERS['preposition_R']:g}", "scenarios.TIERS preposition_R")
    M.put("tierDeployR", f"{TIERS['deploy'][0]:g}", "scenarios.TIERS deploy R")
    M.put("tierDeployA", pct(TIERS["deploy"][1]), "scenarios.TIERS deploy A")
    M.put("minHistory", scenarios.CATALOG_MIN_HISTORY_WEEKS, "scenarios.CATALOG_MIN_HISTORY_WEEKS")
    M.put("leptoRainPer", f(lepto.RAIN_PER, 0), "lepto.RAIN_PER (mm/week per IRR unit)")
    M.put("leptoMaxLag", max(lepto.LAGS), "lepto.LAGS")
    M.put("leptoHeavyPctl", f"{lepto.HEAVY_Q * 100:.0f}th", "lepto.HEAVY_Q")


def put_forecast(M, k):
    e = k["ev"]
    M.put("nScored", lambda: thou(k["n_scored"]), "eval_summary.csv n (all)")
    M.put("relWIS", lambda: f(k["relwis"], 3), "eval_summary.csv relWIS xgb/naive (all)")
    M.put("covNinety", lambda: f(k["cov90"], 2), "eval_summary.csv cov90 xgb (all)")
    M.put("covFifty", lambda: f(k["cov50"], 2), "eval_summary.csv cov50 xgb (all)")
    M.put("relWISDiffPct", lambda: pct(abs(1 - k["relwis"])), "|1 - relWIS|: WIS difference to seasonal naive")
    for i, w in enumerate(("One", "Two", "Three", "Four")):
        M.put(f"relWISH{w}", lambda i=i: f(e.iloc[i]["relWIS xgb/naive"], 2), f"eval_summary.csv relWIS xgb/naive, horizon {i + 1}")
    M.put("covNinetyRange", lambda: rng(e.drop(index="all")["cov90 xgb"].min(), e.drop(index="all")["cov90 xgb"].max()), "eval_summary.csv cov90 by horizon")
    M.put("covFiftyRange", lambda: rng(e.drop(index="all")["cov50 xgb"].min(), e.drop(index="all")["cov50 xgb"].max()), "eval_summary.csv cov50 by horizon")
    M.put("covNinetyHFour", lambda: f(e.iloc[3]["cov90 xgb"], 2), "eval_summary.csv cov90 xgb, horizon 4")
    M.put("relWISGraph", lambda: f(k["relwis_graph"], 3), "eval_summary.csv relWIS xgb/nograph")
    M.put("relWISEnv", lambda: f(k["relwis_env"], 3), "eval_summary.csv relWIS xgb/noenv")
    M.put("relWISNoEnv", lambda: f(k["relwis_noenv"], 3), "eval_summary.csv relWIS noenv/naive")
    M.put("edgesEighteen", lambda: rng(*k["edges_by_year"][2018], fmt=str), "eval_graphs.csv 2018 windows")
    M.put("edgesNineteen", lambda: rng(*k["edges_by_year"][2019], fmt=str), "eval_graphs.csv 2019 windows")


def put_models(M, k):
    al, bo = k.get("mall"), k.get("bench_only", [])
    M.put("nCommon", lambda: thou(k["n_common"]), "eval_models.csv n")
    M.put("ensRelWIS", lambda: f(al.loc["ens_median", "relWIS_vs_naive"], 3), "eval_models.csv ens_median")
    M.put("ensCovNinety", lambda: pct(al.loc["ens_median", "cov90"]), "eval_models.csv ens_median cov90")
    M.put("benchRelWISRange", lambda: rng(al.loc[bo, "relWIS_vs_naive"].min(), al.loc[bo, "relWIS_vs_naive"].max(), fmt=lambda v: f(v, 3)), "eval_models.csv benchmarks")
    M.put("mwXGB", lambda: f(k["mw"]["xgb"], 2), "median WIS, eval_quantiles.parquet re-scored")
    M.put("mwEns", lambda: f(k["mw"]["ens_median"], 2), "median WIS")
    M.put("mwBenchRange", lambda: rng(min(k["mw"][x] for x in bo), max(k["mw"][x] for x in bo)), "median WIS of the benchmarks")
    sp = k.get("split", {})
    M.put("splitThr", lambda: f(sp["thr"], 0), "90th percentile of weekly cases on the scored rows")
    M.put("splitLoRange", lambda: rng(min(sp["lo"][x] for x in bo), max(sp["lo"][x] for x in bo)), "benchmark / XGBoost mean WIS below the split")
    M.put("splitHiRange", lambda: rng(min(sp["hi"][x] for x in bo), max(sp["hi"][x] for x in bo)), "benchmark / XGBoost mean WIS above the split")
    M.put("ensSplitLo", lambda: f(sp["lo"]["ens_median"], 2), "ensemble / XGBoost below the split")
    M.put("ensSplitHi", lambda: f(sp["hi"]["ens_median"], 2), "ensemble / XGBoost above the split")
    var = k.get("variants", {})
    M.put("chronosLogRelWIS", lambda: f(var["chronos2_log1p"], 0), "bench_summary.csv chronos2_log1p")
    M.put("chronosNoCovRelWIS", lambda: f(var["chronos2_nocov"], 3), "bench_summary.csv chronos2_nocov")
    M.put("tabpfnLagCovRelWIS", lambda: f(var["tabpfn_ts_lagcov"], 3), "bench_summary.csv tabpfn_ts_lagcov")
    M.put("mpnnNoneRelWIS", lambda: f(var["mpnn_lstm_none"], 3), "bench_summary.csv mpnn_lstm_none")
    adj = lambda: k["bench_meta"]["mpnn_lstm"]["adjacency"]  # noqa: E731
    M.put("mpnnBorderEdges", lambda: adj()["n_border"], "bench_mpnn_lstm.json adjacency")
    M.put("mpnnFerryEdges", lambda: adj()["n_ferry_new_edges"], "bench_mpnn_lstm.json adjacency")


def put_calibration(M, k, d):
    cal = k.get("calib", {})
    a_ = cal.get("all_rows", {})
    M.put("brierRaw", lambda: f(a_["brier_raw"], 3), "surge_calibration.json all_rows")
    M.put("brierCal", lambda: f(a_["brier_cal"], 3), "surge_calibration.json all_rows")
    M.put("brierClim", lambda: f(a_["brier_climatology"], 3), "surge_calibration.json all_rows")
    M.put("baseRatePct", lambda: pct(a_["base_rate"]), "surge_calibration.json all_rows base_rate")
    M.put("nUncalOrigins", lambda: len(cal["uncalibrated_origins"]), "surge_calibration.json")
    M.put("nUncalRows", lambda: thou(cal["n_uncalibrated"]), "surge_calibration.json")
    M.put("firstCalOrigin", lambda: date(cal["first_calibrated_origin"]), "surge_calibration.json")
    r = d["rel"]

    lo, hi = GAP_BINS

    def gap(mean, obs):
        m = r[(r[mean] > lo) & (r[mean] <= hi)]
        return pct((m[obs] - m[mean]).abs().max())

    M.put("gapBinLo", f"{lo:g}", "middle reliability bins, lower edge (GAP_BINS)")
    M.put("gapBinHi", f"{hi:g}", "middle reliability bins, upper edge (GAP_BINS)")
    M.put("gapRaw", lambda: gap("mean_R", "observed"), "surge_reliability.csv, middle bins")
    M.put("gapCal", lambda: gap("mean_R_cal", "observed_cal"), "surge_reliability.csv, middle bins")
    M.put("surgeExpected", pct(1 - forecast.SURGE_PCTL), "1 - forecast.SURGE_PCTL: the surge rate of a quiet year")
    st = k["storm_tab"]
    M.put("ompongRRaw", lambda: f(st.loc["ompong", "R_raw"], 2), "scenarios.parquet Ompong mean R_raw")
    M.put("ompongR", lambda: f(st.loc["ompong", "R"], 2), "scenarios.parquet Ompong mean R")
    M.put("nDistinctR", lambda: k["n_distinct_R"], "scenarios.parquet Ompong distinct R")
    M.put("nTies", lambda: k["ties"][0], "scenarios.parquet Ompong units sharing the top R")
    M.put("tieValue", lambda: f(k["ties"][1], 2), "scenarios.parquet Ompong top R")


def put_graph(M, k):
    M.put("llEdges", lambda: k["ll_edges"], "leadlag_meta.json pcmciplus n_edges")
    M.put("llN", lambda: k["ll_N"], "leadlag_meta.json n_series")
    M.put("llT", lambda: k["ll_T"], "leadlag_meta.json T")
    M.put("xcEdges", lambda: thou(k["xc_edges"]), "leadlag_edges_xcorr.parquet")


def put_flood(M, k):
    ems = k.get("ems") or {}
    M.put("sOneFloodThr", pct(0.01), "flooded-share threshold of make_results.stats (s1_tab, s1_muni)")
    M.put("emsKm", lambda: f(ems["ems_km2"], 0), "EMSR312 vs Sentinel-1, km2 in the EMS AOIs")
    M.put("sOneKm", lambda: f(ems["s1_km2"], 0), "EMSR312 vs Sentinel-1")
    M.put("bothKm", lambda: f(ems["both_km2"], 0), "EMSR312 vs Sentinel-1")
    M.put("emsPrecision", lambda: pct(ems["precision"]), "share of S1 flood confirmed by EMS")
    M.put("emsRecall", lambda: pct(ems["recall"]), "share of EMS flood S1 recovers")


def put_access(M, k):
    st, mb, pr = k["storm_tab"], k.get("mbase", {}), k.get("proxy", {})
    M.put("cellsPopM", lambda: f(k["cells_pop"] / 1e6, 1) + "~M", "scenarios_adm3.parquet pop")
    M.put("routeShare", lambda: pct(k["route_share"], 1), "scenarios_adm3.parquet")
    M.put("meanHours", lambda: f(k["mean_hours"], 2), "scenarios_adm3.parquet")
    M.put("rasterReach", lambda: pct(mb["pop_reach_raster"], 1), "access_methods.csv baseline")
    M.put("networkReach", lambda: pct(mb["pop_reach_network"], 1), "access_methods.csv baseline")
    M.put("rasterHours", lambda: f(mb["popw_mean_hours_raster"], 2), "access_methods.csv baseline")
    M.put("networkHours", lambda: f(mb["popw_mean_hours_network"], 2), "access_methods.csv baseline")
    M.put("medianRatioBase", lambda: f(mb["median_ratio_raster_network"], 2), "access_methods.csv baseline")
    M.put("spearmanCells", lambda: f(mb["spearman_hours_cells"], 2), "access_methods.csv baseline")
    M.put("cellsBoth", lambda: thou(mb["cells_both_reach"]), "access_methods.csv baseline")
    M.put("spearmanUnits", lambda: f(mb["spearman_unit_base_hours"], 2), "access_methods.csv baseline")
    M.put("cutNetRange", lambda: rng(st.cut.min(), st.cut.max(), fmt=lambda v: f(v / 1e6, 1), unit="~M"), "scenarios.parquet observed tracks")
    M.put("cutRasterRange", lambda: rng(st.cutr.min(), st.cutr.max(), fmt=lambda v: f(v / 1e6, 1), unit="~M"), "scenarios.parquet observed tracks")
    M.put("ferriesRange", lambda: rng(st.ferries.min(), st.ferries.max(), fmt=lambda v: str(int(v))), "scenarios.parquet ferries_cancelled")
    M.put("nProxy", lambda: pr["n"], "shifted backtest tracks")
    M.put("proxyCutRange", lambda: rng(*pr["cut"], fmt=lambda v: f(v / 1e6, 1), unit="~M"), "shifted tracks, network")
    M.put("proxyRatio", lambda: f(pr["ratio"], 2), "shifted tracks: median raster / network")
    M.put("rhoProxyRange", lambda: rng(*pr["rho"]), "access_methods.csv shifted tracks spearman_A_units")
    M.put("rhoObsRange", lambda: rng(min(k["rho_A_obs"].values()), max(k["rho_A_obs"].values())), "access_methods.csv observed tracks")
    M.put("topTenSharedRange", lambda: rng(min(k["top10_methods"].values()), max(k["top10_methods"].values()), fmt=str), "top-10 by P shared by the methods")
    M.put("tauMin", lambda: f(k["tau_min"], 2), "sensitivity.csv kendall_tau min")
    M.put("tauMinRaster", lambda: f(k["tau_min_raster"], 3), "sensitivity.csv kendall_tau_raster min")
    M.put("tauMinAll", lambda: f(min(k["tau_min"], k["tau_min_raster"]), 2), "sensitivity.csv, both methods")
    M.put("uFiveShare", lambda: pct(k["u5_share"], 1), "Meta HRSL under-5 / cell population")
    M.put("oSixtyShare", lambda: pct(k["o60_share"], 1), "Meta HRSL 60+ / cell population")
    M.put("censusUFive", lambda: pct(k["census_u5"], 1), "2020 census age table")
    M.put("censusSixty", lambda: pct(k["census_60"], 1), "2020 census age table")
    M.put("uFiveCutRange", lambda: rng(min(k["u5_cut_share"].values()), max(k["u5_cut_share"].values()), fmt=lambda v: f(100 * v, 1), unit=r"\%"), "under-5 share of those cut off")
    M.put("oSixtyCutRange", lambda: rng(min(k["o60_cut_share"].values()), max(k["o60_cut_share"].values()), fmt=lambda v: f(100 * v, 1), unit=r"\%"), "60+ share of those cut off")
    M.put("benchNCR", lambda: pct(k["bench"], 1), "benchmark_ncr.csv share_cut")
    M.put("nSensVariants", lambda: k["n_sens_variants"], "sensitivity.csv variants")


def put_priority(M, k):
    st, ps = k["storm_tab"], k.get("proxy_storm")
    M.put("nScen", lambda: k["n_scen"], "scenarios.parquet storm x track")
    M.put("nScenTotal", lambda: k["n_scen"] + k["n_cat"], "backtest scenarios + catalogue storms")
    M.put("landfallOmpong", date(STORMS["ompong"]["landfall"]), "config.STORMS")
    for key, nm in STORM_MACRO.items():
        M.put(f"top{nm}", lambda key=key: esc(k["top"][key]), f"scenarios.parquet {nm}: highest P")
        M.put(f"deploy{nm}", lambda key=key: int(st.loc[key, "t3"]), f"scenarios.parquet {nm}: tier 3")
        M.put(f"prepos{nm}", lambda key=key: int(st.loc[key, "t2"]), f"scenarios.parquet {nm}: tier 2")
    M.put("nStormsDeploy", lambda: int((st.t3 > 0).sum()), "observed tracks with any province at deploy")
    M.put("proxyDeployOmpong", lambda: rng(ps.loc["ompong", "t3_min"], ps.loc["ompong", "t3_max"], fmt=lambda v: str(int(v))), "Ompong shifted tracks, tier 3")


def put_catalog(M, k):
    a = k.get("allst")
    cat = a[a.kind == "catalogue"] if a is not None else None
    M.put("nCat", lambda: k["n_cat"], "scenarios_catalog.parquet storms")
    M.put("nCalCat", lambda: k["n_cal_cat"], "catalogue storms with calibrated R")
    M.put("nAllStorms", lambda: len(a), "catalogue + backtests")
    M.put("catYearMin", lambda: pd.Timestamp(a.origin.min()).year, "first scored storm")
    M.put("catYearMax", lambda: pd.Timestamp(a.origin.max()).year, "last scored storm")
    M.put("nSkipped", lambda: len(k["cat_skipped"]), "catalog_storms.csv skipped for short history")
    M.put("nLandStorms", lambda: k["cat_n_land"], "catalog_storms.csv swath_hits_land")
    M.put("largestCutStorms", lambda: lst(esc(x) for x in cat.nlargest(3, "cut").label), "catalogue: 3 largest cut-offs")
    M.put("highRStorms", lambda: lst(esc(x) for x in cat.nlargest(3, "R").label), "catalogue: 3 highest mean R")
    M.put("catRhoMedian", lambda: f(k["cat_rho"][1], 2), "access_methods_catalog.csv spearman_A_units median")
    M.put("catRhoMin", lambda: f(k["cat_rho"][0], 2), "access_methods_catalog.csv spearman_A_units min")
    M.put("catRhoN", lambda: k["cat_rho"][2], "catalogue storms with any cut-off")


def put_validation(M, d):
    v = d["valid"].set_index("storm")
    for key, nm in STORM_MACRO.items():
        M.put(f"rhoR{nm}", lambda nm=nm: f(v.loc[nm, "spearman_R_obs"], 2), f"validation.csv {nm}")
    M.put("rhoRRange", lambda: rng(v.spearman_R_obs.min(), v.spearman_R_obs.max()), "validation.csv")
    M.put("rhoPRange", lambda: rng(v.spearman_P_obs.min(), v.spearman_P_obs.max()), "validation.csv")
    M.put("topTenSurgedOmpong", lambda: f(v.loc["Ompong", "top10_surge_rate"] * 10, 0), "validation.csv top10_surge_rate x 10")
    M.put("surgeRateOmpong", lambda: pct(v.loc["Ompong", "surge_rate"]), "validation.csv surge_rate")


def put_lepto(M, k):
    L = k.get("lepto", {})
    c, n = L.get("city", {}), L.get("nat", {})
    M.put("leptoNCities", lambda: L["n_cities"], "lepto_events.csv cities")
    M.put("cityObs", lambda: thou(c["n_obs"]), "lepto_city_lag.csv n_obs")
    M.put("cityCases", lambda: thou(c["n_cases"]), "lepto_city_lag.csv n_cases")
    M.put("citySigRange", lambda: rng(min(c["sig"]), max(c["sig"]), fmt=str), "lags whose 95% CI excludes 1")
    M.put("cityPeakLag", lambda: int(c["peak"].lag), "joint model, highest IRR")
    M.put("cityPeakIRR", lambda: f(c["peak"].irr, 2), "joint model, highest IRR")
    M.put("cityPeakCI", lambda: ci(c["peak"]), "joint model, peak with CI")
    M.put("cityCumCI", lambda: ci(c["cum"]), "joint model, lags 0-6 cumulative")
    M.put("heavyPeakLag", lambda: int(L["heavy_peak"].lag), "heavy-rain model peak")
    M.put("heavyPeakCI", lambda: ci(L["heavy_peak"]), "heavy-rain model peak")
    M.put("natObs", lambda: n["n_obs"], "lepto_national_lag.csv n_obs")
    M.put("natPeakLag", lambda: int(n["peak"].lag), "national joint model peak")
    M.put("natPeakCI", lambda: ci(n["peak"]), "national joint model peak")
    M.put("natCumCI", lambda: ci(n["cum"]), "national cumulative")
    M.put("natNineteenCumCI", lambda: ci(L["nat19_cum"]), "national, 2019 only, cumulative")
    M.put("didRUPost", lambda: ci(L["ru_post"]), "lepto_events_did.csv rolly+ulysses inside x weeks 1-4")
    M.put("didRUPre", lambda: ci(L["ru_pre"]), "lepto_events_did.csv rolly+ulysses placebo")
    M.put("didOTPost", lambda: ci(L["ot_post"]), "lepto_events_did.csv ompong+tisoy inside x weeks 1-4")
    M.put("didOTPre", lambda: ci(L["ot_pre"]), "lepto_events_did.csv ompong+tisoy placebo")
    sp = L.get("s1_pairs")
    M.put("sOnePairs", lambda: sp[0], "lepto_events.csv city-storm pairs")
    M.put("sOnePairsSeen", lambda: sp[1], "pairs with radar over > 20% of the city")
    M.put("sOnePairsFlooded", lambda: sp[2], "pairs with any new flood")
    M.put("sOnePairsMax", lambda: pct(sp[3], 1), "largest flooded share")


def put_status(M, k):
    """Scorecard status words, decided from the outputs present (as the report's _targets())."""
    word = {"ok": r"\stOk", "part": r"\stPart", "no": r"\stNo"}
    bp, bm = k["bench_present"], k["bench_missing"]
    M.put("statusPanel", word["ok" if k["s1_ok"] else "part"], "Sentinel-1 in the panel")
    M.put("statusBench", word["ok" if not bm else ("part" if bp else "no")], "benchmarks present")
    M.put("statusAccess", word["ok" if k["raster_ok"] else "part"], "raster method present")
    M.put("statusSUS", word["ok" if k["sus_n"] >= 3 else "part" if k["sus_n"] else "no"], "SUS responses")
    M.put("statusLepto", word["part" if k.get("lepto_ok") else "no"], "leptospirosis outputs")


def put_verdicts(M, k, d):
    """Words and conditions for every qualitative claim in the prose, decided from the same numbers (as the report's
    _targets() and its guarded sentences do), so a rebuild that changes the results changes the claims too."""
    e = k["ev"]
    eh = e.drop(index="all")
    lo, hi = COV_TARGET
    M.put("targetCov", f"{lo * 100:.0f}--{hi * 100:.0f}\\%", "COV_TARGET: the proposal's coverage band")
    # forecast skill
    M.flag("ForecastBeats", lambda: k["relwis"] < 1, "relWIS xgb/naive < 1 (all horizons pooled)")
    M.flag("RelBelowAllH", lambda: (eh["relWIS xgb/naive"] < 1).all(), "relWIS < 1 at every horizon")
    M.flag("CovInsideAllH", lambda: eh["cov90 xgb"].between(lo, hi).all(), "cov90 inside COV_TARGET at every horizon")
    M.flag("CovFourNearFloor", lambda: eh["cov90 xgb"].iloc[-1] - lo < 0.03, "4-week cov90 within 0.03 of the floor")
    M.flag("CovFiftyNarrow", lambda: eh["cov50 xgb"].max() < 0.5, "every 50% interval covers less than 50%")
    M.flag("CovFiftyWide", lambda: eh["cov50 xgb"].min() > 0.5, "every 50% interval covers more than 50%")
    M.flag("ConformalSimilar", lambda: abs(e.loc["all", "cov90 conformal"] - k["cov90"]) < 0.03, "conformal and model 90% coverage within 0.03")
    M.put("covNinetyConformal", lambda: f(e.loc["all", "cov90 conformal"], 2), "eval_summary.csv cov90 conformal (all)")
    M.flag("GraphHelps", lambda: k["relwis_graph"] < HELPS, f"relWIS xgb/nograph < {HELPS}")
    M.flag("EnvHelps", lambda: k["relwis_env"] < HELPS, f"relWIS xgb/noenv < {HELPS}")
    # model comparison
    al, bo = k.get("mall"), k.get("bench_only", [])
    M.put("nBench", lambda: len(bo), "benchmarks in eval_models.csv")
    M.put("nBenchBeatXGB", lambda: int((al.loc[bo, "relWIS_vs_xgb"] < 1).sum()), "benchmarks with mean WIS below XGBoost")
    M.flag("AnyBenchBeatsXGB", lambda: (al.loc[bo, "relWIS_vs_xgb"] < 1).any(), "some benchmark below XGBoost on mean WIS")
    M.put("bestMeanLabel", lambda: esc(MR.MODEL_LABEL.get(k["best_mean"], k["best_mean"])), "eval_models.csv: lowest relWIS_vs_naive")
    M.put("bestMeanRelWIS", lambda: f(al.loc[k["best_mean"], "relWIS_vs_naive"], 3), "eval_models.csv")
    M.put("bestMeanCov", lambda: pct(al.loc[k["best_mean"], "cov90"]), "eval_models.csv")
    mw = k.get("mw", {})
    best_md = (lambda: min(mw, key=mw.get))
    M.put("bestMedianLabel", lambda: esc(MR.MODEL_LABEL.get(best_md(), best_md())), "lowest median WIS")
    M.put("bestMedianWIS", lambda: f(mw[best_md()], 2), "lowest median WIS")
    M.flag("MeanMedianDiffer", lambda: best_md() != k["best_mean"], "the best model on mean WIS is not the best on median WIS")
    sp = k.get("split", {})
    M.flag("BenchWinHigh", lambda: all(sp["hi"][x] < 1 for x in bo) and all(sp["lo"][x] > 1 for x in bo),
           "benchmarks beat XGBoost above the 90th percentile of cases and lose below it")
    M.flag("EnsGainsBoth", lambda: sp["lo"]["ens_median"] < 1 and sp["hi"]["ens_median"] < 1, "ensemble below XGBoost in both halves")
    var = k.get("variants", {})
    M.flag("ChronosLogCollapsed", lambda: var["chronos2_log1p"] > 2, "chronos2_log1p relative WIS above 2")
    M.flag("ChronosCovHelps", lambda: var["chronos2"] < var["chronos2_nocov"], "chronos2 with covariates below without")
    M.flag("MpnnGraphSame", lambda: abs(var["mpnn_lstm_none"] - var["mpnn_lstm"]) < SAME, f"MPNN-LSTM with / without graph within {SAME}")
    # calibration
    cal = k.get("calib", {}).get("all_rows", {})
    r = d["rel"]
    mid = r[(r.mean_R > GAP_BINS[0]) & (r.mean_R <= GAP_BINS[1])]
    M.flag("CalImproves", lambda: cal["brier_cal"] < cal["brier_raw"], "Brier calibrated < raw")
    M.flag("RawUnderConfident", lambda: (mid.observed - mid.mean_R).mean() > 0, "middle bins: observed above raw R on average")
    M.flag("CalGapSmaller", lambda: float(M.m["gapCal"][0].rstrip("\\%")) < float(M.m["gapRaw"][0].rstrip("\\%")), "largest middle-bin gap shrinks")
    M.flag("BaseRateHigh", lambda: cal["base_rate"] > 1 - forecast.SURGE_PCTL + 0.05, "base rate well above the quiet-year rate")
    st = k["storm_tab"]
    M.flag("OmpongRRises", lambda: st.loc["ompong", "R"] > st.loc["ompong", "R_raw"], "Ompong mean R calibrated > raw")
    # lead-lag graph
    M.flag("XcorrMany", lambda: k["xc_edges"] > 10 * max(k["ll_edges"], 1), "cross-correlation keeps 10x the PCMCI+ links")
    # Sentinel-1 against EMS
    M.flag("EMSRecallLow", lambda: k["ems"]["recall"] < 0.5, "Sentinel-1 recovers under half of the EMS area")
    # access methods
    mb, pr = k.get("mbase", {}), k.get("proxy", {})
    M.flag("RasterReachMore", lambda: mb["pop_reach_raster"] > mb["pop_reach_network"], "normal day: raster reaches more people")
    M.flag("RasterFaster", lambda: mb["popw_mean_hours_raster"] < mb["popw_mean_hours_network"], "normal day: raster trips shorter")
    M.flag("MethodsRankAlike", lambda: mb["spearman_hours_cells"] >= ALIKE, f"normal day: Spearman over cells >= {ALIKE}")
    M.flag("RasterMoreSOne", lambda: st.cutr.sum() > st.cut.sum(), "observed tracks: raster cuts off more people")
    M.flag("RasterMoreProxy", lambda: pr["ratio"] > 1, "proxy tracks: median raster / network > 1")
    M.flag("ProxyAgreesBetter", lambda: pr["rho"][0] > max(k["rho_A_obs"].values()), "rho of A: every proxy track above every observed track")
    sens = d["sens"]
    gale = sens[sens.variant.str.contains("gale")]
    M.flag("GaleNoEffect", lambda: len(gale) > 0 and (gale.kendall_tau > 1 - 1e-9).all(), "every gale-fallback variant leaves P's ranking unchanged")
    M.flag("SensStable",lambda: min(k["tau_min"], k["tau_min_raster"]) >= STABLE_TAU, f"Kendall's tau >= {STABLE_TAU} for every variant")
    M.flag("HRSLUnderOld", lambda: k["o60_share"] < k["census_60"], "HRSL 60+ share below the census")
    M.flag("HRSLOverYoung", lambda: k["u5_share"] > k["census_u5"], "HRSL under-5 share above the census")
    # validation
    v = d["valid"].set_index("storm")
    pre = v.loc[["Ompong", "Tisoy"]]
    M.flag("RRanksWell", lambda: (pre.spearman_R_obs >= 0.5).all(), "rho(R, observed) >= 0.5 for both 2018-2019 storms")
    M.flag("PLessThanR", lambda: (pre.spearman_P_obs < pre.spearman_R_obs).all(), "rho(P) < rho(R) for both 2018-2019 storms")
    M.put("surgeRateTisoy", lambda: pct(v.loc["Tisoy", "surge_rate"]), "validation.csv surge_rate")
    M.put("topTenSurgedTisoy", lambda: f(v.loc["Tisoy", "top10_surge_rate"] * 10, 0), "validation.csv top10_surge_rate x 10")
    # catalogue
    a = k.get("allst")
    cat = a[a.kind == "catalogue"] if a is not None else None
    M.flag("CatLargestLowR", lambda: cat.nlargest(3, "cut").R.max() < cat.R.median(), "the 3 largest cut-offs all have R below the catalogue median")
    M.flag("CatHighRNineteen", lambda: (cat.nlargest(3, "R").season == 2019).all(), "the 3 highest-R storms are all 2019")
    # leptospirosis
    L = k.get("lepto", {})
    M.flag("CitySig", lambda: len(L["city"]["sig"]) > 0, "some city lag has a 95% CI above 1")
    M.flag("CityPeakLater", lambda: L["city"]["peak"].lag > 2, "city peak later than two weeks")
    M.flag("NatNineteenNull", lambda: L["nat19_cum"].ci_lo < 1, "2019-only national cumulative CI includes 1")
    sig = (lambda r: r.ci_lo > 1 or r.ci_hi < 1)
    M.flag("RUPostSig", lambda: sig(L["ru_post"]), "Rolly+Ulysses inside x weeks 1-4: CI excludes 1")
    M.flag("RUPlaceboOK", lambda: not sig(L["ru_pre"]), "Rolly+Ulysses placebo CI includes 1")
    M.flag("OTPostSig", lambda: sig(L["ot_post"]), "Ompong+Tisoy inside x weeks 1-4: CI excludes 1")
    M.flag("OTPlaceboOK", lambda: not sig(L["ot_pre"]), "Ompong+Tisoy placebo CI includes 1")
    M.flag("LeptoFloodFew", lambda: L["s1_pairs"][2] < 10, "fewer than 10 flooded city-storm pairs")
    # scorecard rows decided by a number
    word = {True: r"\stOk", False: r"\stNo"}
    M.put("statusRelWIS", lambda: word[bool(k["relwis"] < 1)], "relWIS < 1")
    M.put("statusCov", lambda: word[bool(eh["cov90 xgb"].between(lo, hi).all())], "cov90 inside COV_TARGET at every horizon")
    M.flag("SUSPending", lambda: k["sus_n"] < 3, "fewer than three SUS responses")
    M.flag("NHFRMissing", lambda: "nhfr" in k["missing"], "status.json: nhfr missing")


def macros(d, k):
    M = Macros()
    for fn in (put_data, put_calibration):
        fn(M, k, d)
    for fn in (put_methods, put_forecast, put_models, put_graph, put_flood, put_access, put_priority, put_catalog,
               put_lepto, put_status):
        fn(M, k)
    put_validation(M, d)
    put_verdicts(M, k, d)
    return M


# ---------------------------------------------------------------- tables (bodies only; headers live in the .tex)

def tables(d, k):
    t = {
        "sources": html_rows(MR.source_rows(d)),
        "eval": html_rows(MR.eval_rows(k)),
        "edges": html_rows(MR.edge_rows(d)),
        "valid": html_rows(MR.valid_rows(d)),
        "storms": html_rows(MR.storm_rows(k)),
    }
    sens = MR.sens_rows(d)
    t["sens"] = html_rows(sens)
    if k.get("models_ok"):
        t["models"] = html_rows(MR.model_rows(k))
    if k.get("raster_ok"):
        t["methods"] = html_rows(MR.method_rows(k))
    if k.get("s1_muni"):
        t["s1muni"] = html_rows(MR.s1_muni_rows(k))
    if k.get("s1_ok"):
        t["s1"] = "\n".join(rf"{STORMS[s]['local']} & {f(v['pop'] / 1e6, 1)}~M & {v['units']} & {pct(v['frac_max'], 1)} & {esc(v['top'])} \\"
                            for s, v in k["s1_tab"].items())
    if k.get("cat_ok"):
        for i, part in enumerate(MR.catalog_rows(k)):
            t[f"catalog{'AB'[i]}"] = html_rows(part)
    cal = k.get("calib")
    if cal:
        rows = []
        for lab, key in (("all 2018--2019 origins", "all_rows"), ("origins with a calibrator", "calibrated_rows")):
            r = cal[key]
            rows.append(f"{lab} & {thou(r['n'])} & {f(r['base_rate'], 3)} & {f(r['mean_R_raw'], 3)} & {f(r['mean_R_cal'], 3)} & "
                        rf"{f(r['brier_raw'], 3)} & \textbf{{{f(r['brier_cal'], 3)}}} & {f(r['brier_climatology'], 3)} \\")
        t["calib"] = "\n".join(rows)
    return t


def write(d, k):
    GEN.mkdir(parents=True, exist_ok=True)
    M = macros(d, k)
    (GEN / "numbers.tex").write_text(M.tex(), encoding="utf-8")
    T = tables(d, k)
    head = "% Generated by scripts/make_spec.py -- do not edit by hand.\n"
    for name, body in T.items():
        (GEN / f"tab_{name}.tex").write_text(head + body + "\n", encoding="utf-8")
    print(f"  wrote {GEN.relative_to(ROOT)}/numbers.tex ({len(M.m)} macros) and {len(T)} tables")
    for x in M.na:
        print(f"  WARNING n/a: {x}")
    return M, T


def compile_pdf():
    exe = shutil.which("latexmk")
    if exe is None:
        print("  WARNING latexmk not found (install MiKTeX or TeX Live): .tex written, PDF skipped")
        return False
    r = subprocess.run([exe], cwd=SPEC, capture_output=True, text=True, encoding="utf-8", errors="replace")
    pdf = SPEC / "build" / "main.pdf"
    if r.returncode != 0 or not pdf.exists():
        print(r.stdout[-3000:], r.stderr[-2000:])
        print("  ERROR latexmk failed; see docs/spec/build/main.log")
        return False
    shutil.copyfile(pdf, PDF)
    print(f"  wrote {PDF.relative_to(ROOT)} ({PDF.stat().st_size / 1e6:.1f} MB)")
    return True


def main(pdf=True):
    d = MR.load()
    k = MR.stats(d)
    k["valid"] = d["valid"]
    k["n_sens_variants"] = d["sens"].variant.nunique()
    write(d, k)
    if pdf and not compile_pdf():
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pdf", action="store_true")
    main(pdf=not ap.parse_args().no_pdf)
