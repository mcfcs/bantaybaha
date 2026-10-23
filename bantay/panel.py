"""Step 0: the unit x week panel every model reads -> data/processed/panel.parquet + panel_card.md.

One row per harmonised unit (85) and DOH week (Sunday), 2016-01-10 to 2021-01-10. Inputs that are not on disk leave
their columns NaN and are listed as missing in the data card and status.json.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .config import PROCESSED, INTERIM, STORMS, S1_AFTER_DAYS, week_ending, record, status
from . import dengue, units as U, storms, rain, rivers, flood, grids

PANEL = PROCESSED / "panel.parquet"
S1_BY_STORM = PROCESSED / "s1_unit_storm.parquet"  # per-storm observed flood; the panel merges overlapping storms by max
CARD = PROCESSED / "panel_card.md"

COLUMNS = {  # column -> (source, meaning)
    "cases": ("dengue_hdx", "dengue cases in the week; NaN unless every member reporting unit reported"),
    "n_reporting": ("dengue_hdx", "member reporting units with a row that week"),
    "n_members": ("dengue_hdx", "member reporting units (provinces + cities folded in)"),
    "pop": ("census2020 / worldpop", "2020 population (census; WorldPop if the census table is missing)"),
    "incidence": ("derived", "cases per 100,000"),
    "storm_min_dist_km": ("ibtracs", "distance from the nearest WP track fix that week to the unit polygon (2000 = none within 300 km of PHL)"),
    "storm_gale_hit": ("ibtracs", "1 if the unit was inside a gale-radius swath that week (R34 / TOKYO_R30 / 150 km fallback)"),
    "storm_max_wind_near_kt": ("ibtracs", "max wind of fixes within 300 km of the unit"),
    "storm_n": ("ibtracs", "distinct storms within 300 km"),
    "chirps_7d": ("chirps", "area-mean rainfall, Mon-Sun sum (mm)"),
    "chirps_3d": ("chirps", "area-mean rainfall, Fri-Sun sum (mm)"),
    "chirps_max1d": ("chirps", "wettest day of the week (mm)"),
    "imerg_7d": ("imerg (GEE)", "as chirps_7d, from GPM IMERG V07"),
    "imerg_3d": ("imerg (GEE)", "as chirps_3d, from GPM IMERG V07"),
    "imerg_max1d": ("imerg (GEE)", "as chirps_max1d, from GPM IMERG V07"),
    "river_up_7d": ("hydrorivers + chirps", "discharge-weighted upstream-mean weekly rain over the unit's reaches (mm)"),
    "river_excess_7d": ("hydrorivers + chirps", "river_up_7d minus chirps_7d: rain arriving from upstream"),
    "hazard_any_5yr": ("noah", "share of population in any 5-yr flood hazard class (NaN = no NOAH map)"),
    "hazard_high_5yr": ("noah", "share of population in the high 5-yr class"),
    "hazard_any_25yr": ("noah", "share of population in any 25-yr flood hazard class (NaN = no NOAH map)"),
    "hazard_high_25yr": ("noah", "share of population in the high 25-yr class"),
    "storm_hazard_exposure": ("ibtracs x noah", "storm_gale_hit x hazard_any_25yr"),
    "s1_flood_frac": ("sentinel-1 (GEE)", "observed new-flood share of land, on the 4 weeks from the one containing landfall + S1_AFTER_DAYS (when the map is known); NaN otherwise"),
    "s1_flood_pop": ("sentinel-1 (GEE)", "people in observed new flood (WorldPop), same weeks"),
}


def _newest(paths):
    ts = [Path(p).stat().st_mtime for p in paths if Path(p).exists()]
    return max(ts) if ts else 0


def cached(path, inputs, fn):
    """Read `path` if it is newer than every input file, else rebuild with fn() (None = input missing, not cached)."""
    path = Path(path)
    if path.exists() and path.stat().st_mtime >= _newest(inputs):
        return pd.read_parquet(path)
    df = fn()
    if df is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    return df


def rain_layers(u):
    """CHIRPS unit-week + river routing (one CHIRPS pass), IMERG unit-week. Each None if its input is missing."""
    chirps_files = sorted(rain.CHIRPS_DIR.glob("*.nc"))
    reach = rivers.load_reaches(u) if chirps_files else None

    def build_chirps():
        if reach is None:
            res = rain.chirps_daily_units(u)
            return None if res is None else rain.weekly(res, "chirps")
        res = rain.chirps_daily_units(u, points=reach.geometry)
        if res is None:
            return None
        daily, reach_daily = res
        wk = rain.weekly(daily, "chirps")
        riv = rivers.unit_week_river(reach, reach_daily, wk)
        return wk.merge(riv, on=["week", "unit_id"], how="left")

    ch = cached(INTERIM / "rain_chirps_unit_week.parquet", chirps_files + [rivers.HR_ZIP, U.UNITS_GPKG], build_chirps)
    imerg_files = sorted(rain.IMERG_DIR.glob("*.tif"))

    def build_imerg():
        d = rain.imerg_daily_units(u)
        return None if d is None else rain.weekly(d, "imerg")

    im = cached(INTERIM / "rain_imerg_unit_week.parquet", imerg_files + [U.UNITS_GPKG], build_imerg) if imerg_files else rain.imerg_daily_units(u)
    return ch, im


def static_layers(u):
    """NOAH hazard shares per unit (builds the hazard rasters on the first run). None if WorldPop is missing."""
    if grids.build_unit_raster(u) is None:
        return None
    for rp in flood.RPS:
        flood.build_hazard_raster(u, rp)
    return flood.unit_hazard_shares(u)


def s1_layers(u, wk):
    """Observed flood per unit on the 4 weeks from when the map is known: the week containing landfall + S1_AFTER_DAYS
    (its last after-image), not the landfall week, so no feature at an origin uses radar taken after it."""
    rows, per_storm = [], []
    for key, s in STORMS.items():
        f = flood.s1_unit_flood(u, key)
        if f is None:
            continue
        per_storm.append(f)
        w0 = week_ending(pd.Timestamp(s["landfall"]) + pd.Timedelta(days=S1_AFTER_DAYS))
        for k in range(4):
            rows.append(f.assign(week=w0 + pd.Timedelta(weeks=k)))
    if not rows:
        return None
    pd.concat(per_storm, ignore_index=True).to_parquet(S1_BY_STORM)
    # storms close together (Rolly, Ulysses) share weeks: keep the larger observed flood per unit-week
    return pd.concat(rows, ignore_index=True).groupby(["unit_id", "week"], as_index=False)[["s1_flood_frac", "s1_flood_pop"]].max()


def build_panel():
    u = U.load_units()
    wk = dengue.weeks()
    grid = pd.MultiIndex.from_product([sorted(u.unit_id), wk], names=["unit_id", "week"]).to_frame(index=False)
    cases = dengue.unit_week_cases()
    if cases is not None:
        p = grid.merge(cases, on=["unit_id", "week"], how="left")
    else:  # recorded as missing; the panel still builds so the other layers can be checked
        p = grid.assign(cases=np.nan, n_reporting=np.nan, n_members=np.nan)

    pop = dengue.unit_population()
    if pop is not None:
        p = p.merge(pop.rename(columns={"pop2020": "pop"}), on="unit_id", how="left").assign(pop_source="census2020")
    else:
        wp = grids.unit_population_worldpop(u)
        if wp is None:
            raise RuntimeError("no population source: need census2020 or worldpop")
        p = p.merge(wp.rename(columns={"pop_worldpop": "pop"}), on="unit_id", how="left").assign(pop_source="worldpop")
    p["incidence"] = p.cases / p["pop"] * 1e5

    ex = cached(INTERIM / "storm_unit_week.parquet", [storms.IBTRACS, U.UNITS_GPKG], lambda: storms.unit_week_exposure(u))
    if ex is not None:
        p = p.merge(ex, on=["unit_id", "week"], how="left")
        p["storm_min_dist_km"] = p.storm_min_dist_km.fillna(2000.0)
        for c in ("storm_gale_hit", "storm_max_wind_near_kt", "storm_n"):
            p[c] = p[c].fillna(0)

    ch, im = rain_layers(u)
    for layer in (ch, im):
        if layer is not None:
            p = p.merge(layer, on=["unit_id", "week"], how="left")

    hz = static_layers(u)
    if hz is not None:
        p = p.merge(hz, on="unit_id", how="left")
    if "storm_gale_hit" in p and "hazard_any_25yr" in p:
        p["storm_hazard_exposure"] = p.storm_gale_hit * p.hazard_any_25yr

    s1 = s1_layers(u, wk)
    if s1 is not None:
        p = p.merge(s1, on=["unit_id", "week"], how="left")

    for c in COLUMNS:  # every documented column exists, NaN when its input is missing
        if c not in p:
            p[c] = np.nan
    p = p.merge(u[["unit_id", "unit_name", "region"]], on="unit_id", how="left")
    p = p.sort_values(["unit_id", "week"]).reset_index(drop=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    p.to_parquet(PANEL)
    write_card(p)
    record("panel", True, f"{p.unit_id.nunique()} units x {p.week.nunique()} weeks")
    return p


def write_card(p):
    st = status()
    lines = ["# Panel data card", "",
             f"`data/processed/panel.parquet`: {p.unit_id.nunique()} harmonised units x {p.week.nunique()} weeks "
             f"({p.week.min().date()} to {p.week.max().date()}, weeks end Sunday). Built by `python scripts/build.py panel`.",
             "", "Units: COD-AB ADM2 with Maguindanao del Norte/Sur merged, Special Geographic Area -> Cotabato, City of Isabela -> "
             "Basilan (`data/crosswalks/adm2_to_unit.csv`). 2020 is COVID-depressed: used for access scenarios only, never as a "
             "forecast target.", "", "| column | source | non-null | meaning |", "|---|---|---|---|"]
    for c, (src, meaning) in COLUMNS.items():
        lines.append(f"| `{c}` | {src} | {p[c].notna().mean():.0%} | {meaning} |")
    lines += ["", "## Input status", "", "| input | available | detail |", "|---|---|---|"]
    for k, v in sorted(st.items()):
        lines.append(f"| {k} | {'yes' if v['available'] else '**missing**'} | {v['detail']} |")
    CARD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_panel():
    return pd.read_parquet(PANEL)
