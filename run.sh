#!/usr/bin/env bash
# گیم سنتر — launcher: makes sure the local bookkeeping service is up,
# then opens the UI in its own app window.
set -u

APP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PORT="${GAMECENTER_PORT:-8777}"
LOG_DIR="$HOME/.local/share/gamecenter"
LOG="$LOG_DIR/server.log"
mkdir -p "$LOG_DIR"

URL="http://127.0.0.1:$PORT"

if ! curl -fsS --max-time 1 "$URL/api/ping" >/dev/null 2>&1; then
  setsid nohup python3 "$APP_DIR/app.py" --port "$PORT" >>"$LOG" 2>&1 &
  for _ in $(seq 1 80); do
    curl -fsS --max-time 1 "$URL/api/ping" >/dev/null 2>&1 && break
    sleep 0.1
  done
fi

if ! curl -fsS --max-time 2 "$URL/api/ping" >/dev/null 2>&1; then
  echo "سرویس گیم‌سنتر بالا نیامد. گزارش: $LOG" >&2
  command -v notify-send >/dev/null && notify-send "گیم سنتر" "سرویس بالا نیامد — گزارش در $LOG"
  exit 1
fi

BROWSER="${GAMECENTER_BROWSER:-chromium}"
exec "$BROWSER" \
  --app="$URL" \
  --class=GameCenter \
  --user-data-dir="$LOG_DIR/chrome-profile" \
  --window-size=1560,980 \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=Translate,MediaRouter \
  --lang=fa
