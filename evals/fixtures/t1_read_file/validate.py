"""Validate that the agent read the file and found 3 functions."""
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text()
messages = json.loads((workspace / "_agent_messages.json").read_text())

# Check that read_file was called
tool_calls = [
    m for m in messages
    if m.get("role") == "assistant" and m.get("tool_calls")
]
used_read = any(
    tc["name"] == "read_file"
    for m in tool_calls
    for tc in m.get("tool_calls", [])
)
if not used_read:
    print("FAIL: read_file tool was not called", file=sys.stderr)
    sys.exit(1)

# Check the answer contains "3"
if "3" not in output:
    print(f"FAIL: Expected '3' in output, got: {output!r}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
