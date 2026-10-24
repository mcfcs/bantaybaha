"""Pull the Google Earth Engine sources for Bantay-Baha into data/raw/<source>/.

Needs a registered Earth Engine project (free for non-commercial use):
    earthengine authenticate
    python scripts/download_gee.py --project <your-gcp-project-id>

Pulls:
  imerg           GPM IMERG V07 daily precipitation, PHL bbox, 2016-2020 (one GeoTIFF per month, bands = days)
  map_friction    Malaria Atlas Project friction surface 2019 (motorised + walking), PHL bbox
  gfd             Global Flood Database event table for events intersecting the Philippines
  sentinel1       Sentinel-1 GRD scene inventory around the four backtest typhoons (no imagery)
  s1_flood        Sentinel-1 flood masks per typhoon (UN-SPIDER-style change detection, dB-difference rule), 1-degree uint8 tiles near each track:
                  1 = new flood, 0 = not flooded, 255 = no data / sea. Tiles are skipped if already on disk.
                  `--storms Ompong` limits it to one typhoon (useful for a first check).

Files are written to <name>.part and renamed, so an interrupted run never leaves a half file that a later run would
skip; each source's files are recorded in data/raw/MANIFEST.csv when the source finishes.
"""

import argparse
import csv
import io
import math
import time
import zipfile
from datetime import date
from pathlib import Path

import ee
import requests

from download_data import write_manifest  # same MANIFEST.csv as the open sources

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
IBTRACS_NAMES = {"Ompong_Mangkhut_2018": ("MANGKHUT", 2018), "Tisoy_Kammuri_2019": ("KAMMURI", 2019),
                 "Rolly_Goni_2020": ("GONI", 2020), "Ulysses_Vamco_2020": ("VAMCO", 2020)}
# Sentinel-1 windows in days from landfall. bantay/config.py S1_AFTER_DAYS must match the after window's end: the flood
# map is only known once its last image exists, which is when the panel may first use it (no leakage).
S1_BEFORE = (-30, -3)
S1_AFTER = (0, 10)


