"""AI provider registry for MCQ extraction.

All network calls use the standard library. API keys are stored **server side**
in ``outputs/web/ai_providers.json`` and are never echoed to the browser: the
API only returns ``has_key`` flags.

Provider kinds
--------------
``openai``   OpenAI-compatible ``POST /chat/completions`` — covers OpenAI,
             NVIDIA NIM, OpenRouter, Groq, Together, DeepSeek, Mistral, xAI,
             vLLM, LM Studio and any custom OpenAI-compatible endpoint.
``ollama``   Ollama's ``POST /api/chat`` + ``GET /api/tags``.
``opencode`` OpenCode V2's ``POST /api/experimental/generate/text`` +
             ``GET /api/model`` (stateless generation, no session needed).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = float(os.environ.get("OCR_AI_TIMEOUT", "120"))

# id, display name, base URL, kind, needs key, default model, hint
BUILTIN = [
    {"id": "ollama", "name": "Ollama (local)", "base_url": "http://127.0.0.1:11434",
     "kind": "ollama", "key_required": False, "default_model": "llama3.2",
     "hint": "Runs on your machine. Start with: ollama serve"},
    {"id": "nvidia", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1",
     "kind": "openai", "key_required": True, "default_model": "meta/llama-3.3-70b-instruct",
     "hint": "NVIDIA API key from build.nvidia.com"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "kind": "openai", "key_required": True, "default_model": "openai/gpt-4o-mini",
     "hint": "One key for hundreds of models"},
    {"id": "opencode", "name": "OpenCode", "base_url": "http://127.0.0.1:4096",
     "kind": "opencode", "key_required": False, "default_model": "",
     "hint": "Local OpenCode service — token from ~/.local/state/opencode/service.json"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1",
     "kind": "openai", "key_required": True, "default_model": "gpt-4o-mini", "hint": ""},
    {"id": "anthropic", "name": "Anthropic (via compatible gateway)",
     "base_url": "https://api.anthropic.com/v1", "kind": "openai",
     "key_required": True, "default_model": "claude-3-5-haiku-latest",
     "hint": "Use an OpenAI-compatible gateway such as OpenRouter or a local proxy"},
    {"id": "gemini", "name": "Google Gemini (OpenAI-compatible)",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "kind": "openai", "key_required": True, "default_model": "gemini-2.0-flash", "hint": ""},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1",
     "kind": "openai", "key_required": True, "default_model": "llama-3.3-70b-versatile", "hint": ""},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1",
     "kind": "openai", "key_required": True, "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "hint": ""},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "kind": "openai", "key_required": True, "default_model": "deepseek-chat", "hint": ""},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1",
     "kind": "openai", "key_required": True, "default_model": "mistral-small-latest", "hint": ""},
    {"id": "xai", "name": "xAI", "base_url": "https://api.x.ai/v1",
     "kind": "openai", "key_required": True, "default_model": "grok-3-mini", "hint": ""},
    {"id": "vllm", "name": "vLLM (local)", "base_url": "http://127.0.0.1:8000/v1",
     "kind": "openai", "key_required": False, "default_model": "",
     "hint": "Your own vLLM server exposing the OpenAI API"},
    {"id": "lmstudio", "name": "LM Studio (local)", "base_url": "http://127.0.0.1:1234/v1",
     "kind": "openai", "key_required": False, "default_model": "", "hint": ""},
]

VALID_KINDS = {"openai", "ollama", "opencode"}
_CONFIG_PATH = None


def _config_path() -> Path:
    global _CONFIG_PATH
    if _CONFIG_PATH is not None:
        return _CONFIG_PATH
    root = os.environ.get("OCR_ROOT")
    if root:
        base = Path(root)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "outputs" / "web" / "ai_providers.json"


def set_config_path(path):
    """Allowed for tests; production uses outputs/web/ai_providers.json."""
    global _CONFIG_PATH
    _CONFIG_PATH = Path(path) if path is not None else None


def _read_config() -> dict:
    p = _config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("custom", [])
            data.setdefault("keys", {})
            data.setdefault("overrides", {})
            return data
    except Exception:
        pass
    return {"custom": [], "keys": {}, "overrides": {}}


def _write_config(cfg: dict):
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# --------------------------------------------------------------------------- #
# registry / config
# --------------------------------------------------------------------------- #
def _builtin_by_id(pid: str):
    return next((p for p in BUILTIN if p["id"] == pid), None)


def _custom_by_id(cfg: dict, pid: str):
    return next((p for p in cfg["custom"] if p.get("id") == pid), None)


def list_providers() -> list[dict]:
    """Return provider descriptors for the UI — keys are masked, never exposed."""
    cfg = _read_config()
    out = []
    for p in BUILTIN:
        pid = p["id"]
        override = cfg["overrides"].get(pid, {})
        out.append({
            "id": pid, "name": p["name"], "kind": p["kind"],
            "base_url": override.get("base_url") or p["base_url"],
            "default_model": override.get("default_model") or p["default_model"],
            "key_required": p["key_required"], "hint": p["hint"],
            "has_key": bool(cfg["keys"].get(pid)), "builtin": True,
        })
    for p in cfg["custom"]:
        out.append({
            "id": p["id"], "name": p.get("name") or p["id"],
            "kind": p.get("kind") or "openai",
            "base_url": p.get("base_url") or "",
            "default_model": p.get("default_model") or "",
            "key_required": bool(p.get("key_required", True)),
            "hint": p.get("hint") or "Custom provider",
            "has_key": bool(p.get("api_key")), "builtin": False,
        })
    return out


def resolve(pid: str, overrides: dict | None = None) -> dict:
    """Return a fully resolved config, including the real secret (server only)."""
    overrides = overrides or {}
    cfg = _read_config()
    base = _builtin_by_id(pid) or _custom_by_id(cfg, pid)
    if base is None:
        raise KeyError(f"unknown provider: {pid}")
    saved = cfg["overrides"].get(pid, {})
    return {
        "id": pid,
        "name": base.get("name") or pid,
        "kind": base.get("kind") or "openai",
        "base_url": (overrides.get("base_url") or saved.get("base_url")
                     or base.get("base_url") or "").rstrip("/"),
        "api_key": (overrides.get("api_key") or cfg["keys"].get(pid)
                    or base.get("api_key") or ""),
        "default_model": (overrides.get("default_model") or saved.get("default_model")
                          or base.get("default_model") or ""),
        "key_required": base.get("key_required", False),
    }


def add_custom(data: dict) -> dict:
    name = str(data.get("name") or "").strip()
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        raise ValueError("name and base_url are required")
    if not re.match(r"^https?://", base_url):
        raise ValueError("base_url must start with http:// or https://")
    kind = str(data.get("kind") or "openai")
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")
    cfg = _read_config()
    pid = "custom_" + str(int(time.time()))[-8:] + "_" + os.urandom(2).hex()
    entry = {
        "id": pid, "name": name[:60], "base_url": base_url, "kind": kind,
        "api_key": str(data.get("api_key") or ""),
        "default_model": str(data.get("default_model") or "").strip(),
        "key_required": bool(data.get("api_key")),
    }
    cfg["custom"].append(entry)
    _write_config(cfg)
    return {"id": pid, "name": entry["name"], "kind": kind, "base_url": base_url,
            "default_model": entry["default_model"], "has_key": bool(entry["api_key"]),
            "builtin": False}


def remove_custom(pid: str) -> bool:
    cfg = _read_config()
    before = len(cfg["custom"])
    cfg["custom"] = [p for p in cfg["custom"] if p.get("id") != pid]
    cfg["overrides"].pop(pid, None)
    cfg["keys"].pop(pid, None)
    if len(cfg["custom"]) == before:
        return False
    _write_config(cfg)
    return True


def configure(pid: str, data: dict) -> dict:
    """Save a key / base URL / default model for any provider."""
    cfg = _read_config()
    if _builtin_by_id(pid) is None and _custom_by_id(cfg, pid) is None:
        raise KeyError(f"unknown provider: {pid}")
    if "api_key" in data:
        val = str(data["api_key"] or "")
        if val:
            if _custom_by_id(cfg, pid):
                for p in cfg["custom"]:
                    if p["id"] == pid:
                        p["api_key"] = val
                        p["key_required"] = True
            else:
                cfg["keys"][pid] = val
        else:
            if _custom_by_id(cfg, pid):
                for p in cfg["custom"]:
                    if p["id"] == pid:
                        p["api_key"] = ""
            else:
                cfg["keys"].pop(pid, None)
    for field in ("base_url", "default_model"):
        if field in data:
            val = str(data[field] or "").strip().rstrip("/")
            custom = _custom_by_id(cfg, pid)
            if custom:
                if val:
                    custom[field] = val
            else:
                cfg["overrides"].setdefault(pid, {})[field] = val
    _write_config(cfg)
    return next(p for p in list_providers() if p["id"] == pid)


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #
def _request(url: str, data=None, headers=None, timeout=DEFAULT_TIMEOUT, method=None):
    headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read()[:2000].decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code}: {raw}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(str(e.reason)) from None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError("provider returned non-JSON response: " + raw[:200]) from None


def _opencode_token(conf: dict) -> str:
    """Best-effort discovery of a local OpenCode service token."""
    if conf.get("api_key"):
        return conf["api_key"]
    for path in (Path.home() / ".local/state/opencode/service.json",
                 Path.home() / ".config/opencode/service.json"):
        try:
            d = json.loads(path.read_text())
            if d.get("password"):
                return d["password"]
        except Exception:
            continue
    return ""


def _opencode_url(conf: dict) -> str:
    base = conf.get("base_url") or "http://127.0.0.1:4096"
    if base.rstrip("/") in ("http://127.0.0.1:4096", "http://localhost:4096"):
        try:
            d = json.loads((Path.home() / ".local/state/opencode/service.json").read_text())
            if d.get("url"):
                return str(d["url"]).rstrip("/")
        except Exception:
            pass
    return base.rstrip("/")


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
def fetch_models(pid: str, overrides: dict | None = None, timeout=None) -> list[dict]:
    """Return [{id, label}] for a provider."""
    conf = resolve(pid, overrides)
    kind = conf["kind"]
    timeout = timeout or DEFAULT_TIMEOUT
    if kind == "ollama":
        data = _request(conf["base_url"] + "/api/tags", timeout=timeout)
        names = [m.get("name") or m.get("model") for m in data.get("models", [])]
        return [{"id": n, "label": n} for n in names if n]

    if kind == "opencode":
        url = _opencode_url(conf)
        token = _opencode_token(conf)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        data = _request(url + "/api/model", headers=headers, timeout=timeout)
        out = []
        for m in data.get("data", []):
            provider, mid = m.get("providerID") or "?", m.get("modelID") or m.get("id") or "?"
            value = f"{provider}/{mid}"
            out.append({"id": value, "label": m.get("name") or value})
        return out

    # OpenAI-compatible
    url = conf["base_url"] + "/models"
    headers = {}
    if conf["api_key"]:
        headers["Authorization"] = "Bearer " + conf["api_key"]
    if pid == "openrouter":
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "DocExtract MCQ"
    data = _request(url, headers=headers, timeout=timeout)
    rows = data.get("data", data if isinstance(data, list) else [])
    return [{"id": m.get("id"), "label": m.get("name") or m.get("id")}
            for m in rows if m.get("id")]


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def chat(pid: str, model: str, prompt: str, system: str = "",
         overrides: dict | None = None, timeout=None) -> str:
    """Send one prompt and return the assistant text."""
    conf = resolve(pid, overrides)
    kind = conf["kind"]
    timeout = timeout or DEFAULT_TIMEOUT
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if kind == "ollama":
        body = {"model": model, "messages": messages, "stream": False,
                "format": "json", "options": {"temperature": 0.1}}
        data = _request(conf["base_url"] + "/api/chat", data=body, timeout=timeout)
        return (data.get("message") or {}).get("content") or ""

    if kind == "opencode":
        url = _opencode_url(conf)
        token = _opencode_token(conf)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        body = {"prompt": prompt}
        if model:
            if "/" in model:
                provider, mid = model.split("/", 1)
                body["model"] = {"providerID": provider, "id": mid}
            else:
                body["model"] = {"id": model, "providerID": model}
        data = _request(url + "/api/experimental/generate/text", data=body,
                        headers=headers, timeout=timeout)
        return ((data.get("data") or {}).get("text")) or ""

    # OpenAI-compatible
    body = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 6000}
    headers = {}
    if conf["api_key"]:
        headers["Authorization"] = "Bearer " + conf["api_key"]
    if pid == "openrouter":
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "DocExtract MCQ"
    data = _request(conf["base_url"] + "/chat/completions", data=body,
                    headers=headers, timeout=timeout)
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def test_provider(pid: str, model: str = "", overrides: dict | None = None) -> dict:
    """Small connectivity check that does not spend many tokens."""
    try:
        conf = resolve(pid, overrides)
        models = fetch_models(pid, overrides, timeout=15)
        text = chat(pid, model or conf["default_model"] or
                    (models[0]["id"] if models else ""),
                    "Reply with exactly: OK", system="",
                    overrides=overrides, timeout=20)
        return {"ok": True, "models": len(models),
                "sample": text.strip()[:80], "base_url": conf["base_url"]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
