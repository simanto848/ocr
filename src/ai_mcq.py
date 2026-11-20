"""AI-backed MCQ extraction.

Sends already-extracted page text to a configurable model provider and converts
the model's JSON answer into the exact same canonical item schema the heuristic
parser produces, so the dataset builder / review UI / exports need no changes.
"""
from __future__ import annotations

import json
import re
import unicodedata

import mcq


SYSTEM = (
    "You are a meticulous exam-paper transcriber. You extract multiple-choice "
    "questions from OCR text. You never invent content that is not in the text. "
    "Reply with ONLY a single JSON object — no prose, no markdown fences."
)

PROMPT = """Extract every multiple-choice question from the OCR text below.

Return a JSON object with exactly this shape:
{
  "questions": [
    {
      "number": 1,
      "question": "full question stem",
      "options": [{"label": "A", "text": "option text"}, ...],
      "answer": "C",
      "explanation": "explanation text or empty string",
      "passage": "comprehension passage shared by these questions, or empty string"
    }
  ]
}

Rules:
- Keep the original wording, language and script (English, বাংলা, हिन्दी).
- Labels may be A/B/C/D, ক/খ/গ/ঘ, क/ख/ग/घ or 1/2/3/4 — normalise them to A/B/C/D/E.
- "answer" is one normalised label, or null when no answer is given.
- Do not include page numbers, headers, footers or the answer-key heading as questions.
- If a passage precedes a group of questions, repeat it in each question's "passage".
- If there are no MCQs, return {"questions": []}.
{answer_hint}
OCR TEXT (pages are separated by --- PAGE N --- markers):
---
{text}
---
"""

