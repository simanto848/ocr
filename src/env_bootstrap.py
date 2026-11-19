"""Auto-bootstrap external-drive environment. Import FIRST in every entry point.

Derives OCR_ROOT from this file's location (repo root = parent of src/),
then pins ALL caches (HF, transformers, torch, doctr, pip, matplotlib, tmp,
Playwright, fonts) inside it — unless already set. Creates dirs.
This makes `python src/infer.py ...` work without `source ./env.sh`,
while `env.sh` remains the way to also fix PATH/python.
Idempotent, stdlib-only, never overrides explicit user settings.
"""
import os as _os
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
if not (_ROOT / "src").is_dir():  # fallback: walk up
    _r = _Path(__file__).resolve().parent
    while _r != _r.parent and not (_r / "src").is_dir():
        _r = _r.parent
    _ROOT = _r

_os.environ.setdefault("OCR_ROOT", str(_ROOT))
ROOT = _os.environ["OCR_ROOT"]

_DEFAULTS = {
    "PIP_CACHE_DIR": f"{ROOT}/.cache/pip",
    "HF_HOME": f"{ROOT}/.cache/huggingface",
    "HUGGINGFACE_HUB_CACHE": f"{ROOT}/.cache/huggingface/hub",
    "TRANSFORMERS_CACHE": f"{ROOT}/.cache/huggingface/hub",
    "HF_DATASETS_CACHE": f"{ROOT}/.cache/datasets",
    "TORCH_HOME": f"{ROOT}/.cache/torch",
    "TORCH_HUB": f"{ROOT}/.cache/torch/hub",
    "DOCTR_CACHE_DIR": f"{ROOT}/.cache/doctr",
    "FONTS_DIR": f"{ROOT}/fonts",
    "PLAYWRIGHT_BROWSERS_PATH": f"{ROOT}/.cache/ms-playwright",
    "XDG_CACHE_HOME": f"{ROOT}/.cache",
    "TMPDIR": f"{ROOT}/.cache/tmp",
    "MPLCONFIGDIR": f"{ROOT}/.cache/matplotlib",
}
for _k, _v in _DEFAULTS.items():
    _os.environ.setdefault(_k, _v)
    try:
        _Path(_os.environ[_k]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
if str(_Path(ROOT) / "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_Path(ROOT) / "src"))
