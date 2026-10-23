"""Render the revised concept proposal (docs/proposal/Bantay-Baha_Proposal_v3.html) to PDF with headless Chrome or Edge.

Usage:
    python scripts/make_proposal.py            # -> docs/proposal/Bantay-Baha_Proposal_v3.pdf
    python scripts/make_proposal.py --no-pdf   # word counts only

The HTML is the editable source. Each <span class="wc" data-for="ID" [data-limit="N"]> is filled with the word count of the
<div class="body" id="ID"> it names (headings excluded), and the script stops if a section is over its limit (the executive
summary: 250 words). The reference count fills <span class="wc" data-refs="1">. The original PDFs in docs/ are not touched.
"""

import argparse
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "proposal" / "Bantay-Baha_Proposal_v3.html"
PDF = SRC.with_suffix(".pdf")


def browser():
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              shutil.which("chrome"), shutil.which("chromium"), shutil.which("msedge")):
        if p and Path(p).exists():
            return p
    return None


def words(fragment):
    text = html.unescape(re.sub(r"<h3>.*?</h3>", " ", fragment, flags=re.S))
    text = re.sub(r"<[^>]+>", " ", text)
    return len(re.findall(r"[A-Za-z0-9][\w'’.,%()/&+-]*", text))


def fill_counts(doc):
    """Replace every word-count span with the count of its section; returns (html, {id: (n, limit)})."""
    counts = {}
    body = re.sub(r"<!--.*?-->", "", doc, flags=re.S)
    for m in re.finditer(r'<div class="body" id="(\w+)">(.*?)</div>\s*(?=<h2|$)', body, flags=re.S):
        counts[m.group(1)] = words(m.group(2))

    def span(m):
        attrs = dict(re.findall(r'data-(\w+)="([^"]*)"', m.group(1)))
        if "refs" in attrs:
            n = len(re.findall(r"<p>", doc.split('<div class="refs">', 1)[1].split("</div>", 1)[0]))
            return f'<span class="wc">{n} references, APA 7th edition, alphabetical.</span>'
        sec = attrs["for"]
        n = counts[sec]
        lim = attrs.get("limit")
        lims[sec] = (n, int(lim) if lim else None)
        return f'<span class="wc">{n} words{f" (limit {lim})" if lim else ""}</span>'

    lims = {}
    doc = re.sub(r'<span class="wc"([^>]*)></span>', span, doc)
    return doc, lims


def main(pdf=True):
    doc, lims = fill_counts(SRC.read_text(encoding="utf-8"))
    for sec, (n, lim) in lims.items():
        print(f"  {sec:<11} {n:>4} words" + (f" (limit {lim})" if lim else ""))
    over = [s for s, (n, lim) in lims.items() if lim and n > lim]
    if over:
        sys.exit(f"  over the word limit: {', '.join(over)}")
    if not pdf:
        return
    exe = browser()
    if exe is None:
        sys.exit("  no Chrome / Edge found: PDF not written")
    tmp = SRC.with_name("_render_tmp.html")
    tmp.write_text(doc, encoding="utf-8")
    try:
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=5000",
                        f"--print-to-pdf={PDF}", tmp.resolve().as_uri()], check=True, capture_output=True)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"  wrote {PDF.relative_to(ROOT)} ({PDF.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pdf", action="store_true")
    main(pdf=not ap.parse_args().no_pdf)
