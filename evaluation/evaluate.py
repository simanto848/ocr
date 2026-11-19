"""python -m evaluation.evaluate --model base | --checkpoint X [--dataset data/v001] [--split test]
Baseline + trained eval: CER/WER/EM overall + bn/en/mixed + by-doc-type + failure gallery + HTML report.
"""
from __future__ import annotations
import argparse, json, os, shutil
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
import torch
from PIL import Image

ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="base = HF base-printed")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--dataset", default="data/v001")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-samples", type=int, default=200)
    ap.add_argument("--level", default="line", choices=["page", "line"],
                    help="page=whole image (unfair for line models); line=crop GT lines (default)")
    a = ap.parse_args()
    import sys
    sys.path.insert(0, str(ROOT))
    from evaluation.metrics import cer_wer, group_scores
    ds = ROOT / a.dataset if not str(a.dataset).startswith(str(ROOT)) else Path(a.dataset)
    mid = a.checkpoint or ({"base": "microsoft/trocr-base-printed"}.get(a.model or "", None) or a.model or "microsoft/trocr-base-printed")
    if a.checkpoint and not str(mid).startswith(str(ROOT)) and Path(ROOT / mid).exists():
        mid = str(ROOT / mid)
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    dev = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    proc = TrOCRProcessor.from_pretrained(mid)
    model = VisionEncoderDecoderModel.from_pretrained(mid).to(dev).eval()
    ids = (ds / "splits.json")
    if ids.exists():
        split_ids = json.loads(ids.read_text())[a.split]
    else:
        split_ids = [p.stem for p in sorted((ds / "images").glob("*.png"))[:a.max_samples]]
    refs, hyps, items, fails = [], [], [], []
    import cv2
    import numpy as np
    for _id in split_ids[:a.max_samples]:
        ann = json.loads((ds / "annotations" / f"{_id}.json").read_text())
        meta = json.loads((ds / "metadata" / f"{_id}.json").read_text())
        gt = ann["text"].replace("\n", " ").strip()
        if a.level == "line" and ann.get("lines"):
            full = cv2.imread(str(ds / "images" / f"{_id}.png"))
            crops = []
            for ln in ann["lines"][:24]:
                x1, y1, x2, y2 = [max(0, int(v)) for v in ln["bbox"]]
                pad = 3
                x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                x2, y2 = min(full.shape[1], x2 + pad), min(full.shape[0], y2 + pad)
                if y2 - y1 < 5 or x2 - x1 < 5:
                    continue
                crops.append(Image.fromarray(cv2.cvtColor(full[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)))
            pr_lines = []
            for j in range(0, len(crops), 8):
                pv = proc(images=crops[j:j + 8], return_tensors="pt").pixel_values.to(dev)
                with torch.no_grad():
                    out_ids = model.generate(pv, max_length=64, no_repeat_ngram_size=3)
                pr_lines.extend(proc.batch_decode(out_ids, skip_special_tokens=True))
            pr = " ".join(t.strip() for t in pr_lines)
        else:
            img = Image.open(ds / "images" / f"{_id}.png").convert("RGB")
            pv = proc(images=img, return_tensors="pt").pixel_values.to(dev)
            with torch.no_grad():
                out_ids = model.generate(pv, max_length=128, no_repeat_ngram_size=3)
            pr = proc.batch_decode(out_ids, skip_special_tokens=True)[0].strip()
        refs.append(gt); hyps.append(pr)
        lang = meta.get("language", "?"); dt = meta.get("document_type", "?")
        items.append({"id": _id, "ref": gt, "hyp": pr, "group": f"lang={lang}"})
        items.append({"id": _id, "ref": gt, "hyp": pr, "group": f"type={dt}"})
        import jiwer
        try:
            c = jiwer.cer([gt or " "], [pr or " "])
        except Exception:
            c = 1.0
        if c > 0.15:
            fails.append({"id": _id, "cer": round(float(c), 3), "gt": gt[:300], "pr": pr[:300], "meta": meta})
    overall = cer_wer(refs, hyps)
    em = sum(1 for x, y in zip(refs, hyps) if x.strip() == y.strip())
    by_group = group_scores(items)
    fails.sort(key=lambda x: -x["cer"])
    outdir = Path(a.out) if a.out else ROOT / "experiments" / f"eval_{Path(str(mid)).name if '/' not in str(mid) else str(mid).split('/')[-1]}"
    outdir.mkdir(parents=True, exist_ok=True)
    rep = {"model": str(mid), "dataset": str(ds), "split": a.split, "n": len(refs),
           "overall": overall, "exact_match": f"{em}/{len(refs)}", "by_group": by_group,
           "failures": fails[:30]}
    (outdir / "evaluation_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    rows = "".join(f"<tr><td>{f['id']}</td><td>{f['cer']}</td><td>{f['gt'][:150]}</td><td>{f['pr'][:150]}</td></tr>" for f in fails[:30])
    (outdir / "evaluation_report.html").write_text(
        f"<html><body><h1>{mid} — {a.split} n={len(refs)}</h1><p>CER={overall['cer']:.4f} WER={overall['wer']:.4f} EM={em}/{len(refs)}</p><pre>{json.dumps(by_group, indent=1)}</pre><table border=1><tr><th>id</th><th>CER</th><th>GT</th><th>PRED</th></tr>{rows}</table></body></html>")
    # failure gallery images
    gal = outdir / "failure_gallery"; gal.mkdir(exist_ok=True)
    for f in fails[:20]:
        src = ds / "images" / f"{f['id']}.png"
        if src.exists():
            shutil.copy(src, gal / f"{f['cer']:.2f}_{f['id']}.png")
    print(f"n={len(refs)} CER={overall['cer']:.4f} WER={overall['wer']:.4f} EM={em}/{len(refs)} → {outdir}")

if __name__ == "__main__":
    main()
