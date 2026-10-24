# Bantay-Baha

A graph-based early warning and response system for flood-linked disease outbreaks in the Philippines.
PJDSC 2026. The concept and plan are in [docs/](docs/); start with
`docs/Bantay-Baha_Team_Explainer.pdf`.

**Current phase: build.** The pipeline (panel, lead-lag graph, quantile forecast with calibrated surge risk and benchmark
models, two access methods, priority scenarios for the 4 backtest typhoons and a catalogue of 38 more storms,
leptospirosis lag analysis) and the Streamlit dashboard are in place; results are in [docs/results/](docs/results/). See [HANDOFF.md](HANDOFF.md) for where
things stand and what is still missing, and [AGENTS.md](AGENTS.md) for the rules on handling data and code.

## Quick start (Windows)

**Fastest: pull the team's copy from Cloud Storage** (all of `data/raw`, ~7 GB, checked against `MANIFEST.csv`).
You need access to the GCP project `hackathonproper` (ask the project owner to grant you *Storage Object Viewer* on the bucket; that is all a pull needs).

```bat
setup.bat                      :: venv + packages + kernel + Google sign-in (once) + pull all data
setup.bat dengue_hdx cchain    :: same, but only the listed sources
```

Sign in with the Google account that was given bucket access when the browser opens. Re-running is safe; finished steps are skipped.
Then open `notebooks/00_data_eda.ipynb` with the **Python (bantay-baha)** kernel.

The bucket is `gs://bantay-baha-raw-hackathonproper` (private, `asia-southeast1`). It mirrors what the download scripts produce;
after adding or refreshing a source, run the download script and then `scripts\sync_data.py push`.

**From the original sources** (slower; also what rebuilds the bucket):

You need Python 3.10+ on PATH and roughly 8 GB of free disk (the open data are ~7 GB, 4.7 GB of it UP NOAH).

```bat
download_data.bat                     :: open datasets only
download_data.bat my-gee-project-id   :: also the Google Earth Engine datasets
```

The script:
1. creates a virtual environment at `%USERPROFILE%\.venvs\bantay-baha` (outside OneDrive, so it is not synced),
2. installs `requirements.txt` and registers the Jupyter kernel **Python (bantay-baha)**,
3. downloads everything into `data/raw/<source>/` and records each file in `data/raw/MANIFEST.csv`.

It is safe to re-run: finished files are skipped, so after a dropped connection just run it again.

Then open `notebooks/00_data_eda.ipynb` with the **Python (bantay-baha)** kernel.

### Build and run the dashboard

```bat
build.bat                 :: everything: crosswalk panel leadlag forecast ensemble scenarios catalog app lepto (~1.5 h first time)
build.bat panel forecast  :: selected stages
run_app.bat               :: opens the dashboard in the browser
python scripts\make_results.py   :: regenerates the report and slides in docs\results\
python scripts\make_spec.py      :: regenerates the LaTeX technical specification (needs MiKTeX or TeX Live)
```

`build.bat` runs `scripts/build.py`. Inputs that are not on disk yet (Sentinel-1 flood masks, PSGC, NHFR, or anything still
downloading) are skipped with a warning, their outputs are left empty and listed in `data/processed/status.json` and on the
dashboard's *Data & caveats* tab. Re-run the build after the files arrive; no code changes are needed. The panel's data card is
written to `data/processed/panel_card.md`.

**Benchmark models (optional, GPU).** Chronos-2, TabPFN-TS and an MPNN-LSTM run in a separate venv (Python 3.12, CUDA
torch; exact commands in `requirements-bench.txt`) and write `data/processed/app/bench_<model>.parquet`:

```bat
%USERPROFILE%\.venvs\bantay-bench\Scripts\python scripts\benchmark_tsfm.py     :: Chronos-2 (incidence context + past covariates)
%USERPROFILE%\.venvs\bantay-bench\Scripts\python scripts\benchmark_tabpfn.py   :: TabPFN-TS (ungated TabPFN v2 weights)
%USERPROFILE%\.venvs\bantay-bench\Scripts\python scripts\benchmark_mpnn.py     :: MPNN-LSTM (border + RoRo graph)
%USERPROFILE%\.venvs\bantay-bench\Scripts\python scripts\benchmark_score.py    :: bench_summary.csv incl. variants
build.bat ensemble                                                          :: re-score + median ensemble, no refit
```

