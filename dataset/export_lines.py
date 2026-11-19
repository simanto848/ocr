"""Export GT line crops for TrOCR line-training. Uses GT bboxes (never OCR).
python -m dataset.export_lines --dataset data/v001 [--max-lines 20000]
Writes <dataset>/lines/{images/*.png, train.tsv, val.tsv, test.tsv} reusing split ids.
"""
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
import argparse, json
from pathlib import Path
import cv2
ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--max-lines", type=int, default=30000)
    a = ap.parse_args()
    ds = ROOT / a.dataset if not str(a.dataset).startswith(str(ROOT)) else Path(a.dataset)
    splits = json.loads((ds / "splits.json").read_text())
    id2split = {}
    for s, ids in splits.items():
        for _id in ids:
            id2split[_id] = s
    out = ds / "lines"
    (out / "images").mkdir(parents=True, exist_ok=True)
    writers = {s: open(out / f"{s}.tsv", "w") for s in ("train", "val", "test")}
    counts = {s: 0 for s in writers}
    total = 0
    # split-aware order: round-robin across splits so --max-lines keeps all splits
    by_split = {"train": [], "val": [], "test": []}
    for imgp in sorted((ds / "images").glob("*.png")):
        by_split[id2split.get(imgp.stem, "train")].append(imgp)
    quota = {"train": 1.0, "val": 1.0, "test": 1.0}
    ordered = []
    lists = {s: list(v) for s, v in by_split.items()}
    while any(lists.values()) and total < a.max_lines:
        for s in ("train", "val", "test"):
            if lists[s] and total < a.max_lines:
                ordered.append((s, lists[s].pop(0))); total += 1
    total = 0
    for s, imgp in ordered:
        _id = imgp.stem
        ann = json.loads((ds / "annotations" / f"{_id}.json").read_text())
        full = cv2.imread(str(imgp))
        if full is None:
            continue
        for j, ln in enumerate(ann.get("lines", [])):
            if total >= a.max_lines:
                break
            x1, y1, x2, y2 = [int(v) for v in ln["bbox"]]
            pad = 4
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(full.shape[1], x2 + pad), min(full.shape[0], y2 + pad)
            if y2 - y1 < 8 or x2 - x1 < 20:
                continue
            txt = ln["text"].strip()
            if not txt:
                continue
            name = f"{_id}_l{j:02d}.png"
            cv2.imwrite(str(out / "images" / name), full[y1:y2, x1:x2])
            writers[s].write(f"images/{name}\t{txt}\n")
            counts[s] += 1
            total += 1
    for w in writers.values():
        w.close()
    print(f"lines: {counts} total={total} → {out}")

if __name__ == "__main__":
    main()
