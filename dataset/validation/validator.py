"""Dataset validation: schema/image/bbox/unicode/metadata + thresholds + duplicates."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from PIL import Image

def validate_sample(img_path: Path, ann: dict, cfg: dict | None = None):
    errs = []
    c = cfg or {}
    if not img_path.exists():
        return False, ["missing-image"]
    try:
        im = Image.open(img_path)
        w, h = im.size
        if w < c.get("min_image_width", 512) or h < c.get("min_image_height", 300):
            errs.append("too-small")
    except Exception:
        return False, ["unreadable-image"]
    words = ann.get("words", [])
    if not words:
        errs.append("empty-text")
    for wb in words[:5000]:
        x1, y1, x2, y2 = wb["bbox"]
        if not (0 <= x1 < x2 <= w + 2 and 0 <= y1 < y2 <= h + 2):
            errs.append("invalid-bbox"); break
        try:
            wb["text"].encode("utf-8")
        except Exception:
            errs.append("invalid-unicode"); break
    if not (ann.get("meta") or ann.get("document") or ann.get("text")):
        errs.append("missing-meta")
    return (len(errs) == 0), errs

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()

def find_duplicates(images_dir: Path):
    seen, dups = {}, []
    for p in sorted(images_dir.glob("*.png")):
        h = sha256_file(p)
        if h in seen:
            dups.append((str(p), seen[h]))
        else:
            seen[h] = str(p)
    return dups