Only `chronos2`, `tabpfn_ts` and `mpnn_lstm` (`bantay/forecast.py: BENCH_MODELS`) join the median ensemble; other
`bench_*` files are variants.

### Technical specification (LaTeX)

`docs/spec/` is the evaluation report as a LaTeX document the team edits in VS Code; its PDF is
`docs/results/Bantay-Baha_Technical_Spec.pdf`. The prose (`docs/spec/sections/*.tex`) never types a result: every number
is a macro in `docs/spec/generated/numbers.tex`, and the tables are `docs/spec/generated/tab_*.tex`, both written by
`scripts/make_spec.py` from `data/processed/` (it reuses `make_results.stats()`, so the numbers are the report's).
Figures are the PNGs in `docs/results/figures/`. Writing conventions and details: [docs/spec/GUIDE.md](docs/spec/GUIDE.md).

You need MiKTeX or TeX Live (`pdflatex`, `biber`, `latexmk`) on PATH. In **VS Code**, install the recommended
**LaTeX Workshop** extension (`.vscode/extensions.json`) and open any file in `docs/spec/`: saving builds the PDF
(`.vscode/settings.json`: latexmk recipe, build on save, PDF in a tab, SyncTeX; output in `docs/spec/build/`, git-ignored).
On the **command line**:

```bat
cd docs\spec && latexmk                  :: docs\spec\build\main.pdf (reads docs\spec\latexmkrc: pdflatex + biber)
python scripts\make_spec.py              :: after a new build: regenerate generated\*.tex, compile, copy the PDF to docs\results\
python scripts\make_spec.py --no-pdf     :: regenerate generated\*.tex only
```

`docs/spec/generated/` is committed, so the document compiles without the data; after `build.bat` and
`make_results.py`, re-run `make_spec.py` (the tests fail while it is stale).

### Testing

Three kinds of tests live in `tests/`. **Pipeline unit tests** check the logic of `bantay/` and `scripts/` on small
hand-built inputs and need no build. **Build-output tests** (marker `data`) check invariants of the outputs in
`data/processed/` and skip when those are missing. **Dashboard tests** run the app with Streamlit's AppTest and, with
the marker `e2e`, in a real browser (Playwright). No test writes into `data/`: the status registry and SUS answers go to
temporary files, and a session check fails the run if any file under `data/` changed (so don't run the tests during a
build). Screenshots and videos land in `tests/artifacts/` (git-ignored).

```bat
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest tests                            :: everything (~1.5 min)
python -m pytest tests -m "not e2e"               :: no browser (~40 s)
python -m pytest tests -m "not e2e and not data"  :: no browser, no build-output invariants
python -m pytest tests\test_forecast.py           :: one module
python tests\capture.py                           :: refresh docs\results\figures\dashboard.png + record the demo walkthrough video
```

| Tests | What they check |
|---|---|
| `test_config.py` | the DOH week rule (`week_ending`: Mon-Sun, a Sunday maps to itself), the `record` / `missing` / `have` status round trip |
| `test_units.py` | `norm`; the crosswalk rules on a mini COD-AB table: city first (Quezon City is not Quezon), the Isabela collision, the Maguindanao merge and its synthetic id; `#` header comments |
| `test_dengue.py` | HXL row, stripped `loc`, Sunday weeks; a unit-week is NaN unless every member reported; deaths are never used |
| `test_storms.py` | gale-radius fallback (USA R34, TOKYO R30, fixed; below gale = 0), shifted tracks, the forecast-origin exposure window |
| `test_panel.py` | Sentinel-1 placed from the week its map is known, never at its storm's origin week; the interim cache; weekly rain sums, river routing |
| `test_forecast.py` | WIS (hand values, pinball identity), coverage, `prob_exceed`, seasonal naive, no target leakage in features, surge thresholds, R calibration on past outcomes only, benchmark loading and the median ensemble, rolling-origin training windows |
| `test_access.py` | the cut-off rule, summaries, flood multipliers, the network solver on a 4-node road with a ferry, the MAP friction raster on a 5 x 5 GeoTIFF |
| `test_scenarios.py`, `test_leadlag.py`, `test_lepto.py` | tiers from `TIERS`, the access-method range, priority P; an empty graph below `MIN_T`, a planted lead; the leptospirosis findings wording |
| `test_scripts.py` | downloads skip existing files and write through `.part` (no network), manifest merge and sha256, the bucket manifest, `check_code_guide.py` (and that the real guide is current) |
| `test_build_outputs.py`, `test_make_results.py` (`data`) | 85 units x 262 weeks, S1 timing, scenario ranges, catalogue `train_end` <= origin, every model on the same rows, `status.json`; the report and 20 slides on the full build and with each optional part removed |
| `test_flood.py`, `test_spec_flags.py` | the EMS reader leaves `status.json` alone for the documents; the spec's wording flags: registry, recomputed from the outputs (`data`), and a compile with every flag inverted (`slow`) |
| `test_sus.py`, `test_app.py`, `test_e2e.py` (`e2e`) | SUS scoring and storage; every dashboard tab, control and optional output; the browser walk-through (every tab, storm and shift, dark mode, SUS submission; fails on any app exception or browser console error) |

A test marked `xfail(strict=True)` documents a known bug that is not fixed yet; its reason says what is wrong, and the
suite fails as soon as the bug is fixed (then remove the mark).

`tests/test_spec.py` checks the technical specification: every macro the sections use is defined, the generated numbers
and tables match the build outputs and are up to date, no result is typed into the prose, every citation, figure and
table exists, and (marked `slow`, skipped without latexmk) that it compiles with no errors, undefined references or
overfull boxes; `python -m pytest tests -m "not slow"` skips the compile.

User-test answers from the dashboard's *Usability test* tab go to `data/processed/sus/sus_responses.csv` (set
`BANTAY_SUS_PATH` to write elsewhere); no names or identifiers are collected.

