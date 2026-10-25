#!/usr/bin/env bash
# Rewrite a .txt/.md/.docx file (or stdin) with the local humanizer server.
# Starts the server in the background if it is not already up. Extra args go to hz.
#   ./humanize.sh aims.docx -o aims.rewritten.docx
#   ./humanize.sh section.txt --json > report.json
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${HUMANIZER_PORT:-8085}"
URL="http://127.0.0.1:$PORT"

if ! curl -sf "$URL/health" >/dev/null 2>&1; then
    echo "Starting humanizer server on $URL (log: $DIR/server.log) ..." >&2
    nohup "$DIR/start-server.sh" >"$DIR/server.log" 2>&1 &
    until curl -sf "$URL/health" >/dev/null 2>&1; do
        kill -0 $! 2>/dev/null || { echo "Server failed to start; see $DIR/server.log" >&2; exit 1; }
        sleep 2
    done
fi

exec "$DIR/.venv/bin/hz" --server "$URL" "$@"
