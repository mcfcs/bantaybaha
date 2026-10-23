# Results

| File | What |
|---|---|
| `Bantay-Baha_Evaluation_Report.pdf` | Full evaluation results (A4): data, methods, forecast skill, ablations, calibration, lead-lag graph, access loss, scenarios, backtest, sensitivity, benchmark, scorecard against the proposal, limitations, references (APA 7) |
| `Bantay-Baha_Slides.pdf` | 20-slide deck (16:9) for the PJDSC 2026 panel presentation; each slide is tagged with the judging criterion it answers |
| `figures/` | The figures, drawn from the pipeline outputs. `dashboard.png` is a headless-Chrome screenshot of the running app (`run_app.bat`, Ompong, observed track) |
| `src/` | The generated HTML both PDFs are printed from, and the fonts (Big Shoulders Display, Barlow, Space Mono; SIL Open Font License, licences included) |

Regenerate after a new build:

```bat
build.bat
python scripts\make_results.py
```

Every number in both documents is computed from `data/processed/` and `data/raw/MANIFEST.csv` at generation time. To refresh `dashboard.png`, start the app and run Chrome headless with `--screenshot` against `http://localhost:8501`.
