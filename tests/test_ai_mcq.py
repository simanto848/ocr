"""Tests for the AI provider registry and AI-backed MCQ extraction.

No network: provider HTTP is mocked at the `_request` boundary.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ai_mcq  # noqa: E402
import ai_providers  # noqa: E402
import mcq  # noqa: E402


@pytest.fixture(autouse=True)
def temp_config(tmp_path):
    old = ai_providers._CONFIG_PATH
    ai_providers.set_config_path(tmp_path / "ai_providers.json")
    yield
    ai_providers.set_config_path(old)


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #
def test_extract_json_plain_and_fenced():
    assert ai_mcq.extract_json('{"questions": []}') == {"questions": []}
    fenced = 'Here you go:\n```json\n{"questions": [1]}\n```\nThanks.'
    assert ai_mcq.extract_json(fenced) == {"questions": [1]}


def test_extract_json_tolerates_trailing_commas():
    raw = 'prefix {"questions": [{"number": 1,}],} trailing'
    assert ai_mcq.extract_json(raw)["questions"][0]["number"] == 1


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        ai_mcq.extract_json("I cannot answer that")


# --------------------------------------------------------------------------- #
# normalisation into canonical items
# --------------------------------------------------------------------------- #
def test_normalize_ai_result_basic():
    obj = {"questions": [{
        "number": 2,
        "question": "Which gas do plants absorb?",
        "options": [{"label": "A", "text": "Oxygen"},
                    {"label": "B", "text": "Carbon dioxide"},
                    {"label": "C", "text": "Nitrogen"},
                    {"label": "D", "text": "Hydrogen"}],
        "answer": "b",
        "explanation": "Photosynthesis uses CO2",
        "passage": "",
    }]}
    items = ai_mcq.normalize_ai_result(obj, {"page": 3, "filename": "q.pdf"})
    assert len(items) == 1
    it = items[0]
    assert it["answer"] == {"label": "B", "text": "Carbon dioxide", "index": 1}
    assert it["source"] == {"page": 3, "filename": "q.pdf"}
    assert it["explanation"] == "Photosynthesis uses CO2"
    assert it["needs_review"] is False
    assert it["language"] == "en"


def test_normalize_ai_result_indic_labels_and_answer_object():
    obj = [{"question": "রাজধানী কী?",
            "options": {"ক": "ঢাকা", "খ": "চট্টগ্রাম", "গ": "খুলনা"},
            "answer": {"label": "ক", "text": "ঢাকা"}}]
    items = ai_mcq.normalize_ai_result(obj)
    assert [o["label"] for o in items[0]["options"]] == ["A", "B", "C"]
    assert items[0]["answer"]["label"] == "A"
    assert items[0]["answer"]["text"] == "ঢাকা"
    assert items[0]["language"].startswith("bn")


def test_normalize_ai_result_skips_incomplete_rows():
    obj = {"questions": [
        {"question": "No options", "options": [{"label": "A", "text": "x"}]},
        {"question": "Good", "options": [{"label": "A", "text": "1"},
                                          {"label": "B", "text": "2"}], "answer": None},
    ]}
    items = ai_mcq.normalize_ai_result(obj)
    assert len(items) == 1
    assert items[0]["answer"] is None
    assert items[0]["needs_review"] is True


def test_merge_items_fills_missing_answer_from_ai():
    heur = mcq.parse_text(
        "1. Capital of France?\nA) Berlin\nB) Paris\n")["items"]
    assert heur[0]["answer"] is None
    ai = ai_mcq.normalize_ai_result({"questions": [{
        "question": "Capital of France?",
        "options": [{"label": "A", "text": "Berlin"}, {"label": "B", "text": "Paris"}],
        "answer": "B", "explanation": "Paris is the capital",
    }]})
    merged = ai_mcq.merge_items(heur, ai)
    assert len(merged) == 1
    assert merged[0]["answer"]["label"] == "B"
    assert merged[0]["explanation"] == "Paris is the capital"
    assert merged[0]["needs_review"] is False


def test_merge_items_keeps_heuristic_answer():
    heur = mcq.parse_text(
        "1. Capital of France?\nA) Berlin\nB) Paris\nAnswer: A\n")["items"]
    ai = ai_mcq.normalize_ai_result({"questions": [{
        "question": "Capital of France?",
        "options": [{"label": "A", "text": "Berlin"}, {"label": "B", "text": "Paris"}],
        "answer": "B",
    }]})
    merged = ai_mcq.merge_items(heur, ai)
    assert merged[0]["answer"]["label"] == "A"


# --------------------------------------------------------------------------- #
# provider registry
# --------------------------------------------------------------------------- #
def test_builtin_provider_list_masks_keys():
    providers = ai_providers.list_providers()
    ids = {p["id"] for p in providers}
    assert {"ollama", "nvidia", "openrouter", "opencode", "custom_x"} - ids == {"custom_x"}
    assert all("api_key" not in p for p in providers)
    assert all("has_key" in p for p in providers)


def test_custom_provider_crud():
    entry = ai_providers.add_custom({
        "name": "My LLM", "base_url": "https://llm.example/v1/",
        "kind": "openai", "api_key": "secret", "default_model": "my-model",
    })
    assert entry["has_key"] is True
    providers = {p["id"]: p for p in ai_providers.list_providers()}
    p = providers[entry["id"]]
    assert p["base_url"] == "https://llm.example/v1"  # trailing slash stripped
    assert "api_key" not in p
    resolved = ai_providers.resolve(entry["id"])
    assert resolved["api_key"] == "secret"
    assert ai_providers.configure(entry["id"], {"api_key": "new"})["has_key"] is True
    assert ai_providers.resolve(entry["id"])["api_key"] == "new"
    assert ai_providers.remove_custom(entry["id"]) is True
    assert ai_providers.remove_custom(entry["id"]) is False


def test_custom_provider_rejects_bad_url():
    with pytest.raises(ValueError):
        ai_providers.add_custom({"name": "x", "base_url": "not-a-url"})


def test_configure_builtin_key_and_url():
    ai_providers.configure("ollama", {"base_url": "http://myhost:11434",
                                      "api_key": "local-token"})
    p = next(x for x in ai_providers.list_providers() if x["id"] == "ollama")
    assert p["base_url"] == "http://myhost:11434"
    assert p["has_key"] is True
    assert ai_providers.resolve("ollama")["api_key"] == "local-token"


# --------------------------------------------------------------------------- #
# provider adapters (mocked HTTP)
# --------------------------------------------------------------------------- #
def test_openai_chat_and_models(monkeypatch):
    calls = []

    def fake(url, data=None, headers=None, timeout=None, method=None):
        calls.append((url, data, headers))
        if url.endswith("/models"):
            return {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]}
        return {"choices": [{"message": {"content": '{"questions": []}'}}]}

    monkeypatch.setattr(ai_providers, "_request", fake)
    ai_providers.configure("openai", {"api_key": "sk-test"})
    text = ai_providers.chat("openai", "gpt-4o-mini", "hello", system="sys")
    assert text == '{"questions": []}'
    assert calls[0][2]["Authorization"] == "Bearer sk-test"
    assert calls[0][1]["model"] == "gpt-4o-mini"
    assert calls[0][1]["messages"][0]["role"] == "system"
    models = ai_providers.fetch_models("openai")
    assert [m["id"] for m in models] == ["gpt-4o-mini", "gpt-4o"]


def test_ollama_chat_and_models(monkeypatch):
    calls = []

    def fake(url, data=None, headers=None, timeout=None, method=None):
        calls.append(url)
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.2"}, {"name": "qwen2.5:7b"}]}
        return {"message": {"content": '{"questions": []}'}}

    monkeypatch.setattr(ai_providers, "_request", fake)
    text = ai_providers.chat("ollama", "llama3.2", "hello")
    assert text == '{"questions": []}'
    assert calls == ["http://127.0.0.1:11434/api/chat"]
    assert [m["id"] for m in ai_providers.fetch_models("ollama")] == ["llama3.2", "qwen2.5:7b"]


def test_opencode_chat_uses_v2_generate_endpoint(monkeypatch):
    calls = []

    def fake(url, data=None, headers=None, timeout=None, method=None):
        calls.append((url, data))
        if url.endswith("/api/model"):
            return {"data": [{"providerID": "anthropic", "modelID": "claude-x",
                              "name": "Claude X"}]}
        return {"data": {"text": '{"questions": []}'}}

    monkeypatch.setattr(ai_providers, "_request", fake)
    text = ai_providers.chat("opencode", "anthropic/claude-x", "hello")
    assert text == '{"questions": []}'
    url, body = calls[0]
    assert url.endswith("/api/experimental/generate/text")
    assert body["model"] == {"providerID": "anthropic", "id": "claude-x"}
    assert body["prompt"] == "hello"
    models = ai_providers.fetch_models("opencode")
    assert models == [{"id": "anthropic/claude-x", "label": "Claude X"}]


def test_test_provider_reports_errors(monkeypatch):
    def fake(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ai_providers, "_request", fake)
    result = ai_providers.test_provider("ollama")
    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_extract_mcq_uses_chunks_and_progress(monkeypatch):
    seen = []

    def fake_chat(pid, model, prompt, system="", overrides=None, timeout=None):
        seen.append(prompt)
        return json.dumps({"questions": [{
            "number": 1, "question": "Q from chunk?",
            "options": [{"label": "A", "text": "yes"}, {"label": "B", "text": "no"}],
            "answer": "A",
        }]})

    monkeypatch.setattr(ai_providers, "chat", fake_chat)
    progress = []
    pages = [{"page": 1, "text": "x" * 1000}, {"page": 2, "text": "y" * 1000}]
    result = ai_mcq.extract_mcq(pages, "ollama", "llama3.2", "auto",
                               on_progress=lambda i, n: progress.append((i, n)))
    assert result["chunks"] == 1
    assert len(result["items"]) == 1
    assert progress == [(1, 1)]
    assert "--- PAGE 1 ---" in seen[0]
