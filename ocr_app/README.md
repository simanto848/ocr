# DocExtract — Android app (Flutter)

Multilingual document text extraction with two modes:

- **Server** (default) — uploads PDF / DOC / DOCX / RTF / ODT / TXT / HTML / images to the
  Python web app in this repo and shows the extracted text. Supports English, বাংলা and
  हिन्दी.
- **Offline** — on-device Tesseract OCR with bundled `eng`, `ben`, `hin` language data.
  Works with no network for images, camera photos and text files.

## Start the server first (for Server mode)

```bash
cd /Volumes/SSD-SIMANTO/works/ocr
./web/run.sh 8000 0.0.0.0
```

In the app, set the server address to:

- Android emulator: `http://10.0.2.2:8000`
- Physical phone on the same Wi-Fi: `http://192.168.x.y:8000` (your computer's LAN IP)

Tap **Test connection** to confirm.

## Build / install

```bash
flutter pub get
flutter build apk --debug      # build/app/outputs/flutter-apk/app-debug.apk
adb install build/app/outputs/flutter-apk/app-debug.apk
```

## Project layout

| Path | Purpose |
|---|---|
| `lib/main.dart` | app entry |
| `lib/screens/home_screen.dart` | mode, language, file picker, progress, results |
| `lib/services/ocr_service.dart` | offline Tesseract OCR |
| `lib/services/server_service.dart` | upload + poll + status against the Python API |
| `lib/models/extract_result.dart` | result model |
| `assets/tessdata/` | bundled `eng` / `ben` / `hin` traineddata |
| `android/app/src/main/AndroidManifest.xml` | INTERNET + CAMERA permissions, cleartext LAN traffic |