ANSWER_HINTS = {
    "auto": "Answers may be inline, marked, or in a key at the end — use whatever you find.",
    "inline": 'Answers are written inline (e.g. "Answer: B"). Use those.',
    "key": "Answers are in a key at the end of the document. Use that key.",
    "none": "No answers are present. Set every answer to null.",
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def extract_json(raw: str) -> dict:
    """Tolerate markdown fences and short preambles around the JSON object."""
    if not raw:
        return {}
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # try to find the outermost {...} block
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except ValueError:
            pass
        # strip // comments and trailing commas as a last resort
        candidate = re.sub(r"^\s*//.*$", "", candidate, flags=re.M)
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    raise ValueError("model response did not contain valid JSON")


def _norm_question(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def _option_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("label") or "").strip()
    return str(value or "").strip()


def _normalize_options(raw) -> list[dict]:
    """Accept a list of objects, a list of strings, or a {label: text} mapping."""
    out = []
    if isinstance(raw, dict):
        items = [{"label": k, "text": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    for o in items:
        if isinstance(o, dict):
            label = mcq.label_of(str(o.get("label") or o.get("key") or ""))
            text = _option_text(o)
        else:
            label = None
            text = str(o or "").strip()
        if not label:
            # infer from a leading "A)" / "ক)" in the text
            lead = re.match(r"^\s*\(?([A-Ea-eকখগঘঙकखगघङ1-5১২৩৪৫१२३४५])\)?[).:।\-–]\s*(.+)$", text)
            if lead:
                label = mcq.label_of(lead.group(1))
                text = lead.group(2).strip()
        if not label or not text:
            continue
        if any(x["label"] == label for x in out):
            continue
        out.append({"label": label, "text": text[:1000]})
    return out[:5]


def _answer_label(raw) -> str | None:
    if isinstance(raw, dict):
        raw = raw.get("label") or raw.get("text") or raw.get("answer")
    if raw is None or raw is False:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("null", "none", "unknown", "-", "?"):
        return None
    # "C) Paris" / "(c)" / "Answer: C"
    m = re.match(r"^\s*\(?([A-Ea-eকখগঘঙकखगघङ1-5১২৩৪৫१२३४५])\)?(?:[).:।\-–]\s*.*)?$", s)
    if m:
        return mcq.label_of(m.group(1))
    m = re.search(r"(?:answer|ans|উত্তর|उत्तर)\s*[:=-]?\s*\(?([A-Ea-eকখগঘঙकखगघङ1-5])\)?", s, re.I)
    return mcq.label_of(m.group(1)) if m else None


def normalize_ai_result(obj: dict, source: dict | None = None) -> list[dict]:
    """Convert a model JSON object into canonical MCQ items."""
    rows = obj.get("questions") if isinstance(obj, dict) else None
    if rows is None and isinstance(obj, list):
        rows = obj
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stem = str(row.get("question") or row.get("stem") or row.get("text") or "").strip()
        options = _normalize_options(
            row.get("options") or row.get("choices") or row.get("answers") or [])
        if not stem or len(options) < 2:
            continue
        ans = _answer_label(
            row.get("answer") if "answer" in row else
            row.get("correct") or row.get("correct_answer") or row.get("ans"))
        idx = next((i for i, o in enumerate(options) if o["label"] == ans), -1)
        answer = None
        if ans and idx >= 0:
            answer = {"label": ans, "text": options[idx]["text"], "index": idx}
        try:
            number = int(mcq.ascii_digits(str(row.get("number") or "")).strip() or 0) or None
        except ValueError:
            number = None
        explanation = str(row.get("explanation") or row.get("reason") or "").strip()[:4000]
        passage = str(row.get("passage") or row.get("context") or "").strip()[:4000]
        text_for_lang = " ".join([stem, explanation] + [o["text"] for o in options])
        confidence = 0.9 if answer else 0.5
        if len(options) >= 4:
            confidence += 0.03
        items.append({
            "id": "", "uid": mcq._uid(stem, options), "number": number,
            "question": stem, "options": options, "answer": answer,
            "explanation": explanation, "passage": passage,
            "language": mcq.detect_language(text_for_lang),
            "confidence": round(min(0.99, confidence), 2),
            "needs_review": answer is None,
            "include": True,
            "source": dict(source or {}),
            "raw": "",
            "_origin": "ai",
        })
    return items


def _chunks(pages, budget: int = 11000):
    """Group pages into prompt-sized chunks while keeping page numbers."""
    current, size = [], 0
    for pg in pages or []:
        text = str(pg.get("text") or "")
        if not text.strip():
            continue
        if current and size + len(text) > budget:
            yield current
            current, size = [], 0
        current.append({"page": pg.get("page"), "text": text})
        size += len(text)
    if current:
        yield current


def extract_mcq(pages, provider: str, model: str, answer_mode: str = "auto",
                on_progress=None) -> dict:
    """Run AI extraction over pages. Returns {items, warnings, chunks}."""
    import ai_providers

    items, warnings = [], []
    chunks = list(_chunks(pages))
    for i, group in enumerate(chunks, 1):
        body = "\n\n".join(
            f"--- PAGE {pg['page'] or i} ---\n{pg['text']}" for pg in group)
        prompt = (PROMPT
                  .replace("{answer_hint}", ANSWER_HINTS.get(answer_mode, ANSWER_HINTS["auto"]))
                  .replace("{text}", body[:60000]))
        try:
            raw = ai_providers.chat(provider, model, prompt, system=SYSTEM)
            obj = extract_json(raw)
            batch = normalize_ai_result(
                obj, source={"page": group[0].get("page"), "provider": provider,
                             "model": model})
            items.extend(batch)
            if not batch:
                warnings.append(f"AI chunk {i}: no questions found")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"AI chunk {i} failed: {type(e).__name__}: {e}")
        if on_progress:
            on_progress(i, len(chunks))
    # stable ids and dedupe
    items, dup = mcq.normalize_items(items)
    if dup:
        warnings.append(f"{dup} duplicate question(s) removed")
    return {"items": items, "warnings": warnings, "chunks": len(chunks)}


def merge_items(heuristic: list, ai: list) -> list:
    """Combine both extractors: heuristic structure + AI answers/details."""
    merged = [dict(it) for it in heuristic]
    by_text = {_norm_question(it.get("question", "")): it for it in merged}
    added = 0
    for ai_item in ai:
        key = _norm_question(ai_item.get("question", ""))
        target = by_text.get(key)
        if target is None:
            new = dict(ai_item)
            new["id"] = ""
            merged.append(new)
            by_text[key] = new
            added += 1
            continue
        # fill only what the heuristic missed
        if not (target.get("answer") or {}).get("label") and (ai_item.get("answer") or {}).get("label"):
            target["answer"] = ai_item["answer"]
            target["needs_review"] = False
            target["confidence"] = max(float(target.get("confidence") or 0), 0.9)
        for field in ("explanation", "passage"):
            if not target.get(field) and ai_item.get(field):
                target[field] = ai_item[field]
        if len(target.get("options") or []) < 2 and len(ai_item.get("options") or []) >= 2:
            target["options"] = ai_item["options"]
    merged, dup = mcq.normalize_items(merged)
    return merged
