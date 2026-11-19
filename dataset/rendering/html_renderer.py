"""HTML/CSS renderer: correct Bengali shaping via Chromium/Playwright.
Generates HTML per document; screenshots with Playwright if available,
else falls back to PillowRenderer (and records fallback in metadata)."""
from __future__ import annotations
from pathlib import Path
import html as _html

HTML_TMPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 15mm; }}
body {{ font-family: '{body_font}', sans-serif; font-size: 20px; line-height: 1.5; color: #000; }}
h1 {{ font-family: '{head_font}', serif; text-align: center; }}
.center {{ text-align: center; }} .right {{ text-align: right; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #000; padding: 6px 8px; font-size: 18px; }}
.stamp {{ border: 3px solid red; color: red; text-align: center; width: 260px; margin: 20px auto; padding: 8px; }}
.footer {{ text-align: center; color: #555; margin-top: 30px; }}
</style></head><body>{body}</body></html>"""

def to_html(doc) -> str:
    parts = []
    for el in doc.pages[0].elements:
        t = _html.escape(el.text)
        if el.type in ("heading", "header"):
            parts.append(f"<h1>{t}</h1>")
        elif el.type == "paragraph":
            parts.append(f"<p>{t}</p>")
        elif el.type == "table":
            cols = el.meta.get("columns", ["item", "qty", "price"])
            rows = el.meta.get("rows", [])
            th = "".join(f"<th>{c.upper()}</th>" for c in cols)
            tr = "".join("<tr>" + "".join(f"<td>{_html.escape(str(r.get(c,'')))}</td>" for c in cols) + "</tr>" for r in rows[:30])
            parts.append(f"<table><tr>{th}</tr>{tr}</table>")
        elif el.type == "stamp":
            parts.append(f"<div class='stamp'>{t}</div>")
        elif el.type in ("footer",):
            parts.append(f"<div class='footer'>{t}</div>")
        elif el.type in ("signature",):
            parts.append(f"<p class='right'>{t}</p>")
        else:
            align = el.alignment if el.alignment in ("center", "right") else "left"
            parts.append(f"<p class='{align}'>{t}</p>")
    return HTML_TMPL.format(body="\n".join(parts), body_font="Noto Sans Bengali",
                            head_font="Noto Serif Bengali")

def render_html_png(doc, out_png: Path, dpi: int = 200, body_font="Noto Sans Bengali"):
    """Try Playwright Chromium; return (ok: bool, fallback_reason)."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
        html = to_html(doc)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1240, "height": 1754})
            pg.set_content(html)
            pg.screenshot(path=str(out_png), full_page=True)
            b.close()
        return True, None
    except Exception as e:
        return False, str(e)[:200]
