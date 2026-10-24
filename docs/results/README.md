# Results

| File | What |
|---|---|
| `Bantay-Baha_Evaluation_Report.pdf` | Full evaluation results (A4, 20 pages): data, methods, forecast skill and ablations, model comparison (XGBoost vs Chronos-2, TabPFN-TS, MPNN-LSTM and their median ensemble), recalibrated surge probability R, lead-lag graph, Sentinel-1 flood (per unit and per municipality), access loss with both methods (road + ferry network vs MAP friction raster) and vulnerable groups, Ompong priority, the storm catalogue (every scored storm 2017-2020), backtest, sensitivity, Metro Manila benchmark, leptospirosis, scorecard against the proposal, limitations, references (APA 7) |
| `Bantay-Baha_Technical_Spec.pdf` | The technical specification: the evaluation report's content as a LaTeX document (A4), compiled from `docs/spec/` (the editable source; see `docs/spec/GUIDE.md`). Same numbers as the report: they come from the same `make_results.stats()` through `docs/spec/generated/numbers.tex` |
| `Bantay-Baha_Slides.pdf` | 20-slide deck (16:9) for the PJDSC 2026 panel presentation; each slide is tagged with the judging criterion it answers |
| `Bantay-Baha_Demo_Script.md` / `.pdf` | Demonstration-video script (2:50), with the on-screen numbers checked against the build; the markdown is the source, the PDF is generated from it |
| `figures/` | The figures, drawn from the pipeline outputs. `dashboard.png` is a screenshot of the running app (`run_app.bat`, Ompong, observed track), maintained with the dashboard |
| `src/` | The generated HTML the PDFs are printed from, and the fonts (Big Shoulders Display, Barlow, Space Mono; SIL Open Font License, licences included) |

Regenerate after a new build:

```bat
build.bat
python scripts\make_results.py
python scripts\make_spec.py      :: the technical specification (needs MiKTeX or TeX Live: latexmk, biber)
```

`make_spec.py` writes `docs/spec/generated/` (number macros and table rows), compiles `docs/spec/main.tex` with latexmk
and copies the PDF here. The spec's figures are this folder's `figures/`, so run `make_results.py` first.

Every number in the report, the deck and their figures is computed from `data/processed/` (and, for a few data findings,
read-only from `data/raw/`: the MANIFEST, the DOH dengue CSV, the census age table and IBTrACS) at generation time; the
only typed numbers are cited literature figures on the problem slides. The model comparison renders whatever models are
in `data/processed/app/eval_models.csv` and names any expected benchmark that is missing. The demo script's numbers are
typed into the markdown: re-check them on screen after a rebuild. An automatic overflow check (headless Chrome) runs on
both documents and must print `ok`.

The revised concept proposal is in `docs/proposal/` (`python scripts/make_proposal.py`).
