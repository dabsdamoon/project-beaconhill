#!/bin/bash
# A/B test runner: executes the same prompt against two branches of beaconhill.
#
# Usage: bash ab_test/run.sh [N]
#   N = runs per branch (default 3)
#
# Output: ab_test/results/{YYYYMMDDTHHMMSS-shorthash}[_dirty]/
#   run_meta.json   (code version, config, env)
#   main/run-{1..N}/
#   harness/run-{1..N}/
#
# Requires: ollama running locally, gemma4:26b pulled, git, python3.12.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AB_DIR="$ROOT/ab_test"
PROMPT_FILE="$AB_DIR/prompt.md"
RESULTS="$AB_DIR/results"
N="${1:-3}"

MODEL="${BEACONHILL_MODEL:-gemma4:26b}"
CONTEXT_LIMIT="${BEACONHILL_CONTEXT_LIMIT:-32768}"
PLAN_MODE="always"
MAX_EVAL_ITERATIONS="${BEACONHILL_MAX_EVAL_ITERATIONS:-5}"

BRANCHES=("main" "harness")
REFS=(main feat/apply_claude_harness)

mkdir -p "$RESULTS"

# Compute run ID + write run_meta.json; also writes diff.patch if tree is dirty.
RUN_ID=$(python3 "$AB_DIR/run_meta.py" new \
    --results-dir "$RESULTS" \
    --model "$MODEL" \
    --plan-mode "$PLAN_MODE" \
    --n-runs "$N" \
    --max-eval-iterations "$MAX_EVAL_ITERATIONS" \
    --prompt-file "$PROMPT_FILE")
RUN_DIR="$RESULTS/$RUN_ID"
echo "[run] run_id: $RUN_ID"
echo "[run] run_dir: $RUN_DIR"

# Resolve worktree for a branch. Reuse ROOT if the branch is already checked out there.
worktree_path() {
    local name="$1" ref="$2"
    local current
    current=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)
    if [[ "$current" == "$ref" ]]; then
        echo "$ROOT"
    else
        echo "$AB_DIR/worktrees/$name"
    fi
}

setup_worktree() {
    local name="$1" ref="$2"
    local wt
    wt=$(worktree_path "$name" "$ref")

    if [[ "$wt" == "$ROOT" ]]; then
        echo "[setup] $name uses ROOT checkout (branch already checked out there)"
    elif [[ ! -d "$wt/.git" && ! -f "$wt/.git" ]]; then
        echo "[setup] creating worktree for $name ($ref)"
        mkdir -p "$AB_DIR/worktrees"
        git -C "$ROOT" worktree add "$wt" "$ref"
    else
        echo "[setup] worktree for $name exists"
    fi
    if [[ ! -x "$wt/.venv/bin/beaconhill" ]]; then
        echo "[setup] creating venv + installing beaconhill in $name"
        /opt/homebrew/opt/python@3.12/libexec/bin/python3 -m venv "$wt/.venv"
        "$wt/.venv/bin/pip" install --quiet -e "$wt"
    fi
}

run_one() {
    local name="$1" ref="$2" run_idx="$3"
    local wt
    wt=$(worktree_path "$name" "$ref")
    local out="$RUN_DIR/$name/run-$run_idx"
    mkdir -p "$out"

    local extra_args=()
    if [[ "$name" == "harness" ]]; then
        extra_args+=(--plan-mode "$PLAN_MODE")
    fi

    echo "[run] $name run-$run_idx"
    local t0 t1
    t0=$(python3 -c 'import time; print(time.time())')

    (
        cd "$out"
        "$wt/.venv/bin/beaconhill" \
            --model "$MODEL" \
            --allow-all \
            --session-dir "$out/sessions" \
            --prompt "$(cat "$PROMPT_FILE")" \
            "${extra_args[@]}" \
            > "$out/stdout.txt" 2> "$out/stderr.txt" || echo "[warn] beaconhill exited non-zero"
    )

    t1=$(python3 -c 'import time; print(time.time())')
    python3 -c "print(round($t1 - $t0, 2))" > "$out/wall_seconds.txt"

    local session
    session=$(ls "$out/sessions"/*.jsonl 2>/dev/null | head -1 || true)
    if [[ -n "$session" ]]; then
        cp "$session" "$out/session.jsonl"
        python3 "$AB_DIR/extract_plan.py" "$session" "$out" || true
    fi
}

main() {
    for i in "${!BRANCHES[@]}"; do
        setup_worktree "${BRANCHES[$i]}" "${REFS[$i]}"
    done

    for i in "${!BRANCHES[@]}"; do
        local name="${BRANCHES[$i]}"
        local ref="${REFS[$i]}"
        for run in $(seq 1 "$N"); do
            run_one "$name" "$ref" "$run"
        done
    done

    python3 "$AB_DIR/run_meta.py" finish --results-dir "$RESULTS" --run-id "$RUN_ID"

    echo ""
    echo "All runs complete. Results in: $RUN_DIR"
    echo "Next: python3 $AB_DIR/evaluate.py --run-dir $RUN_DIR"
}

main "$@"
