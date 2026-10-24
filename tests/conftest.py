"""Shared fixtures: paths, a throw-away SUS responses file, a live dashboard server for the Playwright tests, and the
isolation and skip helpers of the pipeline tests.

The dashboard reads the real build outputs in data/processed/app/; tests never write there. SUS answers go to a
temporary CSV through BANTAY_SUS_PATH. Screenshots land in tests/artifacts/ (git-ignored). Pipeline unit tests send
the status registry (bantay.config.record) to a temporary file; `data_untouched` fails the session if any file under
data/ changed while the tests ran.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
PROCESSED = ROOT / "data" / "processed"
APP_DATA = PROCESSED / "app"
ARTIFACTS = ROOT / "tests" / "artifacts"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))  # `bantay` without an install
sys.path.append(str(ROOT / "scripts"))  # download_data, sync_data, check_code_guide, make_results

needs_data = pytest.mark.skipif(not (APP_DATA / "scenarios.parquet").exists(),
                                reason="build outputs missing: run build.bat first")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: browser tests (Playwright); deselect with -m 'not e2e'")
    config.addinivalue_line("markers", "data: invariants of the build outputs in data/processed/ (skip when missing)")
    config.addinivalue_line("markers", "slow: builds a document (LaTeX); deselect with -m 'not slow'")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def sus_csv(tmp_path, monkeypatch):
    p = tmp_path / "sus_responses.csv"
    monkeypatch.setenv("BANTAY_SUS_PATH", str(p))
    return p


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """Start `streamlit run` on a free port; yields dict(url, sus_csv). Killed at the end of the session."""
    if not (APP_DATA / "scenarios.parquet").exists():
        pytest.skip("build outputs missing: run build.bat first")
    port = free_port()
    sus_csv = tmp_path_factory.mktemp("sus") / "sus_responses.csv"
    log = (tmp_path_factory.mktemp("log") / "streamlit.log").open("w", encoding="utf-8")
    env = {**os.environ, "BANTAY_SUS_PATH": str(sus_csv), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(APP), "--server.port", str(port),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://localhost:{port}"
    try:
        for _ in range(120):
            try:
                if urllib.request.urlopen(f"{url}/_stcore/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("streamlit did not start")
        yield dict(url=url, sus_csv=sus_csv)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def shots():
    d = ARTIFACTS / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def isolated_status(tmp_path, monkeypatch):
    """Send bantay.config's status registry (record / missing / have) to a temporary status.json."""
    from bantay import config

    monkeypatch.setattr(config, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "_STATUS_FILE", tmp_path / "processed" / "status.json")
    return config._STATUS_FILE


def need(*paths):
    """Skip the calling test unless every build output exists."""
    for p in paths:
        if not Path(p).exists():
            pytest.skip(f"build output missing: {Path(p).relative_to(ROOT)} (run build.bat)")


def _snapshot():
    files = [p for d in ("processed", "interim", "crosswalks") for p in (ROOT / "data" / d).rglob("*") if p.is_file()]
    files.append(ROOT / "data" / "raw" / "MANIFEST.csv")
    return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files if p.exists()}


@pytest.fixture(scope="session", autouse=True)
def data_untouched():
    """Fail the session if a test created, changed or deleted a file under data/ (raw/MANIFEST.csv included)."""
    before = _snapshot()
    yield
    after = _snapshot()
    changed = sorted(str(p.relative_to(ROOT)) for p in set(before) | set(after) if before.get(p) != after.get(p))
    assert not changed, f"tests wrote into data/: {changed[:10]}"
