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
    import ai_providers

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    ai_providers.set_config_path(tmp_path / "ai_providers.json")
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs)
    monkeypatch.setattr(webapp, "INDEX_JSON", tmp_path / "jobs.json")
    monkeypatch.setattr(webapp, "API_KEY", "")
    monkeypatch.setattr(webapp, "CORS_ORIGINS", [])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", jobs
    ai_providers.set_config_path(None)
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


MCQ_TEXT = """\
1. What is the capital of France?
A) Berlin
B) Madrid
C) Paris
D) Rome
Answer: C

2. Which gas do plants absorb?
A) Oxygen
B) Carbon dioxide
C) Nitrogen
D) Hydrogen
Ans: B
"""


def _make_done_job(jobs: Path, jid="abc123def456"):
    jdir = jobs / jid
    jdir.mkdir()
    job = {
        "job_id": jid, "filename": "quiz.pdf", "stored": "upload.pdf",
        "status": "done", "lang": "eng", "ocr_engine": "tesseract",
        "kind": "ocr", "answer_mode": "auto", "n_pages": 1,
        "created": "2026-01-01 00:00:00",
        "progress": {"stage": "done", "page": 1, "of": 1, "percent": 100},
        "pages": [{"page": 1, "text": MCQ_TEXT, "source": "tesseract"}],
        "markdown": "# quiz.pdf\n",
        "result_json": {"file": "quiz.pdf", "pages": []},
    }
    (jdir / "result.json").write_text(json.dumps(job))
    return jid


def test_mcq_build_from_existing_job(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    r = requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=10)
    assert r.status_code == 200
    ds = r.json()["dataset"]
    assert len(ds["items"]) == 2
    assert ds["items"][0]["answer"]["label"] == "C"
    assert ds["manifest"]["stats"]["with_answer"] == 2
    assert (jobs / jid / "mcq" / "rag.jsonl").is_file()