### Earth Engine (optional, free)

IMERG rainfall, the MAP friction surface, the Global Flood Database, the Sentinel-1 scene inventory and the per-typhoon
Sentinel-1 flood masks come from Google Earth Engine.
1. Register a non-commercial project at <https://code.earthengine.google.com/register> (*Unpaid usage → Academia & Research*).
2. `%USERPROFILE%\.venvs\bantay-baha\Scripts\earthengine.exe authenticate`
3. `download_data.bat <your-project-id>` (the team project is `hackathonproper`)

No NASA Earthdata account is needed; IMERG comes through Earth Engine.

### Manual downloads

These sites block scripted downloads, so save the files by hand:

| Dataset | Where | Save to |
|---|---|---|
| PSA PSGC 2Q 2026 (Excel) | <https://psa.gov.ph/classification/psgc> | `data/raw/psgc/` |
| DOH National Health Facility Registry | <https://nhfr.doh.gov.ph/rfacilities2list.php> | `data/raw/nhfr/` |

## Repository layout

```
docs/                       concept proposal, team explainer, submitted proposal (PDF); docs/proposal/ revised v3; docs/results/ report + deck
docs/CODE_GUIDE.md          walkthrough of every file and code block (start here to read the code); after moving code run
                            python scripts/check_code_guide.py --fix (re-syncs its line links), then check it
docs/spec/                  technical specification in LaTeX: main.tex, sections/, refs.bib, latexmkrc, GUIDE.md;
                            generated/ (numbers and tables from scripts/make_spec.py); build/ (git-ignored)
.vscode/                    LaTeX Workshop settings (recipes, build on save) and the recommended extension
scripts/download_data.py    open-source downloads (idempotent, writes MANIFEST.csv)
scripts/download_gee.py     Earth Engine downloads (needs --project)
setup.bat                   one-click team setup: venv, kernel, sign-in, pull data from the bucket
scripts/sync_data.py        push/pull data/raw to/from the team's private Cloud Storage bucket
download_data.bat           one-click setup + download for Windows
scripts/build.py            one-command rebuild of everything the dashboard reads (build.bat)
scripts/make_results.py     regenerates docs/results/ (evaluation report + 20-slide deck, PDF)
scripts/make_spec.py        regenerates docs/spec/generated/ and the technical specification PDF (latexmk)
scripts/benchmark_*.py      optional benchmarks: Chronos-2, TabPFN-TS, MPNN-LSTM + scorer (requirements-bench.txt)
scripts/make_proposal.py    revised anonymous proposal v3 (docs/proposal/, PDF via headless Chrome)
bantay/                     library: units, dengue, storms, rain, rivers, flood, grids, panel, leadlag, forecast, access,
                            scenarios, lepto
app/                        the dashboard (streamlit_app.py + ui, sus, lepto_tab; run_app.bat)
tests/                      pytest: pipeline unit tests, build-output checks, AppTest + Playwright, test_spec.py (LaTeX spec)
notebooks/00_data_eda.ipynb one notebook: a short EDA of every dataset + proposal checks
data/raw/                   downloaded data (git-ignored, read-only; only MANIFEST.csv is tracked)
data/crosswalks/            reviewed crosswalks into the harmonised 2016-2020 province units (tracked)
data/interim/, processed/   derived data (git-ignored, rebuilt by scripts/build.py)
.claude/skills/             agent skills for Claude Code: playwright-cli, web-design-guidelines, and six data-science skills
                            (scikit-learn, statsmodels, shap, statistical-analysis, scientific-critical-thinking,
                            timesfm-forecasting) pinned and hash-checked in VENDORED.json (tests/test_skills.py);
                            usage rules in AGENTS.md "Agent skills"
```

