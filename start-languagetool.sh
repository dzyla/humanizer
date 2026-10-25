#!/usr/bin/env bash
# Start the local LanguageTool server at http://127.0.0.1:8081 (only reachable from this machine).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${LANGUAGETOOL_PORT:-8081}"
LT="$(ls -d "$DIR"/tools/LanguageTool-*/ 2>/dev/null | sort -V | tail -1)"
[ -n "$LT" ] || { echo "LanguageTool not found; run $DIR/setup-languagetool.sh" >&2; exit 1; }

exec java -Xmx1g -cp "$LT/languagetool-server.jar" org.languagetool.server.HTTPServer --port "$PORT"
