"""Tests of the LaTeX technical specification (docs/spec/) and its generator (scripts/make_spec.py).

Static checks need no build: every macro the sections use is defined, no result is typed into the prose, every
citation, figure, table and section file exists, the writing conventions of docs/spec/GUIDE.md hold. Tests that read the
build outputs skip when data/processed/ is missing. The compile test is marked `slow` (deselect with -m "not slow") and
skips when latexmk is not installed.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec"
GEN = SPEC / "generated"
NUMBERS = GEN / "numbers.tex"
SECTIONS = sorted((SPEC / "sections").glob("*.tex"))
FIGURES = ROOT / "docs" / "results" / "figures"
APP_DATA = ROOT / "data" / "processed" / "app"
sys.path.insert(0, str(ROOT / "scripts"))

needs_build = pytest.mark.skipif(not (APP_DATA / "eval_summary.csv").exists() or not (ROOT / "data" / "processed" / "panel.parquet").exists(),
                                 reason="build outputs missing: run build.bat first")

# LaTeX and package commands the sections may use. Anything else must be defined in main.tex or generated/numbers.tex.
STANDARD = set("""
section subsection subsubsection paragraph label ref pageref eqref cite parencite textcite citep citet nocite
textbf textit emph texttt textsc textsf textrm mathrm text textsuperscript textsubscript underline enquote
item begin end caption centering includegraphics input include footnote url href hfill vfill hspace vspace
small footnotesize scriptsize normalsize large Large tiny noindent par newline linebreak pagebreak clearpage newpage
toprule midrule bottomrule cmidrule addlinespace multicolumn multirow arraybackslash raggedright raggedleft linewidth
textwidth columnwidth times pm leq geq approx sim rightarrow leftarrow tau rho alpha beta Sigma sigma mu Delta delta
lambda log exp sum max min ldots dots cdot textdegree dag ddag blacklozenge lozenge quad qquad thinspace
bf it rm sf tt em sc mdseries normalfont ttfamily sffamily rmfamily color textcolor
else fi relax appendix printbibliography tableofcontents maketitle thispagestyle
""".split())

# Typed results the prose must not contain (the heuristic of GUIDE.md "Results are macros, never typed").
TYPED = [
    (re.compile(r"(?<![\w.{}])\d+\.\d+(?![\w.])"), "a decimal number"),
    (re.compile(r"(?<![\w{])\d+(?:\.\d+)?\s*\\%"), "a percentage"),
    (re.compile(r"(?<![\w{])\d{1,3}(?:\{,\}|,)\d{3}\b"), "a number with a thousands separator"),
    (re.compile(r"(?<![\w{])\d+(?:\.\d+)?\s*(?:~|\\,|\s)?(?:M|k)\b(?!m)"), "a number in millions or thousands"),
    (re.compile(r"(?<![\w{-])(?!(?:19|20)\d\d\b)\d+\s+(?:units?|provinces?|storms?|typhoons?|files|sources|links|edges|municipalities|hospitals|"
                r"routes|cities|people|series|quantiles|tracks|variants|refits|responses|origins|pairs|cases)\b"),
     "a typed count"),
]
# Allowed: nominal interval levels ("90\% interval", "95\% confidence"), version numbers (v3.5, V07), 2016--2020 style
# years, and anything inside commands that take labels, keys or file names.
NOMINAL = re.compile(r"(?:(?:50|90|95)\\%\s*(?:and|or|,)\s*)*(?:50|90|95)\\%\s*(?:interval|coverage|confidence|band|CI)")
VERSION = re.compile(r"\b[vV]\d+(?:\.\d+)*\b")
ARGS = re.compile(r"\\(?:label|ref|cite|parencite|textcite|includegraphics|tablerows|input|code|url|href)\*?(?:\[[^\]]*\])*\{[^}]*\}")


def strip_comments(tex):
    return re.sub(r"(?<!\\)%.*", "", tex)


def prose(tex):
    """Section text with comments, command arguments that hold keys or paths, options and nominal levels removed."""
    t = strip_comments(tex)
    t = ARGS.sub(" ", t)
    t = re.sub(r"\\begin\{\w+\*?\}(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})?", " ", t)  # environment options / column specs
    t = re.sub(r"\[[^\]]*(?:width|style|leftmargin|itemsep)[^\]]*\]", " ", t)
    t = NOMINAL.sub(" ", t)
    return VERSION.sub(" ", t)


def defined(tex):
    """Macro names defined in a TeX source: \\newcommand, \\renewcommand, \\newif (+ its true/false switches),
    \\newenvironment / \\newtcolorbox names are environments, not macros."""
    names = set(re.findall(r"\\(?:re)?newcommand\{?\\([A-Za-z]+)\}?", tex))
    for flag in re.findall(r"\\newif\\if([A-Za-z]+)", tex):
        names |= {f"if{flag}", f"{flag}true", f"{flag}false"}
    return names


def numbers():
    return NUMBERS.read_text(encoding="utf-8")


def macro_values():
    """{name: value} of the \\newcommand lines in generated/numbers.tex."""
    out = {}
    for line in numbers().splitlines():
        m = re.match(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}(?:\s*%.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def bib_keys():
    return set(re.findall(r"^@\w+\{([^,\s]+),", (SPEC / "refs.bib").read_text(encoding="utf-8"), re.M))


# ---------------------------------------------------------------- structure


def test_main_inputs_every_section():
    main = (SPEC / "main.tex").read_text(encoding="utf-8")
    inputs = re.findall(r"\\input\{sections/([^}]+)\}", main)
    assert inputs, "main.tex inputs no sections"
    for name in inputs:
        assert (SPEC / "sections" / f"{name}.tex").exists(), f"main.tex inputs sections/{name}.tex, which does not exist"
    assert {p.stem for p in SECTIONS} == set(inputs), "a section file is not input by main.tex (or the reverse)"
    assert "\\input{generated/numbers}" in main


def test_sections_have_root_magic_comment():
    for p in SECTIONS:
        assert p.read_text(encoding="utf-8").startswith("% !TEX root = ../main.tex"), f"{p.name}: first line must be the LaTeX Workshop root comment"


def test_build_settings():
    rc = (SPEC / "latexmkrc").read_text(encoding="utf-8")
    assert "$out_dir = 'build'" in rc and "$bibtex_use = 2" in rc
    settings = (ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8")
    assert "latex-workshop.latex.recipes" in settings and "latexmk" in settings and "%DIR%/build" in settings
    ext = (ROOT / ".vscode" / "extensions.json").read_text(encoding="utf-8")
    assert "james-yu.latex-workshop" in ext
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "docs/spec/build/" in ignore


# ---------------------------------------------------------------- macros


def test_every_macro_used_is_defined():
    main = (SPEC / "main.tex").read_text(encoding="utf-8")
    known = defined(numbers()) | defined(main) | STANDARD | {"tablerows", "code"}
    for p in SECTIONS:
        used = set(re.findall(r"\\([A-Za-z]+)", strip_comments(p.read_text(encoding="utf-8"))))
        missing = sorted(used - known)
        assert not missing, (f"{p.name} uses undefined macros {missing}: add them to scripts/make_spec.py (results), "
                             f"main.tex (notation) or STANDARD in tests/test_spec.py (a LaTeX command)")


def test_generated_macros_are_letters_only_and_unique():
    names = re.findall(r"\\newcommand\{\\([^}]+)\}", numbers())
    assert names, "numbers.tex defines no macros"
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert len(names) == len(set(names))


def test_no_generated_value_is_missing():
    na = [k for k, v in macro_values().items() if "n/a" in v]
    assert not na, f"numbers.tex has n/a values (an output was missing when it was generated): {na}"


def test_generated_tables_exist():
    for p in SECTIONS:
        for name in re.findall(r"\\tablerows\{([^}]+)\}", p.read_text(encoding="utf-8")):
            t = GEN / f"tab_{name}.tex"
            assert t.exists(), f"{p.name}: \\tablerows{{{name}}} but {t.relative_to(ROOT)} does not exist"
            rows = [r for r in t.read_text(encoding="utf-8").splitlines() if r.strip() and not r.startswith("%")]
            assert rows and all(r.rstrip().endswith("\\\\") or r.strip() == "\\midrule" for r in rows), f"{t.name}: not table rows"


# ---------------------------------------------------------------- prose conventions


def test_no_typed_results_in_prose():
    problems = []
    for p in SECTIONS:
        for i, line in enumerate(prose(p.read_text(encoding="utf-8")).splitlines(), 1):
            for pat, what in TYPED:
                for m in pat.finditer(line):
                    problems.append(f"{p.name}:{i}: {what} '{m.group(0)}'")
    assert not problems, "typed results in the prose (use a macro from scripts/make_spec.py):\n" + "\n".join(problems)


def test_typed_result_heuristic_catches_examples():
    bad = ["a relative WIS of 0.544", "covers 74 of 85 units", "lowers it by 46\\%", "34{,}050 forecasts", "0.3--1.0~M people"]
    ok = ["a relative WIS of \\relWIS{}", "the 90\\% interval", "the 50\\% and 90\\% interval coverage", "TabPFN v2 and v3.5",
          "2018--2019", "2020 storms indicative only", "lags 1 to \\tauMax{} weeks",
          "Table~\\ref{tab:eval}", "\\includegraphics[width=0.5\\linewidth]{f04_reliability}"]
    hit = lambda s: any(p.search(prose(s)) for p, _ in TYPED)  # noqa: E731
    assert all(hit(s) for s in bad)
    assert not any(hit(s) for s in ok)


def test_one_paragraph_per_source_line():
    """GUIDE.md: prose is never hard-wrapped. Two consecutive text lines outside a table are one wrapped paragraph."""
    wrapped = []
    for p in SECTIONS:
        lines = p.read_text(encoding="utf-8").splitlines()
        depth = 0
        for i, (a, b) in enumerate(zip(lines, lines[1:]), 1):
            depth += a.count("\\begin{tab") - a.count("\\end{tab")
            text = lambda s: s.strip() and not s.lstrip().startswith(("\\", "%", "&", "}"))  # noqa: E731
            if depth == 0 and text(a) and text(b):
                wrapped.append(f"{p.name}:{i}")
    assert not wrapped, f"hard-wrapped paragraphs (join them into one line): {wrapped}"


def test_no_space_swallowed_after_conditionals():
    """TeX drops the space after a control word: 'estimates.\\fi Among' prints 'estimates.Among'. Write '\\fi{} Among'."""
    bad = []
    for p in SECTIONS:
        for i, line in enumerate(strip_comments(p.read_text(encoding="utf-8")).splitlines(), 1):
            bad += [f"{p.name}:{i}: ...{m.group(0)}" for m in re.finditer(r"\S\\fi [A-Za-z(]", line)]
    assert not bad, "missing {} after \\fi before a word:\n" + "\n".join(bad)


def test_no_hyphenation_preamble():
    main = (SPEC / "main.tex").read_text(encoding="utf-8")
    for setting in ("\\hyphenpenalty=10000", "\\exhyphenpenalty=10000"):
        assert setting in main
    for p in SECTIONS:
        assert "\\sloppy" not in p.read_text(encoding="utf-8"), f"{p.name}: no local \\sloppy (GUIDE.md)"


def test_anonymous_sources():
    """No e-mail address or author field in the sources (the competition is judged anonymously)."""
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for p in [SPEC / "main.tex", SPEC / "GUIDE.md", *SECTIONS]:
        assert not email.search(p.read_text(encoding="utf-8")), f"{p.name} contains an e-mail address"
    assert "pdfauthor" not in (SPEC / "main.tex").read_text(encoding="utf-8")
    pdf = ROOT / "docs" / "results" / "Bantay-Baha_Technical_Spec.pdf"
    if pdf.exists():
        raw = pdf.read_bytes()
        assert b"/Author()" in raw, "the spec PDF names an author"
        assert b"\\Users\\" not in raw and b"/Users/" not in raw, "the spec PDF embeds a local path"


# ---------------------------------------------------------------- citations and figures


def test_every_citation_is_in_refs_bib():
    keys = bib_keys()
    for p in SECTIONS:
        for group in re.findall(r"\\(?:paren|text|foot)?cite[a-z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}", strip_comments(p.read_text(encoding="utf-8"))):
            for key in (k.strip() for k in group.split(",")):
                assert key in keys, f"{p.name}: \\cite{{{key}}} is not in refs.bib"


def test_refs_bib_has_no_duplicate_keys_or_stray_at_signs():
    text = (SPEC / "refs.bib").read_text(encoding="utf-8")
    keys = re.findall(r"^@\w+\{([^,\s]+),", text, re.M)
    assert len(keys) == len(set(keys)), "duplicate keys in refs.bib (biber keeps only the first)"
    assert not [ln for ln in text.splitlines() if ln.lstrip().startswith("%") and "@" in ln], "an at-sign in a comment starts an entry"


def test_every_figure_exists():
    main = (SPEC / "main.tex").read_text(encoding="utf-8")
    paths = [SPEC / g for g in re.findall(r"\\graphicspath\{\{([^}]+)\}\}", main)] or [SPEC]
    for p in SECTIONS:
        for name in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", p.read_text(encoding="utf-8")):
            found = [d / f"{name}{ext}" for d in paths for ext in ("", ".png", ".pdf", ".jpg") if (d / f"{name}{ext}").is_file()]
            assert found, f"{p.name}: \\includegraphics{{{name}}} not found in {[str(d) for d in paths]}"


def test_every_float_is_referenced():
    text = "\n".join(p.read_text(encoding="utf-8") for p in SECTIONS)
    for label in re.findall(r"\\label\{((?:tab|fig):[^}]+)\}", text):
        assert f"\\ref{{{label}}}" in text, f"{label} is never referenced from the text (GUIDE.md: nothing floats unannounced)"


# ---------------------------------------------------------------- generator logic (no build needed)


def test_formatting_helpers():
    import make_spec as S

    assert S.f(0.5437, 3) == "0.544" and S.f(-0.033, 2) == "$-$0.03"
    assert S.pct(0.0386, 1) == "3.9\\%"
    assert S.thou(34050) == "34{,}050"
    assert S.rng(0.3, 1.0, fmt=lambda v: S.f(v, 1), unit="~M") == "0.3--1.0~M"
    assert S.rng(0, 0, fmt=str) == "0"
    assert S.lst(["a", "b", "c"]) == "a, b and c"
    assert S.esc("dengue_hdx & 50%") == "dengue\\_hdx \\& 50\\%"
    with pytest.raises(ValueError):
        S.f(float("nan"))


def test_html_rows_to_latex():
    import make_spec as S

    html = ("<tr><th>x</th></tr><tr><td>Ompong <span class='mono'>Mangkhut 2018</span></td><td class='n'>0.3-0.6 M</td>"
            "<td class='n'>-0.03</td><td>2018-09-16</td></tr><tr class=\"tot\"><td>all</td><td class='n'><b>0.54</b></td></tr>")
    rows = S.html_rows(html).splitlines()
    assert rows[0] == "Ompong (Mangkhut 2018) & 0.3--0.6 M & $-$0.03 & 2018-09-16 \\\\"
    assert rows[1] == "\\midrule" and rows[2] == "\\textbf{all} & \\textbf{0.54} \\\\"


def test_macros_registry():
    import make_spec as S

    M = S.Macros()
    M.put("relWIS", lambda: S.f(0.5437, 3), "eval_summary.csv")
    M.put("missingOne", lambda: {}["x"], "absent output")
    assert M.m["relWIS"][0] == "0.544" and M.m["missingOne"][0] == S.NA and M.na
    with pytest.raises(ValueError):
        M.put("relWIS", "1")  # defined twice
    with pytest.raises(ValueError):
        M.put("cov90", "1")  # digits are not allowed in a macro name
    assert "\\newcommand{\\relWIS}{0.544} % eval_summary.csv" in M.tex()


# ---------------------------------------------------------------- against the build outputs


@needs_build
def test_macro_values_match_build_outputs():
    import pandas as pd

    v = macro_values()
    e = pd.read_csv(APP_DATA / "eval_summary.csv", index_col=0)
    assert v["relWIS"] == f"{e.loc['all', 'relWIS xgb/naive']:.3f}"
    assert v["covNinety"] == f"{e.loc['all', 'cov90 xgb']:.2f}"
    assert v["nScored"] == f"{int(e.loc['all', 'n']):,}".replace(",", "{,}")
    assert v["relWISHOne"] == f"{e.iloc[0]['relWIS xgb/naive']:.2f}"
    m = pd.read_csv(APP_DATA / "eval_models.csv")
    ens = m[(m.model == "ens_median") & (m.horizon.astype(str) == "all")]
    if len(ens):
        assert v["ensRelWIS"] == f"{ens.relWIS_vs_naive.iloc[0]:.3f}"
    cal = json.loads((APP_DATA / "surge_calibration.json").read_text())
    if "calibrated" in cal:
        assert v["brierCal"] == f"{cal['calibrated']['all_rows']['brier_cal']:.3f}"
    meta = [x for x in json.loads((APP_DATA / "leadlag_meta.json").read_text()) if x["method"] == "pcmciplus"][0]
    assert v["llEdges"] == str(meta["n_edges"])
    assert v["nHosp"] == f"{len(pd.read_parquet(APP_DATA / 'hospitals.parquet')):,}".replace(",", "{,}")
    assert v["benchNCR"] == f"{pd.read_csv(APP_DATA / 'benchmark_ncr.csv').share_cut.iloc[0] * 100:.1f}\\%"
    s = pd.read_parquet(APP_DATA / "scenarios.parquet")
    obs = s[(s.dlat == 0) & (s.dlon == 0)].groupby("storm").pop_cut.sum()
    lo, hi = f"{obs.min() / 1e6:.1f}", f"{obs.max() / 1e6:.1f}"
    assert v["cutNetRange"] == (lo if lo == hi else f"{lo}--{hi}") + "~M"
    assert v["nUnits"] == str(pd.read_parquet(ROOT / "data" / "processed" / "panel.parquet", columns=["unit_id"]).unit_id.nunique())


@needs_build
def test_generated_tables_match_build_outputs():
    import pandas as pd

    e = pd.read_csv(APP_DATA / "eval_summary.csv", index_col=0)
    rows = [r for r in (GEN / "tab_eval.tex").read_text(encoding="utf-8").splitlines() if r.endswith("\\\\")]
    assert len(rows) == len(e)
    assert f"{e.loc['all', 'relWIS xgb/naive']:.2f}" in rows[-1]
    edges = pd.read_parquet(APP_DATA / "leadlag_edges_pcmciplus.parquet")
    assert len([r for r in (GEN / "tab_edges.tex").read_text(encoding="utf-8").splitlines() if r.endswith("\\\\")]) == len(edges)


@needs_build
def test_generated_files_are_up_to_date(monkeypatch):
    """docs/spec/generated/ is what scripts/make_spec.py writes for the current build (re-run it after build.bat).
    The generator runs into docs/spec/build/ (git-ignored); the committed files are not touched."""
    import make_spec as S

    out = SPEC / "build" / "test_generated"
    shutil.rmtree(out, ignore_errors=True)
    monkeypatch.setattr(S, "GEN", out)
    try:
        S.main(pdf=False)
        stale = [p.name for p in sorted(out.glob("*.tex"))
                 if not (GEN / p.name).exists() or (GEN / p.name).read_text(encoding="utf-8") != p.read_text(encoding="utf-8")]
    finally:
        shutil.rmtree(out, ignore_errors=True)
    assert not stale, f"stale generated files {stale}: run python scripts/make_spec.py"


# ---------------------------------------------------------------- compile


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not installed (MiKTeX or TeX Live)")
def test_spec_compiles_cleanly(tmp_path):
    """latexmk into a temporary folder: no errors, no undefined references or citations, no overfull box over 1 pt."""
    r = subprocess.run(["latexmk", f"-outdir={tmp_path}", "main.tex"], cwd=SPEC, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace") if (tmp_path / "main.log").exists() else ""
    assert r.returncode == 0 and (tmp_path / "main.pdf").exists(), r.stdout[-2000:] + log[-2000:]
    assert "LaTeX Error" not in log
    assert not re.search(r"(Reference|Citation) [`'][^']+' (on page \d+ )?undefined", log), "undefined references or citations"
    assert "There were undefined references" not in log
    over = [float(x) for x in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)", log)]
    assert all(x <= 1.0 for x in over), f"overfull boxes: {over}"
    blg = tmp_path / "main.blg"
    assert not blg.exists() or "ERROR" not in blg.read_text(encoding="utf-8", errors="replace")
