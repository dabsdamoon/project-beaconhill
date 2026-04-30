#!/bin/bash
# Cell C runner: karpathy-guidelines (system-prompt overlay) + Claude Code + Haiku 4.5.
#
# Differs from cell B by exactly one flag: --append-system-prompt-file pointing
# at the vendored karpathy CLAUDE.md. Same --bare, same --disable-slash-commands,
# same model, same auth, same prompt path. Any quality delta C-vs-B isolates
# the karpathy-guidelines effect.
#
# Auth: --bare forces ANTHROPIC_API_KEY (OAuth and keychain are never read).
#
# Usage: bash run_cell_c.sh <run_dir> <prompt_file>
#
# Output: same as cell B, plus karpathy_sha in cell_meta.json.
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
PROMPT_FILE="$(cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"
MODEL="${HAIKU_MODEL:-claude-haiku-4-5-20251001}"
KARPATHY_FILE="$ROOT/ab_test/cells/karpathy_guidelines.md"
# Frozen upstream SHA recorded in the vendored file's header comment.
KARPATHY_SHA="2c606141936f1eeef17fa3043a72095b4765b9c2"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "[cell-c] ANTHROPIC_API_KEY not set. --bare requires it." >&2
    echo "        export ANTHROPIC_API_KEY=\"\$(op read 'op://Dev/Anthropic API/credential')\"" >&2
    exit 78
fi

if [[ ! -f "$KARPATHY_FILE" ]]; then
    echo "[cell-c] vendored karpathy file missing: $KARPATHY_FILE" >&2
    exit 78
fi

t0=$(python3 -c 'import time; print(time.time())')

(
    cd "$OUT"
    ANTHROPIC_MODEL="$MODEL" \
        claude --bare \
               --disable-slash-commands \
               --append-system-prompt-file "$KARPATHY_FILE" \
               --print \
               --model "$MODEL" \
               --permission-mode bypassPermissions \
               --output-format json \
        < "$PROMPT_FILE" \
        > "$OUT/stdout.txt" 2> "$OUT/stderr.txt" || echo "[cell-c] claude exited non-zero"
)

t1=$(python3 -c 'import time; print(time.time())')
python3 -c "print(round($t1 - $t0, 2))" > "$OUT/wall_seconds.txt"

python3 - "$OUT/stdout.txt" "$OUT/cell_meta.json" "$MODEL" "$KARPATHY_SHA" <<'PY'
import json, sys
from pathlib import Path

stdout_path, meta_path, requested_model, karpathy_sha = sys.argv[1:5]
meta = {
    "cell": "C",
    "harness": "claude_code_karpathy",
    "model": requested_model,
    "karpathy_sha": karpathy_sha,
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

USED=$(python3 -c "import json; print(json.load(open('$OUT/cell_meta.json')).get('model_used') or '')")
if [[ "$USED" != "$MODEL" ]]; then
    echo "[cell-c] WARNING: model_used=$USED differs from requested=$MODEL" >&2
fi
