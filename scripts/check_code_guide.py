"""Check docs/CODE_GUIDE.md against the code, so the guide cannot silently go stale.

Usage:
    python scripts/check_code_guide.py          # exit 1 and list every problem
    python scripts/check_code_guide.py --fix    # after moving code: re-sync the line links, then check
    python scripts/check_code_guide.py --fix main   # ... against another revision than HEAD
(run --fix once per change, against the revision where the guide was last correct: non-function rows are mapped
through a diff, so a second run against the same old version would shift them again)

Checks every link of the form [12-30](../path/file.py#L12-L30) (or #L12):
  - the file exists and the line range lies inside it;
  - in a block table (Block | Lines | Explanation), when the Block cell names exactly one Python function, method or
    class (`fetch()`, `AccessModel`, `AccessModel.run()`), the range starts at its `def`/`class` line (or decorator)
    and ends at its last line;
  - every top-level function and class of a Python file that has its own section is mentioned in that section.
"""

import ast
import difflib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "CODE_GUIDE.md"
LINK = re.compile(r"\[[^\]]*\]\(\.\./([^)#]+)#L(\d+)(?:-L(\d+))?\)")
SECTION = re.compile(r"^#{2,4} .*?`([^`]+\.(?:py|bat|toml))`")
NAME = re.compile(r"^`([A-Za-z_][\w.]*)(\(\))?`$")


def spans(path):
    """{qualified name: (first line incl. decorators, last line)} for functions, methods and classes."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out, top = {}, set()

    def visit(node, prefix=""):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([n.lineno] + [d.lineno for d in n.decorator_list])
                out[prefix + n.name] = (start, n.end_lineno)
                if not prefix:
                    top.add(n.name)
                if isinstance(n, ast.ClassDef):
                    visit(n, prefix + n.name + ".")

    visit(tree)
    return out, top


def main():
    text = GUIDE.read_text(encoding="utf-8")
    problems, section, mentioned = [], None, {}
    cache = {}
    for i, line in enumerate(text.splitlines(), 1):
        m = SECTION.match(line)
        if m:
            section = m.group(1)
            mentioned.setdefault(section, set())
        elif line.startswith("#"):
            section = None  # a heading without a file ends the previous file's section
        if section and section.endswith(".py"):
            mentioned[section] |= set(re.findall(r"`([A-Za-z_][\w]*)(?:\(\))?`", line))
        for f, a, b in LINK.findall(line):
            p = ROOT / f
            a, b = int(a), int(b or a)
            if not p.exists():
                problems.append(f"line {i}: {f} does not exist")
                continue
            n_lines = len(p.read_text(encoding="utf-8").splitlines())
            if not 1 <= a <= b <= n_lines:
                problems.append(f"line {i}: {f}#L{a}-L{b} outside 1-{n_lines}")
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if p.suffix == ".py" and len(cells) >= 3 and LINK.search(cells[1]):
                nm = NAME.match(cells[0])
                if nm:
                    if p not in cache:
                        cache[p] = spans(p)
                    sp, _ = cache[p]
                    key = nm.group(1)
                    if key in sp and sp[key] != (a, b):
                        problems.append(f"line {i}: `{key}` is lines {sp[key][0]}-{sp[key][1]} in {f}, guide says {a}-{b}")
                    elif key not in sp and nm.group(2):
                        problems.append(f"line {i}: `{key}()` not found in {f}")
    for f, names in mentioned.items():
        p = ROOT / f
        if p.suffix == ".py" and p.exists():
            _, top = spans(p)
            for name in sorted(top - names):
                problems.append(f"{f}: top-level `{name}` is not described in its section")
    for f in sorted({m for m in mentioned if not (ROOT / m).exists()}):
        problems.append(f"section for {f}, which does not exist")
    print("\n".join(problems) if problems else f"{GUIDE.relative_to(ROOT)}: all links and blocks match the code")
    return 1 if problems else 0


def _line_map(old, new):
    """1-based old line -> (first, last) new line it now corresponds to (a deleted line maps to its neighbourhood)."""
    m = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for i in range(i1, i2):
            if tag == "equal":
                m[i + 1] = (j1 + i - i1 + 1, j1 + i - i1 + 1)
            else:  # replaced / deleted: the start maps to the block's start, the end to its end
                m[i + 1] = (j1 + 1, max(j1 + 1, j2))
    return m


def _git_old(rev):
    def old(rel):
        r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        return r.stdout.splitlines() if r.returncode == 0 else None
    return old


def fix(old_lines=None):
    """Re-sync every line link after code moved: function rows take their range from the AST, whole-file links follow the
    file's length, other ranges are mapped line by line through a diff of the old file (old_lines(rel) -> lines, default
    git HEAD) against the current one. Returns the number of links changed."""
    old_lines = old_lines or _git_old("HEAD")
    cache, maps, changed, out = {}, {}, 0, []
    for line in GUIDE.read_text(encoding="utf-8").splitlines(keepends=True):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        nm = NAME.match(cells[0]) if len(cells) >= 3 and LINK.search(cells[1]) else None

        def sub(m):
            nonlocal changed
            f, a, b = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
            p = ROOT / f
            if not p.exists():
                return m.group(0)
            new = p.read_text(encoding="utf-8").splitlines()
            if f not in maps:
                old = old_lines(f)
                maps[f] = (len(old), _line_map(old, new)) if old is not None else None
            na, nb, by_ast = a, b, False
            if p.suffix == ".py" and nm:
                if p not in cache:
                    cache[p] = spans(p)[0]
                if nm.group(1) in cache[p]:
                    (na, nb), by_ast = cache[p][nm.group(1)], True  # authoritative: never also diff-mapped
            if not by_ast and maps[f]:
                n_old, mp = maps[f]
                if a == 1 and b == n_old:
                    na, nb = 1, len(new)  # a link to the whole file
                elif a in mp and b in mp:
                    na, nb = mp[a][0], max(mp[a][0], mp[b][1])
            if (na, nb) == (a, b):
                return m.group(0)
            changed += 1
            txt = m.group(0)
            txt = txt.replace(f"#L{a}-L{b}" if m.group(3) else f"#L{a}", f"#L{na}-L{nb}" if m.group(3) or na != nb else f"#L{na}")
            return txt.replace(f"[{a}-{b}]", f"[{na}-{nb}]") if m.group(3) else txt.replace(f"[{a}]", f"[{na}]" if na == nb else f"[{na}-{nb}]")

        out.append(LINK.sub(sub, line))
    GUIDE.write_text("".join(out), encoding="utf-8")
    return changed


if __name__ == "__main__":
    if "--fix" in sys.argv:
        args = sys.argv[sys.argv.index("--fix") + 1:]
        print(f"{fix(_git_old(args[0]) if args else None)} links re-synced")
    sys.exit(main())
