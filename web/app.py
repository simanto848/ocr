"""Universal document text-extraction web service (upload | preview | Markdown/JSON).

Accepts PDF, DOC, DOCX, RTF, ODT, TXT, HTML, images (png/jpg/webp/tif/...).
Digital text is read directly; scanned pages/images use Tesseract OCR with
English + Bangla + Hindi language data (selectable per upload).

  GET  /                        → UI
  GET  /static/<file>           → css/js
  GET  /api/status              → engine, languages, formats
  POST /api/upload              → multipart "file" (+ optional "lang") → {job_id}
  GET  /api/history             → [{job_id, filename, ...}] newest first
  GET  /api/job?id=...          → full job incl. markdown/json (when done)
  GET  /api/preview?job=..&page=N → PNG page render
  GET  /api/download?job=..&format=md|json|txt → attachment
  DELETE /api/job?id=... (or POST /api/delete?id=...) → remove job + files

Usage:
  source ./env.sh && python web/app.py --port 8000
"""
import sys as _sys
from pathlib import Path as _Path
_r = _Path(__file__).resolve().parent
while not (_r / "src" / "env_bootstrap.py").exists():
    if _r == _r.parent:
        break
    _r = _r.parent
_sys.path.insert(0, str(_r / "src"))
import env_bootstrap  # noqa: F401,E402  (pins all caches to external drive)

import argparse
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Universal extractor (direct text for digital docs, VLM/Tesseract for scans).
from extract import SUPPORTED as ALLOWED, LANG_LABELS, _tesseract_version
from vlm_client import status as vlm_status

ROOT = _Path(os.environ["OCR_ROOT"])
WEB_DIR = ROOT / "outputs" / "web"
JOBS_DIR = WEB_DIR / "jobs"
INDEX_JSON = WEB_DIR / "jobs.json"
MAX_UPLOAD = 100 * 1024 * 1024
_lock = threading.Lock()


def _read_index():
    try:
        return json.loads(INDEX_JSON.read_text())
    except Exception:
        return []


def _atomic_write(path: _Path, text: str):
    """Write via a sibling temp file + rename so readers never see partial JSON."""
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _write_index(jobs):
    _atomic_write(INDEX_JSON, json.dumps(jobs, indent=1))


def _save_job(job):
    _atomic_write(JOBS_DIR / job["job_id"] / "result.json",
                  json.dumps(job, ensure_ascii=False, indent=1))
    with _lock:
        jobs = [j for j in _read_index() if j["job_id"] != job["job_id"]]
        jobs.insert(0, {k: job[k] for k in ("job_id", "filename", "status", "pages", "created",
                                            "error", "progress", "n_pages", "lang",
                                            "engine", "ocr_engine")
                        if k in job})
        _write_index(jobs)


def _parse_multipart(body: bytes, boundary: bytes):
    """Return (files, fields) where files is a list of (filename, bytes) (RFC 7578)."""
    files, fields = [], {}
    chunks = body.split(b"--" + boundary)
    for chunk in chunks[1:]:
        if chunk.startswith(b"--"):
            continue  # epilogue
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        m = re.search(br'filename="([^"]*)"', head)
        if not m:
            name = re.search(br'name="([^"]*)"', head)
            if name and data.endswith(b"\r\n"):
                fields[name.group(1).decode("utf-8", "ignore")] = data[:-2].decode("utf-8", "ignore")
            continue
        fname = os.path.basename(m.group(1).decode("utf-8", "ignore")) or "upload"
        if data.endswith(b"\r\n"):  # CRLF belongs to the delimiter, not the file
            data = data[:-2]
        files.append((fname, data))
    return files, fields


def _downscale_preview(src: _Path, dst: _Path, max_w: int = 1000):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    im.save(dst, "PNG")


def _to_markdown(filename, pages):
    lines = [f"# {filename}", ""]
    for pg in pages:
        lines.append(f"## Page {pg['page']}")
        lines.append("")
        lines.append(pg["text"] if pg["text"].strip() else "_(no text detected)_")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _set_progress(job, stage, page=0, of=0, percent=0):
    job["progress"] = {"stage": stage, "page": page, "of": of, "percent": percent}
    _save_job(job)


