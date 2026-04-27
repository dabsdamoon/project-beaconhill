#!/bin/bash
# Cell A runner: Beaconhill (loop-first harness) + Gemma 4 26B via local Ollama.
#
# Usage: bash run_cell_a.sh <run_dir> <prompt_file>
#   run_dir     output directory for this single run (must exist or be creatable)
#   prompt_file path to the spec passed via --prompt
#
# Env overrides:
#   BEACONHILL_MODEL          default gemma4:26b
#   BEACONHILL_PLAN_MODE      default always
#   BEACONHILL_CONTEXT_LIMIT  default 32768
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AB_DIR="$ROOT/ab_test"

MODEL="${BEACONHILL_MODEL:-gemma4:26b}"
PLAN_MODE="${BEACONHILL_PLAN_MODE:-always}"
export BEACONHILL_CONTEXT_LIMIT="${BEACONHILL_CONTEXT_LIMIT:-32768}"

mkdir -p "$OUT"

if [[ ! -x "$ROOT/.venv/bin/beaconhill" ]]; then
    echo "[cell-a] creating venv + installing beaconhill"
    /opt/homebrew/opt/python@3.12/libexec/bin/python3 -m venv "$ROOT/.venv"
    "$ROOT/.venv/bin/pip" install --quiet -e "$ROOT"
fi

t0=$(python3 -c 'import time; print(time.time())')

(
    cd "$OUT"
    "$ROOT/.venv/bin/beaconhill" \
        --model "$MODEL" \
        --plan-mode "$PLAN_MODE" \
        --allow-all \
        --session-dir "$OUT/sessions" \
        --prompt "$(cat "$PROMPT_FILE")" \
        > "$OUT/stdout.txt" 2> "$OUT/stderr.txt" || echo "[cell-a] beaconhill exited non-zero"
)

t1=$(python3 -c 'import time; print(time.time())')
python3 -c "print(round($t1 - $t0, 2))" > "$OUT/wall_seconds.txt"

session=$(ls "$OUT/sessions"/*.jsonl 2>/dev/null | head -1 || true)
if [[ -n "$session" ]]; then
    cp "$session" "$OUT/session.jsonl"
    python3 "$AB_DIR/extract_plan.py" "$session" "$OUT" || true
fi

echo "{\"cell\": \"A\", \"model\": \"$MODEL\", \"harness\": \"beaconhill\"}" \
    > "$OUT/cell_meta.json"
