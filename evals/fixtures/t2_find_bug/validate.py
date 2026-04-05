"""Validate that the agent found the bug in the average function."""
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text().lower()

# The bug is `total / len(numbers) - 1` which should be `total / len(numbers)`
# or `total / (len(numbers) - 1)` depending on intent.
# The key is recognizing the `- 1` is wrong or the parentheses are wrong.
if ("- 1" in output or "minus 1" in output or "subtract" in output or
    "operator precedence" in output or "parenthes" in output or
    "order of operations" in output):
    sys.exit(0)

print(f"FAIL: Agent didn't identify the - 1 bug: {output[:200]!r}", file=sys.stderr)
sys.exit(1)
