#!/usr/bin/env python3
"""Extract plain text from a resume file so it can be normalised into master.md.

Handles .docx, .md, .txt, .rtf, .html — stdlib only, no pip installs.

PDFs are deliberately NOT handled here: Claude Code's Read tool parses PDF pages
natively and far better than any regex would. For a .pdf source, skip this script
and read the file with the Read tool instead.

    python3 extract_text.py <file> [-o out.txt]
"""

import argparse
import html
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def _squeeze(text: str) -> str:
    """Trim trailing spaces and collapse runs of blank lines down to one."""
    out, blank = [], False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.strip():
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def from_docx(path: Path) -> str:
    """Pull the text layer out of word/document.xml.

    Paragraphs and <w:br/> become newlines, <w:tab/> becomes a tab, every other
    tag is dropped. Bullet glyphs live in numbering.xml (not the text), so list
    items arrive as bare lines — the caller re-marks them as '- ' in master.md.
    """
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"<w:tab\b[^>]*/?>", "\t", xml)
    xml = re.sub(r"<w:br\b[^>]*/?>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    return _squeeze(html.unescape(re.sub(r"<[^>]+>", "", xml)))


def from_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    raw = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr)\b[^>]*>", "\n", raw)
    return _squeeze(html.unescape(re.sub(r"<[^>]+>", "", raw)))


def from_rtf(path: Path) -> str:
    """macOS ships textutil, which reads RTF properly. No stdlib RTF parser exists."""
    try:
        done = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"error: cannot read {path.name} — textutil failed ({exc})")
    return _squeeze(done.stdout)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="resume file (.docx/.md/.txt/.rtf/.html)")
    ap.add_argument("-o", "--out", type=Path, help="write here instead of stdout")
    args = ap.parse_args()

    src = args.source.expanduser()
    if not src.is_file():
        sys.exit(f"error: no such file: {src}")

    suffix = src.suffix.lower()
    if suffix == ".pdf":
        sys.exit("error: PDF source — read it with Claude Code's Read tool "
                 "(pages parameter), not this script.")

    readers = {
        ".docx": from_docx,
        ".rtf": from_rtf,
        ".html": from_html, ".htm": from_html,
        ".md": lambda p: _squeeze(p.read_text(encoding="utf-8", errors="replace")),
        ".txt": lambda p: _squeeze(p.read_text(encoding="utf-8", errors="replace")),
    }
    if suffix not in readers:
        sys.exit(f"error: unsupported format '{suffix}'. "
                 f"Supported: {', '.join(sorted(readers))} (PDF → use the Read tool).")

    text = readers[suffix](src)
    if args.out:
        args.out.expanduser().write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