def test_mcq_get_job_returns_dataset(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=10)
    r = requests.get(base + "/api/mcq/job", params={"id": jid}, timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["job_id"] == jid
    assert len(body["dataset"]["items"]) == 2
    assert body["dataset"]["manifest"]["files"]["rag"] == "rag.jsonl"


def test_mcq_item_edit_persists_and_reexports(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=10)
    ds = requests.get(base + "/api/mcq/job", params={"id": jid}, timeout=5).json()["dataset"]
    item = ds["items"][1]
    r = requests.post(base + "/api/mcq/item", json={
        "job_id": jid, "item_id": item["id"],
        "question": "Edited question?", "answer": "D",
    }, timeout=10)
    assert r.status_code == 200
    assert r.json()["item"]["question"] == "Edited question?"
    assert r.json()["item"]["answer"]["label"] == "D"
    # the export on disk reflects the edit, not the original
    rag = (jobs / jid / "mcq" / "rag.jsonl").read_text()
    assert "Edited question?" in rag


def test_mcq_item_rejects_unknown_item(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=10)
    r = requests.post(base + "/api/mcq/item", json={
        "job_id": jid, "item_id": "mcq_9999", "answer": "A"}, timeout=5)
    assert r.status_code == 404


def test_mcq_download_formats(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=10)
    for fmt in ("rag", "sft", "csv", "zip"):
        r = requests.get(base + "/api/mcq/download",
                         params={"id": jid, "format": fmt}, timeout=10)
        assert r.status_code == 200, fmt
        assert r.content
    bad = requests.get(base + "/api/mcq/download",
                       params={"id": jid, "format": "exe"}, timeout=5)
    assert bad.status_code == 400
    assert requests.get(base + "/api/mcq/download",
                        params={"id": "../jobs", "format": "rag"}, timeout=5).status_code == 404


def test_mcq_build_rejects_non_done_job(server):
    base, jobs = server
    jid = _make_done_job(jobs)
    p = jobs / jid / "result.json"
    job = json.loads(p.read_text())
    job["status"] = "processing"
    p.write_text(json.dumps(job))
    r = requests.post(base + "/api/mcq/build", json={"job_id": jid}, timeout=5)
    assert r.status_code == 409


def test_mcq_upload_kind_field(server):
    base, jobs = server
    r = requests.post(base + "/api/upload",
                      files={"file": ("quiz.txt", MCQ_TEXT.encode(), "text/plain")},
                      data={"kind": "mcq", "answer_mode": "auto",
                            "engine": "tesseract"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["jobs"][0]["kind"] == "mcq"
    jid = r.json()["job_ids"][0]
    import time
    for _ in range(80):
        state = requests.get(base + "/api/job", params={"id": jid}, timeout=5).json()
        if state.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    assert state.get("status") == "done"
    assert state.get("mcq", {}).get("stats", {}).get("included") == 2
    assert (jobs / jid / "mcq" / "manifest.json").is_file()


def test_ai_providers_endpoint_lists_builtins_without_keys(server):
    base, _ = server
    r = requests.get(base + "/api/ai/providers", timeout=5)
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()["providers"]}
    assert {"ollama", "nvidia", "openrouter", "opencode", "openai"}.issubset(ids)
    assert all("api_key" not in p for p in r.json()["providers"])


def test_ai_custom_provider_crud_via_api(server):
    base, _ = server
    r = requests.post(base + "/api/ai/provider", json={
        "name": "Local LLM", "base_url": "https://llm.example/v1",
        "kind": "openai", "api_key": "sk-xyz",
    }, timeout=5)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["has_key"] is True
    assert "api_key" not in r.json()
    providers = requests.get(base + "/api/ai/providers", timeout=5).json()["providers"]
    assert not any("api_key" in p for p in providers)
    assert requests.post(base + "/api/ai/provider/configure", json={
        "id": pid, "api_key": "sk-new"}, timeout=5).status_code == 200
    assert requests.post(base + "/api/ai/provider/delete", json={
        "id": pid}, timeout=5).status_code == 200
    assert requests.post(base + "/api/ai/provider/delete", json={
        "id": pid}, timeout=5).status_code == 404


def test_ai_models_and_test_endpoints(server, monkeypatch):
    import ai_providers
    base, _ = server
    monkeypatch.setattr(ai_providers, "fetch_models", lambda *a, **k: [
        {"id": "llama3.2", "label": "Llama 3.2"}])
    monkeypatch.setattr(ai_providers, "test_provider",
                        lambda *a, **k: {"ok": True, "models": 1, "sample": "OK"})
    r = requests.post(base + "/api/ai/models", json={"provider": "ollama"}, timeout=5)
    assert r.status_code == 200
    assert r.json()["models"][0]["id"] == "llama3.2"
    r = requests.post(base + "/api/ai/test", json={
        "provider": "ollama", "model": "llama3.2"}, timeout=5)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_mcq_build_with_ai_mode_hybrid(server, monkeypatch):
    import ai_mcq
    base, jobs = server
    jid = _make_done_job(jobs)
    monkeypatch.setattr(ai_mcq, "extract_mcq", lambda *a, **k: {
        "items": [{
            "id": "", "uid": "ai-uid", "number": 1,
            "question": "What is the capital of France?",
            "options": [{"label": "A", "text": "Berlin"},
                        {"label": "B", "text": "Madrid"},
                        {"label": "C", "text": "Paris"},
                        {"label": "D", "text": "Rome"}],
            "answer": {"label": "C", "text": "Paris", "index": 2},
            "explanation": "AI explanation", "passage": "",
            "language": "en", "confidence": 0.9, "needs_review": False,
            "include": True, "source": {"page": 1}, "raw": "",
        }], "warnings": [], "chunks": 1})
    r = requests.post(base + "/api/mcq/build", json={
        "job_id": jid, "ai_mode": "hybrid",
        "ai_provider": "ollama", "ai_model": "llama3.2",
    }, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["mcq"]["method"] == "hybrid"
    assert body["job"]["mcq"]["ai"]["provider"] == "ollama"
    assert len(body["dataset"]["items"]) == 2  # Q1 merged, Q2 from heuristic
    assert body["dataset"]["items"][0]["explanation"] == "AI explanation"


def test_page_image_endpoint(server):
    from PIL import Image
    base, jobs = server
    jid = _make_done_job(jobs)
    (jobs / jid / "pages").mkdir()
    Image.new("RGB", (40, 60), "white").save(jobs / jid / "pages" / "page_001.png")
    r = requests.get(base + "/api/page-image", params={"job": jid, "page": 1}, timeout=5)
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert requests.get(base + "/api/page-image",
                        params={"job": "../jobs", "page": 1}, timeout=5).status_code == 404
