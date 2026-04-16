#!/bin/bash
# Run only the harness branch inside an existing run folder.
# Use when run.sh was interrupted after the main runs completed.
#
# Usage: bash ab_test/run_harness_only.sh <run_id> [N]
#   run_id = folder name under ab_test/results/ (e.g. 20260415T134500-3de6081)
#   N      = number of runs (default 3)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AB_DIR="$ROOT/ab_test"
PROMPT_FILE="$AB_DIR/prompt.md"
RESULTS="$AB_DIR/results"

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <run_id> [N]" >&2
    exit 2
fi

RUN_ID="$1"
N="${2:-3}"
RUN_DIR="$RESULTS/$RUN_ID"
if [[ ! -d "$RUN_DIR" ]]; then
    echo "run-dir not found: $RUN_DIR" >&2
    exit 1
fi

MODEL="${BEACONHILL_MODEL:-gemma4:26b}"
WT="$ROOT"  # harness branch is checked out at ROOT

for run in $(seq 1 "$N"); do
    out="$RUN_DIR/harness/run-$run"
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

python3 "$AB_DIR/run_meta.py" finish --results-dir "$RESULTS" --run-id "$RUN_ID"

echo ""
echo "Harness runs complete: $RUN_DIR/harness/"
