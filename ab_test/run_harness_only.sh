#!/bin/bash
# One-off: run only the harness branch (3 runs). Used after partial A/B runs
# where the harness portion was interrupted and main runs are kept.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AB_DIR="$ROOT/ab_test"
PROMPT_FILE="$AB_DIR/prompt.md"
RESULTS="$AB_DIR/results"
N="${1:-3}"
MODEL="${BEACONHILL_MODEL:-gemma4:26b}"

WT="$ROOT"  # harness branch is checked out at ROOT

for run in $(seq 1 "$N"); do
    out="$RESULTS/harness/run-$run"
    mkdir -p "$out"
    echo "[run] harness run-$run"

    t0=$(python3 -c 'import time; print(time.time())')
    (
        cd "$out"
        "$WT/.venv/bin/beaconhill" \
            --model "$MODEL" \
            --allow-all \
            --session-dir "$out/sessions" \
            --prompt "$(cat "$PROMPT_FILE")" \
            --plan-mode always \
            > "$out/stdout.txt" 2> "$out/stderr.txt" || echo "[warn] beaconhill exited non-zero"
    )
    t1=$(python3 -c 'import time; print(time.time())')
    python3 -c "print(round($t1 - $t0, 2))" > "$out/wall_seconds.txt"

    session=$(ls "$out/sessions"/*.jsonl 2>/dev/null | head -1 || true)
    if [[ -n "$session" ]]; then
        cp "$session" "$out/session.jsonl"
        python3 "$AB_DIR/extract_plan.py" "$session" "$out" || true
    fi
done

echo ""
echo "Harness runs complete: $RESULTS/harness/"
