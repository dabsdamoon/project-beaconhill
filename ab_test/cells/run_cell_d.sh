#!/bin/bash
# Cell D runner: gstack (process-first harness) + Haiku 4.5 via Claude Code.
#
# Prereqs (one-time):
#   1. Claude Code installed (claude --version >= 2.1.119) and OAuth-authed
#   2. gstack installed at ~/.claude/skills/gstack and ./setup --host claude run
#
# Usage: bash run_cell_d.sh <run_dir> <prompt_file>
#
# Output (in <run_dir>):
#   timer.html         the deliverable (when produced)
#   stdout.txt         claude --print JSON output
#   stderr.txt         claude stderr
#   wall_seconds.txt   wallclock for the run
#   cell_meta.json     model, harness, gstack SHA, model_used (parsed from JSON)
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"  # absolute path so it survives cd inside subshell
PROMPT_FILE="$(cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"
GSTACK_DIR="${GSTACK_DIR:-$HOME/.claude/skills/gstack}"
MODEL="${HAIKU_MODEL:-claude-haiku-4-5-20251001}"

if [[ ! -d "$GSTACK_DIR/.git" ]]; then
    echo "[cell-d] gstack not installed at $GSTACK_DIR" >&2
    echo "        run: git clone --depth 1 https://github.com/garrytan/gstack.git $GSTACK_DIR && \\" >&2
    echo "             cd $GSTACK_DIR && ./setup --host claude" >&2
    exit 78
fi

GSTACK_SHA=$(git -C "$GSTACK_DIR" rev-parse HEAD)

# Wrap the spec in a directive that drives gstack's workflow on Haiku.
# /autoplan -> implement -> /review mirrors gstack's documented "build a feature" flow.
WRAPPED_PROMPT=$(cat <<EOF
Use the gstack workflow to complete the task below.

1. Run /autoplan to produce an engineering plan.
2. Implement the plan: write a single file named "timer.html" in the current working directory. Do not create any other files.
3. Run /review on what you produced and fix any issues found.

Task spec follows. Implement it exactly.

---

$(cat "$PROMPT_FILE")
EOF
)

t0=$(python3 -c 'import time; print(time.time())')

(
    cd "$OUT"
    # NOTE: --add-dir is variadic and eats the positional prompt arg, hanging
    # claude --print waiting for stdin. CWD is already trusted, so omit it.
    # Pass prompt via stdin to remove any positional/variadic ambiguity.
    ANTHROPIC_MODEL="$MODEL" \
        claude --print \
               --model "$MODEL" \
               --permission-mode bypassPermissions \
               --output-format json \
        <<<"$WRAPPED_PROMPT" \
        > "$OUT/stdout.txt" 2> "$OUT/stderr.txt" || echo "[cell-d] claude exited non-zero"
)

t1=$(python3 -c 'import time; print(time.time())')
python3 -c "print(round($t1 - $t0, 2))" > "$OUT/wall_seconds.txt"

# Extract model_used and cost from stdout JSON to confirm Haiku actually answered.
python3 - "$OUT/stdout.txt" "$OUT/cell_meta.json" "$GSTACK_SHA" "$MODEL" <<'PY'
import json, sys
from pathlib import Path

stdout_path, meta_path, gstack_sha, requested_model = sys.argv[1:5]
meta = {
    "cell": "D",
    "harness": "gstack",
    "model": requested_model,
    "gstack_sha": gstack_sha,
    "model_used": None,
    "duration_ms": None,
    "cost_usd": None,
    "stop_reason": None,
}
text = Path(stdout_path).read_text(errors="replace").strip()
try:
    payload = json.loads(text)
    meta["duration_ms"] = payload.get("duration_ms")
    meta["cost_usd"] = payload.get("total_cost_usd")
    meta["stop_reason"] = payload.get("stop_reason")
    usage = payload.get("modelUsage", {})
    if usage:
        meta["model_used"] = next(iter(usage.keys()), None)
except json.JSONDecodeError:
    meta["parse_error"] = "stdout was not valid JSON"

Path(meta_path).write_text(json.dumps(meta, indent=2) + "\n")
PY

# Soft check: warn if model_used != requested_model. Don't fail the run — let
# the orchestrator collect data and the analysis flag bad trials.
USED=$(python3 -c "import json; print(json.load(open('$OUT/cell_meta.json')).get('model_used') or '')")
if [[ "$USED" != "$MODEL" ]]; then
    echo "[cell-d] WARNING: model_used=$USED differs from requested=$MODEL" >&2
fi
