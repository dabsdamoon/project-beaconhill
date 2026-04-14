#!/bin/bash
# A/B test runner: executes the same prompt against two branches of beaconhill.
#
# Usage: bash ab_test/run.sh [N]
#   N = runs per branch (default 3)
#
# Requires: ollama running locally, gemma4:26b pulled, git, python3.12.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AB_DIR="$ROOT/ab_test"
PROMPT_FILE="$AB_DIR/prompt.md"
WORKTREES="$AB_DIR/worktrees"
RESULTS="$AB_DIR/results"
N="${1:-3}"

MODEL="${BEACONHILL_MODEL:-gemma4:26b}"
CONTEXT_LIMIT="${BEACONHILL_CONTEXT_LIMIT:-32768}"

BRANCHES=("main" "harness")
REFS=(main feat/apply_claude_harness)

mkdir -p "$WORKTREES" "$RESULTS"

# Resolve the directory to use for a branch. If the branch is already checked
# out at ROOT, reuse ROOT (git refuses to create a second worktree for it).
worktree_path() {
    local name="$1" ref="$2"
    local current
    current=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)
    if [[ "$current" == "$ref" ]]; then
        echo "$ROOT"
    else
        echo "$WORKTREES/$name"
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
    local out="$RESULTS/$name/run-$run_idx"
    mkdir -p "$out"

    local extra_args=()
    if [[ "$name" == "harness" ]]; then
        extra_args+=(--plan-mode always)
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

    # Extract plan JSON and evaluation JSON from the session JSONL (harness only produces these).
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

    echo ""
    echo "All runs complete. Results in: $RESULTS"
    echo "Next: python3 $AB_DIR/evaluate.py"
}

main "$@"
