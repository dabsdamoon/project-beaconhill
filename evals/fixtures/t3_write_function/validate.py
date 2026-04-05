"""Validate that fibonacci.py was created and tests pass."""
import subprocess
import sys
from pathlib import Path

workspace = Path(sys.argv[1])

fib_file = workspace / "fibonacci.py"
if not fib_file.exists():
    print("FAIL: fibonacci.py not created", file=sys.stderr)
    sys.exit(1)

result = subprocess.run(
    [sys.executable, "-m", "pytest", "test_fibonacci.py", "-v"],
    capture_output=True, text=True, cwd=workspace,
)
if result.returncode != 0:
    print(f"FAIL: Tests failed:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
