"""Validate the agent explained CSV parsing with quote handling."""
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text().lower()

# Must mention key concepts
checks = [
    ("csv" in output or "comma" in output or "delimiter" in output, "parsing/csv/delimiter"),
    ("quote" in output or "quoted" in output, "quote handling"),
    ("field" in output or "split" in output or "column" in output, "fields/splitting"),
]

failures = [desc for passed, desc in checks if not passed]
if failures:
    print(f"FAIL: Missing concepts: {failures}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
