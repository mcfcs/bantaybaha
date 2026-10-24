"""Vendored agent skills in .claude/skills/ stay exactly as reviewed.

The K-Dense data-science skills were copied verbatim at a pinned commit after a safety review (see
.claude/skills/VENDORED.json and AGENTS.md 'Agent skills'). These tests fail if a vendored file is edited, added or
removed, if a skill's name stops matching its folder, or if bundled code gains network or process access.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude" / "skills"
VENDORED = json.loads((SKILLS / "VENDORED.json").read_text(encoding="utf-8"))
NAMES = sorted(VENDORED["skills"])

# The only reviewed process call: a macOS RAM probe (sysctl / vm_stat) in TimesFM's system check.
SUBPROCESS_OK = {"timesfm-forecasting/scripts/check_system.py"}
NETWORK = re.compile(r"^\s*(import|from)\s+(requests|urllib|http|socket|ftplib|smtplib|paramiko|httpx|aiohttp)\b", re.M)
PROCESS = re.compile(r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\beval\(|\bexec\(|__import__")


def _sha(p):
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_provenance_is_pinned():
    assert re.fullmatch(r"[0-9a-f]{40}", VENDORED["commit"])
    assert VENDORED["source"] == "https://github.com/K-Dense-AI/scientific-agent-skills"
    assert {"scikit-learn", "shap", "statsmodels", "statistical-analysis", "scientific-critical-thinking",
            "timesfm-forecasting"} == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_files_match_reviewed_hashes(name):
    listed = VENDORED["skills"][name]
    on_disk = {p.relative_to(SKILLS / name).as_posix() for p in (SKILLS / name).rglob("*") if p.is_file()}
    assert on_disk == set(listed), f"{name}: files added or removed since the review"
    for rel, digest in listed.items():
        assert _sha(SKILLS / name / rel) == digest, f"{name}/{rel} changed since the review"


@pytest.mark.parametrize("name", NAMES)
def test_skill_name_matches_folder(name):
    head = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", head, re.M)


@pytest.mark.parametrize("name", NAMES)
def test_bundled_code_has_no_network_or_process_access(name):
    for p in (SKILLS / name).rglob("*.py"):
        rel = f"{name}/{p.relative_to(SKILLS / name).as_posix()}"
        src = p.read_text(encoding="utf-8")
        assert not NETWORK.search(src), f"{rel} imports a network module"
        if rel not in SUBPROCESS_OK:
            assert not PROCESS.search(src), f"{rel} spawns processes or evaluates code"


def test_excluded_demo_folder_stays_out():
    assert not (SKILLS / "timesfm-forecasting" / "examples").exists()
