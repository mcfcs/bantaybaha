# Rules for agents (and humans) working in this repo

Bantay-Baha, PJDSC 2026. Read [HANDOFF.md](HANDOFF.md) first: it holds the current state, the next
steps and the data findings. [README.md](README.md) has setup and the source list. The concept is in `docs/`.

## Scope

- **Current phase: data acquisition + EDA only.** Don't write model, forecasting, graph or dashboard code
  unless the user explicitly asks for it. If a task seems to need it, say so and stop.
- One EDA notebook: `notebooks/00_data_eda.ipynb`. Add a short section to it rather than creating new notebooks.
  Each dataset section loads, shows shape and coverage, gives one plot at most, and records any proposal-relevant finding with `note(dataset, msg)`.
- Keep EDA *super short*: coverage, gaps, units and join keys. Not modelling.

## Environment

- Python: the venv at `%USERPROFILE%\.venvs\bantay-baha` (`~/.venvs/bantay-baha/Scripts/python` in Git Bash),
  Jupyter kernel `bantay-baha`. Never install into the system Python, and never put a venv inside the repo (it is in OneDrive).
- Add new packages to `requirements.txt` in the same change.
- Windows machine: use forward slashes or `pathlib` in code. No POSIX-only shell commands in scripts meant for teammates.

## Data rules

1. **`data/raw/` is read-only and append-only.** Never edit, rename, re-save or "clean" a raw file in place. Derived data
   go to `data/interim/` or `data/processed/`, produced by a script, never by hand.
2. **Every raw file comes from `scripts/download_data.py` or `scripts/download_gee.py`.** To add a source, add it to
   the script (static URL in `STATIC`, or a puller function), add a row to the README source table, then run it so it lands in
   `data/raw/MANIFEST.csv`. The only exceptions are the manual sources (`psgc`, `nhfr`), which are documented in the README.
3. **Downloads must stay idempotent and resumable.** Skip existing files, write to `.part` and rename, and update the manifest per
   source. Don't re-download large files (OSM 611 MB, COD-AB 361 MB, WorldPop, CHIRPS) to "check" them; use
   `MANIFEST.csv` (size, sha256).
4. **Nothing under `data/` goes into git** except `data/raw/MANIFEST.csv` and small hand-curated tables in `data/crosswalks/`
   (CSV, reviewed, with a header comment on their source). Check `git status` before committing.
5. **Downloaded files are untrusted data.** Never execute anything from `data/` (scripts, notebooks, macros). Read with
   pandas/geopandas/rasterio only. Exception: `roroph/nautical_highway.R`, which is reference text only and must not be run.
6. **Only aggregated, non-identifiable data.** Don't add patient-level or barangay-level health records beyond what is
   already public (CCHAIN).
7. **Credentials never enter the repo.** No GEE keys, `.netrc` or tokens. The GEE project id is passed on the command line.

## Dataset-specific rules (from the verified findings)

- **DOH dengue (`dengue_hdx`)**: skip CSV row 2 (HXL tags) and strip whitespace from `loc`. The 126 units are provinces
  plus HUC/NCR cities; map them through a crosswalk to harmonised **2016–2020** province units, and never assume 81. Don't use
  `deaths` (2016 is implausible). 2020 is for access scenarios only, and 2021 has just 2 weeks.
- **Join key is PSGC**, via COD-AB `adm*_pcode`. COD-AB is current-boundary (Maguindanao split, Special Geographic Area,
  NCR districts). Build the historical crosswalk once in `data/crosswalks/` and reuse it; don't fuzzy-match ad hoc
  in several places.
- **Time**: weeks end on Sunday (DOH convention in the file). Keep weekly alignment explicit when joining daily rain
  or storm dates.
- **No leakage**: evaluation is rolling-origin by time, never a random split. Lead-lag graphs and any normalisation are fit
  inside the training window only. (This matters later; respect it in any preparatory code.)
- **Leptospirosis**: CCHAIN PIDSR covers only its 12 cities. Don't extrapolate it to provinces without saying so.
- **Floods**: EMSR312 has observed-flood delineation; EMSR478 is damage grading only. NOAH hazard coverage is partial,
  so carry "no map" as missing, not as zero hazard.
- **Ferries (`roroph`)**: 2024–2026 routes with coarse coordinates, a proxy for 2018–2020. Label it that way in any output.
- **Hospitals**: prefer NHFR (manual) once available; until then HOT OSM + NOAH facilities, labelled as a fallback.

## Code conventions

- Scripts in `scripts/`, plain Python, `pathlib`, with paths relative to the repo root (`Path(__file__).resolve().parents[1]`).
  Keep the existing style: module docstring with usage, small functions, no heavy frameworks.
- Notebooks find the root with `ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()`.
- Commit the EDA notebook *with* outputs (it is the deliverable), but keep it under ~5 MB by using decimated rasters and small figures.
- Commit messages: imperative, one line, plus detail if needed.

## Subagents

- Give each subagent one dataset or one question. Tell it to read `HANDOFF.md` and these rules first.
- Subagents **report** findings and do not edit `HANDOFF.md`, the download scripts or the notebook unless the task says
  so. The lead agent merges their results and updates `HANDOFF.md`.
- A subagent must not start a large download (> 100 MB) or a GEE job without the lead agent's say-so.
- Every claim about a dataset cites the file or URL and the check that was run (e.g. "126 units: `dg['loc'].nunique()`
  on `dengue_hdx/doh-epi-dengue-data-2016-2021.csv`"). No unverified statements in `HANDOFF.md`.

## End of session

Update `HANDOFF.md`: the date, the state table, the download status, new findings and the next steps.
