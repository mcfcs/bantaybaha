"""Document generators: the library + dashboard code guide, the demo scripts and the deck's demo slide.

Pure-logic tests on small hand-built markdown, plus checks against the real docs/CODE_GUIDE.md and app (no build
outputs needed).
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_results as M  # noqa: E402

GUIDE = ROOT / "docs" / "CODE_GUIDE.md"

SAMPLE = """# Guide

intro

## 3. Getting the data

### `scripts/download_data.py`

| Block | Lines | Explanation |
|---|---|---|
| `fetch()` | [1-2](../scripts/download_data.py#L1-L2) | downloads |

---

## 4. The `bantay` library

### 4.1 `bantay/config.py`

| Block | Lines | Explanation |
|---|---|---|
| `have()` | [3-4](../bantay/config.py#L3-L4) | checks inputs |

---

## 6. The dashboard: `app/streamlit_app.py`

app text

### 6.1 `app/ui.py`

ui text

### 6.5 Tests: `tests/`

test text

---

## 7. Documents

docs text

## 11. Glossary

| Term | Meaning |
|---|---|
| **R** | surge |
"""


def test_library_guide_keeps_library_dashboard_and_glossary_only():
    md = M.library_guide_md(SAMPLE)
    assert "## 1. The `bantay` library" in md and "### 1.1 `bantay/config.py`" in md
    assert "## 2. The dashboard" in md and "### 2.1 `app/ui.py`" in md
    assert "## 3. Glossary" in md
    for gone in ("download_data", "Getting the data", "Tests", "test text", "Documents", "docs text"):
        assert gone not in md, gone
    assert "[TOC]" in md


def test_library_guide_needs_both_sections():
    with pytest.raises(ValueError):
        M.library_guide_md("## 4. The `bantay` library\n\ntext\n")


def test_code_guide_html_builds_contents_and_strips_repo_links():
    html = M.code_guide_html(M.library_guide_md(SAMPLE), "t")
    assert 'class="toc"' in html  # [TOC] became the contents list
    assert "../bantay/config.py" not in html  # repo links are plain text in a PDF
    assert "<table class='blocks'>" in html  # Block | Lines tables get the line-number style


@pytest.mark.skipif(not GUIDE.exists(), reason="docs/CODE_GUIDE.md missing")
def test_real_library_guide_covers_every_bantay_and_app_module():
    md = M.library_guide_md(GUIDE.read_text(encoding="utf-8"))
    modules = [p.stem for p in (ROOT / "bantay").glob("*.py") if p.stem != "__init__"]
    for m in modules:
        assert f"`bantay/{m}.py`" in md, m
    for f in ("streamlit_app.py", "ui.py", "sus.py", "lepto_tab.py"):
        assert f"app/{f}" in md, f
    headings = "\n".join(line for line in md.splitlines() if line.startswith("#"))
    assert "download_data" not in headings and "download_gee" not in headings and "Tests" not in headings


TECH = ROOT / "docs" / "results" / "Bantay-Baha_Tech_Demo_Script.md"
SCRIPT_MD = """# Demo: a test script (0:10)

Intro line.

| Time | On screen (cue) | Narration |
|---|---|---|
| **0:00-0:10** | Open `x.py` | "Hello." |

## Before recording

- One note.
"""


def _app_tabs():
    app = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    block = app[app.index("TABS = ["):]
    return re.findall(r'^\s+\("([^"]+)", tab_\w+', block[: block.index("]\n")], re.M)


def test_demo_script_html_uses_its_own_source_and_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "OUT", tmp_path)
    (tmp_path / "S.md").write_text(SCRIPT_MD, encoding="utf-8")
    html = M.demo_script_html("S", "technical demo")
    assert "PJDSC 2026 / technical demo" in html
    assert "<td class='t'>0:00-0:10</td>" in html and "<code>x.py</code>" in html
    assert "<h2>Before recording</h2>" in html and "<li>One note.</li>" in html


def test_write_demo_scripts_skips_missing_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "OUT", tmp_path)
    monkeypatch.setattr(M, "SRC", tmp_path / "src")
    (tmp_path / "Bantay-Baha_Tech_Demo_Script.md").write_text(SCRIPT_MD, encoding="utf-8")
    M.write_demo_scripts(pdf=False)
    assert (tmp_path / "src" / "tech_demo_script.html").exists()
    assert not (tmp_path / "src" / "demo_script.html").exists()  # its markdown is absent


@pytest.mark.skipif(not TECH.exists(), reason="technical demo script missing")
def test_tech_demo_script_fits_and_matches_the_app():
    """The technical demo fits 2:50, stays on the app (no build or pipeline commands), and every control, tab and
    option it tells you to click exists in the dashboard under that name."""
    md = TECH.read_text(encoding="utf-8")
    rows = [r.split("|") for r in md.splitlines() if r.startswith("| **")]
    words = sum(len(r[3].split()) for r in rows)
    assert words <= 140 * 170 / 60, f"{words} words do not fit 2:50 at 140 words a minute"
    assert rows[-1][1].strip().strip("*").endswith("2:50")
    for banned in ("build", "pytest", "MANIFEST", "scripts/", "bantay/"):
        assert banned not in md, f"the technical demo is about the app; it mentions '{banned}'"
    app = "".join((ROOT / "app" / f).read_text(encoding="utf-8") for f in ("streamlit_app.py", "lepto_tab.py", "ui.py"))
    tabs = _app_tabs()
    assert all(t in md for t in tabs), "the technical demo should show every tab"
    shifts = {"1° south", "1° north", "1° east", "1° west", "no shift"}  # ui.shift_label at the shifts the app offers
    places = {"Pampanga"}  # a province picked in a selectbox: data, not code
    for cue in re.findall(r"\*\*(.+?)\*\*", " ".join(r[2] for r in rows)):
        assert cue in tabs or cue in app or cue in shifts or cue in places, f"no control or tab named '{cue}' in the app"
    # "nothing is trained while you click ... the training is repeatable": the app never fits a model, XGBoost is seeded
    assert "fit_at" not in app and "XGBRegressor" not in app and "import xgboost" not in app
    fc = (ROOT / "bantay" / "forecast.py").read_text(encoding="utf-8")
    assert "def fit_quantile_model(X, y, seed=0)" in fc and "random_state=seed" in fc


NOTES = ROOT / "docs" / "results" / "Bantay-Baha_Slide_Notes.md"


def test_slide_notes_use_thumbnails_that_exist_and_drop_the_rest(tmp_path, monkeypatch):
    pdfium = pytest.importorskip("pypdfium2")
    monkeypatch.setattr(M, "OUT", tmp_path)
    monkeypatch.setattr(M, "SRC", tmp_path / "src")
    deck = pdfium.PdfDocument.new()
    deck.new_page(960, 540)  # a one-slide deck
    deck.save(tmp_path / "Bantay-Baha_Slides.pdf")
    deck.close()
    (tmp_path / "Bantay-Baha_Slide_Notes.md").write_text(
        "# Notes\n\n## 01 · One\n\n![slide 1](slide_01.png)\n\ntext\n\n## 02 · Two\n\n![slide 2](slide_02.png)\n", encoding="utf-8")
    M.write_slide_notes(pdf=False)
    html = (tmp_path / "src" / "slide_notes.html").read_text(encoding="utf-8")
    assert (tmp_path / "src" / "slide_notes" / "slide_01.png").exists()
    assert 'src="slide_notes/slide_01.png"' in html and "slide_02.png" not in html  # no broken image for slide 2
    assert "Bantay-Baha / slide notes" in html and "Bantay-Baha / code guide" not in html


@pytest.mark.skipif(not NOTES.exists(), reason="slide notes missing")
def test_slide_notes_cover_every_slide_with_the_decks_numbers():
    md = NOTES.read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d\d) · ", md, re.M)
    assert heads == [f"{i:02d}" for i in range(1, 21)]
    for i in range(1, 21):
        assert f"](slide_{i:02d}.png)" in md, f"slide {i} has no thumbnail"
    src = ROOT / "docs" / "results" / "src"
    if not (src / "slides.html").exists():
        pytest.skip("generated deck HTML missing")
    known = "".join((src / f).read_text(encoding="utf-8") for f in ("slides.html", "report.html") if (src / f).exists())
    known += (ROOT / "docs" / "results" / "Bantay-Baha_Demo_Script.md").read_text(encoding="utf-8")  # checked on screen
    for n in set(re.findall(r"(?<![\d.])\d\.\d{2,3}(?!\d)", md)):
        assert n in known, f"the notes quote {n}, which is in neither the deck, the report nor the demo script"


def test_demo_slide_lists_every_dashboard_tab():
    """The deck's demo slide names the dashboard's tabs; it went stale once when tabs were added."""
    app = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    block = app[app.index("TABS = ["):]
    labels = re.findall(r'^\s+\("([^"]+)", tab_\w+', block[: block.index("]\n")], re.M)
    assert len(labels) >= 8
    slides = (ROOT / "scripts" / "results_slides.py").read_text(encoding="utf-8")
    demo = slides[slides.index("Signal 18 / Demo"):]
    demo = demo[: demo.index("</section>")]
    for lbl in labels:
        assert lbl.replace("&", "&amp;") in demo or lbl in demo, f"demo slide does not mention the '{lbl}' tab"
