"""Validate that greeting parameter was added correctly."""
import subprocess
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
greeter = workspace / "greeter.py"

if not greeter.exists():
    print("FAIL: greeter.py not found", file=sys.stderr)
    sys.exit(1)

# Test by importing and calling the function
test_code = """
import sys
sys.path.insert(0, '.')
from greeter import greet

# Default should still work
assert greet("World") == "Hello, World!", f"Default failed: {greet('World')}"

# Custom greeting should work
result = greet("World", greeting="Hi")
assert result == "Hi, World!", f"Custom greeting failed: {result}"

print("OK")
"""
result = subprocess.run(
    [sys.executable, "-c", test_code],
    capture_output=True, text=True, cwd=workspace,
)
if result.returncode != 0:
    print(f"FAIL: {result.stderr or result.stdout}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
