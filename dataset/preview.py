"""python -m dataset.preview --dataset data/v001 --count 20 --out <dir>"""
import argparse, json, shutil
from pathlib import Path
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    ds = ROOT / a.dataset if not str(a.dataset).startswith(str(ROOT)) else Path(a.dataset)
    out = Path(a.out) if a.out else ds / "preview_gallery"
    out.mkdir(parents=True, exist_ok=True)
    imgs = sorted((ds / "images").glob("*.png"))[:a.count]
    cards = []
    for img in imgs:
        shutil.copy(img, out / img.name)
        ann = json.loads((ds / "annotations" / f"{img.stem}.json").read_text())
        meta = json.loads((ds / "metadata" / f"{img.stem}.json").read_text())
        cards.append(f"<div><h3>{img.name}</h3><img src='{img.name}' width=600><pre>{(ann['text'][:400])}</pre><pre>{json.dumps(meta, ensure_ascii=False)}</pre></div><hr>")
    (out / "index.html").write_text("<html><body>" + "".join(cards) + "</body></html>")
    print(f"gallery → {out/'index.html'} ({len(imgs)} samples)")

if __name__ == "__main__":
    main()
