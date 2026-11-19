"""python -m dataset.stats --dataset data/v001"""
import argparse, json
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
ROOT = Path(os.environ.get("OCR_ROOT", str(Path(__file__).resolve().parents[1])))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    a = ap.parse_args()
    ds = ROOT / a.dataset if not str(a.dataset).startswith(str(ROOT)) else Path(a.dataset)
    import sys
    sys.path.insert(0, str(ROOT))
    from dataset.validation.statistics import compute_stats
    manifests = [json.loads(p.read_text()) for p in sorted((ds / "metadata").glob("*.json"))]
    stats = compute_stats(manifests)
    (ds / "dataset_statistics.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    html = "<html><body><h1>Dataset statistics: " + ds.name + "</h1><pre>" + json.dumps(stats, indent=2, ensure_ascii=False) + "</pre></body></html>"
    (ds / "dataset_statistics.html").write_text(html)
    print(json.dumps(stats, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
