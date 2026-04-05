"""Validate that the off-by-one bug was fixed."""
import subprocess
import sys
from pathlib import Path

workspace = Path(sys.argv[1])

# Run the test suite
result = subprocess.run(
    [sys.executable, "-m", "pytest", "test_processor.py", "-v"],
    capture_output=True, text=True, cwd=workspace,
)
if result.returncode != 0:
    print(f"FAIL: Tests still failing:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
    sys.exit(1)

# Verify the fix is correct: the `- 1` should be removed
source = (workspace / "processor.py").read_text()
if "- n - 1" in source:
    print("FAIL: Bug not fixed, still has '- n - 1'", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
