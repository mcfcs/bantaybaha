"""Download the raw datasets for Bantay-Baha into data/raw/<source>/.

Idempotent: files that already exist with a non-zero size are skipped.
Every file is recorded in data/raw/MANIFEST.csv (source, path, bytes, sha256, url).

Usage:
    python scripts/download_data.py            # all open sources
    python scripts/download_data.py dengue_hdx chirps   # selected sources

Sources needing credentials (GEE: Sentinel-1, Global Flood Database, MAP friction,
IMERG) are handled separately in scripts/download_gee.py once Earth Engine is set up.
"""

import csv
import hashlib
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (bantay-baha data pull; PJDSC 2026)"}
HDX = "https://data.humdata.org/dataset"

# Static files: source -> list of (url, filename)
STATIC = {
    "dengue_hdx": [
        (f"{HDX}/ac63a95e-7296-42fb-802b-7f7541c73e45/resource/9e839677-3ff0-44b3-992c-1a99e68df515/download/doh-epi-dengue-data-2016-2021.csv",
         "doh-epi-dengue-data-2016-2021.csv"),
    ],
    "cchain": [
        (f"{HDX}/5b580664-365e-4d7e-b5e5-2990df8f12a5/resource/b93c1427-797a-40a4-b99e-872e152d1c86/download/disease_pidsr_totals.csv", "disease_pidsr_totals.csv"),
        (f"{HDX}/5b580664-365e-4d7e-b5e5-2990df8f12a5/resource/0bfe24d0-396a-4906-82ee-202e90d798f8/download/disease.csv", "disease.csv"),
        (f"{HDX}/5b580664-365e-4d7e-b5e5-2990df8f12a5/resource/31a3dddb-decc-4fd7-a0f7-acff922a7a76/download/location.csv", "location.csv"),
        (f"{HDX}/5b580664-365e-4d7e-b5e5-2990df8f12a5/resource/3ca89d0e-3671-4f63-8dff-9af3e05b93cc/download/geoportal_doh_poi_health.csv", "geoportal_doh_poi_health.csv"),
    ],
    "mendeley_parreno": [
        ("https://data.mendeley.com/public-files/datasets/v98325dpxv/files/11430639-a7a4-4479-9c91-614b73442b12/file_downloaded",
         "Diseases_Data_for_NBL.xlsx"),
    ],
    "opendengue": [
        (f"https://raw.githubusercontent.com/OpenDengue/master-repo/v1.3.0/data/releases/V1.3/{n}_extract_V1_3.zip", f"{n}_extract_V1_3.zip")
        for n in ("National", "Spatial", "Temporal")
    ],
    "ibtracs": [
        ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.WP.list.v04r01.csv",
         "ibtracs.WP.list.v04r01.csv"),
    ],
    # HydroSHEDS puts the Philippines in the Australasia ("au") region; the Asia ("as") file has no PHL reaches
    "hydrorivers": [
        ("https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_au_shp.zip", "HydroRIVERS_v10_au_shp.zip"),
    ],
    "osm": [
        ("https://download.geofabrik.de/asia/philippines-latest.osm.pbf", "philippines-latest.osm.pbf"),
    ],
    "roroph": [
        ("https://raw.githubusercontent.com/pinasr/roroph/main/data/roro_routes.rda", "roro_routes.rda"),
        ("https://raw.githubusercontent.com/pinasr/roroph/main/data-raw/nautical_highway.R", "nautical_highway.R"),
    ],
    "hotosm_health": [
        ("https://production-raw-data-api.s3.amazonaws.com/ISO3/PHL/health_facilities/hotosm_phl_health_facilities_osm_gpkg.zip",
         "hotosm_phl_health_facilities_osm_gpkg.zip"),
    ],
    # UP NOAH critical-facility layer (likely NHFR-derived; name + amenity only). NHFR itself blocks scripted access.
    "noah_facilities": [
        ("https://webgis-static.up.edu.ph/api/critical_facilities/hospitals.geojson", "hospitals.geojson"),
    ],
    "worldpop": [
        ("https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/PHL/phl_ppp_2020_UNadj.tif", "phl_ppp_2020_UNadj.tif"),
    ],
    "meta_hrsl": [
        (f"{HDX}/6d9f35c0-4764-49ee-b364-329db0b7a47d/resource/6ec111d4-900d-47cf-a7ad-39899c8a6fdc/download/phl_children_under_five_2020_geotiff.zip",
         "phl_children_under_five_2020_geotiff.zip"),
        (f"{HDX}/6d9f35c0-4764-49ee-b364-329db0b7a47d/resource/c032d20a-aaba-4cf4-8c2d-f356d5862fc3/download/phl_elderly_60_plus_2020_geotiff.zip",
         "phl_elderly_60_plus_2020_geotiff.zip"),
    ],
    "cod_ab": [
        (f"{HDX}/caf116df-f984-4deb-85ca-41b349d3f313/resource/3fa0dbcf-e07d-4506-9821-ba15baa6da07/download/phl_admin_boundaries.gdb.zip",
         "phl_admin_boundaries.gdb.zip"),
        (f"{HDX}/caf116df-f984-4deb-85ca-41b349d3f313/resource/159ffd3d-679f-431c-812f-b6d6f957045e/download/phl_admin_boundaries.xlsx",
         "phl_admin_boundaries.xlsx"),
    ],
    "census2020": [
        (f"{HDX}/c1edf0c5-58c8-4d39-b566-937b1ad7907f/resource/bd5a42c1-2b36-4e1a-8ba8-9e231f0796e2/download/2020-cph-sex_age-group-popn-mun_admin3-new-pcode.xlsx",
         "2020_CPH_SexAge_Popn_Mun_Admin3.xlsx"),
    ],
}

