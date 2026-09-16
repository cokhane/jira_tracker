#!/usr/bin/env python3
"""Render master.md (the resume Markdown subset) into an ATS-safe PDF.

Markdown -> single-column HTML -> PDF via headless Chrome. No pip installs and
no LaTeX; Chrome is already on this machine and its PDFs keep a real, selectable
text layer, which is the one thing applicant tracking systems actually need.

    python3 render_resume.py master.md                       # -> master.pdf
    python3 render_resume.py master.md -o out/resume.pdf --density compact
    python3 render_resume.py master.md --final               # refuse leftover TODOs
    python3 render_resume.py master.md --html-only           # inspect the HTML

Recognised Markdown (see reference/master-format.md for the full spec):
    # Name                      h1, once, first line
    **Target Title**            tagline, immediately after the name
    a | b | c                   contact line(s), before the first section
    ## SECTION                  section heading + rule
    ### Company - Title         entry heading; a following *italic* line is the
                                date and is right-aligned onto the heading row
    #### Project - blurb        sub-entry; a following *italic* line is its meta
    **Label:** value            definition row (skills)
    - bullet                    list item
    [[TODO: ...]]               unresolved fact — flagged in the PDF, blocks --final
"""

import argparse
import html as html_mod
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

# pt sizes and vertical rhythm per density preset. Length is the main lever you
# have on a resume, so this is exposed rather than hard-coded.
DENSITY = {
    "compact": {"base": 9.6, "name": 21, "gap": 0.30, "sec": 0.62, "lh": 1.30},
    "normal":  {"base": 10.4, "name": 23, "gap": 0.40, "sec": 0.78, "lh": 1.38},
    "roomy":   {"base": 11.2, "name": 25, "gap": 0.52, "sec": 0.95, "lh": 1.46},
}

TODO_RE = re.compile(r"\[\[\s*TODO:(.+?)\]\]", re.DOTALL)


# ---------------------------------------------------------------- inline spans

def inline(text: str) -> str:
    """Escape, then apply the inline subset. Escaping first keeps `<` literal."""
    out = html_mod.escape(text.strip())
    out = TODO_RE.sub(
        lambda m: f'<span class="todo">TODO:{html_mod.escape(m.group(1).strip())}</span>',
        out,
    )
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    return out


def is_italic_line(line: str) -> bool:
    s = line.strip()
    return len(s) > 2 and s.startswith("*") and s.endswith("*") and not s.startswith("**")


def strip_italic(line: str) -> str:
    return line.strip()[1:-1].strip()


def split_heading(text: str):
    """'Company - Title' -> ('Company', 'Title'). Accepts -, --, em/en dash, |."""
    for sep in (" — ", " – ", " -- ", " | ", " - "):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    return text.strip(), ""


# ------------------------------------------------------------------ block pass

def parse(md: str) -> dict:
    """Walk the lines once, emitting HTML fragments plus the header metadata."""
    lines = md.replace("\r\n", "\n").split("\n")
    doc = {"name": "", "tagline": "", "contact": [], "body": []}
    body, bullets = doc["body"], []
    i, seen_section = 0, False

    def flush() -> None:
        if bullets:
            body.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    def next_meta(idx: int):
        """Return (meta_text, new_idx) if the next non-blank line is fully italic."""
        j = idx
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and is_italic_line(lines[j]):
            return strip_italic(lines[j]), j + 1
        return None, idx

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("<!--"):                      # comment / editor note
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        if stripped.startswith("# ") and not doc["name"]:
            doc["name"] = inline(stripped[2:])
            i += 1
            continue

        if stripped.startswith("## "):
            flush()
            seen_section = True
            body.append(f'<h2>{inline(stripped[3:])}</h2>')
            i += 1
            continue

        if stripped.startswith("#### "):
            flush()
            left, right = split_heading(stripped[5:])
            tail = f' <span class="blurb">— {inline(right)}</span>' if right else ""
            body.append(f'<h4>{inline(left)}{tail}</h4>')
            meta, i = next_meta(i + 1)
            if meta:
                body.append(f'<p class="meta">{inline(meta)}</p>')
            continue

        if stripped.startswith("### "):
            flush()
            left, right = split_heading(stripped[4:])
            role = f'<span class="role">{inline(right)}</span>' if right else ""
            date, i = next_meta(i + 1)
            date_html = f'<span class="date">{inline(date)}</span>' if date else ""
            body.append(
                '<div class="entry"><h3>'
                f'<span class="who"><span class="org">{inline(left)}</span>{role}</span>'
                f"{date_html}</h3></div>"
            )
            continue

        if stripped.startswith(("- ", "* ", "• ")):
            bullets.append(inline(stripped[2:]))
            i += 1
            continue

        # **Label:** value  — skills rows, and one-line early-career entries
        m = re.match(r"^\*\*(.+?)\*\*(:?)\s*(.*)$", stripped)
        if m and m.group(3) and seen_section:
            flush()
            label = m.group(1).rstrip(":")
            # Keep a colon only where the source had one, so '**COMPANY — Role** ...'
            # does not silently acquire punctuation it never had.
            colon = ":" if (m.group(1).endswith(":") or m.group(2)) else ""
            body.append(
                f'<p class="kv"><strong>{inline(label)}{colon}</strong> {inline(m.group(3))}</p>'
            )
            i += 1
            continue

        # Pre-section lines belong to the header: tagline first, then contact.
        if not seen_section and doc["name"]:
            if not doc["tagline"] and stripped.startswith("**"):
                doc["tagline"] = inline(stripped.strip("*"))
            else:
                doc["contact"].append(inline(stripped))
            i += 1
            continue

        flush()
        # A standalone italic line anywhere is a meta line (stack, context, dates).
        cls = ' class="meta"' if is_italic_line(stripped) else ""
        body.append(f"<p{cls}>{inline(stripped)}</p>")
        i += 1

    flush()
    return doc


