"""scripts/: the download contract (skip existing files, write through .part, manifest merge and sha256; no network),
the bucket manifest round trip, and the code-guide checker on a tiny guide plus module."""

import csv
import hashlib

import pytest

import check_code_guide as CG
import download_data as DD

# ---------------------------------------------------------------- download_data.fetch


class FakeResponse:
    def __init__(self, chunks, content_type="application/octet-stream", status=200, on_chunk=None):
        self.chunks, self.headers, self.status, self.on_chunk = chunks, {"Content-Type": content_type}, status, on_chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def iter_content(self, size):
        for c in self.chunks:
            if self.on_chunk:
                self.on_chunk()
            yield c


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(DD, "RAW", tmp_path / "raw")
    monkeypatch.setattr(DD.time, "sleep", lambda s: None)
    return tmp_path / "raw"


def no_network(*a, **k):
    raise AssertionError("network used for a file that already exists")


def test_fetch_skips_existing_files(raw, monkeypatch):
    dest = raw / "src" / "file.csv"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"already here")
    monkeypatch.setattr(DD.requests, "get", no_network)
    assert DD.fetch("https://example.org/file.csv", dest) == dest
    assert dest.read_bytes() == b"already here"


def test_fetch_writes_through_part_then_renames(raw, monkeypatch):
    dest = raw / "src" / "big.bin"
    part = dest.with_suffix(".bin.part")
    seen = []

    def check():  # while streaming: only the .part file exists
        seen.append((part.exists(), dest.exists()))

    monkeypatch.setattr(DD.requests, "get", lambda url, **kw: FakeResponse([b"ab", b"cd"], on_chunk=check))
    assert DD.fetch("https://example.org/big.bin", dest) == dest
    assert dest.read_bytes() == b"abcd" and not part.exists()
    assert seen == [(True, False), (True, False)]


def test_fetch_redownloads_an_empty_file(raw, monkeypatch):
    dest = raw / "src" / "empty.csv"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"")
    monkeypatch.setattr(DD.requests, "get", lambda url, **kw: FakeResponse([b"x,y\n"]))
    DD.fetch("https://example.org/empty.csv", dest)
    assert dest.read_bytes() == b"x,y\n"


def test_fetch_failure_leaves_no_final_file(raw, monkeypatch):
    dest = raw / "src" / "fail.csv"
    calls = []

    def get(url, **kw):
        calls.append(url)
        return FakeResponse([b"partial"], status=503)

    monkeypatch.setattr(DD.requests, "get", get)
    with pytest.raises(RuntimeError, match="failed"):
        DD.fetch("https://example.org/fail.csv", dest, retries=3)
    assert len(calls) == 3 and not dest.exists()


def test_fetch_binary_rejects_an_html_page(raw, monkeypatch):
    dest = raw / "noah" / "x.tif"
    monkeypatch.setattr(DD.requests, "get", lambda url, **kw: FakeResponse([b"<html>quota</html>"], "text/html; charset=utf-8"))
    with pytest.raises(RuntimeError):
        DD.fetch("https://example.org/x.tif", dest, retries=1, binary=True)
    assert not dest.exists()


# ---------------------------------------------------------------- manifest

def read_csv(p):
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def test_write_manifest_merges_and_hashes(raw):
    a, b = raw / "s1" / "a.csv", raw / "s2" / "sub" / "b.bin"
    for p, data in ((a, b"alpha"), (b, b"bravo!")):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    DD.write_manifest([("s2", b, "https://x/b")])
    DD.write_manifest([("s1", a, "https://x/a")])  # a second source: merged, not overwritten
    rows = read_csv(raw / "MANIFEST.csv")
    assert [r["path"] for r in rows] == ["s1/a.csv", "s2/sub/b.bin"]  # sorted, POSIX paths relative to raw/
    assert rows[0] == dict(source="s1", path="s1/a.csv", bytes="5", sha256=hashlib.sha256(b"alpha").hexdigest(), url="https://x/a")
    assert rows[1]["sha256"] == DD.sha256(b) == hashlib.sha256(b"bravo!").hexdigest()


def test_write_manifest_rehashes_only_on_size_change(raw):
    a = raw / "s1" / "a.csv"
    a.parent.mkdir(parents=True)
    a.write_bytes(b"alpha")
    DD.write_manifest([("s1", a, "u")])
    first = read_csv(raw / "MANIFEST.csv")[0]["sha256"]
    a.write_bytes(b"ALPHA")  # same size: the recorded checksum is kept (files are not re-read to "check" them)
    DD.write_manifest([("s1", a, "u")])
    assert read_csv(raw / "MANIFEST.csv")[0]["sha256"] == first
    a.write_bytes(b"alphabet")
    DD.write_manifest([("s1", a, "u")])
    r = read_csv(raw / "MANIFEST.csv")[0]
    assert r["bytes"] == "8" and r["sha256"] == hashlib.sha256(b"alphabet").hexdigest()


def test_every_static_source_has_unique_files():
    names = [(s, n) for s, files in DD.STATIC.items() for _, n in files]
    assert len(names) == len(set(names))
    assert set(DD.STATIC) <= set(DD.PULLERS) and {"noah", "chirps", "copernicus_ems"} <= set(DD.PULLERS)


