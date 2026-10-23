"""End-to-end checks in a real browser (pytest-playwright, Chromium): start the dashboard, visit every tab, change the
storm and the track, submit the SUS form to a temporary file, and fail on any app exception or browser console error.
Screenshots go to tests/artifacts/screenshots/ (git-ignored)."""

import re

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

from conftest import APP_DATA

pytestmark = pytest.mark.e2e
TABS = ["Action map", "Risk vs access", "Provinces", "Municipalities", "Outbreak graph", "Forecast skill",
        "Validation", "Data & caveats", "Usability test"]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1600, "height": 1300}}


@pytest.fixture
def app(page: Page, server):
    """Open the dashboard and record console errors and uncaught page errors."""
    errors = []
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(server["url"])
    wait_map(page)
    yield page
    assert not errors, errors


def idle(page: Page):
    page.wait_for_timeout(300)
    page.wait_for_selector(".stApp[data-test-script-state=notRunning]", timeout=60_000)
    page.wait_for_timeout(300)


def wait_map(page: Page):
    page.wait_for_function("document.querySelectorAll('.choroplethlayer path').length > 80", timeout=90_000)
    idle(page)


def no_exception(page: Page):
    expect(page.get_by_test_id("stException")).to_have_count(0)


def main_title(page: Page):
    return page.get_by_test_id("stMain").locator("h1").first


def kpi(page: Page, label: str):
    m = page.get_by_test_id("stMetric").filter(has_text=label).first
    return m.get_by_test_id("stMetricValue").inner_text()


def test_every_tab(app: Page, shots):
    names = app.get_by_role("tab").all_inner_texts()
    assert [n for n in names if n != "Leptospirosis"] == TABS  # optional tabs appear only with their outputs
    for i, name in enumerate(names):
        app.get_by_role("tab", name=name).click()
        idle(app)
        no_exception(app)
        expect(app.get_by_role("tab", name=name)).to_have_attribute("aria-selected", "true")
        app.screenshot(path=str(shots / f"tab{i}_{name.replace(' ', '_').replace('&', 'and')}.png"))
    expect(app).to_have_url(re.compile(r"tab=Usability"))  # the open tab is deep-linkable


def test_storm_and_shift(app: Page, shots):
    expect(main_title(app)).to_have_text("Typhoon Ompong")
    ferries_observed = kpi(app, "Ferries cancelled")
    # move the track 1 degree south with the keyboard (two steps of 0.5)
    slider = app.get_by_test_id("stSidebar").get_by_role("slider").first
    slider.focus()
    slider.press("ArrowLeft")
    idle(app)
    slider.press("ArrowLeft")
    wait_map(app)
    expect(main_title(app)).to_have_text("Typhoon Ompong, track moved 1° south")
    assert kpi(app, "Ferries cancelled") != ferries_observed
    expect(app.get_by_text("Upper bound").first).to_be_visible()  # shifted track = NOAH proxy
    app.screenshot(path=str(shots / "ompong_1S.png"))
    app.get_by_role("button", name="Back to observed track").click()
    wait_map(app)
    assert kpi(app, "Ferries cancelled") == ferries_observed
    # change the storm
    app.get_by_test_id("stSidebar").get_by_role("combobox").first.click()
    app.get_by_role("option", name="Tisoy (Kammuri, 2019)").click()
    wait_map(app)
    expect(main_title(app)).to_have_text("Typhoon Tisoy")
    no_exception(app)
    app.screenshot(path=str(shots / "tisoy.png"))
    # a catalogue storm (observed track only): type to search the long list
    if (APP_DATA / "scenarios_catalog.parquet").exists():
        app.get_by_test_id("stSidebar").get_by_role("combobox").first.click()
        app.keyboard.type("Haikui", delay=50)
        app.get_by_role("option", name="Haikui 2017").click()
        wait_map(app)
        expect(main_title(app)).to_have_text("Haikui 2017")
        expect(app.get_by_test_id("stSidebar").get_by_role("slider")).to_have_count(0)
        no_exception(app)
        app.screenshot(path=str(shots / "catalogue_haikui.png"))


def test_dark_mode(page: Page, server, shots):
    page.emulate_media(color_scheme="dark")
    page.goto(server["url"])
    wait_map(page)
    no_exception(page)
    fill = page.eval_on_selector(".choroplethlayer path", "e => getComputedStyle(e).fill")
    assert fill == "rgb(29, 35, 44)", fill  # dark 'no data' land colour, not the light one
    page.screenshot(path=str(shots / "dark.png"))


def test_sus_submit(app: Page, server, shots):
    app.get_by_role("tab", name="Usability test").click()
    idle(app)
    form = app.get_by_test_id("stForm")
    form.get_by_role("combobox").first.click()
    app.get_by_role("option", name="LGU health office").click()
    form.get_by_text("Completed", exact=True).click()
    form.get_by_label("Minutes taken (optional)").fill("14")
    for i in range(1, 11):
        app.get_by_test_id("stRadio").filter(has_text=f"{i}. ").first.get_by_text("4" if i % 2 else "2",
                                                                                   exact=True).click()
    app.get_by_role("button", name="Submit answers").click()
    idle(app)
    expect(app.get_by_text("Saved. This response scores 75.0 out of 100.")).to_be_visible()
    app.screenshot(path=str(shots / "sus_saved.png"))
    r = pd.read_csv(server["sus_csv"])
    assert r.sus.iloc[-1] == 75.0 and r.role.iloc[-1] == "LGU health office" and r.task_minutes.iloc[-1] == 14
