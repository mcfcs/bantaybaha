"""The plain-language code book: every code block of `bantay/` and `app/`, its real code, and an explain-like-I'm-five note.

Usage:
    python scripts/make_eli5.py            # docs/results/Bantay-Baha_Code_ELI5.pdf (needs Chrome or Edge)
    python scripts/make_eli5.py --no-pdf   # HTML only (docs/results/src/code_eli5.html)
    python scripts/make_eli5.py --check    # list blocks with no note, and notes whose block no longer exists

The code is read from the source files at generation time, so the PDF always shows the current code. The notes live in
docs/code_eli5/ (one markdown file per source file), one `### <key>` per block under a `## <file>` heading. A block is a top-level function, a class
header, a method (`Class.method`), or a run of top-level statements between them (keyed by the first name it assigns,
or `imports` / `script` when it assigns none). Every source line belongs to exactly one block.
"""

import argparse
import ast
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

NOTES = ROOT / "docs" / "code_eli5"  # one notes file per source file: bantay_config.md, app_ui.md, ...
OUT = ROOT / "docs" / "results"
SRC = OUT / "src"
PDF = OUT / "Bantay-Baha_Code_ELI5.pdf"


def source_files():
    """bantay/ then app/, in pipeline order (the order a reader meets them)."""
    order = ["__init__", "config", "units", "dengue", "storms", "rain", "rivers", "grids", "flood", "panel", "leadlag",
             "forecast", "access", "scenarios", "lepto"]
    lib = sorted((ROOT / "bantay").glob("*.py"), key=lambda p: order.index(p.stem) if p.stem in order else 99)
    app = sorted((ROOT / "app").glob("*.py"), key=lambda p: (p.stem != "streamlit_app", p.stem))
    return lib + app


