"""Package the submission: code, launchers, documents and the pre-computed dashboard outputs -> one zip.

Usage:
    python scripts/make_submission.py              # dist/Bantay-Baha_Submission.zip
    python scripts/make_submission.py --no-data    # code and documents only (no data/processed outputs)

Run it on the machine with the full, current build: the zip carries that machine's data/processed/app/, which is
what the dashboard shows. Only git-tracked files are packed (no caches, no work in progress), plus the build outputs.
At the zip root: README.md (the user guide, from docs/submission/README.md), README_DEVELOPERS.md (this repo's
README) and requirements.txt with every package pinned to the version installed in the running environment.
Left out on purpose: raw data (downloaded by script, see MANIFEST.csv), the team-only bucket sync (setup.bat,
scripts/sync_data.py), agent notes and internal docs, and usability-test responses. The zip is refused if any text
file in it names a contributor (anonymous judging).
"""

import argparse
import fnmatch
import re
import subprocess
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ZIP = DIST / "Bantay-Baha_Submission.zip"
GUIDE = ROOT / "docs" / "submission" / "README.md"

INCLUDE = ["bantay/*", "app/*", "scripts/*", "tests/*", ".streamlit/*", "data/crosswalks/*", "data/raw/MANIFEST.csv",
           "notebooks/00_data_eda.ipynb", "docs/CODE_GUIDE.md", "docs/results/*.pdf", "build.bat", "run_app.bat",
           "download_data.bat", "install.bat", "requirements-bench.txt"]
EXCLUDE = ["scripts/sync_data.py"]  # pulls from the team's private bucket: useless outside the team
DATA = ["data/processed/app/*", "data/processed/status.json"]
REQUIREMENTS = ["requirements.txt", "requirements-dev.txt"]
TEXT = {".py", ".md", ".bat", ".txt", ".csv", ".json", ".toml", ".ipynb", ".html", ".cfg", ".yml", ".yaml"}


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def tracked_files(root=ROOT):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def code_files(files):
    """The tracked files that go in the zip, as repo-relative posix paths."""
    return [f for f in files if matches(f, INCLUDE) and not matches(f, EXCLUDE) and "__pycache__" not in f]


def data_files(root=ROOT):
    return sorted(p.relative_to(root).as_posix() for pat in DATA for p in root.glob(pat) if p.is_file())


def requirement_names(texts):
    """Package names from requirements files: no comments, no `-r` includes, no version specifiers, no duplicates."""
    names = []
    for t in texts:
        for line in t.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
            if name.lower() not in (n.lower() for n in names):
                names.append(name)
    return names


def pinned_requirements(names, get_version=version):
    """requirements.txt text with each package pinned to the installed version; unknown ones stay unpinned."""
    lines = [f"# Every Python package for the dashboard, the pipeline and the tests, pinned to the versions the results",
             f"# were made with (Python {sys.version_info.major}.{sys.version_info.minor}). Install: pip install -r requirements.txt",
             "# Tests in a browser also need: python -m playwright install chromium",
             "# The optional benchmark models need requirements-bench.txt in a separate environment (see that file)."]
    for n in names:
        try:
            lines.append(f"{n}=={get_version(n)}")
        except PackageNotFoundError:
            lines.append(n)
    return "\n".join(lines) + "\n"


def contributors(root=ROOT):
    """Names and emails in the git history: none may appear in the zip."""
    out = subprocess.run(["git", "log", "--format=%an%n%ae%n%cn%n%ce"], cwd=root, capture_output=True, text=True).stdout
    words = set()
    for v in out.splitlines():
        v = v.strip()
        if not v or v.lower() in ("github", "noreply@github.com") or v.lower().startswith("claude") or "anthropic" in v:
            continue
        words.add(v)
        if "@" in v:
            words.add(v.split("@")[0])
    return sorted(words)


def identity_hits(name, text, words):
    hits = [w for w in words if len(w) >= 4 and re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", text, re.I)]
    if re.search(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public)[^\\/\s\"']+", text):
        hits.append("a user folder path")
    return [f"{name}: {h}" for h in hits]


def build_zip(dest=ZIP, with_data=True, root=ROOT):
    files = code_files(tracked_files(root))
    data = data_files(root) if with_data else []
    if with_data and not any(f.startswith("data/processed/app/") for f in data):
        sys.exit("no data/processed/app/ outputs: run build.bat first, or pass --no-data")
    extra = {"README.md": GUIDE.read_text(encoding="utf-8"),
             "README_DEVELOPERS.md": (root / "README.md").read_text(encoding="utf-8"),
             "requirements.txt": pinned_requirements(requirement_names(
                 (root / r).read_text(encoding="utf-8") for r in REQUIREMENTS))}
    words = contributors(root)
    problems = [h for n, t in extra.items() for h in identity_hits(n, t, words)]
    for f in files + data:
        if Path(f).suffix in TEXT:
            problems += identity_hits(f, (root / f).read_text(encoding="utf-8", errors="ignore"), words)
    if problems:
        sys.exit("refusing to package, identifying text found:\n  " + "\n  ".join(problems[:20]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, text in extra.items():
            z.writestr(f"Bantay-Baha/{name}", text)
        for f in files + data:
            z.write(root / f, f"Bantay-Baha/{f}")
    tmp.replace(dest)
    shown = dest.relative_to(root) if dest.is_relative_to(root) else dest
    print(f"  wrote {shown} ({dest.stat().st_size / 1e6:.1f} MB): {len(files)} code and document files, "
          f"{len(data)} output files, README.md, README_DEVELOPERS.md, pinned requirements.txt")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-data", action="store_true", help="leave out data/processed (code and documents only)")
    build_zip(with_data=not ap.parse_args().no_data)
