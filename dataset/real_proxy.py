"""Build real_world_test/ proxy set: held-out seeds + heavy degradation.
These are SYNTHETIC stand-ins with a documented gap. Drop genuine scans into
real_world_test/images + rows into real_world_test/ground_truth.tsv to replace.
Never used for training (excluded from all generate.py outputs by construction).
"""
from __future__ import annotations
import json, random, sys
from pathlib import Path
import cv2
import os
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)
ROOT = Path(os.environ.get("OCR_ROOT", "/Volumes/SSD-SIMANTO/works/ocr"))

HEAVY = {"blur_p": 0.6, "noise_p": 0.7, "jpeg_p": 0.6, "perspective_p": 0.8,
         "lighting_p": 0.6, "rotation_max": 7}

def main(count=12, seed=999):
    sys.path.insert(0, str(ROOT))
    from dataset.fonts.registry import FontRegistry
    from dataset.fonts.selector import FontSelector
    from dataset.templates.documents import build
    from dataset.rendering.pillow_renderer import PillowRenderer
    from dataset.augmentation.degrader import DocumentDegrader
    out = ROOT / "real_world_test"
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    reg = FontRegistry(); sel = FontSelector(reg, seed=seed)
    ren = PillowRenderer(reg, sel, dpi=150)  # phone-camera-ish resolution
    rows, metas = [], []
    types = ["invoice", "gov_form", "receipt", "application", "mixed", "legal"]
    langs = ["bn", "en", "bn-en"]
    for i in range(count):
        doc = build(rng.choice(types), rng.choice(langs), seed * 1000 + i)
        img_pil, ann = ren.render(doc, seed=seed + i)
        import numpy as np
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        img, boxes, applied = DocumentDegrader(HEAVY, seed=seed + i)(img, [w["bbox"] for w in ann["words"]])
        name = f"realproxy_{i:03d}.png"
        cv2.imwrite(str(out / "images" / name), img)
        for w, b in zip(ann["words"], boxes):
            w["bbox"] = b
        (out / "annotations" / f"realproxy_{i:03d}.json").write_text(json.dumps(
            {"id": f"realproxy_{i:03d}", "text": doc.full_text(),
             "words": ann["words"], "lines": ann["lines"],
             "document": doc.to_dict()}, ensure_ascii=False))
        (out / "metadata" / f"realproxy_{i:03d}.json").write_text(json.dumps(
            {"id": f"realproxy_{i:03d}", "proxy": True, "language": doc.language,
             "fonts": ann["meta"]["fonts"], "document_type": doc.document_type,
             "resolution": 150, "augmentation": applied, "difficulty": 0.9},
            ensure_ascii=False))
        rows.append(f"images/{name}\t{doc.full_text().replace(chr(10), ' ').strip()}")
        metas.append(f"realproxy_{i:03d}")
    (out / "splits.json").write_text(json.dumps({"train": [], "val": [], "test": metas}))
    (out / "test.tsv").write_text("\n".join(rows))
    (out / "ground_truth.tsv").write_text("\n".join(rows))
    (out / "manifest.json").write_text(json.dumps(
        {"note": "SYNTHETIC PROXY — replace with genuine scans. Never train on this dir.",
         "samples": len(rows), "seed": seed}, indent=1))
    (out / "README.md").write_text(
        "# real_world_test\n\nSynthetic proxy set (heavy degradation, held-out seeds).\n"
        "To add genuine scans: put PNGs in `images/`, append `images/<f>\\t<text>` rows to\n"
        "`ground_truth.tsv`, and evaluate with:\n\n"
        "  python -m evaluation.evaluate --checkpoint <ckpt> --dataset real_world_test --split test\n\n"
        "NEVER include this directory in training data.\n")
    print(f"proxy real set: {len(rows)} → {out}")

if __name__ == "__main__":
    main()
