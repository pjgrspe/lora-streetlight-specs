"""Export each spec in specs/ to pdf/ with a sign-off page.

Usage:
    python tools/build_pdf.py              # all specs
    python tools/build_pdf.py 03 05        # only specs starting with these numbers

Needs the `markdown` package and an installed Chrome or Edge (used headless to print).
"""
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
OUT = ROOT / "pdf"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

# Who signs each spec (see README).
SIGNERS = {
    "00": ["Gateway hardware developer (for the client)", "Device developer", "pgorospe"],
    "01": ["Gateway hardware developer (for the client)", "pgorospe"],
    "02": ["Gateway hardware developer (for the client)", "pgorospe"],
    "03": ["Device developer", "Gateway hardware developer (for the client)", "pgorospe"],
    "04": ["Gateway hardware developer (for the client)", "pgorospe"],
    "05": ["Gateway hardware developer (for the client)", "Device developer", "pgorospe"],
    "06": ["Gateway hardware developer", "pgorospe"],
    "07": ["Gateway hardware developer (for the client)", "pgorospe"],
}

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 18pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; color: #1f4e79; }
h2 { font-size: 13pt; color: #1f4e79; margin-top: 18pt; page-break-after: avoid; }
h3 { font-size: 11pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #b7c4d1; padding: 3px 5px; vertical-align: top; text-align: left; overflow-wrap: break-word; }
table.wide { font-size: 6.8pt; table-layout: fixed; }
table.wide td, table.wide th { overflow-wrap: anywhere; }
table.wide code { font-size: 6.5pt; }
table.wide th, table.wide td { padding: 2px 3px; }
th { background: #e8eef5; }
table:first-of-type thead { display: none; }   /* the spec's metadata table has an empty header row */
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f3f5f8; padding: 0 2px; }
pre { background: #f3f5f8; border: 1px solid #d9e0e8; padding: 6px 8px; font-size: 8.3pt; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
.signoff { page-break-before: always; }
.signoff td { height: 34pt; }
.footer-note { color: #666; font-size: 8pt; margin-top: 16pt; }
"""


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    sys.exit("No Chrome or Edge found. Edit BROWSERS in tools/build_pdf.py.")


def git_describe() -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "untracked"


def signoff_html(num: str, title: str, version: str) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(who)}</td><td></td><td></td><td></td></tr>"
        for who in SIGNERS.get(num, ["pgorospe"])
    )
    return f"""
<div class="signoff">
<h2>Sign-off</h2>
<p>By signing, each party confirms it has reviewed <b>{html.escape(title)}</b>, version <b>{html.escape(version)}</b>,
and accepts it as the agreed specification. Changes after sign-off follow the change-request process in the README.</p>
<table>
<tr><th style="width:28%">Party</th><th style="width:28%">Name</th><th style="width:28%">Signature</th><th>Date</th></tr>
{rows}
</table>
</div>"""


def mark_wide_tables(body: str) -> str:
    """Give tables with many columns a smaller font so they fit the page width."""
    def tag(m: re.Match) -> str:
        header = re.search(r"<tr>(.*?)</tr>", m.group(0), re.S)
        cols = header.group(1).count("<th") if header else 0
        return m.group(0).replace("<table>", '<table class="wide">', 1) if cols >= 7 else m.group(0)
    return re.sub(r"<table>.*?</table>", tag, body, flags=re.S)


def build(md_path: Path, browser: str, rev: str) -> Path:
    text = md_path.read_text(encoding="utf-8")
    num = md_path.name[:2]
    title = text.splitlines()[0].lstrip("# ").strip()
    m = re.search(r"\|\s*\*\*Version\*\*\s*\|\s*([^|]+)\|", text)
    version = m.group(1).strip() if m else "draft"
    # Links between specs point at .md files; in the PDFs they should point at the PDFs.
    text = re.sub(r"\]\((\d\d-[\w-]+)\.md\)", r"](\1.pdf)", text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    body = mark_wide_tables(body)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>{body}
<p class="footer-note">Source: lora-streetlight-specs @ {html.escape(rev)} · {html.escape(md_path.name)}</p>
{signoff_html(num, title, version)}</body></html>"""
    OUT.mkdir(exist_ok=True)
    pdf = OUT / (md_path.stem + ".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "page.html"
        page_path.write_text(page, encoding="utf-8")
        subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf}", page_path.as_uri()],
            check=True, capture_output=True,
        )
    return pdf


def main() -> None:
    wanted = sys.argv[1:]
    browser = find_browser()
    rev = git_describe()
    for md_path in sorted(SPECS.glob("[0-9][0-9]-*.md")):
        if wanted and md_path.name[:2] not in wanted:
            continue
        print("built", build(md_path, browser, rev).relative_to(ROOT))


if __name__ == "__main__":
    main()
