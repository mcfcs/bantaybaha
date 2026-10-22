# Handoff

_Last updated: 2026-10-22._ Update this file at the end of every work session.

## Where we are

**Phase: data acquisition + one quick EDA notebook.** The brief: initialise the repo only to get the datasets and
sources right and to check the proposal's references and development plan against the real data. **Do not start
model or dashboard code** until the data findings below are reviewed by the team.

| Step | State |
|---|---|
| Read the three docs in `docs/` | done |
| Verify each data source in Appendix B, Table 1 (exists, reachable, covers what the proposal assumes) | done (findings below) |
| Python env + Jupyter kernel `bantay-baha` | done (`%USERPROFILE%\.venvs\bantay-baha`) |
| `scripts/download_data.py`, `scripts/download_gee.py`, `download_data.bat` | written; the open script has run, the GEE script has not |
| Open-data download | **partial**: the connection dropped (see below) |
| Earth Engine download | **not started**: the user is registering a GEE project |
| PSGC + NHFR manual downloads | **not done** (both sites block scripts) |
| `notebooks/00_data_eda.ipynb` | written, **not executed yet** |

### Download status (as of the network drop)

| Source | Status |
|---|---|
| dengue_hdx, cchain, mendeley_parreno, opendengue, ibtracs, hydrorivers, roroph, hotosm_health, noah_facilities, copernicus_ems, census2020, cod_ab, worldpop, meta_hrsl | complete |
| osm | complete (resumed with curl; MD5 matches Geofabrik's `.md5`) |
| chirps | 2016, 2017 complete; **2018–2020 missing** |
| noah | **not started** (5yr: 67 files, 25yr: 72 files on the UP NOAH Google Drive) |
| imerg, map_friction, gfd, sentinel1 | waiting on GEE |
| psgc, nhfr | manual |

`data/raw/MANIFEST.csv` was not written, because both runs were interrupted before the old end-of-run write. The script now writes
it after each source. **Re-running `download_data.bat` fetches only the missing files and rebuilds the manifest.**

## Next steps

1. Re-run `download_data.bat` (or `python scripts/download_data.py chirps noah`, then a plain run to rebuild the manifest).
   If Google Drive rate-limits the NOAH files (gdown errors), wait an hour and re-run.
2. GEE: register a project, then `earthengine authenticate` and `download_data.bat <project-id>`.
3. Download PSGC 2Q 2026 and NHFR by hand into `data/raw/psgc/` and `data/raw/nhfr/`.
4. Execute `notebooks/00_data_eda.ipynb` top to bottom. Fix any cell that breaks on real data. The last cell collects
   the findings into one table.
5. Review the findings with the team, then update the proposal's Table 1 and the plan (see "Proposal corrections").
6. Only then: build the historical province crosswalk (`data/crosswalks/`) and the province-week panel.

## Findings so far (checked against the real files)

### Proposal corrections

1. **The dengue file has 126 reporting units, not 81 provinces.** It mixes provinces with 45 HUC/NCR cities (Cebu City,
   Davao City, all NCR cities, …) and has misspellings: `NUEVA VISCAYA`, `SISQUIJOR`, `BASILIG CITY`, `NORTH COTABATO`,
   and leading spaces in `" CAGAYAN DE ORO CITY"` and `" NEGROS ORIENTAL"`. Row 2 of the CSV holds HXL tags (skip it).
   The data run from 2016-01-10 to 2021-01-10, weekly, on Sundays.
2. **Dengue deaths are unreliable.** 2016 has 8,127 deaths (about 3.9% CFR) against 1,195–4,563 in the other years. Don't use deaths.
3. **2020 cases fell to 91k (2019: 442k)** because of the COVID reporting collapse. The proposal's "2020 for access only" holds.
4. **A subnational leptospirosis series is openly available.** Project CCHAIN (HDX) has weekly PIDSR city counts, 2008–2022,
   for leptospirosis, dengue and 7 other diseases across its 12 cities, which spans all four backtest typhoons. The
   proposal says "no open subnational series exists" and plans to digitise DOH reports; revisit that.
5. **EMSR478 (Rolly) has only damage-grading products (4 AOIs), no flood delineation**, so it can't cross-check
   Sentinel-1 flood extent. EMSR312 (Ompong) does have observed-flood delineation, for 6 Northern Luzon AOIs
   (Tuguegarao, Ilagan, Vigan, Candon, Sudipen, Aparri). No EMS activation was found for Tisoy or Ulysses.
6. **The flood hazard maps come from the UP NOAH Google Drive, not LiPAD.** They are per province at 5/25/100-year return periods, and
   coverage is partial (67 files at 5-year, 72 at 25-year), so "share of population in a hazard zone" is undefined for some provinces.
7. **COD-AB uses current boundaries (88 ADM2 units)**: 4 NCR districts, Maguindanao del Norte/Sur (split in 2022), the
   "Special Geographic Area" (2024) and "City of Isabela". The 2016–2020 dengue data use the old units, so a harmonised
   historical crosswalk is required.
8. **The IBTrACS 34-kt gale radius (USA_R34) is on only ~67% of fixes** for the four storms (TOKYO_R30 is on ~75%). The ferry-closure
   buffer needs a fallback.
9. **roroph** (CRAN/r-universe `pinasr/roroph`) has 108 routes, as stated, but covers **2024–2026** operations. Names are
   GADM-style (`AgusandelNorte`) and port coordinates are coarse (to 0.1°). For 2018–2020 it is a proxy and needs snapping to OSM ports.
10. **NHFR blocks scripted access.** It needs a manual download, or use the fallbacks: HOT OSM health facilities and the UP NOAH
    critical-facilities layer (20,051 points, name + amenity only, no facility level).
11. **IMERG V07 and the MAP friction surface 2019 are both in the GEE catalog**, so no NASA Earthdata account is needed.
12. **The Global Flood Database ends in 2018**, so at most it covers Ompong.
13. **The development plan dates (13–24 Oct 2026) are mostly past.** As of 2026-10-22 the panel and model deadlines
    (15 and 20 Oct) were missed; replan.

### Confirmed as stated in the proposal

DOH-Epi dengue on HDX (2016 to Jan 2021); Mendeley v98325dpxv (Parreño; national weekly, 2019–2023 with gaps in 2020);
OpenDengue V1.3 exists (May 2025; for PHL only national weekly 2012–2023 is useful); EMSR312 = Mangkhut/Ompong and
EMSR478 = Goni/Rolly; IBTrACS has all four storms (MANGKHUT 2018, KAMMURI 2019, GONI 2020, VAMCO 2020); HydroRIVERS Asia,
WorldPop 2020 and Meta HRSL under-5/60+ are all downloadable.

## Gotchas

- The repo lives in **OneDrive**. `data/raw` is git-ignored but still synced to OneDrive (~4 GB); the venv is outside on purpose.
- In Git Bash, `python -I` ignores the user site-packages, so always use the venv interpreter
  (`~/.venvs/bantay-baha/Scripts/python`).
- psa.gov.ph and nhfr.doh.gov.ph return 403 to scripts. The CHIRPS IRI server drops long transfers; just re-run.
- Copernicus EMS vector zips sit on a static S3 bucket. The script scrapes the activation page for the links.
