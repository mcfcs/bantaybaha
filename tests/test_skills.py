"""Vendored agent skills in .claude/skills/ stay exactly as reviewed.

The K-Dense data-science skills were copied verbatim at a pinned commit after a safety review (see
.claude/skills/VENDORED.json and AGENTS.md 'Agent skills'). These tests fail if a vendored file is edited, added or
removed, if a skill's name stops matching its folder, if bundled code gains network or process access, or if any
project skill pre-approves tools beyond read-only ones and scoped Bash commands (a skill's allowed-tools runs them
without a permission prompt).
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
# allowed-tools entries a project skill may pre-approve: read-only tools, or Bash scoped to one command.
SAFE_TOOL = re.compile(r"^(Read|Grep|Glob|Bash\([\w .:*-]+\))$")
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


def _allowed_tools(skill_md):
    head = skill_md.read_text(encoding="utf-8").split("---")[1]
    m = re.search(r"^allowed-tools:\s*(.*)$", head, re.M)
    return re.findall(r"\S+\([^)]*\)|[^\s()]+", m.group(1).strip().strip('"')) if m else []


@pytest.mark.parametrize("name", NAMES)
def test_vendored_skills_grant_no_tools(name):
    assert _allowed_tools(SKILLS / name / "SKILL.md") == []


def test_patches_are_recorded():
    assert set(VENDORED["patches"]) == {f"{n}/SKILL.md" for n in
                                         ("scikit-learn", "shap", "statsmodels", "scientific-critical-thinking",
                                          "timesfm-forecasting")}
    for rel, patch in VENDORED["patches"].items():
        name, file = rel.split("/", 1)
        assert re.fullmatch(r"[0-9a-f]{64}", patch["upstream_sha256"])
        assert patch["upstream_sha256"] != VENDORED["skills"][name][file]


@pytest.mark.parametrize("skill_md", sorted(SKILLS.glob("*/SKILL.md")), ids=lambda p: p.parent.name)
def test_no_project_skill_pre_approves_broad_tools(skill_md):
    for tool in _allowed_tools(skill_md):
        assert SAFE_TOOL.match(tool), f"{skill_md.parent.name} pre-approves {tool!r}"


def test_tool_check_catches_broad_grants(tmp_path):
    bad = tmp_path / "SKILL.md"
    bad.write_text('---\nname: x\nallowed-tools: "Read Bash"\n---\n', encoding="utf-8")
    assert [t for t in _allowed_tools(bad) if not SAFE_TOOL.match(t)] == ["Bash"]
    bad.write_text("---\nname: x\nallowed-tools: Bash(git:*) Write\n---\n", encoding="utf-8")
    assert [t for t in _allowed_tools(bad) if not SAFE_TOOL.match(t)] == ["Write"]


def test_excluded_demo_folder_stays_out():
    assert not (SKILLS / "timesfm-forecasting" / "examples").exists()
