"""Pull the Google Earth Engine sources for Bantay-Baha into data/raw/<source>/.

Needs a registered Earth Engine project (free for non-commercial use):
    earthengine authenticate
    python scripts/download_gee.py --project <your-gcp-project-id>

Pulls:
  imerg           GPM IMERG V07 daily precipitation, PHL bbox, 2016-2020 (one GeoTIFF per month, bands = days)
  map_friction    Malaria Atlas Project friction surface 2019 (motorised + walking), PHL bbox
  gfd             Global Flood Database event table for events intersecting the Philippines
  sentinel1       Sentinel-1 GRD scene inventory around the four backtest typhoons (no imagery)
"""

import argparse
import csv
import io
import zipfile
from datetime import date
from pathlib import Path

import ee
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BBOX = [116, 4, 127, 21.5]  # lon_min, lat_min, lon_max, lat_max

# Landfall / closest-approach dates used for the before/after windows
TYPHOONS = {
    "Ompong_Mangkhut_2018": "2018-09-15",
    "Tisoy_Kammuri_2019": "2019-12-02",
    "Rolly_Goni_2020": "2020-11-01",
    "Ulysses_Vamco_2020": "2020-11-11",
}


def download_image(img, dest, scale, region):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip  {dest.relative_to(RAW)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = img.getDownloadURL({"region": region, "scale": scale, "format": "GEO_TIFF", "crs": "EPSG:4326"})
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    if r.content[:2] == b"PK":  # some band stacks come back zipped
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            dest.write_bytes(z.read(z.namelist()[0]))
    else:
        dest.write_bytes(r.content)
    print(f"  ok    {dest.relative_to(RAW)}  {dest.stat().st_size / 1e6:.1f} MB")


def pull_imerg(region):
    col = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").select("precipitation")  # half-hourly, mm/hr
    for y in range(2016, 2021):
        for m in range(1, 13):
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1)
            days = (end - start).days

            def daily(i, start=start):
                d0 = ee.Date(start.isoformat()).advance(i, "day")
                # mean mm/hr over the day x 24 = mm/day
                return col.filterDate(d0, d0.advance(1, "day")).mean().multiply(24).rename(d0.format("YYYYMMdd"))

            img = ee.ImageCollection(ee.List.sequence(0, days - 1).map(lambda i: daily(ee.Number(i)))).toBands()
            download_image(img.toFloat(), RAW / "imerg" / f"imerg_v07_daily_mm_phl_{y}{m:02d}.tif", 11132, region)


def pull_map_friction(region):
    base = "projects/malariaatlasproject/assets/accessibility/friction_surface/2019_v5_1"
    for name, asset in {"motorized": base, "walking": base + "_walking_only"}.items():
        img = ee.Image(asset).toFloat()
        download_image(img, RAW / "map_friction" / f"friction_surface_2019_{name}_phl.tif", 927.67, region)


def pull_gfd(region):
    col = ee.ImageCollection("GLOBAL_FLOOD_DB/MODIS_EVENTS/V1").filterBounds(region)
    props = ["id", "dfo_main_cause", "dfo_severity", "dfo_dead", "dfo_displaced", "began", "ended", "countries", "cc"]
    feats = col.map(lambda im: ee.Feature(None, im.toDictionary(props)).set("system_index", im.get("system:index"))).getInfo()["features"]
    dest = RAW / "gfd" / "gfd_events_phl.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["system_index"] + props, extrasaction="ignore")
        w.writeheader()
        w.writerows(ft["properties"] for ft in feats)
    print(f"  ok    {dest.relative_to(RAW)}  {len(feats)} events")


def pull_sentinel1(region):
    rows = []
    for storm, d in TYPHOONS.items():
        d0 = ee.Date(d)
        col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
               .filterDate(d0.advance(-24, "day"), d0.advance(14, "day"))
               .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
               .filter(ee.Filter.eq("instrumentMode", "IW")))
        info = col.aggregate_array("system:index").getInfo()
        times = col.aggregate_array("system:time_start").getInfo()
        orbits = col.aggregate_array("orbitProperties_pass").getInfo()
        for idx, t, o in zip(info, times, orbits):
            rows.append(dict(typhoon=storm, landfall=d, scene=idx, time_ms=t, orbit_pass=o))
        print(f"  {storm}: {len(info)} S1 IW VV scenes in [-24, +14] days")
    dest = RAW / "sentinel1" / "s1_scene_inventory.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["typhoon", "landfall", "scene", "time_ms", "orbit_pass"])
        w.writeheader()
        w.writerows(rows)


PULLERS = {"imerg": pull_imerg, "map_friction": pull_map_friction, "gfd": pull_gfd, "sentinel1": pull_sentinel1}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="Google Cloud project registered for Earth Engine")
    ap.add_argument("sources", nargs="*", default=list(PULLERS))
    a = ap.parse_args()
    ee.Initialize(project=a.project)
    region = ee.Geometry.Rectangle(BBOX)
    for s in a.sources:
        print(f"[{s}]")
        PULLERS[s](region)
