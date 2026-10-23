# Bantay-Baha

A graph-based early warning and response system for flood-linked disease outbreaks in the Philippines.
PJDSC 2026. The concept and plan are in [docs/](docs/); start with
`docs/Bantay-Baha_Team_Explainer.pdf`.

**Current phase: build.** The pipeline (panel, lead-lag graph, quantile forecast, access model, priority scenarios) and
the Streamlit dashboard are in place; results are in [docs/results/](docs/results/). See [HANDOFF.md](HANDOFF.md) for where
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
build.bat                 :: everything: crosswalk, panel, leadlag, forecast, scenarios, app (about 1 h the first time)
build.bat panel forecast  :: selected stages
run_app.bat               :: opens the dashboard in the browser
python scripts\make_results.py   :: regenerates the report and slides in docs\results\
```

`build.bat` runs `scripts/build.py`. Inputs that are not on disk yet (Sentinel-1 flood masks, PSGC, NHFR, or anything still
downloading) are skipped with a warning, their outputs are left empty and listed in `data/processed/status.json` and on the
dashboard's *Data status* tab. Re-run the build after the files arrive; no code changes are needed. The panel's data card is
written to `data/processed/panel_card.md`.

Optional zero-shot benchmark (Chronos-2, installs torch): `pip install -r requirements-bench.txt`, then
`python scripts/benchmark_tsfm.py`.

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
docs/                       concept proposal, team explainer, submitted proposal (PDF)
scripts/download_data.py    open-source downloads (idempotent, writes MANIFEST.csv)
scripts/download_gee.py     Earth Engine downloads (needs --project)
setup.bat                   one-click team setup: venv, kernel, sign-in, pull data from the bucket
scripts/sync_data.py        push/pull data/raw to/from the team's private Cloud Storage bucket
download_data.bat           one-click setup + download for Windows
scripts/build.py            one-command rebuild of everything the dashboard reads (build.bat)
scripts/make_results.py     regenerates docs/results/ (evaluation report + 20-slide deck, PDF)
scripts/benchmark_tsfm.py   optional Chronos-2 benchmark (requirements-bench.txt)
bantay/                     library: units, dengue, storms, rain, rivers, flood, grids, panel, leadlag, forecast, access, scenarios
app/streamlit_app.py        the dashboard (run_app.bat)
notebooks/00_data_eda.ipynb one notebook: a short EDA of every dataset + proposal checks
data/raw/                   downloaded data (git-ignored, read-only; only MANIFEST.csv is tracked)
data/crosswalks/            reviewed crosswalks into the harmonised 2016-2020 province units (tracked)
data/interim/, processed/   derived data (git-ignored, rebuilt by scripts/build.py)
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