# ------------------------------------------------------------------- rendering

def build_html(doc: dict, d: dict, title: str) -> str:
    contact = ""
    if doc["contact"]:
        rows = "".join(f'<div class="contact">{c}</div>' for c in doc["contact"])
        contact = rows
    tagline = f'<div class="tagline">{doc["tagline"]}</div>' if doc["tagline"] else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html_mod.escape(title)}</title>
<style>
  @page {{ size: Letter; margin: 0.5in 0.55in; }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{
    margin: 0;
    font-family: Calibri, Carlito, "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: {d['base']}pt;
    line-height: {d['lh']};
    color: #14181f;
  }}
  header {{ text-align: center; margin-bottom: {d['sec']}em; }}
  h1 {{
    font-size: {d['name']}pt; line-height: 1.1; margin: 0 0 .10em;
    letter-spacing: .035em; font-weight: 700; text-transform: uppercase;
  }}
  .tagline {{ font-size: {d['base'] + 1.1}pt; font-weight: 600; color: #2d4a7c; margin-bottom: .30em; }}
  .contact {{ font-size: {d['base'] - 0.7}pt; color: #333a44; }}
  .contact a {{ color: #2d4a7c; text-decoration: none; }}
  h2 {{
    font-size: {d['base'] + 0.6}pt; text-transform: uppercase; letter-spacing: .10em;
    font-weight: 700; color: #1b2a44;
    margin: {d['sec']}em 0 .34em; padding-bottom: .14em;
    border-bottom: 1.1pt solid #1b2a44;
  }}
  h2:first-of-type {{ margin-top: 0; }}
  .entry {{ margin-top: {d['gap'] + 0.16}em; break-inside: avoid; }}
  h3 {{
    font-size: {d['base'] + 0.3}pt; font-weight: 700; margin: 0;
    display: flex; justify-content: space-between; align-items: baseline; gap: 1em;
  }}
  .org {{ text-transform: uppercase; letter-spacing: .02em; }}
  .role {{ font-weight: 600; color: #2d4a7c; }}
  .role::before {{ content: " — "; color: #6b7480; font-weight: 400; }}
  .date {{ font-weight: 600; font-size: {d['base'] - 0.7}pt; color: #4a525e; white-space: nowrap; }}
  h4 {{
    font-size: {d['base']}pt; font-weight: 600; margin: {d['gap'] + 0.10}em 0 .06em;
    break-after: avoid;
  }}
  .blurb {{ font-weight: 400; color: #4a525e; }}
  .meta {{
    font-size: {d['base'] - 0.9}pt; color: #4a525e; font-style: italic;
    margin: 0 0 .12em;
  }}
  p {{ margin: 0 0 {d['gap']}em; }}
  .kv {{ margin: 0 0 .22em; }}
  ul {{ margin: .10em 0 {d['gap']}em; padding-left: 1.05em; }}
  li {{ margin-bottom: .12em; break-inside: avoid; }}
  li::marker {{ color: #6b7480; }}
  code {{ font-family: Consolas, Menlo, monospace; font-size: .92em; }}
  a {{ color: inherit; }}
  .todo {{
    background: #ffe9a8; color: #7a4b00; font-weight: 700;
    padding: 0 .22em; border-radius: 2px;
  }}
</style></head>
<body>
<header><h1>{doc['name']}</h1>{tagline}{contact}</header>
{chr(10).join(doc['body'])}
</body></html>"""


def find_chrome() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    sys.exit("error: no Chrome/Chromium/Edge found — install one, or rerun with "
             "--html-only and print the HTML to PDF from your browser.")


def page_count(pdf: Path):
    """Chrome leaves the page tree uncompressed, so counting /Type /Page works."""
    try:
        blob = pdf.read_bytes()
    except OSError:
        return None
    n = len(re.findall(rb"/Type\s*/Page(?![s/\w])", blob))
    return n or None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="resume Markdown (master.md)")
    ap.add_argument("-o", "--out", type=Path, help="output PDF (default: <source>.pdf)")
    ap.add_argument("--density", choices=sorted(DENSITY), default="normal",
                    help="type size and spacing — the length lever (default: normal)")
    ap.add_argument("--final", action="store_true",
                    help="refuse to render while [[TODO: ...]] markers remain")
    ap.add_argument("--html-only", action="store_true", help="write the HTML, skip the PDF")
    ap.add_argument("--timeout", type=int, default=45,
                    help="seconds to wait on Chrome for the PDF (default: 45)")
    args = ap.parse_args()

    src = args.source.expanduser()
    if not src.is_file():
        sys.exit(f"error: no such file: {src}")
    md = src.read_text(encoding="utf-8")

    todos = [t.strip() for t in TODO_RE.findall(md)]
    if todos and args.final:
        listing = "\n".join(f"  - {t}" for t in todos)
        sys.exit(f"error: --final blocked by {len(todos)} unresolved TODO(s):\n{listing}")

    doc = parse(md)
    if not doc["name"]:
        sys.exit("error: no '# Name' heading found — see reference/master-format.md")

    out_pdf = (args.out.expanduser() if args.out else src.with_suffix(".pdf"))
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    # Chrome is handed a file:// URI, which requires an absolute path — a relative
    # -o would otherwise blow up in Path.as_uri().
    out_pdf = out_pdf.resolve()
    html_doc = build_html(doc, DENSITY[args.density], out_pdf.stem)

    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html_doc, encoding="utf-8")

    if args.html_only:
        print(f"HTML : {html_path}")
        return

    if out_pdf.exists():
        out_pdf.unlink()          # so a stale PDF can't be mistaken for a fresh render

    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--user-data-dir={profile}", "--no-pdf-header-footer",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-sync", "--disable-crash-reporter",
            "--virtual-time-budget=4000",
            f"--print-to-pdf={out_pdf}", html_path.as_uri(),
        ]
        # Headless Chrome reliably writes the PDF but does not reliably exit, so we
        # poll for the file, wait for its size to settle, then stop the process
        # ourselves. The PDF on disk is the verdict, never the exit code.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline, size, settled = time.monotonic() + args.timeout, -1, 0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if out_pdf.exists():
                now = out_pdf.stat().st_size
                settled = settled + 1 if now == size and now > 0 else 0
                size = now
                if settled >= 3:            # ~0.6s of no growth = finished writing
                    break
            time.sleep(0.2)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        stderr = (proc.stderr.read() or b"").decode("utf-8", "replace") if proc.stderr else ""

    if not out_pdf.exists():
        sys.exit(f"error: Chrome produced no PDF within {args.timeout}s.\n{stderr.strip()[:800]}")

    pages = page_count(out_pdf)
    print(f"PDF   : {out_pdf}")
    print(f"HTML  : {html_path}")
    print(f"Pages : {pages if pages else 'unknown'}   (density={args.density})")
    if pages and pages > 2:
        print(f"NOTE  : {pages} pages. Try --density compact, or cut the oldest roles "
              "to one line each.")
    if todos:
        print(f"TODO  : {len(todos)} unresolved marker(s) — highlighted in the PDF:")
        for t in todos:
            print(f"        - {t}")


if __name__ == "__main__":
    main()
