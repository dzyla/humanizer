#!/usr/bin/env bash
# Two-panel humanizer UI (draft left, rewrite right) at http://127.0.0.1:8086.
# Starts the model server in the background if it is not already up.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${HUMANIZER_PORT:-8085}"
UI_PORT="${HUMANIZER_UI_PORT:-8086}"
URL="http://127.0.0.1:$PORT"

if ! curl -sf "$URL/health" >/dev/null 2>&1; then
    echo "Starting humanizer server on $URL (log: $DIR/server.log) ..." >&2
    nohup "$DIR/start-server.sh" >"$DIR/server.log" 2>&1 &
    until curl -sf "$URL/health" >/dev/null 2>&1; do
        kill -0 $! 2>/dev/null || { echo "Server failed to start; see $DIR/server.log" >&2; exit 1; }
        sleep 2
    done
fi

# grammar check (optional): start LanguageTool if it is installed and not running
LT_URL="http://127.0.0.1:${LANGUAGETOOL_PORT:-8081}"
if ! curl -sf "$LT_URL/v2/languages" >/dev/null 2>&1; then
    if ls -d "$DIR"/tools/LanguageTool-*/ >/dev/null 2>&1; then
        echo "Starting LanguageTool on $LT_URL (log: $DIR/languagetool.log) ..." >&2
        nohup "$DIR/start-languagetool.sh" >"$DIR/languagetool.log" 2>&1 &
    else
        echo "LanguageTool not installed; grammar check is off. Run $DIR/setup-languagetool.sh to add it." >&2
    fi
fi

# open the page in the Windows browser under WSL, or the desktop default elsewhere
( sleep 1; { command -v wslview >/dev/null && wslview "http://127.0.0.1:$UI_PORT"; } \
    || { command -v explorer.exe >/dev/null && explorer.exe "http://127.0.0.1:$UI_PORT"; } \
    || { command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$UI_PORT"; } ) >/dev/null 2>&1 &

exec "$DIR/.venv/bin/python" "$DIR/ui/app.py" --port "$UI_PORT" --server "$URL" --lt "$LT_URL"
