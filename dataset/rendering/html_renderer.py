"""HTML/CSS renderer: correct Bengali shaping via Chromium/Playwright.

Unlike the Pillow path (which lacks libraqm on many installs and therefore
mis-shapes Bengali conjuncts), Chromium shapes Indic scripts correctly. This
renderer also exports *annotation boxes* by measuring each word's DOM Range,
so the rest of the dataset pipeline (degradation bboxes, validator, line/word
labels) works unchanged.

`render(doc, seed=0, dpi=200)` returns the same `(image, ann)` shape as
PillowRenderer.render, or `None` when Chromium is unavailable so callers can
fall back.
"""
from __future__ import annotations
from pathlib import Path
import html as _html
import os

HTML_TMPL = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: 'BodyFont'; src: url('{body_font_url}'); }}
@font-face {{ font-family: 'HeadFont'; src: url('{head_font_url}'); }}
@page {{ size: A4; margin: 15mm; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: 'BodyFont', sans-serif; font-size: 20px; line-height: 1.5; color: #000; }}
h1 {{ font-family: 'HeadFont', serif; text-align: center; font-size: 30px; }}
.center {{ text-align: center; }} .right {{ text-align: right; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #000; padding: 6px 8px; font-size: 18px; }}
.stamp {{ border: 3px solid red; color: red; text-align: center; width: 260px; margin: 20px auto; padding: 8px; }}
.footer {{ text-align: center; color: #555; margin-top: 30px; }}
</style></head><body style="padding:15mm">{body}</body></html>"""


def _font_urls():
    """Resolve bundled font file URIs so Chromium uses the same fonts as GT."""
    root = Path(os.environ.get("OCR_ROOT", Path(__file__).resolve().parents[2]))
    fallback_b = root / "fonts" / "bengali" / "NotoSansBengali.ttf"
    fallback_h = root / "fonts" / "bengali" / "NotoSerifBengali.ttf"
    body = fallback_b if fallback_b.exists() else fallback_h
    return body.as_uri(), (fallback_h if fallback_h.exists() else body).as_uri()


def to_html(doc) -> str:
    parts = []
    for idx, el in enumerate(doc.pages[0].elements):
        t = _html.escape(el.text)
        attr = f'data-el="{idx}"'
        if el.type in ("heading", "header"):
            parts.append(f"<h1 {attr}>{t}</h1>")
        elif el.type == "paragraph":
            parts.append(f"<p {attr}>{t}</p>")
        elif el.type == "table":
            cols = el.meta.get("columns", ["item", "qty", "price"])
            rows = el.meta.get("rows", [])
            th = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)
            tr = "".join(
                "<tr>" + "".join(f"<td>{_html.escape(str(r.get(c, '')))}</td>" for c in cols)
                + "</tr>" for r in rows[:30]
            )
            parts.append(f"<table {attr}><tr>{th}</tr>{tr}</table>")
        elif el.type == "stamp":
            parts.append(f"<div class='stamp' {attr}>{t}</div>")
        elif el.type == "footer":
            parts.append(f"<div class='footer' {attr}>{t}</div>")
        else:
            align = el.alignment if el.alignment in ("center", "right") else "left"
            parts.append(f"<p class='{align}' {attr}>{t}</p>")
    body_url, head_url = _font_urls()
    return HTML_TMPL.format(body="\n".join(parts),
                            body_font_url=body_url, head_font_url=head_url)


_WORD_BOXES_JS = r"""() => {
  const out = {words: [], lines: []};
  const sx = window.scrollX, sy = window.scrollY;
  document.querySelectorAll('[data-el]').forEach((el, idx) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = []; let n;
    while ((n = walker.nextNode())) nodes.push({node: n, len: n.textContent.length});
    const full = el.textContent || '';
    function rectFor(start, end) {
      let s = 0, sn = null, so = 0, en = null, eo = 0;
      for (const item of nodes) {
        if (sn === null && s + item.len > start) { sn = item.node; so = start - s; }
        if (s + item.len >= end) { en = item.node; eo = end - s; break; }
        s += item.len;
      }
      if (!sn || !en) return null;
      try {
        const r = document.createRange();
        r.setStart(sn, Math.max(0, Math.min(so, sn.textContent.length)));
        r.setEnd(en, Math.max(0, Math.min(eo, en.textContent.length)));
        const b = r.getBoundingClientRect();
        if (!b.width && !b.height) return null;
        return [Math.round(b.left + sx), Math.round(b.top + sy),
                Math.round(b.right + sx), Math.round(b.bottom + sy)];
      } catch (e) { return null; }
    }
    const re = /\S+/g; let m;
    while ((m = re.exec(full))) {
      const b = rectFor(m.index, m.index + m[0].length);
      if (b) out.words.push({text: m[0], bbox: b, level: 'word', el: idx});
    }
  });
  out.words.sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
  let cur = [], curY = null;
  const flush = () => {
    if (!cur.length) return;
    out.lines.push({
      text: cur.map(w => w.text).join(' '),
      bbox: [Math.min(...cur.map(w => w.bbox[0])), Math.min(...cur.map(w => w.bbox[1])),
             Math.max(...cur.map(w => w.bbox[2])), Math.max(...cur.map(w => w.bbox[3]))],
      level: 'line'
    });
    cur = []; curY = null;
  };
  for (const w of out.words) {
    const y = (w.bbox[1] + w.bbox[3]) / 2;
    if (curY === null || Math.abs(y - curY) <= 10) {
      cur.push(w); curY = curY === null ? y : (curY * (cur.length - 1) + y) / cur.length;
    } else { flush(); cur = [w]; curY = y; }
  }
  flush();
  return out;
}"""


def render(doc, seed: int = 0, dpi: int = 200):
    """Render a page with Chromium and return (PIL image, annotations).

    Returns None when Playwright/Chromium is unavailable.
    """
    import tempfile
    from PIL import Image
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        root = Path(os.environ.get("OCR_ROOT", Path(__file__).resolve().parents[2]))
        size = doc.pages[0].size if doc.pages else "A4"
        mm = {"A4": (210, 297), "A5": (148, 210),
              "Letter": (216, 279), "Legal": (216, 356)}.get(size, (210, 297))
        wpx, hpx = int(mm[0] * dpi / 25.4), int(mm[1] * dpi / 25.4)
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "page.png"
            html = to_html(doc)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": wpx, "height": hpx},
                                        device_scale_factor=1)
                page.set_content(html, wait_until="load")
                try:
                    page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                page.screenshot(path=str(png), full_page=True)
                ann = page.evaluate(_WORD_BOXES_JS)
                browser.close()
            img = Image.open(png).convert("RGB")
            # Scale DOM pixel boxes to the requested DPI page size if needed.
            sx = img.width / max(1, wpx)
            sy = img.height / max(1, hpx)
            if sx != 1 or sy != 1:
                for w in ann["words"]:
                    b = w["bbox"]
                    w["bbox"] = [int(b[0] * sx), int(b[1] * sy),
                                 int(b[2] * sx), int(b[3] * sy)]
                for ln in ann["lines"]:
                    b = ln["bbox"]
                    ln["bbox"] = [int(b[0] * sx), int(b[1] * sy),
                                  int(b[2] * sx), int(b[3] * sy)]
            ann["meta"] = {
                "renderer": "html-chromium", "dpi": dpi,
                "size_px": [img.width, img.height],
                "fonts": ["noto_sans_bengali", "noto_serif_bengali"],
                "languages": [doc.language], "fallbacks": [],
            }
            return img, ann
    except Exception:
        return None


def render_html_png(doc, out_png: Path, dpi: int = 200, body_font="Noto Sans Bengali"):
    """Backwards-compatible helper: render straight to a PNG file."""
    result = render(doc, dpi=dpi)
    if result is None:
        return False, "chromium-unavailable"
    result[0].save(out_png)
    return True, None