EMS = {"EMSR312": "DELINEATION", "EMSR478": ""}  # activation -> filename filter
NOAH_FOLDERS = {"5yr": "17ecJuf2vnkrpCzNVLes0fI08XFsR1x8N", "25yr": "1PYdJFtfxzmAwk1gIgn8wYLh8WPkiZvOf"}
NOAH_DOCS = {"01ReadMe_Flood.pdf": "1Z6gT7FDUCMps-qHT5Jiy7nwCdaH0rhwR", "metadata_flood.txt": "1qbOoN_CZ6AUIk22owtJxRFENALIWCszq",
             "NOAH_License.pdf": "1z6MH_QI6gU_e2gNnhIMsKkENugHscNl9"}

# CHIRPS v2.0 daily 0.05 deg, Philippines bounding box, subset server-side by the IRI Data Library
CHIRPS_BBOX = dict(x0=116, x1=127, y0=4, y1=21.5)
CHIRPS_YEARS = range(2016, 2021)

PARTIAL = []  # single files that failed inside a source that otherwise finished


def fetch(url, dest, retries=3, binary=False):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip  {dest.relative_to(RAW)}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=(30, 600)) as r:
                r.raise_for_status()
                if binary and "text/html" in r.headers.get("Content-Type", ""):
                    raise RuntimeError("got an HTML page instead of the file (quota or permission page?)")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
            print(f"  ok    {dest.relative_to(RAW)}  {dest.stat().st_size / 1e6:.1f} MB")
            return dest
        except Exception as e:  # noqa: BLE001 - retry any network failure
            print(f"  retry {attempt}/{retries} {dest.name}: {e}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"failed: {url}")


def drive_listing(folder_id):
    html = requests.get(f"https://drive.google.com/embeddedfolderview?id={folder_id}", headers=UA, timeout=60).text
    return re.findall(r'href="https://drive.google.com/file/d/([A-Za-z0-9_-]+)[^"]*".*?flip-entry-title">([^<]+)<', html, re.S)


def fetch_drive(file_id, dest):
    # confirm=t skips the "virus scan warning" page Drive serves for files > 100 MB (gdown 6.x fails on it)
    return fetch(f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t", dest, binary=True)


def pull_static(source):
    return [(fetch(url, RAW / source / name), url) for url, name in STATIC[source]]


def pull_ems():
    out = []
    for act, filt in EMS.items():
        html = requests.get(f"https://mapping.emergency.copernicus.eu/activations/{act}/", headers=UA, timeout=60).text
        urls = sorted(set(re.findall(r"https://cems-mapping-website[^\"']+_vector\.zip", html)))
        for u in (u for u in urls if filt in u):
            out.append((fetch(u, RAW / "copernicus_ems" / act / u.rsplit("/", 1)[1]), u))
    return out


def pull_noah():
    out = []
    for name, fid in NOAH_DOCS.items():
        out.append((fetch_drive(fid, RAW / "noah" / name), f"gdrive:{fid}"))
    for rp, folder in NOAH_FOLDERS.items():
        files = drive_listing(folder)
        print(f"  NOAH {rp}: {len(files)} files")
        for fid, fname in files:
            try:  # one blocked file should not stop the other provinces
                out.append((fetch_drive(fid, RAW / "noah" / rp / fname), f"gdrive:{fid}"))
            except RuntimeError as e:
                print(f"  FAILED {rp}/{fname}: {e}")
                PARTIAL.append(f"noah/{rp}/{fname}")
    return out


def pull_chirps():
    b = CHIRPS_BBOX
    out = []
    for y in CHIRPS_YEARS:
        url = ("https://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily-improved/.global/.0p05/.prcp/"
               f"X/{b['x0']}/{b['x1']}/RANGEEDGES/Y/{b['y0']}/{b['y1']}/RANGEEDGES/"
               f"T/(1%20Jan%20{y})/(31%20Dec%20{y})/RANGEEDGES/data.nc")
        out.append((fetch(url, RAW / "chirps" / f"chirps_v2_daily_p05_phl_{y}.nc"), url))
    return out


PULLERS = {**{s: (lambda s=s: pull_static(s)) for s in STATIC}, "copernicus_ems": pull_ems, "noah": pull_noah, "chirps": pull_chirps}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(rows):
    manifest = RAW / "MANIFEST.csv"
    old = {}
    if manifest.exists():
        with open(manifest, newline="") as f:
            old = {r["path"]: r for r in csv.DictReader(f)}
    for source, path, url in rows:
        rel = path.relative_to(RAW).as_posix()
        size = path.stat().st_size
        if rel in old and int(old[rel]["bytes"]) == size:
            continue
        old[rel] = dict(source=source, path=rel, bytes=size, sha256=sha256(path), url=url)
    with open(manifest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source", "path", "bytes", "sha256", "url"])
        w.writeheader()
        w.writerows(sorted(old.values(), key=lambda r: r["path"]))


def main(selected):
    n, failed = 0, []
    for source in selected or PULLERS:
        print(f"[{source}]")
        try:
            rows = [(source, p, u) for p, u in PULLERS[source]()]
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            print(f"  FAILED {source}: {e}")
            failed.append(source)
            continue
        write_manifest(rows)  # per source, so an interrupted run keeps what finished
        n += len(rows)
    print(f"\n{n} files recorded in {RAW / 'MANIFEST.csv'}")
    if failed:
        print("Failed sources:", ", ".join(failed))
    if PARTIAL:
        print(f"Failed files ({len(PARTIAL)}), re-run to retry:", ", ".join(PARTIAL))
    if failed or PARTIAL:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
