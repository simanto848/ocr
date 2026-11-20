# DocExtract — Multilingual Document Text Extraction (Web + Android)

> Upload **PDF, Word, images and other files** and get back clean, reading-ordered text in
> **English**, **বাংলা (Bangla)** and **हिन्दी (Hindi)** — with a modern web UI and a Flutter
> Android app that works both online (server) and fully offline (on-device).

This repository contains two things:

1. **A production document-parsing stack** — a universal extraction engine that reads digital
   text directly and OCRs scanned pages with **Tesseract 5** or a local **PaddleOCR-VL 1.6**
   vision-language model (109 languages, layout/table/formula aware, verified on Apple Silicon).
2. **An OCR research lab** — a <0.5B-parameter TrOCR pipeline with synthetic document generation,
   LoRA/full fine-tuning, evaluation and hard-example mining (kept for experimentation).

---

## Table of contents

- [Quick start](#quick-start)
- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Setup](#setup)
  - [Web app + VLM service](#web-app--vlm-service)
  - [One-command launcher](#one-command-launcher)
  - [Android app](#android-app)
- [Using the web app](#using-the-web-app)
- [Using the Android app](#using-the-android-app)
- [OCR engines compared](#ocr-engines-compared)
- [Supported formats & languages](#supported-formats--languages)
- [API reference](#api-reference)
- [The research pipeline (legacy TrOCR)](#the-research-pipeline-legacy-trocr)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [License & credits](#license--credits)

---

## Quick start

```bash
cd ocr

# 1. Install Python dependencies (once)
source ./env.sh
pip install -r requirements.txt
python -m pip install paddlepaddle==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -U "paddleocr[doc-parser]>=3.4.0"

# 2. Start EVERYTHING (VLM service + web app) with one command
./start.sh

# 3. Open the UI
open http://127.0.0.1:8000
```

That's it. The launcher waits for the VLM to load before starting the web app, so the UI
immediately shows **“PaddleOCR-VL ready”**.

For the Android app: `WEB_HOST=0.0.0.0 ./start.sh`. LAN mode automatically requires a shared
secret — the launcher prints a **API key** and stores it in `.cache/run/api_key`. Enter that key
in the app's **API key** field (and in the server URL field use your computer's LAN IP,
e.g. `http://<your-computer-ip>:8000`). The browser UI gets the key automatically.

---

## Features

| Feature | Details |
|---|---|
| **Multiple file upload** | Select/drag/paste many files at once; each becomes an independent async job with its own progress bar and live batch queue. |
| **Digital text extraction** | PDF text layer, DOCX paragraphs & tables, TXT/HTML/CSV read directly — no OCR, perfect fidelity. |
| **Broken-PDF detection** | Garbled text layers (bad font maps) are detected and the pages are re-OCR'd automatically. |
| **Two OCR engines** | Tesseract (`eng+ben+hin`) for speed; PaddleOCR-VL 1.6 for accuracy, layout, tables and Indic scripts. `Auto` picks the best available. |
| **Reading order** | Words → lines → paragraphs; VLM output preserves headings, tables and document structure. |
| **Rich web UI** | Drag-anywhere upload, dark mode, toasts, keyboard shortcuts, page previews, per-page “digital text / OCR” badges, copy/download (MD/TXT/JSON)/share, delete files, responsive layout. |
| **MCQ dataset builder** | A dedicated **MCQ dataset** page turns a question paper (PDF or image) into a reviewable dataset: question stem, options, answer and explanation are detected in English/বাংলা/हिन्दी, then exported as **RAG chunks**, **SFT chat / Alpaca** fine-tuning pairs, **CSV** or a **ZIP** bundle. |
| **Android app** | Server mode (all formats/languages) + offline mode (on-device Tesseract with bundled language data), camera capture, history, share. |
| **Research tooling** | Synthetic multilingual document generation, LoRA/full fine-tuning of TrOCR, CER/WER evaluation, hard-example mining. |

---

## Architecture

```
                         ┌──────────────────────────────┐
   PDF / DOCX / images ──▶  web/app.py  (job queue API)  │
   (multi-file upload)     └───────────────┬──────────────┘
                                           │  per-file background thread
                                           ▼
                              src/extract.py  ── digital text? ──▶ direct text
                                           │
                                           └── needs OCR? ──▶ src/vlm_client.py
                                                                  │ HTTP
                                                                  ▼
                                                    src/vlm_service.py (port 8090)
                                                    PaddleOCR-VL 1.6 (isolated venv)
                                                                  │ fallback
                                                                  ▼
                                                          Tesseract eng+ben+hin
                                           │
                                           ▼
                              results: pages + Markdown + JSON
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
          web/static/* (3-pane UI)                 ocr_app (Flutter, Android)
```

**Why an isolated service for the VLM?** PaddleOCR-VL needs PaddlePaddle, whose dependencies
conflict with the PyTorch training stack. It therefore runs in `.venv-paddle` behind a tiny
localhost HTTP API (`src/vlm_service.py`). If it is not running, the web app transparently falls
back to Tesseract — nothing breaks.

All caches, models, virtualenvs and uploaded files live on the external drive
(`<repo-root>`) and are **not** committed to Git.

---

## Requirements

### Hardware
- Apple Silicon Mac (M1–M4; PaddleOCR-VL is officially verified on M4) or a CPU machine.
- ~8 GB RAM for the VLM (~5 GB resident), ~120 GB disk for caches/models.

### Software
- macOS with Python 3.11 (here: `python3.11` via uv).
- Tesseract 5 with `eng`, `ben`, `hin` language data:
  ```bash
  brew install tesseract tesseract-lang
  tesseract --list-langs | grep -E '^(eng|ben|hin)$'
  ```
- Flutter 3.44+ / Dart 3.12+ and Android SDK (only for the Android app).
- `adb` (via Android SDK platform-tools) for installing the APK.

### Python packages
See `requirements.txt`. The app additionally uses `python-docx`, `pytesseract`, and, in the
separate Paddle environment, `paddlepaddle==3.2.1` + `paddleocr[doc-parser]>=3.4.0`.

---

## Setup

`env.sh` pins every cache (`HF_HOME`, `TORCH_HOME`, `DOCTR_CACHE_DIR`, `TMPDIR`, …) to the
external drive. **Source it first** in every shell:

```bash
source ./env.sh
```

### Web app + VLM service

```bash
# Python deps (training/extraction stack)
source ./env.sh && pip install -r requirements.txt

# Paddle stack (separate venv, one time)
python3.11 -m venv .venv-paddle
.venv-paddle/bin/python -m pip install paddlepaddle==3.2.1 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.venv-paddle/bin/python -m pip install -U "paddleocr[doc-parser]>=3.4.0"
# NOTE: keep PADDLE_PDX_CPU_NUM_THREADS unset — it triggers a Paddle static-graph bug.

# First run downloads ~2 GB of model weights into .cache/paddlex/
./run_vlm.sh        # VLM service on :8090
./web/run.sh        # web app on :8000  (add 0.0.0.0 to expose on LAN)
```

### One-command launcher

```bash
./start.sh                     # VLM + web, Ctrl+C stops both
./start.sh --detach            # both in background
./start.sh --no-vlm            # web only (Tesseract)
WEB_HOST=0.0.0.0 ./start.sh    # expose on LAN for the phone
./start.sh status | stop | logs
```

### Android app

```bash
cd ocr_app
flutter pub get
flutter build apk --debug      # build/app/outputs/flutter-apk/app-debug.apk
adb install build/app/outputs/flutter-apk/app-debug.apk
```

The app bundles `eng`/`ben`/`hin` Tesseract data for offline use. Two dependency overrides in
`pubspec.yaml` (`path_provider_android`, `shared_preferences_android`) avoid a Gradle native-assets
dependency that would otherwise force a fresh NDK 28 download.

---

## Using the web app

1. Open `http://127.0.0.1:8000`.
2. Choose **OCR language** (Auto covers English + বাংলা + हिन्दी) and **OCR engine**.
3. Drop one or many files anywhere on the window (or click/paste). Each file gets its own
   progress bar in the **Batch queue** and in **Recent files**.
4. Browse page previews with `←` / `→`, then copy, download (Markdown / TXT / JSON) or share.
5. Delete unwanted results with the trash icon on a history row.

Shortcuts: `⌘/Ctrl+K` upload · `←`/`→` pages · `Esc` close dialogs.

---

## MCQ dataset mode

The **MCQ dataset** tab turns multiple-choice question papers into a structured dataset.
Upload a PDF, photo or text file; the normal extraction pipeline runs, then a parser splits
the text into individual questions.

- **Detected layouts** — numbering (`1.`, `1)`, `(1)`, `Q1`, `১।`), options on separate lines
  (`A) …`, `(B) …`, `ক) …`, `ख) …`) or inline on one line, and bullets used as options.
- **Answers** — inline (`Answer: B`, `Ans - (c)`, `উত্তর: গ`, `उत्तर: ख`), a separate
  **answer key** block (`Answer Key` / `উত্তরমালা`), a marked option (`**bold**`,
  `__underline__`, `✔`, `[x]`, trailing `(correct)`), or no answers at all. Choose
  **Auto-detect** or force one convention.
- **Passages** — a `Passage:` / `উদ্দীপক` / `निम्नलिखित` block is attached to the questions
  that follow it.
- **Review before export** — every question is editable (stem, options, answer, explanation),
  can be excluded, and is flagged **needs review** when its confidence is low or it has no
  answer. Edits regenerate the exports immediately.
- **Exports** — `rag.jsonl` (one self-contained chunk per question, with metadata),
  `sft_chat.jsonl` (system/user/assistant), `sft_alpaca.jsonl`, `mcq.csv`, `mcq.md`,
  `dataset_card.md`, deterministic 90/5/5 `splits/`, and a full `zip`.

**AI extraction (optional).** The **Extraction method** selector offers three modes:
*Heuristic* (regex, no API), *AI model* (a model does the parsing), or *AI + heuristic*
(heuristic structure with AI-filled answers/explanations). Built-in providers: **Ollama**,
**NVIDIA NIM**, **OpenRouter**, **OpenCode** (V2 generate API), OpenAI, Gemini, Groq,
Together, DeepSeek, Mistral, xAI, vLLM and LM Studio. **＋ Add custom provider** registers
any additional OpenAI-compatible, Ollama-style or OpenCode-style endpoint. API keys are
stored server-side in `outputs/web/ai_providers.json` and never returned to the browser.
Use **↻ Models** to refresh the model list and **Test connection** to verify credentials.

- **Source linking** — each extracted question carries the OCR line box it came from.
  In the **Extract text** panel, hovering an extracted line highlights the matching
  region of the page image and hovering an image region highlights the text; the
  MCQ card's **📍 Source** button jumps straight to its question in the original page.
  The MCQ panel also supports **↻ Rebuild** with a different method/model and deleting
  a set from its history.

Datasets live in `outputs/web/jobs/<job_id>/mcq/`, next to the page renders they came from.

CLI equivalent (works on an existing extraction result, no server needed):

```bash
source ./env.sh
python -m mcq --job outputs/web/jobs/<job_id>/result.json --out data/mcq_biology
python -m mcq --text paper.txt --out data/mcq_x --name "Class 9 Biology"
```

---

## Using the Android app

- **Server mode** (default): full format/language support via the Python server. Emulator:
  `http://10.0.2.2:8000`. Physical phone: `http://<computer-LAN-IP>:8000` (same Wi-Fi, start the
  server with `WEB_HOST=0.0.0.0 ./start.sh`). LAN mode prints an API key — paste it into the
  **API key** field. Tap **Test connection**.
- **Offline mode**: on-device Tesseract for images, camera photos and text files — no network
  needed. For PDF/DOC/DOCX use Server mode.

See `WEB_AND_ANDROID.md` for the full guide.

---

## OCR engines compared

| | PaddleOCR-VL 1.6 | Tesseract 5 |
|---|---|---|
| Parameters | 0.9 B VLM | classical engine |
| Languages | 109 (incl. bn/hi) | eng+ben+hin (bundled) |
| Layout / tables / formulas | yes (Markdown/HTML/LaTeX) | no |
| Reading order | yes | basic |
| Speed (M4, warm) | ~10 s/page | <1 s/page |
| First-run setup | ~2 GB weights, ~5 min load | none |
| Where it runs | local service in `.venv-paddle` | in the web app process |

Measured on a mixed English/Bangla/Hindi sample, PaddleOCR-VL transcribed all three scripts
essentially perfectly, while Tesseract garbled the Hindi/Bangla lines — so **Auto** prefers the
VLM whenever the service is up.

---

## Supported formats & languages

- **Documents:** `.pdf .doc .docx .rtf .odt .txt .md .html .htm .csv .log`
- **Images:** `.png .jpg .jpeg .webp .bmp .tif .tiff .gif`
- **OCR languages:** `eng` (English), `ben` (বাংলা), `hin` (हिन्दी), or any combination.
- Max **100 MB per file**, up to 10 files per upload.

---

## API reference

| Endpoint | Purpose |
|---|---|
| `GET /` | Web UI |
| `GET /api/status` | Engine info, languages, formats, VLM readiness |
| `POST /api/upload` | multipart `file` (repeatable) + `lang` + `engine` → `{job_id, job_ids, jobs, errors}` |
| `GET /api/history` | All jobs, newest first |
| `GET /api/job?id=…` | Status, progress, pages, markdown, result JSON |
| `GET /api/preview?job=…&page=N` | Page image |
| `GET /api/page-image?job=…&page=N` | Full-resolution page render (OCR box coordinate space) |
| `GET /api/download?job=…&format=md\|txt\|json` | Download |
| `POST /api/delete?id=…` / `DELETE /api/job?id=…` | Delete a job and its files |
| `POST /api/upload` with `kind=mcq` (+ `answer_mode=auto\|inline\|key\|none`) | Extraction job that also builds an MCQ dataset |
| `POST /api/mcq/build` `{job_id, answer_mode?, name?}` | (Re)build a dataset from an already-extracted job |
| `GET /api/mcq/job?id=…` | `{job, dataset:{manifest, items}}` for the review UI |
| `POST /api/mcq/item` `{job_id, item_id, question?, options?, answer?, include?, …}` | Save one review edit and regenerate exports |
| `GET /api/mcq/download?id=…&format=jsonl\|rag\|sft\|alpaca\|csv\|md\|card\|zip` | Download a dataset |
| `GET /api/ai/providers` | Provider list (keys masked) |
| `POST /api/ai/models` `{provider, base_url?, api_key?}` | Fetch model list |
| `POST /api/ai/test` `{provider, model, ...}` | Test credentials |
| `POST /api/ai/provider` / `.../configure` / `.../delete` | Manage custom providers |
| `GET /health` (VLM, :8090) | VLM readiness |
| `POST /ocr` (VLM, :8090) | `{"image": "/abs/path.png"}` → Markdown |

---

## The research pipeline (legacy TrOCR)

A separate, small-model pipeline (<0.5 B params) is kept for experiments:
`detect → crop → TrOCR recognize → layout`. See `PROJECT_ANALYSIS.md`, `DATASET_CARD.md`,
`MODEL_ANALYSIS.md`, `DOMAIN_GAP_REPORT.md`, `TRAINING_REPORT.md` and `docs/`.

```bash
source ./env.sh
python -m dataset.fonts.scan
python -m dataset.generate --count 1000 --output data/v001
python -m dataset.export_lines --dataset data/v001
python -m dataset.validate --dataset data/v001
python -m evaluation.evaluate --model base --dataset data/v001 --level line
python -m training.train --config configs/training_lines.yaml
python src/infer.py outputs/multi_doc.png --out outputs/out.txt
```

The web/Android apps use the Tesseract/PaddleOCR-VL engine, not this TrOCR path.

---

## Repository layout

```
src/            extraction engine (extract.py), MCQ parser/dataset builder (mcq.py),
                AI providers (ai_providers.py), AI MCQ extraction (ai_mcq.py),
                VLM client/service, TrOCR pipeline,
                detection, layout, training data, model loading, CLI inference
dataset/        synthetic multilingual document generator (fonts, templates, rendering,
                augmentation, annotations, validation, stats, preview)
web/            Flask-free stdlib server (app.py) + static UI (index.html/app.js/mcq.js/style.css)
ocr_app/        Flutter Android app (offline + server modes, bundled Indic language data)
configs/        dataset / augmentation / training YAML configs
training/       TrOCR fine-tuning entry points        evaluation/  CER/WER + hard-example mining
tests/          pytest unit tests                     docs/        detailed pipeline docs
start.sh        one-command launcher for web + VLM services
run_vlm.sh      launcher for the PaddleOCR-VL service only
env.sh          pins all caches to the external drive
```

---

## Testing

```bash
source ./env.sh
python -m pytest tests/ -q          # extraction, layout, dataset, MCQ parser and web API
cd ocr_app && flutter analyze && flutter test
```

---

## Troubleshooting

- **VLM not ready / static-graph error** — make sure `PADDLE_PDX_CPU_NUM_THREADS` is unset;
  re-run `./start.sh`. Model load can take ~5 min on first start.
- **Tesseract languages missing** — `brew install tesseract-lang`, then check `tesseract --list-langs`.
- **Web app can't be reached from the phone** — start with `WEB_HOST=0.0.0.0`, use the LAN IP,
  and make sure phone/computer share the same Wi-Fi (no guest-network isolation).
- **Stale jobs after restart** — the server marks them as errors; re-upload them.
- **Protobuf error in `.venv-paddle`** — `pip install -U "protobuf>=7.36.1"`.

---

## License & credits

- OCR app code: MIT-style / see individual component licenses.
- **PaddleOCR-VL** — Apache-2.0, © PaddlePaddle.
- **Tesseract** — Apache-2.0, © Google / HP.
- TrOCR fine-tuning stack — © Microsoft / Hugging Face.

Built with PaddleOCR-VL, Tesseract, Transformers, Flutter and a lot of chai. ☕
