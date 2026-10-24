"""The committed build-output snapshot (data/processed/): what is tracked, that it is complete for the dashboard, and that
it is safe to publish. See AGENTS.md data rule 4."""

import re
import subprocess
from pathlib import Path

import pytest

from conftest import APP_DATA, PROCESSED, ROOT, need

GITHUB_WARN_MB = 50  # GitHub warns above 50 MB per file and refuses 100 MB; stay below the warning
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/home/[^/\s]+/|OneDrive", re.I)


def ignored(rel):
    """True if git would ignore the repo-relative path (it need not exist)."""
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT)
    return r.returncode == 0


@pytest.mark.parametrize("rel, expect", [
    ("data/processed/app/scenarios.parquet", False),   # outputs are committed
    ("data/processed/panel.parquet", False),
    ("data/processed/status.json", False),
    ("data/processed/sus/sus_responses.csv", True),     # usability-test answers never are
    ("data/interim/units_100m.tif", True),              # caches are rebuilt
    ("data/raw/osm/philippines-latest.osm.pbf", True),  # raw data come from the scripts / bucket
    ("data/raw/MANIFEST.csv", False),
    ("data/build_full.log", True),
])
def test_gitignore_tracks_outputs_but_not_raw_caches_or_answers(rel, expect):
    assert ignored(rel) is expect


def _dashboard_files():
    """Output files the dashboard reads, from the names in app/*.py (glob patterns kept as patterns)."""
    src = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").glob("*.py"))
    names = set(re.findall(r"([a-z_0-9]+\*?\.(?:parquet|csv|json|geojson))", src))
    return sorted(n for n in names if not n.startswith("sus_"))  # answers are collected at run time, not built


@pytest.mark.data
@pytest.mark.parametrize("name", _dashboard_files())
def test_snapshot_has_every_file_the_dashboard_reads(name):
    need(APP_DATA)
    dirs = (APP_DATA, PROCESSED)  # most outputs live in app/; status.json sits one level up
    if "*" in name:
        assert any(list(d.glob(name)) for d in dirs), f"no output matches {name}"
    else:
        assert any((d / name).exists() for d in dirs), f"{name} missing from data/processed/(app/)"


@pytest.mark.data
def test_no_output_file_near_the_github_size_limit():
    need(PROCESSED)
    big = [(p.relative_to(ROOT).as_posix(), round(p.stat().st_size / 1e6, 1)) for p in PROCESSED.rglob("*")
           if p.is_file() and p.stat().st_size > GITHUB_WARN_MB * 1e6]
    assert not big, f"files over {GITHUB_WARN_MB} MB cannot be committed safely: {big}"


@pytest.mark.data
def test_text_outputs_hold_no_local_paths():
    """Published outputs must not leak the builder's machine (user folder, OneDrive path)."""
    need(PROCESSED)
    leaks = [p.relative_to(ROOT).as_posix() for p in PROCESSED.rglob("*")
             if p.is_file() and p.suffix in (".json", ".csv", ".md", ".geojson", ".txt")
             and LOCAL_PATH.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not leaks, f"local paths in {leaks}"


def test_local_path_pattern():
    assert LOCAL_PATH.search(r"C:\Users\someone\x") and LOCAL_PATH.search("C:/Users/a/b") and LOCAL_PATH.search("/home/u/x")
    assert not LOCAL_PATH.search("data/raw/osm/philippines-latest.osm.pbf")
    assert not LOCAL_PATH.search("Gregorio del Pilar")  # a real municipality, not a user folder