## Data sources

| Folder | Dataset | Role | Access |
|---|---|---|---|
| `dengue_hdx` | DOH-Epi dengue cases/deaths, province/city × week, 2016 to Jan 2021 (HDX) | Forecast target | open |
| `cchain` | Project CCHAIN PIDSR city-week disease totals (dengue, leptospirosis, …), 2008–2022 | Lepto stretch goal, cross-check | open |
| `mendeley_parreno` | Parreño (2023) national weekly notifiable diseases, 2019–2023 | National cross-check | open |
| `opendengue` | OpenDengue V1.3 | National cross-check | open |
| `cod_ab` | HDX COD-AB administrative boundaries (current) | Geometry, join keys | open |
| `census2020` | 2020 CPH population by municipality (HDX) | Population | open |
| `ibtracs` | IBTrACS v04r01, Western Pacific | Storm tracks, gale radius | open |
| `chirps` | CHIRPS v2.0 daily 0.05°, PHL subset (IRI Data Library) | Rainfall | open |
| `imerg` | GPM IMERG V07 daily | Rainfall | GEE |
| `copernicus_ems` | EMSR312 (Ompong) flood delineation; EMSR478 (Rolly) damage grading | Flood cross-check | open |
| `noah` | UP NOAH flood hazard, 5- and 25-year, per province | Static susceptibility | open (Google Drive) |
| `gfd`, `sentinel1` | Global Flood Database events; Sentinel-1 scene inventory | Observed flood | GEE |
| `s1_flood` | Sentinel-1 flood masks per backtest typhoon (UN-SPIDER change detection, 100 m tiles near each track) | Observed flood | GEE |
| `hydrorivers` | HydroRIVERS v1.0 Australasia (covers PHL) | River routing | open |
| `osm` | OpenStreetMap Philippines (Geofabrik PBF) | Road network | open |
| `roroph` | MARINA/PPA RoRo routes (roroph R package data) | Ferry edges | open |
| `hotosm_health`, `noah_facilities` | OSM health facilities; UP NOAH critical facilities | Hospital nodes (NHFR fallback) | open |
| `map_friction` | Malaria Atlas Project friction surface 2019 | Raster access method | GEE |
| `worldpop`, `meta_hrsl` | WorldPop 2020 100 m (UN-adjusted); Meta HRSL under-5 / 60+ | Population weights | open |
| `psgc`, `nhfr` | PSA PSGC; DOH NHFR | Join keys; hospital list | manual |
