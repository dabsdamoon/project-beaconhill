#!/bin/bash
# Cell G runner: Beaconhill (loop-first harness) + Haiku 4.5 via Anthropic API.
#
# Same Beaconhill stack as cell A, model swapped to Haiku via the new
# AnthropicClient (selected by name prefix `claude-*` in cli.py).
#
# Usage: bash run_cell_g.sh <run_dir> <prompt_file>
#
# Env:
#   ANTHROPIC_API_KEY        REQUIRED — exported by caller (e.g. from .env)
#   BEACONHILL_MODEL         default claude-haiku-4-5-20251001
#   BEACONHILL_PLAN_MODE     default always (parity with cell A)
#   BEACONHILL_CONTEXT_LIMIT default 32768
#
# Output (mirrors cell A):
#   stdout.txt, stderr.txt, wall_seconds.txt
#   sessions/, session.jsonl, plan.json
#   cell_meta.json — model, harness, model_used, total_cost_usd
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AB_DIR="$ROOT/ab_test"

MODEL="${BEACONHILL_MODEL:-claude-haiku-4-5-20251001}"
PLAN_MODE="${BEACONHILL_PLAN_MODE:-always}"
export BEACONHILL_CONTEXT_LIMIT="${BEACONHILL_CONTEXT_LIMIT:-32768}"
# Cache mode: "off" (default) or "rolling" (Option B: system + last-turn breakpoints).
# Caller exports this to pick a mode for the run.
export BEACONHILL_CACHE_MODE="${BEACONHILL_CACHE_MODE:-off}"

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
PROMPT_FILE="$(cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "[cell-g] ANTHROPIC_API_KEY not set." >&2
    echo "        export ANTHROPIC_API_KEY before running, e.g.:" >&2
    echo "        set -a; source .env; set +a; bash $0 ..." >&2
    exit 78
fi

if [[ ! -x "$ROOT/.venv/bin/beaconhill" ]]; then
    echo "[cell-g] creating venv + installing beaconhill (with cloud extra)"
    /opt/homebrew/opt/python@3.12/libexec/bin/python3 -m venv "$ROOT/.venv"
    "$ROOT/.venv/bin/pip" install --quiet -e "$ROOT[cloud]"
fi

# Ensure anthropic SDK is importable even if the venv predates this milestone.
if ! "$ROOT/.venv/bin/python" -c "import anthropic" 2>/dev/null; then
    echo "[cell-g] installing missing anthropic SDK"
    "$ROOT/.venv/bin/pip" install --quiet 'anthropic>=0.40,<1.0'
fi

t0=$(python3 -c 'import time; print(time.time())')

# Per-call usage log; AnthropicClient appends one JSON line per API response.
export BEACONHILL_USAGE_LOG="$OUT/usage.jsonl"

(
    cd "$OUT"
    "$ROOT/.venv/bin/beaconhill" \
        --model "$MODEL" \
        --plan-mode "$PLAN_MODE" \
        --allow-all \
        --session-dir "$OUT/sessions" \
        --prompt "$(cat "$PROMPT_FILE")" \
        > "$OUT/stdout.txt" 2> "$OUT/stderr.txt" || echo "[cell-g] beaconhill exited non-zero"
)

t1=$(python3 -c 'import time; print(time.time())')
python3 -c "print(round($t1 - $t0, 2))" > "$OUT/wall_seconds.txt"

session=$(ls "$OUT/sessions"/*.jsonl 2>/dev/null | head -1 || true)
MODEL_USED=""
COST_USD=""
if [[ -n "$session" ]]; then
    cp "$session" "$OUT/session.jsonl"
    python3 "$AB_DIR/extract_plan.py" "$session" "$OUT" || true
    # Sniff session.jsonl meta for model + cost. Beaconhill writes a meta line at
    # the top; if AnthropicClient logs cost per call, sum them.
    read MODEL_USED COST_USD <<< "$(python3 - "$session" <<'PY'
import json, sys
path = sys.argv[1]
model = ""
cost = 0.0
with open(path) as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            model = d.get("model") or model
            c = d.get("cost_usd")
            if isinstance(c, (int, float)):
                cost += float(c)
print(model or "unknown", f"{cost:.6f}")
PY
    )"
fi

python3 - "$OUT/cell_meta.json" "$MODEL" "$MODEL_USED" "$BEACONHILL_CACHE_MODE" "$OUT/usage.jsonl" <<'PY'
import json, sys
from pathlib import Path

meta_path, requested, used, cache_mode, usage_path = sys.argv[1:6]

# Sum usage from per-call JSONL the AnthropicClient writes.
totals = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cost_usd": 0.0,
}
p = Path(usage_path)
if p.exists():
    for line in p.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        totals["calls"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            totals[k] += int(d.get(k) or 0)
        totals["cost_usd"] += float(d.get("cost_usd") or 0.0)
totals["cost_usd"] = round(totals["cost_usd"], 6)

meta = {
    "cell": "G",
    "harness": "beaconhill",
    "model": requested,
    "model_used": used or None,
    "cache_mode": cache_mode,
    "total_cost_usd": totals["cost_usd"],
    "usage_totals": totals,
}
with open(meta_path, "w") as f:
    f.write(json.dumps(meta, indent=2) + "\n")
PY
