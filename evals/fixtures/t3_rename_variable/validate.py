"""Validate that MAX_RETRIES was renamed to MAX_ATTEMPTS everywhere."""
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
source = (workspace / "config.py").read_text()

if "MAX_RETRIES" in source:
    print("FAIL: MAX_RETRIES still present", file=sys.stderr)
    sys.exit(1)

if "MAX_ATTEMPTS" not in source:
    print("FAIL: MAX_ATTEMPTS not found", file=sys.stderr)
    sys.exit(1)

# Should appear at least 3 times (declaration + 2 usages)
count = source.count("MAX_ATTEMPTS")
if count < 3:
    print(f"FAIL: MAX_ATTEMPTS appears only {count} times, expected at least 3", file=sys.stderr)
    sys.exit(1)

# Verify the module still parses
try:
    compile(source, "config.py", "exec")
except SyntaxError as e:
    print(f"FAIL: Syntax error after rename: {e}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
