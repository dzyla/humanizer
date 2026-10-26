#!/usr/bin/env bash
# Start the clarity model (suggested wording for hard-to-read sentences) at http://127.0.0.1:8087.
# On the GPU when about 4 GB is free, otherwise on the CPU (slower, but it only rewrites one sentence at a time).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="${CLARITY_MODEL:-$DIR/clarity-model/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
PORT="${CLARITY_PORT:-8087}"
LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo ~/.local/bin/llama-server)}"
[ -f "$MODEL" ] || { echo "Clarity model not found: $MODEL (see README)" >&2; exit 1; }

NGL="${CLARITY_NGL:-}"
if [ -z "$NGL" ]; then
    FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
    if [ "${FREE:-0}" -gt 4000 ]; then NGL=99; else NGL=0; fi
fi
echo "clarity model on $([ "$NGL" = 0 ] && echo CPU || echo GPU)" >&2

exec "$LLAMA_SERVER" -m "$MODEL" -c 4096 -np 1 -ngl "$NGL" --host 127.0.0.1 --port "$PORT" --jinja
