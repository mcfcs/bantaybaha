# Bantay-Baha

Early warning for flood-linked disease after a typhoon. For any typhoon track, Bantay-Baha ranks the Philippine provinces
by **where dengue is likely to surge** and **who will lose their road or ferry route to a hospital**, and turns the two
into an action: deploy mobile clinics, pre-position supplies, or monitor sentinel sites.

This package has the dashboard, the pre-computed results it shows, all the code that produced them, and the
documents (report, slides, demo scripts, code guide). Everything runs on open data.

---

## 1. Open the dashboard (about 5 minutes)

Windows, with Python 3.11 or newer on PATH (tested with Python 3.13):

1. Unzip this folder somewhere short, e.g. `C:\bantay-baha`.
2. Double-click **`install.bat`**. It creates a Python environment in `%USERPROFILE%\.venvs\bantay-baha` and installs
   `requirements.txt`. It downloads no data.
3. Double-click **`run_app.bat`**. The dashboard opens in your browser at <http://localhost:8501>.
   Stop it with Ctrl+C in the black window.

macOS / Linux, or without the .bat files:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The dashboard reads only the pre-computed files in `data/processed/app/`, so it starts in seconds and needs no
internet connection (except for the web font).

---

## 2. Using the dashboard

### Choose a scenario (left sidebar)

| Control | What it does |
|---|---|
| **Typhoon** | The four backtest typhoons come first (Ompong 2018, Tisoy 2019, Rolly 2020, Ulysses 2020), then every other 2017-2020 storm whose gale-force winds reached land (the storm catalogue). Type a name to search. |
| **Move track north or south / east or west** | For the four backtest typhoons only: replays the same storm with its track moved 0.5-1° north or south, or 1° east or west. Use it to ask "what if it comes in further south?" |
| **Back to observed track** | Returns to the real track. |
| **How to read this** | The definitions of R, A, P and the action tiers. |

Your choice is kept in the page address, so you can share a scenario by copying the link.

### The three numbers

- **Surge risk R**: the chance that the province's dengue cases over the next 4 weeks exceed its usual bad month (its
  90th percentile), calibrated on past forecasts.
- **Access loss A**: the share of the province's people who lose their route to a hospital because of this storm (flooded
  roads, cancelled ferries). Measured two ways, a road-and-ferry network and a travel-time map, so it is shown as a range.
- **Priority P = R x A**: high only where a surge is likely *and* people are cut off. The map and tables rank by P.

Action tiers: **deploy** mobile clinics when R >= 0.5 and A >= 10%; **pre-position** doxycycline and vector-control
supplies when R >= 0.3, or A >= 10% with R >= 0.15; otherwise **monitor** sentinel sites.

### The tabs

| Tab | What you see |
|---|---|
| **Action map** | Provinces coloured by priority (switch to R or A), the storm track, its gale-force swath and the cancelled ferry routes; **Act first** lists the top ten with their tier. |
| **Risk vs access** | Every province on two axes, surge risk and access loss; top right means act first. The dotted lines are the tier thresholds. |
| **Provinces** | The full ranked table: R (and R before calibration), A with its method range, expected cases for the next 4 weeks with a 90% range, people cut off (all, under 5, aged 60+), sentinel and community, and the main drivers of the risk. Hover a column header for its definition; **Download table (CSV)** saves it. |
| **Municipalities** | Pick a province to see its towns and cities: people cut off and, where radar saw it, people in new floodwater. Tells you where a mobile clinic should go. |
| **Outbreak graph** | Which provinces' dengue rises before others' (lead-lag links), the sentinel provinces to watch first, and groups that move together. |
| **Forecast skill** | How good the forecast was in two years of real-time-style tests: the model against a seasonal baseline and three benchmark models, calibration of R, and forecast ranges for any province, 1-4 weeks ahead. |
| **Leptospirosis** | How many weeks after heavy rain leptospirosis cases rise, in 12 cities and nationally, and whether cities inside a typhoon's swath saw more cases. |
| **Validation** | Did high-priority provinces really surge afterwards; how much the two access methods agree; whether the ranking changes when the settings change; a Metro Manila benchmark against a published study. |
| **Data & caveats** | The limits of the current scenario, which inputs were available for this run, and the storm catalogue (which storms are included and why others were skipped). |
| **Usability test** | A 15-minute scenario task and the System Usability Scale questionnaire for health officers; responses are saved locally. |

