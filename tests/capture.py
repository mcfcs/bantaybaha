"""Refresh the dashboard figure and record a silent walkthrough of the demo-script cues (Playwright, Chromium).

Usage (repo root):
    python tests/capture.py                 # both
    python tests/capture.py --no-video      # only docs/results/figures/dashboard.png
    python tests/capture.py --no-shot       # only the video

The figure is 1600x1300, Typhoon Ompong, observed track, taken once the map has drawn. The video follows
docs/results/Bantay-Baha_Demo_Script.md (1920x1080, no narration) and is saved to
tests/artifacts/video/bantay_baha_walkthrough.webm (git-ignored; not for the repository).
SUS answers are never written: the server gets a throw-away BANTAY_SUS_PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import free_port  # noqa: E402

FIGURE = ROOT / "docs" / "results" / "figures" / "dashboard.png"
VIDEO_DIR = ROOT / "tests" / "artifacts" / "video"


def start():
    port = free_port()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "BANTAY_SUS_PATH": str(Path(tempfile.mkdtemp()) / "sus_responses.csv")}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "streamlit_app.py"),
                             "--server.port", str(port), "--server.headless", "true"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://localhost:{port}"
    for _ in range(120):
        try:
            if urllib.request.urlopen(f"{url}/_stcore/health", timeout=1).status == 200:
                return proc, url
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("streamlit did not start")


def ready(page, map_=True):
    page.wait_for_timeout(300)
    if map_:
        page.wait_for_function("document.querySelectorAll('.choroplethlayer path').length > 80", timeout=90_000)
    page.wait_for_selector(".stApp[data-test-script-state=notRunning]", timeout=60_000)
    page.wait_for_timeout(800)


def centre(page, selector, nth=0):
    box = page.locator(selector).nth(nth).bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def unit_path(page, name):
    """Screen centre of a province on the map, found through the figure's own data (no hard-coded pixels)."""
    i = page.evaluate("""(name) => {
        const gd = document.querySelector('.js-plotly-plot');
        const tr = gd.data.findIndex(t => t.type === 'choropleth' && t.text);
        return [tr, gd.data[tr].text.indexOf(name)];
    }""", name)
    sel = f".choroplethlayer .trace:nth-child({i[0] + 1}) path"
    return centre(page, sel, i[1])


def glide(page, xy, steps=30, pause=1200):
    page.mouse.move(*xy, steps=steps)
    page.wait_for_timeout(pause)


def shot(url):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1300}, color_scheme="light")
        pg.goto(url)
        ready(pg)
        pg.wait_for_timeout(1500)
        FIGURE.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(FIGURE))
        b.close()
    print("figure:", FIGURE)


def video(url):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light",
                            record_video_dir=str(tmp), record_video_size={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        pg.goto(url)
        ready(pg)
        pg.wait_for_timeout(1500)
        # 0:35 priority map: track, gale swath, cancelled ferries, then the KPI row
        track = pg.locator(".scatterlayer .trace").last.locator("path.point")
        glide(pg, centre(pg, ".scatterlayer .trace:last-child path.point", track.count() // 2), pause=1800)
        glide(pg, centre(pg, ".legend .traces", 0), pause=1500)
        glide(pg, centre(pg, ".legend .traces", 1), pause=1500)
        glide(pg, centre(pg, "[data-testid=stMetric]", 2), pause=2500)
        # 1:00 Pampanga tooltip
        glide(pg, unit_path(pg, "Pampanga"), pause=3500)
        # 1:15 shift the track south, then north, then back
        slider = pg.get_by_test_id("stSidebar").get_by_role("slider").first
        bb = slider.bounding_box()
        glide(pg, (bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2), pause=600)
        slider.focus()
        for key, n in (("ArrowLeft", 2), ("ArrowRight", 4)):
            for _ in range(n):
                slider.press(key)
                ready(pg)
            pg.wait_for_timeout(2500)
        pg.get_by_role("button", name="Back to observed track").click()
        ready(pg)
        # 1:35 risk vs access
        pg.get_by_role("tab", name="Risk vs access").click()
        ready(pg, map_=False)
        glide(pg, centre(pg, ".js-plotly-plot >> visible=true"), pause=3500)
        # 1:55 ranked provinces, then municipalities (opens on the top province)
        pg.get_by_role("tab", name="Provinces").click()
        ready(pg, map_=False)
        glide(pg, centre(pg, "[data-testid=stDataFrame] >> visible=true"), pause=800)
        pg.mouse.wheel(0, 300)
        pg.wait_for_timeout(2500)
        pg.get_by_role("tab", name="Municipalities").click()
        ready(pg, map_=False)
        pg.wait_for_timeout(3500)
        # 2:15 forecast skill: Cagayan, 4 weeks ahead; then validation
        pg.get_by_role("tab", name="Forecast skill").click()
        ready(pg, map_=False)
        pg.wait_for_timeout(2000)
        box = pg.locator("[data-testid=stSelectbox] >> visible=true").filter(has_text="Province").first
        box.get_by_role("combobox").click()
        pg.keyboard.type("Cagayan", delay=90)  # the option list is virtualised: filter, then pick
        pg.get_by_role("option", name="Cagayan", exact=True).click()
        ready(pg, map_=False)
        pg.get_by_test_id("stRadio").filter(has_text="Weeks ahead").get_by_text("4", exact=True).click()
        ready(pg, map_=False)
        pg.mouse.wheel(0, 500)
        pg.wait_for_timeout(3000)
        pg.get_by_role("tab", name="Validation").click()
        ready(pg, map_=False)
        pg.wait_for_timeout(3500)
        path = pg.video.path()
        ctx.close()
        b.close()
    out = VIDEO_DIR / "bantay_baha_walkthrough.webm"
    shutil.move(path, out)
    print("video:", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-shot", action="store_true")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    proc, url = start()
    try:
        if not a.no_shot:
            shot(url)
        if not a.no_video:
            video(url)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
