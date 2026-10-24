"""Check docs/CODE_GUIDE.md against the code, so the guide cannot silently go stale.

Usage:
    python scripts/check_code_guide.py          # exit 1 and list every problem

Checks every link of the form [12-30](../path/file.py#L12-L30) (or #L12):
  - the file exists and the line range lies inside it;
  - in a block table (Block | Lines | Explanation), when the Block cell names exactly one Python function, method or
    class (`fetch()`, `AccessModel`, `AccessModel.run()`), the range starts at its `def`/`class` line (or decorator)
    and ends at its last line;
  - every top-level function and class of a Python file that has its own section is mentioned in that section.
"""

import ast
import re
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


if __name__ == "__main__":
    sys.exit(main())