Hover any point on a map or chart for its values. Light and dark mode follow your system setting.

---

## 3. What is in this folder

| Path | Contents |
|---|---|
| `install.bat`, `run_app.bat` | Install the environment; start the dashboard. |
| `download_data.bat`, `build.bat` | Rebuild everything from the original open sources (section 4). |
| `requirements.txt` | Every Python package, pinned to the versions the results were made with. |
| `requirements-bench.txt` | Optional, heavy: only for re-running the benchmark models (Chronos-2, TabPFN-TS, MPNN-LSTM). |
| `app/` | The dashboard (Streamlit). |
| `bantay/` | The library: units, dengue, storms, rain, rivers, flood, population grids, panel, lead-lag graph, forecast, access, scenarios, leptospirosis. |
| `scripts/` | `build.py` (the pipeline), the download scripts, the benchmark scripts and the document generators. |
| `tests/` | The test suite (`python -m pytest tests`). |
| `data/processed/app/` | The pre-computed results the dashboard reads; `data/processed/status.json` lists the inputs each run had. |
| `data/raw/MANIFEST.csv` | Every raw file the results were built from, with its source URL, size and checksum. |
| `data/crosswalks/` | The reviewed tables that map the dengue reporting units to 2016-2020 provinces. |
| `docs/results/` | Evaluation report, slide deck, demonstration and technical demo scripts, code guides (PDF). |
| `docs/CODE_GUIDE.md` | A walkthrough of every file and code block. |
| `notebooks/00_data_eda.ipynb` | The raw-data checks (coverage, gaps, units, join keys). |
| `README_DEVELOPERS.md` | The full developer README: sources, pipeline stages, outputs, testing. |

---

## 4. Rebuild from the raw data (optional)

The raw data (about 7 GB from 22 open sources) are not in this package; they are downloaded by script.

1. `download_data.bat` downloads the open sources into `data/raw/` and checks them against `MANIFEST.csv`.
   `download_data.bat <your-earth-engine-project>` also pulls the Google Earth Engine sources (Sentinel-1 flood maps,
   IMERG rain, the travel-time raster); it needs a free Earth Engine project and `earthengine authenticate` first.
2. Two sources block scripted downloads and are saved by hand (links in `README_DEVELOPERS.md`): the PSA PSGC code list
   (`data/raw/psgc/`) and the DOH National Health Facility Registry (`data/raw/nhfr/`). Without NHFR, hospitals come
   from OpenStreetMap and UP NOAH.
3. `build.bat` runs the whole pipeline and rewrites `data/processed/`. Inputs that are missing are skipped with a
   warning and listed in `status.json`; nothing is ever filled with made-up data. Re-run after they arrive.
4. Refresh the dashboard page to see the new results.

The forecast models are retrained from scratch on every build, each only on data available before its storm, with a
fixed random seed: the same data give the same model. The dashboard itself never trains anything.

---

## 5. Data and limits

- Disease data are aggregated and non-identifiable: DOH weekly dengue per province (2016-2020), city-level
  leptospirosis from Project CCHAIN, national PIDSR counts.
- 2020 dengue reporting collapsed under COVID-19, so 2020 is used for access scenarios only, never as a forecast target.
- Flood-hazard maps are missing for some provinces; those are shown as missing, never as zero hazard.
- Ferry routes are 2024-2026 data used as a proxy for 2018-2020.
- Shifted tracks use flood-hazard maps instead of observed radar flood, so their access losses are upper-bound estimates.
- The leptospirosis results cover 12 cities and are not extrapolated to provinces.
