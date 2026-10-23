# Rules for agents (and humans) working in this repo

Bantay-Baha, PJDSC 2026. Read [HANDOFF.md](HANDOFF.md) first: it holds the current state, the next
steps and the data findings. [README.md](README.md) has setup and the source list. The concept is in `docs/`.

## Scope

- **Current phase: build (since 2026-10-23).** The full pipeline and dashboard exist: library code in `bantay/`,
  one entry point `scripts/build.py` (stages `crosswalk panel leadlag forecast ensemble scenarios catalog app lepto`, or `build.bat`), and the
  Streamlit app in `app/streamlit_app.py` (`run_app.bat`). Extend these; don't start parallel pipelines or notebooks.
- **Missing data never blocks a build.** A stage that lacks an input calls `config.missing()` / `config.have()`, prints a
  warning, records it in `data/processed/status.json`, and leaves its columns NaN or skips the output. Code for pending
  sources (GEE: IMERG, MAP friction, Sentinel-1 flood; manual: PSGC, NHFR) must pick the files up on the next run with no
  code change. **Never substitute fake, synthetic or imputed-as-real data** for a missing source.
- The dashboard reads only pre-computed files in `data/processed/app/`; keep heavy work in the build.
- Model choices that are provisional (action-tier thresholds, travel speeds, cut-off rule) are named constants with a
  comment; change them there, and say so in `HANDOFF.md`.
- The EDA notebook `notebooks/00_data_eda.ipynb` stays the one place for raw-data checks: short sections only
  (coverage, gaps, units, join keys), findings recorded with `note(dataset, msg)`.

## Environment

- Python: the venv at `%USERPROFILE%\.venvs\bantay-baha` (`~/.venvs/bantay-baha/Scripts/python` in Git Bash),
  Jupyter kernel `bantay-baha`. Never install into the system Python, and never put a venv inside the repo (it is in OneDrive).
- Add new packages to `requirements.txt` in the same change.
- Windows machine: use forward slashes or `pathlib` in code. No POSIX-only shell commands in scripts meant for teammates.

## Data rules

1. **`data/raw/` is read-only and append-only.** Never edit, rename, re-save or "clean" a raw file in place. Derived data
   go to `data/interim/` or `data/processed/`, produced by a script, never by hand.
2. **Every raw file comes from `scripts/download_data.py` or `scripts/download_gee.py`** (both write `MANIFEST.csv`). To add a source, add it to
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
- Reusable logic lives in the `bantay/` package (one module per layer: `units`, `dengue`, `storms`, `rain`, `rivers`,
  `flood`, `grids`, `panel`, `leadlag`, `forecast`, `access`, `scenarios`, `lepto`); paths and constants come from `bantay/config.py`.
  Expensive intermediates are cached in `data/interim/` and rebuilt when their raw inputs are newer.
- Heavy optional packages (torch, chronos-forecasting, tabpfn) go in `requirements-bench.txt` and its own venv
  (`%USERPROFILE%\.venvs\bantay-bench`), not `requirements.txt`. Benchmarks write `bench_<model>.parquet`; only
  `forecast.BENCH_MODELS` join the ensemble.
- Dashboard changes: run `python -m pytest tests` (AppTest + Playwright) before committing; keep new sections guarded so
  the app renders when an output is missing.
- Git worktrees that link `data/raw/<source>` as junctions: remove the junctions (`rmdir`) before `git worktree remove`.
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
