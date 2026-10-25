#!/usr/bin/env bash
# Start the humanizer model on the GPU at http://127.0.0.1:8085 (port 8080 is used by another service).
# Settings follow the model card, except 4k context (hz pieces are ~350 words) to stay under ~10 GB VRAM, one slot, all layers on GPU, sampling defaults from the GGUF.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="${HUMANIZER_MODEL:-$DIR/humanizer-model/humanizer-12b-Q4_K_M.gguf}"
PORT="${HUMANIZER_PORT:-8085}"

LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo ~/.local/bin/llama-server)}"

exec "$LLAMA_SERVER" -m "$MODEL" -c "${HUMANIZER_CTX:-4096}" -np 1 -ngl 99 \
    --host 127.0.0.1 --port "$PORT" \
    --temp 1.0 --top-p 0.95 --top-k 0 --min-p 0 --repeat-penalty 1.0
