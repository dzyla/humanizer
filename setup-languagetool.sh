#!/usr/bin/env bash
# Download LanguageTool (the grammar checker, ~250 MB, needs Java 17+) into tools/. Runs fully offline afterwards.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/tools"
if ls -d "$DIR"/tools/LanguageTool-*/ >/dev/null 2>&1; then
    echo "LanguageTool is already in $DIR/tools"; exit 0
fi
command -v java >/dev/null || { echo "LanguageTool needs Java 17 or newer (e.g. sudo apt install openjdk-21-jre-headless)" >&2; exit 1; }
curl -fL -o "$DIR/tools/LanguageTool-stable.zip" https://languagetool.org/download/LanguageTool-stable.zip
unzip -q "$DIR/tools/LanguageTool-stable.zip" -d "$DIR/tools"
rm "$DIR/tools/LanguageTool-stable.zip"
ls -d "$DIR"/tools/LanguageTool-*/
