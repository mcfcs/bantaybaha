"""Shared fixtures: paths, a throw-away SUS responses file, and a live dashboard server for the Playwright tests.

The dashboard reads the real build outputs in data/processed/app/; tests never write there. SUS answers go to a
temporary CSV through BANTAY_SUS_PATH. Screenshots land in tests/artifacts/ (git-ignored).
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
APP_DATA = ROOT / "data" / "processed" / "app"
ARTIFACTS = ROOT / "tests" / "artifacts"
sys.path.insert(0, str(ROOT / "app"))

needs_data = pytest.mark.skipif(not (APP_DATA / "scenarios.parquet").exists(),
                                reason="build outputs missing: run build.bat first")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: browser tests (Playwright); deselect with -m 'not e2e'")


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
