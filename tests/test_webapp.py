"""Security + API tests for the stdlib web server (no real OCR needed)."""
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "web"))


@pytest.fixture
def server(tmp_path, monkeypatch):
    import app as webapp

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs)
    monkeypatch.setattr(webapp, "INDEX_JSON", tmp_path / "jobs.json")
    monkeypatch.setattr(webapp, "API_KEY", "")
    monkeypatch.setattr(webapp, "CORS_ORIGINS", [])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", jobs
    srv.shutdown()
    srv.server_close()
    t.join(timeout=3)


def test_status_and_history(server):
    base, _ = server
    r = requests.get(base + "/api/status", timeout=5)
    assert r.status_code == 200
    assert r.json()["languages"] == ["eng", "ben", "hin"]
    assert requests.get(base + "/api/history", timeout=5).json() == []


def test_job_id_validation_blocks_traversal(server):
    """../jobs must not resolve to the jobs directory itself."""
    base, jobs = server
    (jobs / "victim").mkdir()
    (jobs / "victim" / "result.json").write_text("{}")
    for path in ("/api/job", "/api/preview", "/api/download"):
        assert requests.get(base + path, params={"id": "../jobs", "job": "../jobs"},
                            timeout=5).status_code == 404
    assert requests.post(base + "/api/delete", params={"id": "../jobs"},
                         timeout=5).status_code == 404
    assert requests.delete(base + "/api/job", params={"id": "../../etc"},
                           timeout=5).status_code == 404
    assert (jobs / "victim" / "result.json").exists(), "a sibling job was deleted!"


def test_upload_delete_roundtrip(server):
    base, jobs = server
    r = requests.post(base + "/api/upload",
                      files={"file": ("note.txt", b"hello", "text/plain")},
                      data={"lang": "en", "engine": "tesseract"}, timeout=10)
    assert r.status_code == 200
    jid = r.json()["job_ids"][0]
    assert len(jid) == 12
    assert (jobs / jid / "upload.txt").exists()
    # Wait for the background thread to finish before tmp_path is torn down.
    import time
    for _ in range(60):
        state = requests.get(base + "/api/job", params={"id": jid}, timeout=5).json()
        if state.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert state.get("status") == "done"
    assert requests.post(base + "/api/delete", params={"id": jid}, timeout=5).status_code == 200
    assert not (jobs / jid).exists()


def test_api_key_required_when_set(server, monkeypatch):
    import app as webapp
    base, _ = server
    monkeypatch.setattr(webapp, "API_KEY", "secret123")
    assert requests.get(base + "/api/history", timeout=5).status_code == 401
    assert requests.get(base + "/api/history", headers={"X-API-Key": "secret123"},
                        timeout=5).status_code == 200
    assert requests.get(base + "/api/history", headers={"Authorization": "Bearer secret123"},
                        timeout=5).status_code == 200


def test_csrf_origin_rejected(server, monkeypatch):
    import app as webapp
    base, jobs = server
    monkeypatch.setattr(webapp, "API_KEY", "secret123")
    r = requests.post(base + "/api/delete", params={"id": "a" * 12},
                      headers={"X-API-Key": "secret123",
                               "Origin": "https://evil.example"}, timeout=5)
    assert r.status_code == 401
