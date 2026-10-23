# Handoff

_Last updated: 2026-10-23._ Update this file at the end of every work session.

## Where we are

**Phase: data acquisition + one quick EDA notebook.** The brief: initialise the repo only to get the datasets and
sources right and to check the proposal's references and development plan against the real data. **Do not start
model or dashboard code** until the data findings below are reviewed by the team.

| Step | State |
|---|---|
| Read the three docs in `docs/` | done |
| Verify each data source in Appendix B, Table 1 (exists, reachable, covers what the proposal assumes) | done (findings below) |
| Python env + Jupyter kernel `bantay-baha` | done (`%USERPROFILE%\.venvs\bantay-baha`) |
| `scripts/download_data.py`, `scripts/download_gee.py`, `download_data.bat` | written; both scripts have run in full |
| Open-data download | **complete** (2026-10-22, fresh machine): 186 files, 6.95 GB in `data/raw/MANIFEST.csv` |
| Earth Engine download | **complete** (2026-10-23) with GCP project `hackathonproper` |
| Shared data bucket | `gs://bantay-baha-raw-hackathonproper` (private, `asia-southeast1`, public access blocked); `scripts/sync_data.py push/pull` |
| PSGC + NHFR manual downloads | **not done** (both sites block scripts) |
| `notebooks/00_data_eda.ipynb` | **executed** top to bottom on real data incl. GEE sources, no errors, no `PENDING`, saved with outputs (1 MB) |

### Download status

| Source | Status |
|---|---|
| dengue_hdx, cchain, mendeley_parreno, opendengue, ibtracs, roroph, hotosm_health, noah_facilities, copernicus_ems, census2020, cod_ab, worldpop, meta_hrsl, osm | complete |
| hydrorivers | complete, **now the Australasia (`au`) file** (finding 13). The old `HydroRIVERS_v10_as_shp.zip` is still on disk and in the manifest; it is unused |
| chirps | complete, 2016–2020 (1,827 days, none missing) |
| noah | complete: 5yr 67 files, 25yr 72 files, 4.7 GB (plus readme, metadata and licence) |
| imerg | complete: 60 monthly GeoTIFFs, 2016-01-01 to 2020-12-31, 0.1° |
| map_friction, gfd, sentinel1 | complete (2 rasters ~1 km; 62 GFD events; 979 Sentinel-1 scenes listed) |
| psgc, nhfr | manual |

