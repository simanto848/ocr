"""python -m dataset.validate --dataset data/v001"""
import argparse, json, sys
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
    ap.add_argument("--config", default="configs/dataset.yaml")
    a = ap.parse_args()
    ds = ROOT / a.dataset if not str(a.dataset).startswith(str(ROOT)) else Path(a.dataset)
    sys.path.insert(0, str(ROOT))
    from dataset.validation.validator import validate_sample, find_duplicates
    bad, total = 0, 0
    for img in sorted((ds / "images").glob("*.png")):
        ann = json.loads((ds / "annotations" / f"{img.stem}.json").read_text())
        ok, errs = validate_sample(img, ann)
        total += 1
        if not ok:
            bad += 1
            print(f"BAD {img.name}: {errs}")
    dups = find_duplicates(ds / "images")
    print(f"validated {total}: bad={bad} ({bad/max(1,total)*100:.2f}%), duplicates={len(dups)}")
    if dups[:5]:
        for x, y in dups[:5]:
            print(f"  DUP {Path(x).name} == {Path(y).name}")
    if bad / max(1, total) > 0.01:
        print("FAIL: quality below threshold (max 1% bad)"); sys.exit(1)
    print("PASS")

if __name__ == "__main__":
    main()
