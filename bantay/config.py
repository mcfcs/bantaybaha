"""Paths, constants and the missing-input registry used by every build stage.

Missing inputs never stop a build: a stage calls `have()` / `missing()`, the gap is printed as a warning and recorded in
data/processed/status.json, and the affected columns stay NaN (or the output is skipped). Re-running the build after
the files arrive picks them up with no code change.
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
CROSSWALKS = ROOT / "data" / "crosswalks"
APP_DATA = PROCESSED / "app"

BBOX = (116, 4, 127, 21.5)  # lon_min, lat_min, lon_max, lat_max
CRS_M = 32651  # UTM 51N, metres; PHL spans zones 50-52, fine at province scale

# Weekly grid: DOH weeks end on Sunday. 2021 has only 2 weeks and 2020 is COVID-depressed (access scenarios only).
WEEK_FREQ = "W-SUN"
FIRST_WEEK, LAST_WEEK = "2016-01-10", "2021-01-10"
MODEL_END = "2019-12-29"  # last week used to train or score forecasts; 2020 surveillance is not used as a target

# Backtest typhoons. landfall = closest-approach date used for before/after windows (same as scripts/download_gee.py)
STORMS = {
    "ompong": dict(local="Ompong", name="MANGKHUT", season=2018, landfall="2018-09-15", gee="Ompong_Mangkhut_2018"),
    "tisoy": dict(local="Tisoy", name="KAMMURI", season=2019, landfall="2019-12-02", gee="Tisoy_Kammuri_2019"),
    "rolly": dict(local="Rolly", name="GONI", season=2020, landfall="2020-11-01", gee="Rolly_Goni_2020"),
    "ulysses": dict(local="Ulysses", name="VAMCO", season=2020, landfall="2020-11-11", gee="Ulysses_Vamco_2020"),
}

# Sentinel-1 flood maps use images up to this many days after landfall (scripts/download_gee.py S1_AFTER), so a map is
# known only from the DOH week containing landfall + S1_AFTER_DAYS. Features must not use it before that week.
S1_AFTER_DAYS = 10

# CDC FluSight 23 quantile levels
QUANTILES = [0.01, 0.025] + [round(0.05 * i, 2) for i in range(1, 20)] + [0.975, 0.99]


def week_ending(ts):
    """Sunday that ends the DOH week (Mon-Sun) containing `ts`; a Sunday maps to itself. Scalar or Series."""
    import pandas as pd

    s = pd.Series(pd.to_datetime(ts)) if pd.api.types.is_scalar(ts) else pd.to_datetime(pd.Series(ts))
    out = s.dt.normalize() + pd.to_timedelta((6 - s.dt.weekday) % 7, unit="D")
    return out.iloc[0] if pd.api.types.is_scalar(ts) else out.set_axis(getattr(ts, "index", out.index))


# ---------------------------------------------------------------- missing-input registry

_STATUS_FILE = PROCESSED / "status.json"


def _load_status():
    if _STATUS_FILE.exists():
        return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    return {}


def record(key, available, detail=""):
    """Record whether input/output `key` was available in this build (merged into status.json)."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    st = _load_status()
    st[key] = dict(available=bool(available), detail=detail, checked=datetime.now().isoformat(timespec="seconds"))
    _STATUS_FILE.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")


def status():
    return _load_status()


def missing(key, detail):
    """Warn that an input is missing and record it. Returns None so callers can `return missing(...)`."""
    print(f"  WARNING missing {key}: {detail}")
    record(key, False, detail)


def have(key, *paths, pattern=None):
    """True if every path exists (and, for a directory with `pattern`, holds at least one match). Records the result."""
    for p in paths:
        p = Path(p)
        ok = p.exists() and (p.is_file() or (any(p.glob(pattern)) if pattern else any(p.iterdir())))
        if not ok:
            missing(key, f"{_rel(p)} not found")
            return False
    record(key, True, ", ".join(str(_rel(Path(p))) for p in paths))
    return True


def _rel(p):
    """Path relative to the repo root when it is inside it, else as given (inputs may live elsewhere)."""
    return p.relative_to(ROOT) if p.is_relative_to(ROOT) else p


def ensure_dirs():
    for d in (INTERIM, PROCESSED, APP_DATA):
        d.mkdir(parents=True, exist_ok=True)
