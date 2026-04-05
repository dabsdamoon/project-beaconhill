"""Validate that the agent found all 3 Python files."""
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text()

# Should mention all 3 .py files
expected = ["main.py", "utils.py", "test_main.py"]
found = [f for f in expected if f in output]

if len(found) < 3:
    missing = [f for f in expected if f not in output]
    print(f"FAIL: Missing files in output: {missing}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
