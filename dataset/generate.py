"""Multi-stage dataset generation: content→layout→fonts→render→degrade→annotate→split→version.
Usage:
  python -m dataset.generate --count 1000 --output data/v001 [--config configs/dataset.yaml] [--seed 42]
Never overwrites versions silently: refuses if output exists unless --force.
Ground truth comes from structured Document (never OCR of the image).
"""
from __future__ import annotations
import argparse, json, random, shutil, sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)
import cv2

ROOT = None
def _root():
    global ROOT
    if ROOT is None:
        import os
        ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))
    return ROOT

def load_yaml(p):
    import yaml
    return yaml.safe_load(Path(p).read_text()) if p and Path(p).exists() else {}

TIERS = [("clean", 0.4, {}), ("light", 0.3, {"blur_p": 0.15, "noise_p": 0.2, "jpeg_p": 0.2, "rotation_max": 2}),
         ("moderate", 0.2, {"blur_p": 0.3, "noise_p": 0.4, "jpeg_p": 0.4, "perspective_p": 0.4, "rotation_max": 4}),
         ("heavy", 0.1, {"blur_p": 0.5, "noise_p": 0.6, "jpeg_p": 0.6, "perspective_p": 0.7, "lighting_p": 0.5, "rotation_max": 7})]

def pick_tier(rng):
    u = rng.random()
    acc = 0.0
    for name, p, cfg in TIERS:
        acc += p
        if u < acc:
            return name, cfg
    return "clean", {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=None, help="overrides dataset.count in config")
    ap.add_argument("--output", default="data/v001")
    ap.add_argument("--config", default="configs/dataset.yaml")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=0, help="0=serial (safe on M4)")
    a = ap.parse_args()
    root = _root()
    out = root / a.output if not str(a.output).startswith(str(root)) else Path(a.output)
    if out.exists() and any(out.iterdir()) and not a.force:
        print(f"REFUSE: {out} exists and non-empty. Use --force or new version."); sys.exit(2)
    cfg = load_yaml(root / a.config if not str(a.config).startswith("/") else a.config)
    ds_cfg = cfg.get("dataset", {})
    n = int(a.count) if a.count else int(ds_cfg.get("count", 1000))
    seed = int(ds_cfg.get("seed", a.seed))
    dpi = int(ds_cfg.get("dpi", 200))
    lang_dist = ds_cfg.get("languages", {"bn": 0.4, "en": 0.4, "bn-en": 0.2})
    type_dist = ds_cfg.get("document_types", {"plain": .1, "gov_form": .12, "invoice": .15, "receipt": .1,
        "certificate": .08, "legal": .1, "application": .1, "article": .08, "academic": .07, "mixed": .1})
    rng = random.Random(seed)

    sys.path.insert(0, str(root))
    from dataset.fonts.registry import FontRegistry
    from dataset.fonts.selector import FontSelector
    from dataset.templates.documents import build, DOC_TYPES
    from dataset.rendering.pillow_renderer import PillowRenderer
    from dataset.rendering.html_renderer import render as html_render
    from dataset.augmentation.degrader import DocumentDegrader
    from dataset.validation.statistics import difficulty_score
    from dataset.validation.validator import validate_sample

    reg = FontRegistry()
    if not reg.entries:
        from dataset.fonts.scanner import scan
        scan()
        reg = FontRegistry()
    sel = FontSelector(reg, seed=seed)
    pillow = PillowRenderer(reg, sel, dpi=dpi)
    # Pillow without libraqm mis-shapes Bengali conjuncts. Chromium shapes Indic
    # correctly AND exports word boxes via DOM ranges, so prefer it whenever
    # raqm is missing. The choice is recorded per sample in its metadata.
    from PIL import features as _pil_features
    raqm = _pil_features.check("raqm")
    use_html = (not raqm)
    renderer_name = "html-chromium" if use_html else "pillow-ttf"
    if use_html:
        probe = html_render(build("plain", "bn", seed), dpi=dpi)
        if probe is None:
            use_html = False
            renderer_name = "pillow-ttf"
            print("WARN: raqm missing and Chromium unavailable — falling back to "
                  "Pillow (Bengali shaping may be imperfect). "
                  "Install Playwright's chromium or libraqm for correct output.")
    elif raqm:
        print("raqm available: Pillow renderer will shape Indic text correctly.")

    imgdir, anndir, metadir = out / "images", out / "annotations", out / "metadata"
    for d_ in (imgdir, anndir, metadir):
        d_.mkdir(parents=True, exist_ok=True)

    langs = list(lang_dist); lang_w = [lang_dist[k] for k in langs]
    types = list(type_dist); type_w = [type_dist[k] for k in types]
    manifests = []
    ok = 0
    for i in range(n):
        lang = rng.choices(langs, weights=lang_w)[0]
        typ = rng.choices(types, weights=type_w)[0]
        doc = build(typ, lang, seed * 100000 + i)
        rendered = html_render(doc, seed=seed + i, dpi=dpi) if use_html else None
        if rendered is not None:
            img_pil, ann = rendered
        else:
            img_pil, ann = pillow.render(doc, seed=seed + i)
            ann["meta"]["renderer"] = "pillow-ttf"
        import numpy as np
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        boxes = [w["bbox"] for w in ann["words"]]
        tier, tier_cfg = pick_tier(rng)
        deg = DocumentDegrader(tier_cfg, seed=seed + i)
        img, boxes, applied = deg(img, boxes)
        for w, b in zip(ann["words"], boxes):
            w["bbox"] = b
        # difficulty + metadata
        has_table = any(e.type == "table" for e in doc.pages[0].elements)
        diff = difficulty_score({"fonts": ann["meta"]["fonts"], "has_table": has_table}, applied)
        name = f"{doc.document_id}.png"
        cv2.imwrite(str(imgdir / name), img)
        full = doc.full_text()
        (anndir / f"{doc.document_id}.json").write_text(json.dumps(
            {"id": doc.document_id, "text": full, "words": ann["words"], "lines": ann["lines"],
             "document": doc.to_dict()}, ensure_ascii=False, indent=1))
        m = {"id": doc.document_id, "language": lang, "fonts": ann["meta"]["fonts"],
             "document_type": typ, "resolution": dpi, "augmentation": applied,
             "tier": tier, "difficulty": diff, "fallbacks": ann["meta"].get("fallbacks", []),
             "renderer": ann["meta"].get("renderer", renderer_name)}
        (metadir / f"{doc.document_id}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
        valid, errs = validate_sample(imgdir / name, ann)
        if not valid:
            print(f"WARN {name}: {errs}")
            continue
        manifests.append(m)
        ok += 1
        if (i + 1) % 200 == 0:
            print(f"{i+1}/{n} ok={ok}")
    # deterministic 80/10/10 split by sorted id
    manifests.sort(key=lambda m: m["id"])
    nT = int(len(manifests) * 0.8); nV = int(len(manifests) * 0.1)
    splits = {"train": [m["id"] for m in manifests[:nT]],
              "val": [m["id"] for m in manifests[nT:nT + nV]],
              "test": [m["id"] for m in manifests[nT + nV:]]}
    (out / "splits.json").write_text(json.dumps(splits, indent=1))
    (out / "manifest.json").write_text(json.dumps(
        {"dataset_version": out.name, "samples": len(manifests), "seed": seed, "dpi": dpi,
         "splits": {k: len(v) for k, v in splits.items()}}, indent=1))
    # TSVs for src/ compat (line-level full text per image)
    for split, ids in splits.items():
        with open(out / f"{split}.tsv", "w") as f:
            for _id in ids:
                ann = json.loads((anndir / f"{_id}.json").read_text())
                f.write(f"images/{_id}.png\t{ann['text'].replace(chr(10),' ').strip()}\n")
    print(f"DONE {out}: valid {ok}/{n}, splits { {k: len(v) for k,v in splits.items()} }")

if __name__ == "__main__":
    main()
