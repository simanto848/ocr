"""Client for the local PaddleOCR-VL service (see vlm_service.py).

The service runs in a separate venv (.venv-paddle) so PaddlePaddle cannot
conflict with the training stack in .venv. The main web app talks to it over
a tiny localhost HTTP API. When the service is not running, callers simply
fall back to Tesseract — the app keeps working either way.
"""
import env_bootstrap  # noqa: F401

import os
import requests

DEFAULT_URL = os.environ.get("VLM_SERVICE_URL", "http://127.0.0.1:8090")
_TIMEOUT = (5, 600)  # (connect, read) — first page loads the VLM weights


def available(url: str = DEFAULT_URL) -> bool:
    try:
        r = requests.get(url.rstrip("/") + "/health", timeout=_TIMEOUT[0])
        return r.status_code == 200 and bool(r.json().get("ready"))
    except Exception:
        return False


def status(url: str = DEFAULT_URL) -> dict:
    try:
        r = requests.get(url.rstrip("/") + "/health", timeout=_TIMEOUT[0])
        return r.json() if r.status_code == 200 else {"ready": False}
    except Exception as e:
        return {"ready": False, "error": str(e)}


def ocr_image(path: str, url: str = DEFAULT_URL) -> dict:
    """OCR one image; returns {'text', 'markdown', 'engine', 'elapsed'}."""
    r = requests.post(
        url.rstrip("/") + "/ocr",
        json={"image": os.path.abspath(path)},
        timeout=_TIMEOUT,
    )
    if r.status_code != 200:
        try:
            msg = r.json().get("error")
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"VLM service error: {msg or r.status_code}")
    return r.json()
