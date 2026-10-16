"""Build the branded PDF for one or more example guides.

    pip install -r tools/pdf/requirements.txt
    python tools/pdf/build.py examples/*/guide.md

Each ``guide.md`` (with a small front-matter block: title, subtitle,
category) becomes ``guide.pdf`` beside it. Images referenced by the guide are
inlined, so the PDF is self-contained. Rendering uses Playwright: it drives
an installed Google Chrome when there is one, else Playwright's own Chromium
(``python -m playwright install chromium``).
"""
from __future__ import annotations

import base64
import html
import mimetypes
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOGO = ROOT / "brand" / "behavry-horizontal-onwhite.svg"

# Repeated on every page by the PDF engine, with the page number.
FOOTER = (
    '<div style="width:100%;margin:0 0.75in;padding-top:5pt;border-top:1px solid #E3E6EB;'
    'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,system-ui,sans-serif;font-size:7.5pt;'
    'color:#5B6577;display:flex;justify-content:space-between;">'
    '<span><b style="color:#1B2A4A">Behavry</b> &middot; the system of record for autonomous agents'
    ' &middot; behavry.ai</span><span class="pageNumber"></span></div>'
)
CLOSING = (
    '<div class="closing"><strong>About Behavry.</strong> Behavry is the independent, signed record '
    "of what AI agents did across every system they touched. It binds every action to an identity, "
    "reconstructs the sequence into a signed Decision Trace, and, because it sits in the path, can "
    "permit, redact, hold or block an action against policy. Learn more at "
    '<a href="https://behavry.ai">behavry.ai</a>.</div>'
)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        for line in head.splitlines():
            key, _, value = line.partition(":")
            if key.strip():
                meta[key.strip()] = value.strip()
        return meta, body
    return meta, text


def inline_images(body_html: str, base: Path) -> str:
    def repl(m: re.Match[str]) -> str:
        src = m.group(2)
        if re.match(r"^(https?:|data:)", src):
            return m.group(0)
        path = (base / src).resolve()
        if path.suffix == ".svg":
            # Inline SVG keeps text sharp and selectable in the PDF.
            svg = path.read_text()
            return f'<figure class="svg">{svg}</figure>'
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode()
        return f'{m.group(1)}data:{mime};base64,{data}{m.group(3)}'

    return re.sub(r'(<img[^>]*?src=")([^"]+)("[^>]*>)', repl, body_html)


def render_html(guide: Path) -> str:
    meta, body = split_front_matter(guide.read_text())
    body_html = markdown.markdown(body, extensions=["tables", "sane_lists"])
    body_html = inline_images(body_html, guide.parent)
    title = html.escape(meta.get("title", guide.parent.name))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} | Behavry</title>
<style>{(HERE / "style.css").read_text()}</style></head>
<body>
<header class="cover">
  <div class="logo">{LOGO.read_text()}</div>
  <div class="eyebrow">Behavry example &middot; {html.escape(meta.get("category", "Agent governance"))}</div>
  <h1>{title}</h1>
  <p class="subtitle">{html.escape(meta.get("subtitle", ""))}</p>
</header>
{body_html}
{CLOSING}
</body></html>"""


def build(paths: list[Path]) -> None:
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome")
        except Error:
            browser = pw.chromium.launch()
        page = browser.new_page()
        for guide in paths:
            out = guide.with_suffix(".pdf")
            page.set_content(render_html(guide), wait_until="load")
            page.pdf(
                path=str(out), format="Letter", print_background=True,
                display_header_footer=True, header_template="<span></span>",
                footer_template=FOOTER,
                margin={"top": "0.8in", "bottom": "0.9in", "left": "0.75in", "right": "0.75in"},
            )
            print(out)
        browser.close()


def main(args: list[str]) -> None:
    if not args:
        sys.exit(__doc__)
    build([Path(a).resolve() for a in args])


if __name__ == "__main__":
    main(sys.argv[1:])