Script changes this session: Google Drive files are now fetched directly from `drive.usercontent.google.com` with `confirm=t`
(gdown 6.x failed on Drive's virus-scan page for files over 100 MB, e.g. `Bukidnon.zip`; gdown was removed from `requirements.txt`).
One failed NOAH file no longer aborts the source. `dask` was added (needed by `xr.open_mfdataset`).

## Next steps

1. Bucket read access (*Storage Object Viewer*, bucket-level) was granted on 2026-10-23 to the five team `@student.ateneo.edu`
   accounts (Angeline Go, Hubert Olegario, Princess Giron, Gregorio Pascua, Beatrice de Castro). Each runs `earthengine authenticate`, then
   `python scripts/sync_data.py pull`. Running Earth Engine or pushing to the bucket also needs project-level IAM
   (*Service Usage Consumer*, *Earth Engine Resource Viewer*, write access on the bucket), granted in the Cloud console.
2. Download PSGC 2Q 2026 and NHFR by hand into `data/raw/psgc/` and `data/raw/nhfr/`.
3. Review the findings with the team (the notebook's last cell has them in one table), then update the proposal's
   Table 1 and the plan (see "Proposal corrections").
4. Only then: build the historical province crosswalk (`data/crosswalks/`) and the province-week panel. Start from
   the name match in notebook section 5 (126/126 dengue units resolved to a COD-AB ADM2; see finding 1).

## Findings so far (checked against the real files)

### Proposal corrections

1. **The dengue file has 126 reporting units, not 81 provinces.** It mixes provinces with 45 HUC/NCR cities (Cebu City,
   Davao City, all NCR cities, …) and has misspellings: `NUEVA VISCAYA`, `SISQUIJOR`, `BASILIG CITY` (= Bislig City, Surigao del Sur: listed under CARAGA,
   so not Basilan), `NORTH COTABATO`,
   and leading spaces in `" CAGAYAN DE ORO CITY"` and `" NEGROS ORIENTAL"`. Row 2 of the CSV holds HXL tags (skip it).
   The data run from 2016-01-10 to 2021-01-10, weekly, on Sundays. Matching names to COD-AB needs care: city units must be
   looked up as cities first (`QUEZON CITY` ≠ Quezon province, `COTABATO CITY` ≠ Cotabato, `SAN JUAN`/`SANTIAGO CITY` ≠ the
   same-name towns), `ñ` must be folded (Las Piñas, Parañaque), and `NAGA CITY` is ambiguous (Camarines Sur vs Cebu; Region V
   says Camarines Sur). With that, 126/126 units resolve (notebook section 5).
2. **Dengue deaths are unreliable.** 2016 has 8,127 deaths (about 3.9% CFR) against 1,195–4,563 in the other years. Don't use deaths.
3. **2020 cases fell to 91k (2019: 442k)** because of the COVID reporting collapse. The proposal's "2020 for access only" holds.
4. **A subnational leptospirosis series is openly available.** Project CCHAIN (HDX) has weekly PIDSR city counts, 2008–2022,
   for leptospirosis, dengue and 7 other diseases across its 12 cities, which spans all four backtest typhoons. The
   proposal says "no open subnational series exists" and plans to digitise DOH reports; revisit that.
5. **EMSR478 (Rolly) has only damage-grading products (4 AOIs), no flood delineation**, so it can't cross-check
   Sentinel-1 flood extent. EMSR312 (Ompong) does have observed-flood delineation, for 6 Northern Luzon AOIs
   (Tuguegarao, Ilagan, Vigan, Candon, Sudipen, Aparri): 48 km² observed flood at first delineation (`MAP`) and 120 km² in the
   later monitoring product (`MONIT01`) of the same AOIs, so don't add the two. No EMS activation was found for Tisoy or Ulysses.
6. **The flood hazard maps come from the UP NOAH Google Drive, not LiPAD.** They are per province at 5/25/100-year return periods, and
   coverage is partial (67 files at 5-year, 72 at 25-year). Matched to COD-AB by shapefile name (or old 9-digit PSGC in 8 files),
   the 25-year maps cover 75/88 ADM2 units (5-year: 71/88). No 25-year map for Basilan, Batanes, Biliran, Camiguin, City of Isabela,
   Davao Occidental, Guimaras, Northern Samar, Romblon, Siquijor, Special Geographic Area, Sulu, Tawi-Tawi, so "share of
   population in a hazard zone" is undefined there (carry as missing). Some zips hold two provinces (Cotabato + South Cotabato,
   Samar + Eastern Samar), and Maguindanao (pre-split), Metro Manila and Mindoro come as one file each.
7. **COD-AB uses current boundaries (88 ADM2 units)**: 4 NCR districts, Maguindanao del Norte/Sur (split in 2022), the
   "Special Geographic Area" (2024) and "City of Isabela". The 2016–2020 dengue data use the old units, so a harmonised
   historical crosswalk is required.
8. **The IBTrACS 34-kt gale radius (USA_R34_NE) is missing on many fixes**: Ompong 85%, Tisoy 71%, Ulysses 69%, Rolly only 42%
   (notebook section 6). The ferry-closure buffer needs a fallback (TOKYO_R30 or a fixed radius).
9. **roroph** (CRAN/r-universe `pinasr/roroph`) has 108 routes, as stated, but covers **2024–2026** operations. Names are
   GADM-style (`AgusandelNorte`) and port coordinates are partly coarse (33% of coordinates sit on a 0.1° grid). For 2018–2020 it is a proxy and needs snapping to OSM ports.
10. **NHFR blocks scripted access.** It needs a manual download, or use the fallbacks: HOT OSM health facilities and the UP NOAH
    critical-facilities layer (20,051 points, name + amenity only, no facility level).
11. **IMERG V07 and the MAP friction surface 2019 are both in the GEE catalog**, so no NASA Earthdata account is needed.
12. **The Global Flood Database covers none of the four backtest storms.** In the PHL bbox, its 44 PHL-tagged events run
    2002-07-06 to 2017-06-14 (`gfd_events_phl.csv`, dates parsed from `system_index`; the `began`/`ended` properties come back
    empty). The proposal's "covers Ompong at most" is too generous: it can't validate any backtest storm.
13. **HydroRIVERS "Asia" has no Philippine rivers.** HydroSHEDS puts the Philippines in the Australasia (`au`) region:
    `HydroRIVERS_v10_au_shp.zip` gives 41,097 reaches touching PHL (4,065 outlets: many small island basins); the `as` file gives 0.
    The script and README now use `au`.
14. **CHIRPS from the IRI Data Library has a `julian_day` time axis** (2457389.0 = 2016-01-01), which xarray doesn't decode;
    convert with `T - 2440587.5` days since 1970-01-01. Land cells only (sea is NaN). 2016–2020 complete, no missing days.
15. **MAP friction encodes sea as a constant, not nodata** (3.16 min/km motorised, 60 min/km walking, ~83% of bbox cells).
    Mask it before any access computation. Land medians: 3.0 min/km motorised, 18.9 walking.
16. **IMERG GeoTIFFs from GEE carry no band names**: band *i* is day *i* of the month in the file name. The daily bbox mean
    correlates 0.79 with CHIRPS (IMERG includes sea).
17. **Sentinel-1 is plentiful around all four storms**: 223/237/260/259 IW VV scenes in [-24, +14] days over the PHL bbox
    (Ompong/Tisoy/Rolly/Ulysses; 83–100 after landfall each), so before/after pairs are available for every backtest.
18. **The development plan dates (13–24 Oct 2026) are mostly past.** As of 2026-10-22 the panel and model deadlines
    (15 and 20 Oct) were missed; replan.

### Confirmed as stated in the proposal

DOH-Epi dengue on HDX (2016 to Jan 2021); Mendeley v98325dpxv (Parreño; national weekly, 2019–2023 with gaps in 2020);
OpenDengue V1.3 exists (May 2025; for PHL only national weekly 2012–2023 is useful); EMSR312 = Mangkhut/Ompong and
EMSR478 = Goni/Rolly; IBTrACS has all four storms (MANGKHUT 2018, KAMMURI 2019, GONI 2020, VAMCO 2020); HydroRIVERS
(Australasia file), WorldPop 2020 and Meta HRSL under-5/60+ are all downloadable. OpenDengue national weekly vs the HDX national sum,
2016–2020: 246 overlapping weeks, r = 0.947, median ratio 0.93. WorldPop 2020 UN-adjusted totals 109.6 M (PSA CPH 2020: 109.0 M).

## Gotchas

- The repo lives in **OneDrive**. `data/raw` is git-ignored but still synced to OneDrive (~7 GB); the venv is outside on purpose.
- In Git Bash, `python -I` ignores the user site-packages, so always use the venv interpreter
  (`~/.venvs/bantay-baha/Scripts/python`).
- pandas 3 / numpy 2 are installed (Python 3.14 venv); `.unique()` returns Arrow arrays and `np.int64(...)` reprs, so use `.tolist()` in prints.
- `earthengine authenticate` (no gcloud needed) also gives the token `sync_data.py` uses for the bucket; it sits in
  `%USERPROFILE%\.config\earthengine\`, outside the repo. EE `getDownloadURL` sometimes returns 503; `download_gee.py` retries.
- psa.gov.ph and nhfr.doh.gov.ph return 403 to scripts. The CHIRPS IRI server drops long transfers; just re-run.
- Copernicus EMS vector zips sit on a static S3 bucket. The script scrapes the activation page for the links.
