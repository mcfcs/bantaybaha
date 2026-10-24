"""The technical spec's qualitative claims: every \\if<Name> flag in docs/spec/generated/numbers.tex.

The flags decide wording such as "beats the bar" or "the placebo fails". These tests recompute the flags straight from
the CSV / JSON build outputs (not through make_spec's own code path), check that the prose uses only generated flags,
and (slow) that the document still compiles with every flag inverted, so both wordings of every claim build.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec"
NUMBERS = SPEC / "generated" / "numbers.tex"
APP = ROOT / "data" / "processed" / "app"
FLAG = re.compile(r"\\newif\\if([A-Za-z]+)\\\1(true|false)")
sys.path.insert(0, str(ROOT / "scripts"))


def flags():
    return {n: v == "true" for n, v in FLAG.findall(NUMBERS.read_text(encoding="utf-8"))}


def used_flags():
    names = set()
    for p in (SPEC / "sections").glob("*.tex"):
        names |= set(re.findall(r"\\if([A-Z][A-Za-z]+)\b", p.read_text(encoding="utf-8")))
    return names


def test_flag_registry():
    f = flags()
    assert f, "numbers.tex defines no flags"
    used = used_flags()
    assert not used - set(f), f"prose uses flags that are not generated: {sorted(used - set(f))}"
    assert not set(f) - used, f"generated flags the prose never uses: {sorted(set(f) - used)}"


OUTPUTS = ["eval_summary.csv", "eval_models.csv", "bench_summary.csv", "surge_calibration.json", "access_methods.csv",
           "validation.csv", "sensitivity.csv", "lepto_events_did.csv"]


@pytest.mark.data
@pytest.mark.skipif(not all((APP / f).exists() for f in OUTPUTS), reason="build outputs missing: run build.bat first")
def test_flags_match_build_outputs():
    import make_spec as S
    from make_results import BENCH_LABEL

    e = pd.read_csv(APP / "eval_summary.csv", index_col=0)
    eh = e.drop(index="all")
    lo, hi = S.COV_TARGET
    m = pd.read_csv(APP / "eval_models.csv")
    al = m[m.horizon.astype(str) == "all"].set_index("model")
    bench = [x for x in BENCH_LABEL if x in al.index and x != "ens_median"]
    bs = pd.read_csv(APP / "bench_summary.csv")
    var = bs[bs.horizon.astype(str) == "all"].set_index("model")["relWIS vs naive"]
    cal = json.loads((APP / "surge_calibration.json").read_text(encoding="utf-8"))["calibrated"]["all_rows"]
    mb = pd.read_csv(APP / "access_methods.csv").query("kind == 'baseline'").iloc[0]
    v = pd.read_csv(APP / "validation.csv").set_index("storm")
    pre = v.loc[["Ompong", "Tisoy"]]
    sens = pd.read_csv(APP / "sensitivity.csv")
    did = pd.read_csv(APP / "lepto_events_did.csv").set_index(["storms", "term"])
    sig = lambda r: r.ci_lo > 1 or r.ci_hi < 1  # noqa: E731
    status = json.loads((ROOT / "data" / "processed" / "status.json").read_text(encoding="utf-8"))

    expected = {
        "ForecastBeats": e.loc["all", "relWIS xgb/naive"] < 1,
        "RelBelowAllH": (eh["relWIS xgb/naive"] < 1).all(),
        "CovInsideAllH": eh["cov90 xgb"].between(lo, hi).all(),
        "GraphHelps": e.loc["all", "relWIS xgb/nograph"] < S.HELPS,
        "EnvHelps": e.loc["all", "relWIS xgb/noenv"] < S.HELPS,
        "AnyBenchBeatsXGB": (al.loc[bench, "relWIS_vs_xgb"] < 1).any(),
        "ChronosLogCollapsed": var["chronos2_log1p"] > 2,
        "ChronosCovHelps": var["chronos2"] < var["chronos2_nocov"],
        "MpnnGraphSame": abs(var["mpnn_lstm_none"] - var["mpnn_lstm"]) < S.SAME,
        "CalImproves": cal["brier_cal"] < cal["brier_raw"],
        "RasterReachMore": mb.pop_reach_raster > mb.pop_reach_network,
        "RasterFaster": mb.popw_mean_hours_raster < mb.popw_mean_hours_network,
        "MethodsRankAlike": mb.spearman_hours_cells >= S.ALIKE,
        "RRanksWell": (pre.spearman_R_obs >= 0.5).all(),
        "PLessThanR": (pre.spearman_P_obs < pre.spearman_R_obs).all(),
        "SensStable": min(sens.kendall_tau.min(), sens.kendall_tau_raster.min()) >= S.STABLE_TAU,
        "RUPostSig": sig(did.loc[("rolly+ulysses", "inside_x_post1_4")]),
        "RUPlaceboOK": not sig(did.loc[("rolly+ulysses", "inside_x_pre")]),
        "OTPostSig": sig(did.loc[("ompong+tisoy", "inside_x_post1_4")]),
        "OTPlaceboOK": not sig(did.loc[("ompong+tisoy", "inside_x_pre")]),
        "NHFRMissing": not status.get("nhfr", {}).get("available", False),
    }
    f = flags()
    wrong = {n: (f.get(n), bool(x)) for n, x in expected.items() if f.get(n) != bool(x)}
    assert not wrong, f"flags (generated, from outputs) disagree; re-run python scripts/make_spec.py: {wrong}"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not installed (MiKTeX or TeX Live)")
def test_spec_compiles_with_every_flag_inverted(tmp_path):
    """Both wordings of every claim must build: flip every flag in a copy of the spec and compile it."""
    spec = tmp_path / "docs" / "spec"
    shutil.copytree(SPEC, spec, ignore=shutil.ignore_patterns("build"))
    shutil.copytree(ROOT / "docs" / "results" / "figures", tmp_path / "docs" / "results" / "figures")
    nums = spec / "generated" / "numbers.tex"
    text = nums.read_text(encoding="utf-8")
    flipped = FLAG.sub(lambda m: m.group(0)[: -len(m.group(2))] + ("false" if m.group(2) == "true" else "true"), text)
    assert flipped != text
    nums.write_text(flipped, encoding="utf-8")
    out = tmp_path / "out"
    r = subprocess.run(["latexmk", f"-outdir={out}", "main.tex"], cwd=spec, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    log = (out / "main.log").read_text(encoding="utf-8", errors="replace") if (out / "main.log").exists() else ""
    assert r.returncode == 0 and (out / "main.pdf").exists(), r.stdout[-2000:] + log[-2000:]
    assert "LaTeX Error" not in log
    assert not re.search(r"(Reference|Citation) [`'][^']+' (on page \d+ )?undefined", log), "undefined references or citations"
