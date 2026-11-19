#!/bin/zsh
# OCR web app launcher. Everything stays on the external drive.
# Usage: ./web/run.sh [port] [host]
#   ./web/run.sh                     -> http://127.0.0.1:8000  (local only)
#   ./web/run.sh 8000 0.0.0.0        -> reachable from your phone on the same Wi-Fi
cd "$(dirname "$0")/.." || exit 1
source ./env.sh
exec python -u web/app.py --port "${1:-8000}" --host "${2:-127.0.0.1}"