def _process_job(job_id: str):
    job_path = JOBS_DIR / job_id / "result.json"
    job = json.loads(job_path.read_text())
    from extract import extract_file
    try:
        upload = JOBS_DIR / job_id / job["stored"]
        pages_dir = JOBS_DIR / job_id / "pages"
        prev_dir = JOBS_DIR / job_id / "preview"
        pages_dir.mkdir(exist_ok=True)
        prev_dir.mkdir(exist_ok=True)

        job["status"] = "processing"
        _set_progress(job, "preparing", 0, 0, 1)

        def _cb(i, n, stage):
            if stage == "rendering":
                pct = round(1 + 9 * (i - 1) / max(1, n), 1)
            else:  # ocr
                pct = round(10 + 90 * (i - 1) / max(1, n), 1)
            _set_progress(job, stage, i, n, pct)

        result = extract_file(upload, lang=job.get("lang", "auto"),
                              out_dir=pages_dir, on_page=_cb,
                              ocr_engine=job.get("ocr_engine", "auto"))
        pages = result["pages"]
        # Build previews as soon as each page image exists.
        for pg in pages:
            render = pages_dir / pg["render"] if pg.get("render") else None
            if render and render.is_file():
                _downscale_preview(render, prev_dir / f"page_{pg['page']:03d}.png")
            _set_progress(job, "ocr", pg["page"], len(pages),
                          round(10 + 90 * pg["page"] / max(1, len(pages)), 1))

        for pg in pages:
            pg.pop("render", None)  # internal filename not part of the API result
        job["pages"] = pages
        job["n_pages"] = len(pages)
        job["markdown"] = _to_markdown(job["filename"], pages)
        job["engine"] = result["engine"]
        job["ocr_engine"] = job.get("ocr_engine", "auto")
        job["ocr_langs"] = result["ocr_langs"]
        job["language"] = result["language"]
        job["result_json"] = {"file": job["filename"], "language": result["language"],
                              "engine": result["engine"], "pages": pages}
        job["status"] = "done"
        _set_progress(job, "done", len(pages), len(pages), 100)
        job.pop("error", None)
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    _save_job(job)


