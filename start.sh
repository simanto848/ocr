#!/bin/zsh
# =============================================================================
# DocExtract — start everything with one command
#   ./start.sh                 start VLM + web (foreground, Ctrl+C stops both)
#   ./start.sh --detach        start both in background and return
#   ./start.sh --no-vlm        start web only (Tesseract engine)
#   ./start.sh stop            stop all services
#   ./start.sh status          show status of services
#   ./start.sh logs            tail both log files
#   WEB_HOST=0.0.0.0 ./start.sh     expose web on your LAN (for the Android app)
# =============================================================================
set -u
if [ -n "${ZSH_VERSION:-}" ]; then
  ROOT="${0:A:h}"
else
  ROOT="$(cd "$(dirname "$0")" && pwd)"
fi
VLM_PORT="${VLM_PORT:-8090}"
WEB_PORT="${WEB_PORT:-8000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
RUN_DIR="$ROOT/.cache/run"
LOG_DIR="$ROOT/logs"
VLM_PID="$RUN_DIR/vlm.pid"
WEB_PID="$RUN_DIR/web.pid"
VLM_LOG="$LOG_DIR/vlm_service.log"
WEB_LOG="$LOG_DIR/web_app.log"
KEY_FILE="$RUN_DIR/api_key"
mkdir -p "$RUN_DIR" "$LOG_DIR"

# A LAN-exposed server must require a shared secret. Generate one once and
# reuse it so the Android app keeps working across restarts.
if [[ "$WEB_HOST" != "127.0.0.1" && "$WEB_HOST" != "localhost" ]]; then
  if [[ -z "${OCR_API_KEY:-}" ]]; then
    if [[ -f "$KEY_FILE" ]]; then OCR_API_KEY="$(cat "$KEY_FILE")"; else
      OCR_API_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || openssl rand -hex 16)"
      printf '%s\n' "$OCR_API_KEY" > "$KEY_FILE"; chmod 600 "$KEY_FILE"
    fi
  fi
  export OCR_API_KEY
  printf '%s\n' "🔑 LAN mode — API key: $OCR_API_KEY"
  printf '%s\n' "   Enter this in the Android app (Server settings)."
fi

# ---------- helpers ----------
say() { printf '%s\n' "$*"; }
stop_pid() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local pid; pid="$(cat "$f" 2>/dev/null)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    for i in {1..20}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
}
is_alive() { local f="$1"; [[ -f "$f" ]] && kill -0 "$(cat "$f" 2>/dev/null)" 2>/dev/null; }
http_ok() { command curl -sf --max-time 3 "$1" >/dev/null 2>&1; }

start_vlm() {
  if http_ok "http://127.0.0.1:$VLM_PORT/health" && is_alive "$VLM_PID"; then
    say "✔  VLM service already running on :$VLM_PORT"
    return 0
  fi
  say "▸  Starting PaddleOCR-VL service on :$VLM_PORT …"
  cd "$ROOT"
  nohup ./run_vlm.sh "$VLM_PORT" >>"$VLM_LOG" 2>&1 &
  echo $! >"$VLM_PID"
  local ok=0
  for i in {1..240}; do
    if http_ok "http://127.0.0.1:$VLM_PORT/health"; then ok=1; break; fi
    if ! is_alive "$VLM_PID"; then break; fi
    sleep 2
  done
  if (( ok )); then
    say "✔  VLM ready (first inference warms up ~60 s)"
  else
    say "✘  VLM failed to start — see $VLM_LOG"
    return 1
  fi
}

start_web() {
  if http_ok "http://127.0.0.1:$WEB_PORT/api/status" && is_alive "$WEB_PID"; then
    say "✔  Web app already running on :$WEB_PORT"
    return 0
  fi
  say "▸  Starting web app on $WEB_HOST:$WEB_PORT …"
  cd "$ROOT"
  source ./env.sh >/dev/null 2>&1
  nohup python -u web/app.py --port "$WEB_PORT" --host "$WEB_HOST" >>"$WEB_LOG" 2>&1 &
  echo $! >"$WEB_PID"
  local ok=0
  for i in {1..30}; do
    if http_ok "http://127.0.0.1:$WEB_PORT/api/status"; then ok=1; break; fi
    if ! is_alive "$WEB_PID"; then break; fi
    sleep 1
  done
  (( ok )) || { say "✘  Web app failed to start — see $WEB_LOG"; return 1; }
  return 0
}

status() {
  local v="stopped" w="stopped"
  http_ok "http://127.0.0.1:$VLM_PORT/health" && v="running :$VLM_PORT"
  http_ok "http://127.0.0.1:$WEB_PORT/api/status" && w="running $WEB_HOST:$WEB_PORT"
  say "VLM service : $v"
  say "Web app     : $w"
}

case "${1:-}" in
  stop)
    say "Stopping services…"
    stop_pid "$WEB_PID"; stop_pid "$VLM_PID"
    # also sweep any orphaned processes from this project
    pkill -f "web/app.py --port $WEB_PORT" 2>/dev/null || true
    pkill -f "src/vlm_service.py --port $VLM_PORT" 2>/dev/null || true
    say "Stopped."
    ;;
  status) status ;;
  logs)
    say "--- web ($WEB_LOG) ---"; tail -n 20 "$WEB_LOG" 2>/dev/null
    say "--- vlm ($VLM_LOG) ---"; tail -n 20 "$VLM_LOG" 2>/dev/null
    ;;
  --no-vlm)
    start_web || exit 1
    say ""
    say "➜  Web app ready at http://127.0.0.1:$WEB_PORT  (Tesseract engine)"
    say "   Logs: $WEB_LOG   •   Stop: $ROOT/start.sh stop"
    ;;
  --detach)
    start_vlm || say "⚠  continuing without VLM (Tesseract fallback)"
    start_web || exit 1
    say ""
    say "➜  Web app : http://127.0.0.1:$WEB_PORT"
    say "➜  VLM     : http://127.0.0.1:$VLM_PORT"
    say "   Stop everything: $ROOT/start.sh stop"
    ;;
  "" )
    start_vlm || say "⚠  continuing without VLM (Tesseract fallback)"
    start_web || exit 1
    say ""
    say "════════════════════════════════════════════"
    say "  DocExtract is running"
    say "  Web app : http://127.0.0.1:$WEB_PORT"
    say "  VLM     : http://127.0.0.1:$VLM_PORT"
    say "  Stop    : Ctrl+C  or  $ROOT/start.sh stop"
    say "════════════════════════════════════════════"
    # keep web in foreground; trap guarantees both die together
    trap 'say "\nStopping services…"; stop_pid "$WEB_PID"; stop_pid "$VLM_PID"; exit 0' INT TERM
    while is_alive "$WEB_PID"; do sleep 2; done
    say "Web app stopped."
    stop_pid "$VLM_PID"
    ;;
  *)
    say "Usage: $0 [--detach] [--no-vlm] [stop|status|logs]"
    ;;
esac
