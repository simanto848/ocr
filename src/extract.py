"""Universal document text extraction for the web app.

Digital text (PDF text layer, DOCX, TXT, ...) is read directly; scanned pages and
images are run through Tesseract OCR.  Supported OCR languages: English (eng),
Bangla/Bengali (ben) and Hindi (hin), individually or combined.

Public entry point:
    extract_file(path, lang="auto", out_dir=None, dpi=200, on_page=None)

Returns:
    {
      "pages": [{"page": 1, "text": "...", "boxes": [...], "source": "ocr|digital",
                 "render": "page_001.png"}],
      "engine": "tesseract 5.5.3",
      "language": "eng+ben+hin",
      "ocr_langs": ["eng", "ben", "hin"],
    }
"""
import env_bootstrap  # noqa: F401  (must be first: pins caches to external drive)

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
DOC_EXTS = {".doc", ".docx", ".rtf", ".odt", ".txt", ".md", ".html", ".htm", ".csv", ".log"}
PDF_EXTS = {".pdf"}
SUPPORTED = IMAGE_EXTS | DOC_EXTS | PDF_EXTS

# User-facing choice -> Tesseract -l value
LANG_MAP = {
    "auto": "eng+ben+hin", "mixed": "eng+ben+hin", "multi": "eng+ben+hin",
    "en": "eng", "eng": "eng", "english": "eng",
    "bn": "ben", "ben": "ben", "bangla": "ben", "bengali": "ben",
    "hi": "hin", "hin": "hin", "hindi": "hin",
}
LANG_LABELS = {
    "auto": "Auto (English + বাংলা + हिन्दी)",
    "en": "English",
    "bn": "বাংলা (Bangla)",
    "hi": "हिन्दी (Hindi)",
    "mixed": "English + বাংলা + हिन्दी",
}

# Below this many non-space chars, a PDF text layer is treated as empty/scanned.
MIN_DIGITAL_CHARS = 24

# Characters that are almost never frequent in normal prose but are the classic
# signature of a PDF with a broken/missing ToUnicode font map.
_GARBLE_CHARS = "{}\\€¢£¥§¶¬¤|~^`"
_GOOD_PUNCT = set(".,:;-()/'\".?!@#&%+=_$—–‘’“”।॥،؛؟")


def _text_quality(text: str) -> float:
    """Fraction of characters that look like ordinary readable text.

    Unicode marks (Indic vowel signs such as ি, ी, ্) are category M, not L,
    so they must be counted explicitly or every Bangla/Hindi page looks garbled.
    """
    import unicodedata
    if not text:
        return 0.0
    good = sum(
        1 for c in text
        if c.isspace() or c in _GOOD_PUNCT or unicodedata.category(c)[0] in ("L", "N", "M", "P", "Z")
    )
    return good / len(text)


def _text_is_garbled(text: str) -> bool:
    """Detect a broken PDF text layer so we can OCR the page instead."""
    if not text:
        return True
    weird = sum(text.count(c) for c in _GARBLE_CHARS)
    return weird / max(1, len(text)) > 0.02 or _text_quality(text) < 0.96


def _tesseract_version() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        return "tesseract (not found)"
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"tesseract\s+([\d.]+)", out)
        return f"tesseract {m.group(1)}" if m else "tesseract"
    except Exception:
        return "tesseract"


def _lang_arg(lang: str) -> str:
    return LANG_MAP.get((lang or "auto").lower().strip(), "eng+ben+hin")


