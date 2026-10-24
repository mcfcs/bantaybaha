"""scripts/make_submission.py: what goes in the submission zip, the pinned requirements and the anonymity check.

Pure-logic tests on small inputs, plus one real packaging run without build outputs (--no-data) into a temp folder.
"""

import re
import shutil
import sys
import zipfile
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_submission as MS  # noqa: E402


def test_code_files_keep_code_and_launchers_and_drop_team_only_and_internal_files():
    files = ["bantay/forecast.py", "app/streamlit_app.py", "scripts/build.py", "scripts/sync_data.py", "setup.bat",
             "run_app.bat", "install.bat", "HANDOFF.md", "AGENTS.md", "docs/results/Bantay-Baha_Slides.pdf",
             "docs/results/src/slides.html", "docs/proposal/x.pdf", "scripts/__pycache__/a.pyc", "data/raw/MANIFEST.csv"]
    got = MS.code_files(files)
    assert got == ["bantay/forecast.py", "app/streamlit_app.py", "scripts/build.py", "run_app.bat", "install.bat",
                   "docs/results/Bantay-Baha_Slides.pdf", "data/raw/MANIFEST.csv"]


def test_requirement_names_skip_comments_includes_and_versions():
    texts = ["# comment\n-r requirements.txt\npandas\nstreamlit>=1.66\n", "pytest>=9  # tests\nPandas\nxgboost[dask]\n"]
    assert MS.requirement_names(texts) == ["pandas", "streamlit", "pytest", "xgboost"]


def test_pinned_requirements_pin_installed_and_keep_unknown_unpinned():
    def fake(name):
        if name == "nope":
            raise PackageNotFoundError(name)
        return "1.2.3"

    lines = [ln for ln in MS.pinned_requirements(["pandas", "nope"], fake).splitlines() if not ln.startswith("#")]
    assert lines == ["pandas==1.2.3", "nope"]


def test_identity_hits_find_names_emails_and_user_paths_only():
    words = ["someone", "someone@example.com"]
    assert MS.identity_hits("a.md", "made by Someone", words) == ["a.md: someone"]
    assert MS.identity_hits("a.md", "mail someone@example.com", words)  # the address and its user part
    users = "C:" + "\\Users\\"  # split so this file does not trip the scan itself when it is packaged
    assert MS.identity_hits("a.py", f"open('{users}anybody\\x.csv')", words) == ["a.py: a user folder path"]
    assert MS.identity_hits("a.ipynb", "base64 4SomeoneX9 blob", words) == []  # inside a longer token: not a name
    assert MS.identity_hits("a.md", f"{users}Public\\x", words) == []


def test_every_listed_launcher_and_document_exists():
    for pat in MS.INCLUDE:
        assert list(ROOT.glob(pat)), f"nothing in the repo matches {pat}"
    assert MS.GUIDE.exists()


def test_user_guide_covers_every_dashboard_tab_and_launcher():
    guide = MS.GUIDE.read_text(encoding="utf-8")
    app = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    block = app[app.index("TABS = ["):]
    tabs = re.findall(r'^\s+\("([^"]+)", tab_\w+', block[: block.index("]\n")], re.M)
    for t in tabs:
        assert f"**{t}**" in guide, f"the user guide does not explain the '{t}' tab"
    for bat in ("install.bat", "run_app.bat", "download_data.bat", "build.bat"):
        assert bat in guide
    assert "setup.bat" not in guide  # team-only, not in the zip


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_real_zip_without_data(tmp_path):
    dest = MS.build_zip(tmp_path / "s.zip", with_data=False)
    names = zipfile.ZipFile(dest).namelist()
    top = {n.split("/", 1)[1] for n in names}
    for need in ("README.md", "README_DEVELOPERS.md", "requirements.txt", "install.bat", "run_app.bat", "build.bat",
                 "download_data.bat", "app/streamlit_app.py", "bantay/forecast.py", "data/raw/MANIFEST.csv"):
        assert need in top, need
    for gone in ("setup.bat", "scripts/sync_data.py", "HANDOFF.md", "AGENTS.md", "CLAUDE.md"):
        assert gone not in top, gone
    assert not any(n.startswith("data/processed") for n in top)
    req = zipfile.ZipFile(dest).read("Bantay-Baha/requirements.txt").decode()
    assert "streamlit==" in req and "xgboost==" in req and "pytest==" in req
