"""python -m dataset.fonts.scan [--extra DIR]"""
import argparse
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)
from .scanner import scan

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", action="append", default=[])
    a = ap.parse_args()
    scan(extra_dirs=a.extra)

if __name__ == "__main__":
    main()
