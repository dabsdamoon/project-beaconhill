"""Validate the project summary covers key aspects."""
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text().lower()

checks = [
    ("mylib" in output, "project name/package"),
    ("engine" in output, "Engine class"),
    ("test" in output, "test suite"),
]

failures = [desc for passed, desc in checks if not passed]
if failures:
    print(f"FAIL: Missing from summary: {failures}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
