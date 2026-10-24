# Technical specification: writing and building guide

The technical specification (`docs/spec/`) is the LaTeX version of the evaluation report: the same sections, written as
a document the team edits in VS Code. Its PDF is `docs/results/Bantay-Baha_Technical_Spec.pdf`.

## Layout

```
docs/spec/
  main.tex               preamble (fonts, layout, no-hyphenation penalties, biblatex) and the order of the sections
  sections/NN_name.tex   one file per section; each starts with "% !TEX root = ../main.tex"
  refs.bib               references (biblatex, style=apa, backend=biber)
  latexmkrc              latexmk settings: pdflatex + biber, output in build/
  generated/             written by scripts/make_spec.py; never edit by hand
    numbers.tex          one \newcommand per result or data fact, each with a comment naming its source
    tab_*.tex            table rows (the headers and captions stay in sections/)
  build/                 aux files and main.pdf (git-ignored)
```

Figures are not copied: `main.tex` sets `\graphicspath{{../results/figures/}}`, so `\includegraphics{f03_wis}` uses the
PNG that `scripts/make_results.py` draws.

## Building

You need a TeX distribution (MiKTeX or TeX Live with `pdflatex`, `biber` and `latexmk`) and, for the editor, the
**LaTeX Workshop** extension (`james-yu.latex-workshop`; VS Code offers it from `.vscode/extensions.json`).

**In VS Code.** Open the repository folder and any file in `docs/spec/`. Saving builds the document (`.vscode/settings.json`:
build on save, PDF in a tab, SyncTeX: Ctrl+click in the PDF jumps to the source). Three recipes are offered
(LaTeX Workshop sidebar > Build LaTeX project > Recipe):

| Recipe | Use |
|---|---|
| Spec (latexmk) | Default. Runs as many pdflatex and biber passes as needed. |
| Spec (full: pdflatex > biber > pdflatex x2) | The same chain spelled out, if latexmk is missing. |
| Quick (pdflatex only) | Fast loop while writing prose; new citations and references show as `[?]` until a full run. |

**On the command line.**

```bat
cd docs\spec
latexmk                  :: build\main.pdf
latexmk -c               :: remove the aux files (keeps the PDF)
```

**After a new pipeline build** the numbers change. Regenerate them, then the PDF:

```bat
python scripts\make_results.py        :: figures (and the HTML report and slides)
python scripts\make_spec.py           :: generated\*.tex, latexmk, copies the PDF to docs\results\
python scripts\make_spec.py --no-pdf  :: generated\*.tex only
```

A clean build has **zero errors, no undefined references or citations, and no overfull boxes**. Underfull boxes are
expected: they are the price of never hyphenating (below). If a run fails, read `build/main.log` from the first error;
LaTeX Workshop stops the recipe at the first failing step, so biber silently stops running after a LaTeX error.

## Writing conventions

### Results are macros, never typed

Every result in the prose comes from `generated/numbers.tex`: write `\relWIS{}`, not `0.544`. To quote a new number,
add a `M.put("name", ..., "source")` line to the matching `put_*()` function in `scripts/make_spec.py`, re-run it and use
`\name{}`. Macro names are letters only (`\relWISHOne`, `\cutNetRange`). Tables are generated the same way and read with
`\tablerows{name}` (it uses TeX's primitive input, because LaTeX's `\input` before `\bottomrule` fails).

Typed figures are allowed only where nothing computes them, and they live in `main.tex` as macros: the proposal's
assumption (`\proposalProvinces`) and figures quoted from the literature (`\litNCRShare`). The proposal's targets that
the results are judged against (`\targetCov`) and the method settings that live in the code (tier thresholds, PCMCI+
settings, the cut-off rule, track shifts) are written by the generator from the code, so the text cannot drift from it.

### Qualitative claims are conditions

Words such as "beats", "best", "does not help" or "the targets are met" are results too. The generator writes them as
TeX conditionals next to the numbers (`M.flag("ForecastBeats", lambda: ..., "source")` gives `\ifForecastBeats`), and the
prose states both outcomes:

```latex
\ifForecastBeats The forecast beats the bar.\else The forecast does not beat the bar.\fi
```

so a rebuild with different results changes the wording instead of leaving a stale claim. The thresholds behind the
flags (what counts as "helps", "the same", "alike", "stable") are named constants at the top of `scripts/make_spec.py`. `tests/test_spec.py` fails on a result typed into a section (a decimal, a
percentage, a number with M or k, a thousands separator, or a count of units, storms, links and the like).

### Acronyms

Expand an acronym exactly once, at its first use in the document (the abstract counts), and use the acronym alone
after that. Don't re-expand in a later section. If a term is used only once, spell it out and skip the acronym. Product
and dataset names (XGBoost, CHIRPS, PCMCI+, Sentinel-1) are not acronyms: introduce them with a short gloss. Every
acronym also goes in `sections/14_acronyms.tex`, sorted by the expanded name.

### Citations

Cite the work, not the people: never name authors in the running text (`a study of Metro Manila reported ...
\parencite{tariverdi2023}`, not `Tariverdi et al. found`). The citation goes at the end of the clause it supports, before
the punctuation, with one space before it: `... access loss \parencite{petricola2022}.` Several keys in one citation
go in alphabetical order, separated by `, `.

`refs.bib` pitfalls: biber treats every at-sign as the start of an entry, even on a `%` line, so never type one in a
comment; a duplicate key keeps only the first entry; protect capitals in titles with braces (`{Philippines}`); a
corporate author or a publisher that contains "and" needs double braces (`{{NASA ... Data and Information ...}}`).

### Line breaking and hyphenation

Words are never split across lines. `main.tex` sets this once:

```latex
\hyphenpenalty=10000  \exhyphenpenalty=10000  \tolerance=9999  \emergencystretch=3em
```

Don't add `\sloppy` to a section. Looser interword spacing (underfull boxes) is the accepted trade.

### One paragraph, one source line

Write each paragraph on a single line; never hard-wrap prose. LaTeX treats a single newline as a space, so wrapping
changes nothing in the PDF but makes diffs and search worse. Soft wrap in the editor is on for `[latex]` files.
Structural commands (`\section`, `\label`, `\begin`, `\end`) keep their own lines, and so do table rows; `\item` and
`\caption` start a line and run on.

### Tables, figures and references

- Every table and figure has a `\label` after its `\caption` and is named from the text with `Table~\ref{tab:x}` or
  `Figure~\ref{fig:x}` (non-breaking tilde, type named). Never write "the table below": floats move.
- Label prefixes: `sec:`, `tab:`, `fig:`. Use `Section~\ref{sec:x}` rather than typed section numbers.
- Captions go above tables and below figures. `booktabs` rules only (`\toprule`, `\midrule`, `\bottomrule`), no
  vertical rules.

### Anonymity

The competition is judged anonymously: no team name, member names, school or e-mail addresses anywhere in the sources or
the PDF (the PDF has no author field).

### Mechanics

- Thousands separators in typed numbers use `{,}`; the generator writes them that way.
- Ranges use an en dash `--` (`2018--2019`); a minus sign is `$-$`.
- `\section{...}` with no space before the brace.
