#!/bin/bash
# Cell B runner: gstack (process-first harness) + Gemma 4 26B via Claude Code -> Ollama bridge.
#
# Usage: bash run_cell_b.sh <run_dir> <prompt_file>
#
# Status: NOT IMPLEMENTED (M3). See docs/design/gstack-vs-beaconhill-experiment.md §7.
set -euo pipefail

OUT="$1"
PROMPT_FILE="$2"

mkdir -p "$OUT"

cat <<EOF >&2
[cell-b] not yet implemented (M3).

To implement:
  1. Install Claude Code (already present at ~/.local/bin/claude)
  2. Configure Anthropic-compatible Ollama proxy and set ANTHROPIC_BASE_URL
  3. Install gstack and pin to a recorded SHA
  4. Drive the gstack workflow non-interactively to produce \$OUT/timer.html
  5. Record cell_meta.json with model, harness=gstack, gstack_sha, base_url

Falling back: writing placeholder cell_meta.json and exiting non-zero.
EOF

echo '{"cell": "B", "harness": "gstack", "model": "gemma4:26b", "status": "not_implemented"}' \
    > "$OUT/cell_meta.json"
exit 78
