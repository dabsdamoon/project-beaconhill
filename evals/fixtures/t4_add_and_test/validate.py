"""Validate that strings.py, test_strings.py exist and tests pass."""
import subprocess
import sys
from pathlib import Path

workspace = Path(sys.argv[1])

strings_file = workspace / "strings.py"
if not strings_file.exists():
    print("FAIL: strings.py not created", file=sys.stderr)
    sys.exit(1)

if "snake_to_camel" not in strings_file.read_text():
    print("FAIL: snake_to_camel not defined in strings.py", file=sys.stderr)
    sys.exit(1)

test_file = workspace / "test_strings.py"
if not test_file.exists():
    print("FAIL: test_strings.py not created", file=sys.stderr)
    sys.exit(1)

assertion_count = test_file.read_text().count("assert ")
if assertion_count < 3:
    print(
        f"FAIL: expected at least 3 assert statements, found {assertion_count}",
        file=sys.stderr,
    )
    sys.exit(1)

result = subprocess.run(
    [sys.executable, "-m", "pytest", "test_strings.py"],
    capture_output=True,
    text=True,
    cwd=workspace,
)
if result.returncode != 0:
    print(f"FAIL: pytest failed:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