def _assigned(stmt):
    """First name a top-level statement assigns, or None."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) else []
    for t in targets:
        if isinstance(t, ast.Name):
            return t.id
        if isinstance(t, ast.Tuple) and t.elts and isinstance(t.elts[0], ast.Name):
            return t.elts[0].id
    return None


def _start(node):
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])


def blocks(path):
    """[(key, first line, last line)] covering every line of the file once (blank lines between blocks trimmed)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    raw = []  # (key, start, end) before comment attachment
    group = []

    def flush():
        if not group:
            return
        names = [n for n in (_assigned(s) for s in group) if n]
        if names:
            key = names[0]
        elif all(is_import(s) for s in group):
            key = "imports"
        else:
            key = "script"
        raw.append((key, _start(group[0]), group[-1].end_lineno))
        group.clear()

    def is_import(s):
        return isinstance(s, (ast.Import, ast.ImportFrom)) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))

    for node in tree.body:
        if group and is_import(node) != is_import(group[-1]):  # imports and settings are separate blocks
            flush()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            flush()
            raw.append((node.name, _start(node), node.end_lineno))
        elif isinstance(node, ast.ClassDef):
            flush()
            methods = [m for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            head_end = (_start(methods[0]) - 1) if methods else node.end_lineno
            raw.append((node.name, _start(node), head_end))
            for m in methods:
                raw.append((f"{node.name}.{m.name}", _start(m), m.end_lineno))
        else:
            group.append(node)
    flush()
    # comments and blank lines before a block belong to it; make keys unique (script, script 2, ...)
    out, seen, prev_end = [], {}, 0
    for key, a, b in raw:
        a = prev_end + 1
        while a <= b and not lines[a - 1].strip():
            a += 1
        seen[key] = seen.get(key, 0) + 1
        out.append((key if seen[key] == 1 else f"{key} {seen[key]}", a, b))
        prev_end = b
    return out


def read_notes(path=NOTES):
    """{file: {"_file": intro, key: note}} from the markdown files in docs/code_eli5/ (or one markdown file)."""
    files = sorted(Path(path).glob("*.md")) if Path(path).is_dir() else [Path(path)]
    text = "
".join(f.read_text(encoding="utf-8") for f in files)
    notes, file, key = {}, None, None
    for line in text.splitlines():
        if line.startswith("## "):
            file, key = line[3:].strip().strip("`"), "_file"
            notes[file] = {"_file": ""}
        elif line.startswith("### ") and file:
            key = line[4:].strip().strip("`")
            notes[file][key] = ""
        elif file and key:
            notes[file][key] += line + "\n"
    return {f: {k: v.strip() for k, v in d.items()} for f, d in notes.items()}


def check(notes=None):
    """(missing, stale): blocks without a note, and notes without a block."""
    notes = read_notes() if notes is None else notes
    missing, stale = [], []
    for p in source_files():
        rel = p.relative_to(ROOT).as_posix()
        have = notes.get(rel, {})
        keys = [k for k, _, _ in blocks(p)]
        missing += [f"{rel} :: {k}" for k in keys if not have.get(k)]
        stale += [f"{rel} :: {k}" for k in have if k != "_file" and k not in keys]
    stale += [f"{f} (no such file)" for f in notes if not (ROOT / f).exists()]
    return missing, stale


def _md(text):
    """The little markdown the notes use: paragraphs, **bold**, `code`, and '- ' bullets."""
    out, items = [], []
    for para in re.split(r"\n\s*\n", html.escape(text, quote=False)):
        lines = para.splitlines()
        if lines and all(l.startswith("- ") for l in lines):
            out.append("<ul>" + "".join(f"<li>{l[2:]}</li>" for l in lines) + "</ul>")
        else:
            out.append(f"<p>{' '.join(lines)}</p>")
    s = "".join(out)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


CSS = """
@page { size: A4; margin: 15mm 14mm 16mm 14mm;
        @bottom-left { content: "Bantay-Baha / the code, explained simply"; font-family: "Space Mono"; font-size: 7pt; color: #6B7A88; }
        @bottom-right { content: counter(page) " / " counter(pages); font-family: "Space Mono"; font-size: 7pt; color: #6B7A88; } }
body { font-size: 9.8pt; line-height: 1.45; }
h1 { font-family: "Big Shoulders Display"; font-weight: 800; text-transform: uppercase; font-size: 36pt; line-height: .95; margin: 0 0 3mm;
     border-bottom: 3px solid var(--signal); padding-bottom: 2mm; }
h2 { font-family: "Big Shoulders Display"; font-weight: 800; font-size: 22pt; margin: 0 0 1.5mm; color: var(--ink); break-after: avoid; }
.file { break-before: page; }
.file > .intro { font-size: 10.5pt; color: #2C3A44; border-left: 4px solid var(--teal); padding: 1mm 0 1mm 3mm; margin-bottom: 4mm; }
.block { margin: 0 0 5mm; }
.bh { display: flex; justify-content: space-between; align-items: baseline; border-top: 1.5px solid var(--ink); padding-top: 1.2mm;
      break-after: avoid; }
.bh h3 { font-family: "Space Mono"; font-weight: 700; font-size: 10.5pt; margin: 0; color: var(--teal); }
.bh span { font-family: "Space Mono"; font-size: 7.5pt; color: var(--grey); }
.eli5 { background: #FFF7EA; border-left: 4px solid var(--signal); padding: 1.5mm 3mm; margin: 1.5mm 0 2mm; break-after: avoid; }
.eli5 p, .eli5 li { margin: 0 0 1.2mm; } .eli5 ul { margin: 0; padding-left: 5mm; }
.eli5 code, .intro code, p code { font-family: "Space Mono"; font-size: 8pt; background: rgba(15,30,40,.06); padding: 0 .8mm; }
pre { font-family: "Space Mono"; font-size: 7.1pt; line-height: 1.38; background: #F4F7F9; border: 1px solid var(--rule);
      padding: 2mm 2.5mm; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
pre .ln { color: #9AA8B3; user-select: none; display: inline-block; width: 8mm; }
.toc { columns: 2; column-gap: 8mm; font-size: 9.5pt; } .toc p { margin: 0 0 1mm; } .toc a { color: var(--teal); text-decoration: none; }
.how { background: var(--mist); padding: 3mm 4mm; margin: 3mm 0 5mm; }
"""


def highlight(code, first_line):
    """Syntax-highlighted code with real file line numbers."""
    from pygments import highlight as hl
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import PythonLexer

    body = hl(code, PythonLexer(), HtmlFormatter(nowrap=True, style="friendly"))
    rows = body.split("\n")
    if rows and rows[-1] == "":
        rows = rows[:-1]
    return "<pre>" + "\n".join(f"<span class='ln'>{first_line + i}</span>{r}" for i, r in enumerate(rows)) + "</pre>"


def page_html(notes=None):
    from pygments.formatters import HtmlFormatter

    from make_results import FONT_CSS

    notes = read_notes() if notes is None else notes
    files, toc = [], []
    for p in source_files():
        rel = p.relative_to(ROOT).as_posix()
        lines = p.read_text(encoding="utf-8").splitlines()
        fn = notes.get(rel, {})
        anchor = re.sub(r"[^a-z0-9]+", "-", rel.lower())
        toc.append(f"<p><a href='#{anchor}'>{rel}</a> <span style='color:#6B7A88'>({len(lines)} lines)</span></p>")
        parts = [f"<section class='file' id='{anchor}'><h2>{rel}</h2><div class='intro'>{_md(fn.get('_file', ''))}</div>"]
        for key, a, b in blocks(p):
            note = fn.get(key) or "<i>No note yet: run <code>python scripts/make_eli5.py --check</code>.</i>"
            note_html = _md(note) if fn.get(key) else f"<p>{note}</p>"
            parts.append(f"<div class='block'><div class='bh'><h3>{html.escape(key)}</h3><span>lines {a}-{b}</span></div>"
                         f"<div class='eli5'>{note_html}</div>{highlight(chr(10).join(lines[a - 1:b]), a)}</div>")
        files.append("".join(parts) + "</section>")
    intro = (f"<h1>The code, explained simply</h1>"
             f"<div class='how'><p><b>How to read this.</b> Every piece of the <code>bantay</code> library (the pipeline that turns raw data "
             f"into forecasts, maps and rankings) and of the dashboard in <code>app/</code>, in the order the pipeline uses them. Each piece has a "
             f"yellow note that explains it in plain words, like you would to someone who has never coded, and then the actual code with its "
             f"real line numbers. The code is copied from the files when this PDF is made, so it is always the current code.</p>"
             f"<p>The data-download scripts, the build script, the benchmarks, the document generators and the tests are not in this book; "
             f"the full code guide covers them.</p></div>"
             f"<h2 style='font-size:16pt'>Files</h2><div class='toc'>{''.join(toc)}</div>")
    css = FONT_CSS + CSS + HtmlFormatter(style="friendly").get_style_defs("pre")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Bantay-Baha: the code, explained simply</title><style>{css}</style></head><body>{intro}{''.join(files)}</body></html>"


def main(pdf=True):
    missing, stale = check()
    if missing or stale:
        print(f"  WARNING notes: {len(missing)} blocks without a note, {len(stale)} notes without a block (--check lists them)")
    SRC.mkdir(parents=True, exist_ok=True)
    page = SRC / "code_eli5.html"
    page.write_text(page_html(), encoding="utf-8")
    print(f"  wrote {page.relative_to(ROOT)}")
    if pdf:
        from make_results import to_pdf

        to_pdf(page, PDF)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        missing, stale = check()
        for m in missing:
            print("missing:", m)
        for s in stale:
            print("stale:  ", s)
        print(f"{len(missing)} missing, {len(stale)} stale")
        sys.exit(1 if missing or stale else 0)
    main(pdf=not a.no_pdf)
