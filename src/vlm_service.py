"""Local PaddleOCR-VL OCR service.

Runs in .venv-paddle (PaddlePaddle stack isolated from the training venv):

    cd /Volumes/SSD-SIMANTO/works/ocr
    PADDLE_PDX_CACHE_HOME=$PWD/.cache/paddlex \
      .venv-paddle/bin/python -u src/vlm_service.py --port 8090

Endpoints:
    GET  /health -> {"ready": bool, "engine": "...", "model": "..."}
    POST /ocr    JSON {"image": "/abs/path.png"} -> {"text", "markdown", "elapsed"}
"""
import argparse
import json
import os
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(ROOT / ".cache" / "paddlex"))
os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", "4")

_pipe = None
_pipe_lock = threading.Lock()
MODEL = os.environ.get("VLM_MODEL", "PaddlePaddle/PaddleOCR-VL-1.6")


def get_pipe():
    global _pipe
    if _pipe is None:
        with _pipe_lock:
            if _pipe is None:
                from paddleocr import PaddleOCRVL
                print(f"[vlm] loading {MODEL} ...", flush=True)
                _pipe = PaddleOCRVL()
                print("[vlm] ready", flush=True)
    return _pipe


def _result_to_markdown(res, tmp_dir: Path) -> str:
    """Pull Markdown from a PaddleOCR result object using several fallbacks."""
    # 1) direct attribute — may be a string or a dict with 'markdown_texts'
    md = getattr(res, "markdown", None)
    if isinstance(md, str) and md.strip():
        return md.strip()
    if isinstance(md, dict):
        text = md.get("markdown_texts") or md.get("markdown") or md.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    # 2) dict-style json → gather text fields (PaddleOCR 3.x shape)
    data = getattr(res, "json", None)
    if callable(data):
        try:
            data = data()
        except Exception:
            data = None
    if isinstance(data, dict):
        texts = []
        for key in ("markdown_texts", "markdown", "text", "rec_text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                texts.append(val.strip())
        if texts:
            return "\n".join(texts)
        # fall back to per-block text in parsing_res_list
        blocks = (data.get("res") or {}).get("parsing_res_list") or []
        block_texts = [b.get("block_content", "").strip() for b in blocks
                       if isinstance(b, dict) and b.get("block_content", "").strip()]
        if block_texts:
            return "\n\n".join(block_texts)
    # 3) save_to_markdown writes a file we can read
    try:
        res.save_to_markdown(save_path=str(tmp_dir))
        files = sorted(tmp_dir.glob("*.md"))
        if files:
            text = files[-1].read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def ocr(image_path: str) -> dict:
    if not os.path.isfile(image_path):
        raise FileNotFoundError(image_path)
    started = time.time()
    pipe = get_pipe()
    with tempfile.TemporaryDirectory() as td:
        out = pipe.predict(image_path)
        markdown = "\n\n".join(
            m for res in (out or []) if (m := _result_to_markdown(res, Path(td)))
        ).strip()
    return {
        "text": markdown,
        "markdown": markdown,
        "engine": f"PaddleOCR-VL ({MODEL})",
        "elapsed": round(time.time() - started, 2),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "VLM OCR/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {"ready": _pipe is not None, "model": MODEL,
                             "engine": "PaddleOCR-VL"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/ocr":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
            image = payload.get("image", "")
            result = ocr(image)
            self._send(200, result)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    # Build in the MAIN thread: PaddleX's static-graph engine is not reliably
    # initialised from a request handler thread. Inference then runs per request.
    get_pipe()
    print(f"[vlm] OCR service → http://{args.host}:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