def done(dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip  {dest.relative_to(RAW)}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    return False


def save(dest, data):
    tmp = dest.with_suffix(dest.suffix + ".part")  # write then rename, so an interrupted run leaves no half file
    tmp.write_bytes(data)
    tmp.replace(dest)


def write_csv(dest, fieldnames, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    save(dest, buf.getvalue().encode("utf-8"))


def download_image(img, dest, scale, region, retries=4):
    if done(dest):
        return dest
    for attempt in range(1, retries + 1):
        try:  # EE computes the image on request and sometimes answers 503/429; a fresh URL usually works
            url = img.getDownloadURL({"region": region, "scale": scale, "format": "GEO_TIFF", "crs": "EPSG:4326"})
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            break
        except Exception as e:  # noqa: BLE001 - retry any EE/network failure
            if attempt == retries:
                raise
            print(f"  retry {attempt}/{retries} {dest.name}: {str(e)[:120]}")
            time.sleep(20 * attempt)
    if r.content[:2] == b"PK":  # some band stacks come back zipped
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            save(dest, z.read(z.namelist()[0]))
    else:
        save(dest, r.content)
    print(f"  ok    {dest.relative_to(RAW)}  {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def pull_imerg(region):
    out = []
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
            out.append(download_image(img.toFloat(), RAW / "imerg" / f"imerg_v07_daily_mm_phl_{y}{m:02d}.tif", 11132, region))
    return [(p, "ee:NASA/GPM_L3/IMERG_V07") for p in out]


def pull_map_friction(region):
    base = "projects/malariaatlasproject/assets/accessibility/friction_surface/2019_v5_1"
    out = []
    for name, asset in {"motorized": base, "walking": base + "_walking_only"}.items():
        img = ee.Image(asset).toFloat()
        out.append((download_image(img, RAW / "map_friction" / f"friction_surface_2019_{name}_phl.tif", 927.67, region), f"ee:{asset}"))
    return out


def pull_gfd(region):
    dest = RAW / "gfd" / "gfd_events_phl.csv"
    if done(dest):
        return [(dest, "ee:GLOBAL_FLOOD_DB/MODIS_EVENTS/V1")]
    col = ee.ImageCollection("GLOBAL_FLOOD_DB/MODIS_EVENTS/V1").filterBounds(region)
    props = ["id", "dfo_main_cause", "dfo_severity", "dfo_dead", "dfo_displaced", "began", "ended", "countries", "cc"]
    feats = col.map(lambda im: ee.Feature(None, im.toDictionary(props)).set("system_index", im.get("system:index"))).getInfo()["features"]
    write_csv(dest, ["system_index"] + props, [ft["properties"] for ft in feats])
    print(f"  ok    {dest.relative_to(RAW)}  {len(feats)} events")
    return [(dest, "ee:GLOBAL_FLOOD_DB/MODIS_EVENTS/V1")]


def pull_sentinel1(region):
    dest = RAW / "sentinel1" / "s1_scene_inventory.csv"
    if done(dest):
        return [(dest, "ee:COPERNICUS/S1_GRD")]
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
    write_csv(dest, ["typhoon", "landfall", "scene", "time_ms", "orbit_pass"], rows)
    return [(dest, "ee:COPERNICUS/S1_GRD")]


def track_tiles(storm, near_km=350, tile=1.0):
    """1-degree tiles of the PHL bbox whose centre is within near_km (+ half a tile) of the storm's IBTrACS fixes."""
    import pandas as pd

    name, season = IBTRACS_NAMES[storm]
    ib = pd.read_csv(RAW / "ibtracs/ibtracs.WP.list.v04r01.csv", skiprows=[1], usecols=["NAME", "SEASON", "LAT", "LON"],
                     na_values=[" "], low_memory=False)
    tr = ib[(ib.NAME == name) & (ib.SEASON == season)]
    out = []
    for lon in range(BBOX[0], BBOX[2]):
        for lat in range(BBOX[1], math.ceil(BBOX[3])):
            cx, cy = lon + tile / 2, lat + tile / 2
            d = ((((tr.LON - cx) * math.cos(math.radians(cy))) ** 2 + (tr.LAT - cy) ** 2) ** 0.5 * 111.2).min()
            if d <= near_km + 79:
                out.append((lon, lat))
    return out


def s1_flood_image(landfall, region):
    """Change detection after the UN-SPIDER recommended practice, per relative orbit, with a dB-difference rule.

    Before = median of days -30..-3, after = darkest (smoothed) image of days 0..+10, both from the SAME relative orbit
    so the viewing geometry matches; floods from all orbits are combined. A pixel is new flood when VH drops by at least
    3 dB and ends water-dark (<= -18 dB). UN-SPIDER's after/before ratio > 1.25 on dB values under-detects surfaces that
    were already dark (checked against EMSR312 at Tuguegarao: 2 of 12 flooded sample points vs 6 of 12 with this rule).
    Permanent water, slopes > 5 deg and specks < 8 px are removed."""
    d0 = ee.Date(landfall)
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
          .select("VH"))
    smooth = lambda im: im.focal_mean(50, "circle", "meters")  # noqa: E731
    b_win = s1.filterDate(d0.advance(S1_BEFORE[0], "day"), d0.advance(S1_BEFORE[1], "day"))
    a_win = s1.filterDate(d0.advance(S1_AFTER[0], "day"), d0.advance(S1_AFTER[1], "day"))
    orbits = sorted(set(a_win.aggregate_array("relativeOrbitNumber_start").getInfo())
                    & set(b_win.aggregate_array("relativeOrbitNumber_start").getInfo()))
    floods = []
    for o in orbits:
        same = ee.Filter.eq("relativeOrbitNumber_start", o)
        before = b_win.filter(same).map(smooth).median()
        after = a_win.filter(same).map(smooth).min()
        floods.append(after.subtract(before).lte(-3).And(after.lte(-18)).rename("flood"))
    if not floods:
        return None
    flood = ee.ImageCollection(floods).max()  # masked where no orbit saw both dates
    seen = flood.mask().select(0)
    flood = flood.unmask(0)
    perm = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("seasonality").unmask(0).gte(10)
    dem = ee.Image("WWF/HydroSHEDS/03VFDEM")
    flood = flood.where(perm, 0).where(ee.Terrain.slope(dem).gt(5), 0)
    fm = flood.selfMask()
    flood = fm.updateMask(fm.connectedPixelCount(8, False).gte(8)).unmask(0)  # drop specks under 8 pixels
    valid = seen.And(dem.mask())  # land seen before and after by the same orbit
    return ee.Image(255).where(valid, flood).toUint8()


STORM_FILTER = []  # --storms: limit s1_flood to some typhoons (substring of the TYPHOONS key, e.g. Ompong)


def pull_s1_flood(region, scale=100):
    out = []
    for storm, d in TYPHOONS.items():
        if STORM_FILTER and not any(f.lower() in storm.lower() for f in STORM_FILTER):
            continue
        tiles = track_tiles(storm)
        print(f"  {storm}: {len(tiles)} tiles at {scale} m")
        url = f"ee:COPERNICUS/S1_GRD change detection, landfall {d}"
        for lon, lat in tiles:
            dest = RAW / "s1_flood" / storm / f"s1flood_{lon:03d}E_{lat:02d}N.tif"
            if done(dest):
                out.append((dest, url))
                continue
            tile = ee.Geometry.Rectangle([lon, lat, lon + 1, lat + 1])
            img = s1_flood_image(d, tile)  # orbits are picked per tile
            if img is None:
                print(f"  none  {dest.name}: no relative orbit imaged this tile both before and after landfall")
                continue
            out.append((download_image(img, dest, scale, tile), url))
    return out


PULLERS = {"imerg": pull_imerg, "map_friction": pull_map_friction, "gfd": pull_gfd, "sentinel1": pull_sentinel1,
           "s1_flood": pull_s1_flood}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="Google Cloud project registered for Earth Engine")
    ap.add_argument("sources", nargs="*", default=list(PULLERS))
    ap.add_argument("--storms", nargs="*", default=[], help="s1_flood only: typhoons to pull, e.g. Ompong Tisoy (default: all four)")
    a = ap.parse_args()
    STORM_FILTER.extend(a.storms)
    ee.Initialize(project=a.project)
    region = ee.Geometry.Rectangle(BBOX)
    for s in a.sources:
        print(f"[{s}]")
        write_manifest([(s, p, u) for p, u in PULLERS[s](region)])  # per source, so an interrupted run keeps what finished
