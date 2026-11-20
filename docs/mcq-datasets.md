# MCQ datasets and source linking

This document describes the **MCQ dataset** page of the web app and the
bidirectional text ↔ page-image highlighting used by the extraction view.

## 1. What the MCQ page does

1. Upload a PDF, Word file or image containing multiple-choice questions.
2. The normal extraction pipeline runs first (`digital text → PaddleOCR-VL →
   Tesseract`), so the same code path handles digital and scanned documents.
3. The extracted page text is parsed into canonical MCQ records, optionally
   with the help of an AI model provider.
4. Every record is reviewable and editable before export.
5. Exports are written to `outputs/web/jobs/<job_id>/mcq/`.

### Canonical record

```json
{
  "id": "mcq_0001",
  "uid": "mcq_2543caced4",
  "number": 1,
  "question": "What is the capital of France?",
  "options": [{"label": "A", "text": "Berlin"}, {"label": "C", "text": "Paris"}],
  "answer": {"label": "C", "text": "Paris", "index": 1},
  "explanation": "",
  "passage": "",
  "language": "en",
  "confidence": 0.95,
  "needs_review": false,
  "include": true,
  "source": {"page": 1, "filename": "quiz.pdf", "bbox": [10, 20, 400, 45]},
  "raw": "..."
}
```

`include: false` keeps a record in the canonical `items.json` for review but
removes it from every export. IDs are sequential and stable while editing.

### Recognised layouts

- Numbering: `1.`, `1)`, `(1)`, `Q1.`, `১।`, `१.`
- Options: `A)`, `(B)`, `C.`, `ক)`, `ख)`, numbered `1) 2) 3)`, inline
  `(a) red (b) green`, or bullet lists.
- Answers: inline (`Answer: B`, `Ans - (c)`, `উত্তর: গ`), an answer-key block,
  or a marked option (`**bold**`, `__underline__`, `✔`, `[x]`, `(correct)`).
- Passages: `Passage:` / `উদ্দীপক` / `निम्नलिखित` blocks are attached to the
  questions that follow.

## 2. Extraction methods

| Method | What happens | When to use |
|---|---|---|
| **Heuristic** | Regex/structure parser, no network, instant | Clean printed papers |
| **AI model** | A model returns JSON MCQs; no regex parser runs | Messy OCR, unusual layouts |
| **AI + heuristic** | Heuristic structure, AI fills missing answers/explanations and adds questions | Default for mixed quality |

### Providers

Built in: **Ollama**, **NVIDIA NIM**, **OpenRouter**, **OpenCode**, OpenAI,
Gemini, Groq, Together, DeepSeek, Mistral, xAI, vLLM, LM Studio.
**＋ Add custom provider** accepts any OpenAI-compatible `/chat/completions`
endpoint, an Ollama-style `/api/chat` endpoint, or an OpenCode V2 server.

- Keys are stored server-side in `outputs/web/ai_providers.json` (gitignored).
  The API returns only a `has_key` flag — never the secret.
- **↻ Models** calls the provider's model-list endpoint; the model field is a
  free-text input with autocomplete so a model can be typed even when the
  provider is offline.
- **Test connection** performs a tiny generation and reports the model count.
- OpenCode uses `POST /api/experimental/generate/text` and `GET /api/model`.
  A local service token is read from `~/.local/state/opencode/service.json`
  when one is not entered explicitly.

## 3. Export formats

| file | use |
|---|---|
| `mcq.jsonl` | canonical records (includes excluded ones) |
| `rag.jsonl` | one self-contained chunk + metadata per question |
| `sft_chat.jsonl` | system / user / assistant fine-tuning rows |
| `sft_alpaca.jsonl` | instruction / input / output rows |
| `splits/{train,val,test}.jsonl` | deterministic 90/5/5 split of answered rows |
| `mcq.csv`, `mcq.md`, `dataset_card.md` | human review and provenance |
| `manifest.json` | stats, warnings, source list, file index |

Answerless and excluded questions are skipped from training/RAG exports but
kept in `items.json`.

## 4. Source linking

Tesseract returns one bounding box per OCR line. `extract.py` stores those
boxes plus the full page image size in `result.json`. The text panel renders
each OCR line as a `<span class="hl-line" data-page data-line data-box>` and
the image panel draws the matching scaled rectangles in `#hlOverlay`.

- Hovering a text line highlights its image rectangle (and switches the
  preview to that page first if needed).
- Hovering an image rectangle highlights the corresponding text line and
  scrolls it into view, with a tooltip containing the recognised text.
- MCQ records get `source.bbox` via token-overlap matching against the page's
  OCR lines; the **📍 Source** button opens the source page with that question
  highlighted.

Boxes are only available for OCR pages. Digital-text and VLM pages have no
geometry, so they render as ordinary text without an overlay.

## 5. API

```
GET  /api/ai/providers
POST /api/ai/models            {provider, base_url?, api_key?}
POST /api/ai/test              {provider, model, ...}
POST /api/ai/provider          {name, base_url, kind, api_key?, default_model?}
POST /api/ai/provider/configure /api/ai/provider/delete
POST /api/upload               (multipart) kind=mcq + ai_mode + ai_provider + ai_model
POST /api/mcq/build            {job_id, ai_mode?, ai_provider?, ai_model?, ...}
GET  /api/mcq/job?id=
POST /api/mcq/item             {job_id, item_id, ...edits}
GET  /api/mcq/download?id=&format=
GET  /api/page-image?job=&page=
```