class Handler(BaseHTTPRequestHandler):
    server_version = "OCRWeb/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def _delete_job(self, jid):
        """Remove a job's directory on disk and its entry in the index."""
        jdir = (JOBS_DIR / jid).resolve()
        # Safety: only delete inside our jobs directory.
        if not jid or not str(jdir).startswith(str(JOBS_DIR.resolve())) or not jdir.is_dir():
            return self._json({"error": "unknown job"}, 404)
        try:
            shutil.rmtree(jdir)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"could not delete files: {e}"}, 500)
        with _lock:
            jobs = [j for j in _read_index() if j.get("job_id") != jid]
            _write_index(jobs)
        return self._json({"ok": True, "job_id": jid})

    def do_DELETE(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/job":
            return self._delete_job((q.get("id") or [""])[0])
        self._json({"error": "not found"}, 404)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self._send(200, (WEB_DIR.parent.parent / "web" / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif u.path.startswith("/static/"):
            f = (ROOT / "web" / u.path[1:]).resolve()
            if not str(f).startswith(str(ROOT / "web")) or not f.is_file():
                return self._json({"error": "not found"}, 404)
            self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        elif u.path == "/api/status":
            vlm = vlm_status()
            self._json({"engine": _tesseract_version(),
                        "vlm": vlm,
                        "languages": ["eng", "ben", "hin"],
                        "language_labels": LANG_LABELS,
                        "formats": sorted(ALLOWED),
                        "max_upload_mb": MAX_UPLOAD // (1024 * 1024)})
        elif u.path == "/api/history":
            self._json(_read_index())
        elif u.path == "/api/job":
            jid = (q.get("id") or [""])[0]
            p = JOBS_DIR / jid / "result.json"
            if not jid or not p.is_file():
                return self._json({"error": "unknown job"}, 404)
            self._json(json.loads(p.read_text()))
        elif u.path == "/api/preview":
            jid = (q.get("job") or [""])[0]
            try:
                n = int((q.get("page") or ["1"])[0])
            except ValueError:
                n = 1
            p = JOBS_DIR / jid / "preview" / f"page_{n:03d}.png"
            if not p.is_file():
                return self._json({"error": "no preview yet"}, 404)
            self._send(200, p.read_bytes(), "image/png")
        elif u.path == "/api/download":
            jid = (q.get("job") or [""])[0]
            fmt = (q.get("format") or ["md"])[0]
            p = JOBS_DIR / jid / "result.json"
            if not p.is_file():
                return self._json({"error": "unknown job"}, 404)
            job = json.loads(p.read_text())
            if job.get("status") != "done":
                return self._json({"error": "job not done"}, 409)
            base = _Path(job["filename"]).stem
            if fmt == "json":
                body, name, ct = (json.dumps(job["result_json"], ensure_ascii=False, indent=2).encode(),
                                  f"{base}.ocr.json", "application/json")
            elif fmt == "txt":
                body, name, ct = ("\n\n".join(pg["text"] for pg in job["pages"]).encode(),
                                  f"{base}.txt", "text/plain; charset=utf-8")
            else:
                body, name, ct = (job["markdown"].encode(), f"{base}.md", "text/markdown; charset=utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/api/delete":
            q = parse_qs(u.query)
            return self._delete_job((q.get("id") or [""])[0])
        if u.path != "/api/upload":
            return self._json({"error": "not found"}, 404)
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype or "boundary=" not in ctype:
            return self._json({"error": "expected multipart upload with field 'file'"}, 400)
        boundary = ctype.split("boundary=")[-1].strip().strip('"').encode()
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        # Allow up to 10 files per request; each file capped at MAX_UPLOAD.
        if length <= 0 or length > 10 * (MAX_UPLOAD + 1024 * 1024):
            return self._json({"error": f"empty or too large (max 10 files × {MAX_UPLOAD // (1024 * 1024)}MB)"}, 400)
        body = self.rfile.read(length)
        files, fields = _parse_multipart(body, boundary)
        if not files:
            return self._json({"error": "no file part found"}, 400)
        lang = (fields.get("lang") or "auto").strip()
        engine = (fields.get("engine") or "auto").strip()
        if engine not in {"auto", "vlm", "tesseract"}:
            engine = "auto"

        job_ids, jobs_meta, errors = [], [], []
        for fname, data in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED or not data:
                errors.append({"filename": fname,
                               "error": f"unsupported type '{ext or 'none'}'"})
                continue
            if len(data) > MAX_UPLOAD:
                errors.append({"filename": fname, "error": "file exceeds 100 MB"})
                continue
            job_id = uuid.uuid4().hex[:12]
            jdir = JOBS_DIR / job_id
            jdir.mkdir(parents=True, exist_ok=True)
            stored = f"upload{ext}"
            (jdir / stored).write_bytes(data)
            job = {"job_id": job_id, "filename": fname, "stored": stored,
                   "lang": lang, "ocr_engine": engine, "status": "queued",
                   "pages": [], "n_pages": 0,
                   "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "progress": {"stage": "queued", "page": 0, "of": 0, "percent": 0}}
            _save_job(job)
            threading.Thread(target=_process_job, args=(job_id,), daemon=True).start()
            job_ids.append(job_id)
            jobs_meta.append({"job_id": job_id, "filename": fname})
        if not job_ids:
            return self._json({"error": "none of the files were supported", "errors": errors}, 400)
        # `job_id` kept for backwards compatibility with single-file clients.
        self._json({"job_id": job_ids[0], "job_ids": job_ids,
                    "jobs": jobs_meta, "errors": errors})


def _recover_stale_jobs():
    """Jobs stuck in queued/processing from a previous (dead) server can never
    finish — their worker threads are gone. Fail them loudly instead of showing
    'processing' forever."""
    try:
        index = _read_index()
    except Exception:
        return
    changed = False
    for entry in index:
        if entry.get("status") in ("queued", "processing"):
            p = JOBS_DIR / entry["job_id"] / "result.json"
            try:
                job = json.loads(p.read_text())
            except Exception:
                continue
            if job.get("status") in ("queued", "processing"):
                job["status"] = "error"
                job["error"] = "server restarted during processing — please re-upload"
                p.write_text(json.dumps(job, ensure_ascii=False, indent=1))
                entry["status"] = "error"
                entry["error"] = job["error"]
                changed = True
    if changed:
        _write_index(index)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _recover_stale_jobs()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"OCR web app → http://{a.host}:{a.port}  (storage: {WEB_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
