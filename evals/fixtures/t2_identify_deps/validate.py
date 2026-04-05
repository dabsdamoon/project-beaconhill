"""Validate that the agent identified the stdlib dependencies."""
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text().lower()

# Expected stdlib deps: sqlite3, hashlib, hmac
expected = ["sqlite3", "hashlib", "hmac"]
found = [dep for dep in expected if dep in output]

if len(found) < 2:
    print(f"FAIL: Found only {found} of {expected}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