def test_sync_manifest_round_trip(tmp_path, monkeypatch):
    sync_data = pytest.importorskip("sync_data")
    monkeypatch.setattr(sync_data, "RAW", tmp_path)
    rows = {"b/x.tif": dict(source="b", path="b/x.tif", bytes="10", sha256="f" * 64, url="gs://x"),
            "a/y.csv": dict(source="a", path="a/y.csv", bytes="3", sha256="0" * 64, url="https://y")}
    sync_data.write_manifest(rows)
    text = (tmp_path / "MANIFEST.csv").read_text()
    assert text.splitlines()[0] == "source,path,bytes,sha256,url"
    assert text.splitlines()[1].startswith("a,a/y.csv")  # sorted by path
    assert sync_data.read_manifest(text) == rows


# ---------------------------------------------------------------- check_code_guide

MODULE = '''def foo():
    return 1


def bar():
    return 2


class Thing:
    def run(self):
        return 3
'''


def guide_repo(tmp_path, monkeypatch, table):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    g = tmp_path / "docs" / "CODE_GUIDE.md"
    g.write_text("# Guide\n\n### `pkg/mod.py`\n\n| Block | Lines | Explanation |\n|---|---|---|\n" + table + "\n", encoding="utf-8")
    monkeypatch.setattr(CG, "ROOT", tmp_path)
    monkeypatch.setattr(CG, "GUIDE", g)


GOOD = ("| `foo()` | [1-2](../pkg/mod.py#L1-L2) | one |\n| `bar()` | [5-6](../pkg/mod.py#L5-L6) | two |\n"
        "| `Thing.run()` | [10-11](../pkg/mod.py#L10-L11) | method of `Thing` |")


def test_check_code_guide_passes_a_correct_guide(tmp_path, monkeypatch, capsys):
    guide_repo(tmp_path, monkeypatch, GOOD)
    assert CG.main() == 0
    assert "all links and blocks match" in capsys.readouterr().out


def test_check_code_guide_catches_a_wrong_range(tmp_path, monkeypatch, capsys):
    guide_repo(tmp_path, monkeypatch, GOOD.replace("[5-6](../pkg/mod.py#L5-L6)", "[4-6](../pkg/mod.py#L4-L6)"))
    assert CG.main() == 1
    assert "`bar` is lines 5-6 in pkg/mod.py, guide says 4-6" in capsys.readouterr().out


def test_check_code_guide_catches_a_missing_function(tmp_path, monkeypatch, capsys):
    guide_repo(tmp_path, monkeypatch, GOOD.split("\n", 1)[1])  # foo() no longer described
    assert CG.main() == 1
    out = capsys.readouterr().out
    assert "pkg/mod.py: top-level `foo` is not described in its section" in out


def test_check_code_guide_catches_bad_links(tmp_path, monkeypatch, capsys):
    guide_repo(tmp_path, monkeypatch, GOOD + "\n| `gone()` | [1-2](../pkg/mod.py#L1-L2) | x |\n"
               "| Range | [10-99](../pkg/mod.py#L10-L99) | x |\n| File | [1](../pkg/nope.py#L1) | x |")
    assert CG.main() == 1
    out = capsys.readouterr().out
    assert "`gone()` not found in pkg/mod.py" in out
    assert "pkg/mod.py#L10-L99 outside 1-11" in out
    assert "pkg/nope.py does not exist" in out


def test_check_code_guide_fix_resyncs_moved_code(tmp_path, monkeypatch, capsys):
    extra = "\n| Whole file | [1-11](../pkg/mod.py#L1-L11) | x |\n| Class body | [9-11](../pkg/mod.py#L9-L11) | x |"
    guide_repo(tmp_path, monkeypatch, GOOD + extra)
    old = MODULE.splitlines()
    moved = "import os\n\n\n" + MODULE.replace("    return 2\n", "    x = 2\n    return x\n")  # +3 lines on top, bar() +1
    (tmp_path / "pkg" / "mod.py").write_text(moved, encoding="utf-8")
    assert CG.main() == 1  # stale
    assert CG.fix(lambda rel: old) > 0
    capsys.readouterr()
    assert CG.main() == 0
    g = CG.GUIDE.read_text(encoding="utf-8")
    assert "[4-5](../pkg/mod.py#L4-L5)" in g and "[8-10](../pkg/mod.py#L8-L10)" in g  # foo, bar from the AST
    assert "[1-15](../pkg/mod.py#L1-L15)" in g  # the whole-file link follows the new length
    assert "[13-15](../pkg/mod.py#L13-L15)" in g  # a non-function block mapped through the diff
    CG.fix(lambda rel: old)  # a second run against the same old version must not shift anything again
    assert CG.GUIDE.read_text(encoding="utf-8").count("[4-5](../pkg/mod.py#L4-L5)") == 1 and CG.main() == 0


def test_real_code_guide_matches_the_code():
    assert CG.main() == 0, "docs/CODE_GUIDE.md is stale: run python scripts/check_code_guide.py"
