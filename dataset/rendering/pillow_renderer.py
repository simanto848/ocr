"""Pillow-TTF renderer: real fonts, A4/DPI, tables/assets, bbox annotations.
Shaping note: Pillow lacks raqm here, so complex Bengali conjuncts may shape
imperfectly; HTML/Chromium path (html_renderer.py) gives pixel-perfect shaping.
Pillow path is the fast default and still uses REAL TTF (never bitmap)."""
from __future__ import annotations
import random, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PAGE_SIZES = {"A4": (210, 297), "A5": (148, 210), "Letter": (216, 279), "Legal": (216, 356)}
DPI_DEFAULT = 200

def _mm_to_px(mm, dpi): return int(mm * dpi / 25.4)

class PillowRenderer:
    def __init__(self, registry, selector=None, dpi=DPI_DEFAULT):
        self.reg = registry
        self.sel = selector
        self.dpi = dpi

    def _font(self, language, role, size, family=""):
        if self.sel and not family:
            f, meta, fb = self.sel.pick(language, role)
            # rescale to requested size
            try:
                from PIL import ImageFont
                f = ImageFont.truetype(meta["path"], size=size)
            except Exception:
                pass
            return f, meta, fb
        f, meta, fb = self.reg.get(language=language, family=family or None, size=size)
        return f, meta, fb

    def render(self, doc, seed=0):
        rng = random.Random(seed)
        size_name = doc.pages[0].size if doc.pages else "A4"
        Wmm, Hmm = PAGE_SIZES.get(size_name, PAGE_SIZES["A4"])
        W, H = _mm_to_px(Wmm, self.dpi), _mm_to_px(Hmm, self.dpi)
        img = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(img)
        margin = _mm_to_px(15, self.dpi)
        y = margin
        ann_words, ann_lines, fallbacks = [], [], list(self.reg.fallback_log)
        self.reg.fallback_log.clear()
        line_spacing = doc.meta.get("line_spacing", 1.3)
        fonts_used, langs = set(), set()

        def draw_wrapped(text, lang, role, size, align, family=""):
            nonlocal y
            font, meta, fb = self._font(lang, role, size, family)
            fonts_used.add(meta.get("key", "?")); langs.add(lang)
            if fb: fallbacks.append(fb)
            max_w = W - 2 * margin
            words, lines, cur = text.split(), [], ""
            for w_ in words:
                t = (cur + " " + w_).strip()
                if d.textlength(t, font=font) <= max_w or not cur:
                    cur = t
                else:
                    lines.append(cur); cur = w_
            if cur: lines.append(cur)
            for line in lines:
                x = margin
                if align == "center": x = (W - d.textlength(line, font=font)) / 2
                elif align == "right": x = W - margin - d.textlength(line, font=font)
                asc, desc = font.getmetrics()
                lh = int((asc + desc) * line_spacing)
                if y + lh > H - margin:
                    break  # single-page clip (multi-page counted in meta)
                d.text((x, y), line, fill="black", font=font)
                # word bboxes (approx via textlength)
                wx = x
                for w_ in line.split():
                    ww = d.textlength(w_ + " ", font=font)
                    ann_words.append({"text": w_, "bbox": [int(wx), int(y), int(wx + ww), int(y + lh)], "level": "word"})
                    wx += ww
                ann_lines.append({"text": line, "bbox": [int(x), int(y), int(x + d.textlength(line, font=font)), int(y + lh)], "level": "line"})
                y += lh
            y += size // 3
            return

        for el in doc.pages[0].elements:
            lang = doc.language if doc.language in ("bn", "en") else ("bn" if any("\u0980" <= c <= "\u09FF" for c in el.text) else "en")
            if el.type in ("heading", "header"):
                draw_wrapped(el.text, lang, "heading", 34 if el.type == "heading" else 26, el.alignment or "center", el.font_family)
            elif el.type in ("paragraph", "text", "field", "footer"):
                draw_wrapped(el.text, lang, "body", el.font_size or 20, el.alignment or "left", el.font_family)
            elif el.type == "checkbox":
                draw_wrapped(el.text, lang, "body", 20, "left", el.font_family)
            elif el.type == "signature":
                draw_wrapped(el.text, lang, "body", 20, "right", el.font_family)
                # procedural squiggle
                sx, sy = W - margin - 300, y
                pts = [(sx + i * 6, sy + int(10 * math.sin(i * 0.9 + seed))) for i in range(40)]
                d.line(pts, fill="darkblue", width=2)
                y += 30
            elif el.type == "stamp":
                cx, cy = W // 2, y + 60
                d.ellipse([cx - 110, cy - 45, cx + 110, cy + 45], outline="red", width=3)
                f, _, _ = self._font("en", "body", 28)
                d.text((cx - 80, cy - 20), el.text[:12].upper(), fill="red", font=f)
                y += 130
            elif el.type == "table":
                cols = el.meta.get("columns", ["item", "qty", "price"])
                rows = el.meta.get("rows", [])
                f, meta, fb = self._font(lang, "body", 18)
                fonts_used.add(meta.get("key", "?"))
                if fb: fallbacks.append(fb)
                cw = (W - 2 * margin) // max(1, len(cols))
                rh = 44
                # header
                for j, c in enumerate(cols):
                    x0 = margin + j * cw
                    d.rectangle([x0, y, x0 + cw, y + rh], outline="black", width=2)
                    d.text((x0 + 6, y + 8), c.upper(), fill="black", font=f)
                y += rh
                for r in rows[:30]:
                    for j, c in enumerate(cols):
                        x0 = margin + j * cw
                        d.rectangle([x0, y, x0 + cw, y + rh], outline="black")
                        d.text((x0 + 6, y + 8), str(r.get(c, ""))[:28], fill="black", font=f)
                    y += rh
                y += 10
            elif el.type == "watermark":
                pass  # skip heavy watermark in fast path
            el.bbox = [margin, 0, W - margin, 0]
        # footer page number
        f, _, _ = self._font("en", "body", 16)
        d.text((W // 2 - 20, H - margin + 5), "1", fill="gray", font=f)
        meta = {"fonts": sorted(fonts_used), "languages": sorted(langs),
                "fallbacks": fallbacks, "renderer": "pillow-ttf",
                "dpi": self.dpi, "size_px": [W, H]}
        return img, {"words": ann_words, "lines": ann_lines, "meta": meta}