def _preprocess(image_path: Path, tmp_dir: Path) -> Path:
    """Upscale only tiny images; leave binarisation to Tesseract.

    Tesseract's own adaptive binarisation is markedly better than external
    Otsu/adaptive thresholds for printed Indic scripts — those smear vowel
    signs and conjuncts, so we deliberately do NOT threshold here.
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode image: {image_path.name}")
    h, w = img.shape[:2]
    if w < 1000:
        scale = min(2.5, 1000 / max(1, w))
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        out = tmp_dir / "ocr_input.png"
        cv2.imwrite(str(out), img)
        return out
    return image_path


def _parse_tsv(tsv: str, offset_x: int = 0, offset_y: int = 0):
    """Turn Tesseract TSV output into reading-ordered lines with boxes."""
    rows = []
    for line in tsv.splitlines():
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] == "level":
            continue
        try:
            level = int(parts[0]); left = int(parts[6]); top = int(parts[7])
            width = int(parts[8]); height = int(parts[9]); conf = float(parts[10])
        except ValueError:
            continue
        text = parts[11].strip()
        if level != 5 or not text:  # 5 = word
            continue
        rows.append({"block": int(parts[2]), "par": int(parts[3]), "line": int(parts[4]),
                     "left": left + offset_x, "top": top + offset_y,
                     "w": width, "h": height, "conf": conf, "text": text})
    groups = {}
    for r in rows:
        key = (r["block"], r["par"], r["line"])
        groups.setdefault(key, []).append(r)
    lines = []
    for key in sorted(groups):
        words = sorted(groups[key], key=lambda r: r["left"])
        text = " ".join(w["text"] for w in words).strip()
        if not text:
            continue
        x1 = min(w["left"] for w in words)
        y1 = min(w["top"] for w in words)
        x2 = max(w["left"] + w["w"] for w in words)
        y2 = max(w["top"] + w["h"] for w in words)
        lines.append({"box": [x1, y1, x2, y2], "text": text,
                      "conf": round(sum(w["conf"] for w in words) / len(words), 1)})
    # Reading order: group order from Tesseract is already good; keep it.
    return lines


def ocr_image(image_path: Path, lang: str = "auto", psm: int = 3,
              preprocess: bool = True):
    """OCR one image with Tesseract. Returns (text, boxes)."""
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract binary not found on PATH")
    langs = _lang_arg(lang)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        target = _preprocess(image_path, tmp) if preprocess else image_path
        common = [exe, str(target), "stdout", "-l", langs, "--psm", str(psm)]
        data = subprocess.run(common + ["tsv"], capture_output=True, text=True,
                              timeout=300)
        lines = _parse_tsv(data.stdout or "")
        text = "\n".join(l["text"] for l in lines).strip()
        if not text:  # fall back to plain text output for odd layouts
            plain = subprocess.run(common, capture_output=True, text=True, timeout=300)
            text = (plain.stdout or "").strip()
            lines = [{"box": [0, 0, 0, 0], "text": text, "conf": 0.0}] if text else []
        return text, lines


def _ocr_with_engine(image_path: Path, lang: str, engine: str, on_page=None,
                     page: int = 1, total: int = 1, vlm_ok: bool = True):
    """OCR a page with the requested engine.

    `vlm_ok` is resolved ONCE per document by extract_file — a 100-page PDF must
    not make 100 health-check calls. `page`/`total` are real page numbers so the
    UI progress bar advances instead of sticking at 10%.
    Returns (text, boxes, engine_name).
    """
    from vlm_client import ocr_image as vlm_ocr

    want_vlm = engine != "tesseract" and vlm_ok
    if want_vlm:
        if on_page:
            on_page(page, total, "vlm")
        try:
            r = vlm_ocr(str(image_path))
            text = (r.get("markdown") or r.get("text") or "").strip()
            if text:
                return text, [], r.get("engine", "PaddleOCR-VL")
        except Exception as e:  # noqa: BLE001
            if engine == "vlm":
                raise RuntimeError(
                    f"PaddleOCR-VL selected but unavailable: {e}. "
                    "Start src/vlm_service.py or choose Tesseract."
                ) from e
            # 'auto' degrades gracefully to Tesseract.
    text, boxes = ocr_image(image_path, lang=lang)
    return text, boxes, _tesseract_version()


def _save_page_image(src: Path, out_dir: Path, n: int) -> Path:
    """Ensure each job has a page_NNN.png available for preview."""
    from PIL import Image
    dst = out_dir / f"page_{n:03d}.png"
    if src.resolve() != dst.resolve():
        im = Image.open(src).convert("RGB")
        im.save(dst, "PNG")
    return dst


def _pdf_pages(path: Path, out_dir: Path, lang: str, dpi: int, on_page, engine: str,
               vlm_ok: bool = True):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    scale = dpi / 72.0
    pages = []
    total = len(pdf)
    for i in range(total):
        if on_page:
            on_page(i + 1, total, "rendering")
        page = pdf[i]
        bitmap = page.render(scale=scale).to_pil().convert("RGB")
        rendered = out_dir / f"page_{i + 1:03d}.png"
        bitmap.save(rendered, "PNG")
        tp = page.get_textpage()
        digital = (tp.get_text_range() or "").strip()
        if len(re.sub(r"\s", "", digital)) >= MIN_DIGITAL_CHARS and not _text_is_garbled(digital):
            text, boxes, source = digital, [], "digital"
        else:
            text, boxes, _ = _ocr_with_engine(rendered, lang, engine, on_page,
                                              page=i + 1, total=total, vlm_ok=vlm_ok)
            source = "ocr"
        pages.append({"page": i + 1, "text": text, "boxes": boxes,
                      "source": source, "render": rendered.name})
    pdf.close()
    return pages


def _docx_pages(path: Path, out_dir: Path, lang: str, engine: str = "auto",
                vlm_ok: bool = True):
    import docx
    from PIL import Image
    import io
    doc = docx.Document(str(path))
    parts = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    pages = []
    if parts:
        pages.append({"page": 1, "text": "\n".join(parts), "boxes": [],
                      "source": "digital", "render": None})
    # OCR embedded inline images (e.g. scanned signatures / screenshots).
    img_no = 0
    for rel in doc.part.rels.values():
        if "image" not in rel.reltype:
            continue
        try:
            blob = rel.target_part.blob
            im = Image.open(io.BytesIO(blob)).convert("RGB")
            img_no += 1
            tmp = out_dir / f"embedded_{img_no}.png"
            im.save(tmp, "PNG")
            text, boxes, _ = _ocr_with_engine(tmp, lang, engine, vlm_ok=vlm_ok)
            if text.strip():
                pages.append({"page": len(pages) + 1, "text": text, "boxes": boxes,
                              "source": "ocr", "render": None,
                              "note": f"embedded image {img_no}"})
        except Exception:
            continue
    if not pages:
        pages.append({"page": 1, "text": "", "boxes": [], "source": "digital", "render": None})
    return pages


def _plain_text_pages(path: Path, lang: str):
    ext = path.suffix.lower()
    text = ""
    # macOS textutil handles .doc, .rtf, .odt, .html, .docx robustly.
    textutil = shutil.which("textutil")
    if textutil and ext in {".doc", ".rtf", ".odt", ".html", ".htm", ".docx"}:
        try:
            r = subprocess.run([textutil, "-convert", "txt", "-stdout", str(path)],
                               capture_output=True, timeout=120)
            text = (r.stdout or b"").decode("utf-8", "ignore")
        except Exception:
            text = ""
    if not text.strip():
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    if ext in {".html", ".htm"}:
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text,
                      flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as _html
        text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return [{"page": 1, "text": text, "boxes": [], "source": "digital", "render": None}]


def extract_file(path, lang="auto", out_dir=None, dpi=200, on_page=None,
                 ocr_engine="auto"):
    """Extract text from any supported file. See module docstring for return shape.

    ocr_engine: 'auto' (VLM if the local service is up, else Tesseract),
                'vlm' (force PaddleOCR-VL), 'tesseract' (force Tesseract).
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported file type: {ext or '(none)'}")
    if out_dir is None:
        out_dir = path.parent / "_extract"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lang = _lang_arg(lang)

    # Resolve VLM availability ONCE for the whole document.
    from vlm_client import available as vlm_available
    vlm_ok = (ocr_engine != "tesseract") and vlm_available()
    if ocr_engine == "vlm" and not vlm_ok:
        raise RuntimeError(
            "PaddleOCR-VL selected but its service is not running. "
            "Start src/vlm_service.py (./run_vlm.sh) or choose Auto/Tesseract."
        )

    if ext in IMAGE_EXTS:
        text, boxes, _ = _ocr_with_engine(path, lang, ocr_engine, on_page,
                                          page=1, total=1, vlm_ok=vlm_ok)
        _save_page_image(path, out_dir, 1)
        pages = [{"page": 1, "text": text, "boxes": boxes, "source": "ocr",
                  "render": "page_001.png"}]
    elif ext in PDF_EXTS:
        pages = _pdf_pages(path, out_dir, lang, dpi, on_page, ocr_engine, vlm_ok)
    elif ext == ".docx":
        pages = _docx_pages(path, out_dir, lang, ocr_engine, vlm_ok)
    else:
        pages = _plain_text_pages(path, lang)

    # For non-image, non-PDF documents there is no natural page render; generate
    # a simple text-sheet preview so the UI still shows something meaningful.
    for pg in pages:
        if not pg.get("render"):
            _make_text_preview(pg, out_dir)
    has_ocr = any(pg.get("source") == "ocr" for pg in pages)
    if has_ocr and vlm_ok:
        try:
            from vlm_client import status as vlm_status
            engine_name = (vlm_status().get("engine") or "PaddleOCR-VL")
        except Exception:
            engine_name = "PaddleOCR-VL"
    else:
        engine_name = _tesseract_version()
    return {"pages": pages, "engine": engine_name, "language": lang,
            "ocr_langs": lang.split("+")}


def _make_text_preview(page: dict, out_dir: Path):
    """Render extracted digital text to a PNG so every job has a preview."""
    from PIL import Image, ImageDraw, ImageFont
    n = page["page"]
    dst = out_dir / f"page_{n:03d}.png"
    if dst.exists():
        page["render"] = dst.name
        return
    text = (page.get("text") or "").strip() or "(no text detected)"
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/NotoSansBengali-Regular.ttf",
    ]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 22)
                break
            except Exception:
                continue
    font = font or ImageFont.load_default()
    lines = text.replace("\r", "").split("\n")[:60]
    width = 1000
    height = max(300, 60 + len(lines) * 32)
    im = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(im)
    draw.text((30, 25), f"Page {n} — extracted text (digital)", fill=(60, 60, 60), font=font)
    y = 70
    for ln in lines:
        draw.text((30, y), ln[:150], fill=(20, 20, 20), font=font)
        y += 32
    im.save(dst, "PNG")
    page["render"] = dst.name


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    r = extract_file(a.file, lang=a.lang, out_dir=a.out)
    for pg in r["pages"]:
        print(f"--- page {pg['page']} [{pg['source']}] ---")
        print(pg["text"][:2000])
    print("engine:", r["engine"], "lang:", r["language"])
