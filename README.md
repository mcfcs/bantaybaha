# Bantay-Baha

A graph-based early warning and response system for flood-linked disease outbreaks in the Philippines.
Team **G is Cash**, PJDSC 2026. The concept and plan are in [docs/](docs/); start with
`docs/Bantay-Baha_Team_Explainer.pdf`.

**Current phase: data acquisition and a quick EDA.** No model or dashboard code yet. See [HANDOFF.md](HANDOFF.md) for
where things stand and [AGENTS.md](AGENTS.md) for the rules on handling data and code.

## Quick start (Windows)

You need Python 3.10+ on PATH and roughly 4 GB of free disk.

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

### Earth Engine (optional, free)

IMERG rainfall, the MAP friction surface, the Global Flood Database and the Sentinel-1 scene inventory come from Google Earth Engine.
1. Register a non-commercial project at <https://code.earthengine.google.com/register> (*Unpaid usage → Academia & Research*).
2. `%USERPROFILE%\.venvs\bantay-baha\Scripts\earthengine.exe authenticate`
3. `download_data.bat <your-project-id>`

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
download_data.bat           one-click setup + download for Windows
notebooks/00_data_eda.ipynb one notebook: a short EDA of every dataset + proposal checks
data/raw/                   downloaded data (git-ignored, read-only; only MANIFEST.csv is tracked)
data/interim/, processed/   derived data (git-ignored, rebuilt by scripts)
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
| `hydrorivers` | HydroRIVERS v1.0 Asia | River routing | open |
| `osm` | OpenStreetMap Philippines (Geofabrik PBF) | Road network | open |
| `roroph` | MARINA/PPA RoRo routes (roroph R package data) | Ferry edges | open |
| `hotosm_health`, `noah_facilities` | OSM health facilities; UP NOAH critical facilities | Hospital nodes (NHFR fallback) | open |
| `map_friction` | Malaria Atlas Project friction surface 2019 | Raster access method | GEE |
| `worldpop`, `meta_hrsl` | WorldPop 2020 100 m (UN-adjusted); Meta HRSL under-5 / 60+ | Population weights | open |
| `psgc`, `nhfr` | PSA PSGC; DOH NHFR | Join keys; hospital list | manual |
