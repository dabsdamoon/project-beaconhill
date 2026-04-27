#!/bin/bash
# Cell D runner: gstack (process-first harness) + Haiku 4.5 via Anthropic API.
#
# Usage: bash run_cell_d.sh <run_dir> <prompt_file>
#
# Status: NOT IMPLEMENTED (M4). See docs/design/gstack-vs-beaconhill-experiment.md §7.
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

mkdir -p "$OUT"

cat <<EOF >&2
[cell-d] not yet implemented (M4).

To implement, drive gstack via Claude Code with Haiku forced:
    ANTHROPIC_MODEL=claude-haiku-4-5-20251001 \\
      claude --model claude-haiku-4-5-20251001 \\
             --print \\
             --permission-mode bypassPermissions \\
             --max-budget-usd 2.00 \\
             --output-format json \\
             "\$(cat \$PROMPT_FILE)"

Steps:
  1. Read ANTHROPIC_API_KEY from 1Password (op read "op://Dev/Anthropic API/credential")
  2. Install gstack and pin to a recorded SHA
  3. Drive the gstack workflow non-interactively to produce \$OUT/timer.html
  4. Parse JSON output to extract model_used and capture in cell_meta.json
  5. Verify model_used == claude-haiku-4-5-20251001 before counting the run

Falling back: writing placeholder cell_meta.json and exiting non-zero.
EOF

echo '{"cell": "D", "harness": "gstack", "model": "claude-haiku-4-5-20251001", "status": "not_implemented"}' \
    > "$OUT/cell_meta.json"
exit 78
