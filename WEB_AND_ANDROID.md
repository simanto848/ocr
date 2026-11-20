# Multilingual document extraction — Web + Android

Upload a file, detect and extract its text. Works with **English**, **বাংলা (Bangla)**
and **हिन्दी (Hindi)**, using:

- **Digital text** read straight from the file (PDF text layer, DOCX, TXT, HTML …) — no OCR needed.
- **PaddleOCR-VL 1.6** (layout-aware VLM, 109 languages) for scanned pages — the default when
  its service is running. **Tesseract 5** (`eng+ben+hin`) is the fast fallback.

The old TrOCR pipeline is still available under `src/infer.py` for experiments. The web/Android
apps prefer PaddleOCR-VL for accurate Bengali/Hindi and fall back to Tesseract automatically.

---

## ⚡ One-command startup

```bash
cd ocr
./start.sh                 # starts VLM + web app; Ctrl+C stops both
./start.sh --detach        # starts both in background and returns
./start.sh --no-vlm        # web app only (Tesseract engine)
./start.sh status          # show what's running
./start.sh stop            # stop everything
./start.sh logs            # tail both logs
WEB_HOST=0.0.0.0 ./start.sh   # expose on your LAN for the Android app
                              # (prints a one-time API key you must enter in the app)
```

The launcher waits for the VLM to finish loading before starting the web app, so
opening the page immediately shows the accurate engine as ready. Logs go to `logs/`.

---

## 0. OCR engines

Two OCR engines are available for scanned pages / images:

| Engine | Strengths | Run it |
|---|---|---|
| **PaddleOCR-VL 1.6** (0.9B VLM, 109 languages incl. Bengali/Hindi, layout + tables + formulas, M4-optimised) | highest accuracy, reading order, Indic scripts | `./run_vlm.sh` (separate venv, first run downloads ~2 GB) |
| **Tesseract** (`eng+ben+hin`) | fast, no model download | automatic |

The web UI has an **OCR engine** selector: `Auto` uses PaddleOCR-VL when the
service is running, otherwise Tesseract. `vlm` forces the VLM; `tesseract` forces
Tesseract. The Android app's Server mode benefits automatically — just run the
VLM service alongside the web server.

### Set up the VLM service (one time)
```bash
cd ocr
python3.11 -m venv .venv-paddle
.venv-paddle/bin/python -m pip install paddlepaddle==3.2.1 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.venv-paddle/bin/python -m pip install -U "paddleocr[doc-parser]>=3.4.0"
./run_vlm.sh                      # → http://127.0.0.1:8090  (GET /health)
```
All weights are cached in `.cache/paddlex/` on the external drive. Keep
`PADDLE_PDX_CPU_NUM_THREADS` unset — setting it triggers a Paddle static-graph bug
during inference. First inference after startup warms up (~60 s); later pages take
roughly 8–12 s each on an M4.

Measured comparison on a mixed English/Bangla/Hindi sample:

| Engine | Hindi line | Bengali line |
|---|---|---|
| PaddleOCR-VL | `नमस्ते, यह हिंदी पाठ है। कुल राशि १२५०` | `নমস্কার, এটি বাংলা পাঠ্য। মোট টাকা ১২৫০` (1-char typo) |
| Tesseract | `TAR, यह Stet पाठ है। कुल रार्शा १२५०` | `এটিবাংলা পাঠ্য। ACAD টাকা ১২৫০` |

PaddleOCR-VL is the clear winner for Indic scripts and complex layouts; Tesseract
remains available as a fast fallback.

---

## 1. Web app

```bash
cd ocr
source ./env.sh
./web/run.sh                       # local: http://127.0.0.1:8000
./web/run.sh 8000 0.0.0.0          # also reachable from your phone on the same Wi-Fi
```

Open the URL in a browser. Choose a language, drop a file, and read/copy/download/share
the result. Each page is labelled **digital text** or **OCR** so you know where the text
came from.

### Supported formats
`pdf, doc, docx, rtf, odt, txt, md, html, htm, csv, log, png, jpg, jpeg, webp, bmp, tif, tiff, gif`

### API
| Endpoint | Purpose |
|---|---|
| `GET /api/status` | engine, languages, formats |
| `POST /api/upload` | multipart `file` + optional `lang` (`auto`, `en`, `bn`, `hi`, `mixed`) → `{job_id}` |
| `GET /api/job?id=…` | status, progress, pages, markdown |
| `GET /api/preview?job=…&page=N` | page image |
| `GET /api/download?job=…&format=md\|json\|txt` | download |

Everything is stored under `outputs/web/` on the external drive.

Implementation: `src/extract.py` (extraction engine) and `web/app.py` (server).

---

## 2. Android app (Flutter)

Located in `ocr_app/`. Two modes:

- **Server mode** (default): uploads any supported file to the Python web app. Full
  format and language support. Set the server address in the app:
  - Android emulator → `http://10.0.2.2:8000`
  - Physical phone → `http://<your-computer-LAN-IP>:8000` (start the server with
    `WEB_HOST=0.0.0.0 ./start.sh`; phone and computer must be on the same Wi-Fi).
    LAN mode requires an API key — the launcher prints it; paste it into the app's
    **API key** field.
- **Offline mode**: on-device Tesseract OCR with bundled `eng`, `ben`, `hin` language data.
  Works with no network for images/photos and plain text files. For PDF/DOC/DOCX, use
  Server mode.

### Build & install

```bash
cd ocr/ocr_app
flutter pub get
flutter build apk --debug            # or: flutter build apk --release
# APK: build/app/outputs/flutter-apk/app-debug.apk
adb install build/app/outputs/flutter-apk/app-debug.apk   # if a device is connected
```

To open the Android project in Android Studio, open `ocr_app/android`.

### Notes
- The app requests INTERNET (server mode) and CAMERA (take a photo) permissions.
- Cleartext HTTP is enabled for LAN addresses via `android:usesCleartextTraffic="true"`.
- The bundled language data lives in `ocr_app/assets/tessdata/` (~6 MB).

---

## 3. Verification performed

- PDF (scanned) → OCR text accurately recognised.
- PDF with a **broken text layer** (garbled font map) → detected and re-OCR'd automatically.
- DOCX with English + বাংলা + हिन्दी → exact digital text.
- Image with English + Bengali numerals → OCR via `eng+ben+hin`.
- Web app tested **end-to-end in the browser**: language selection, file upload,
  progress, preview, OCR badge, extracted text, JSON view and download (all formats).
- Python tests: 13 passed. Flutter `analyze`: no issues. Flutter test: passed.
- APK built at `ocr_app/build/app/outputs/flutter-apk/app-debug.apk` (~172 MB).
