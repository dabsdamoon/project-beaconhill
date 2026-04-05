"""Validate that the agent handled the error gracefully."""
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text().upper()
messages = json.loads((workspace / "_agent_messages.json").read_text())

# Check that a tool was called (it should try read_file)
tool_calls = [
    m for m in messages
    if m.get("role") == "assistant" and m.get("tool_calls")
]
if not tool_calls:
    print("FAIL: No tool calls made", file=sys.stderr)
    sys.exit(1)

# Check the agent acknowledged the file doesn't exist
if "NOT FOUND" not in output and "DOES NOT EXIST" not in output and "NOT EXIST" not in output and "NO SUCH" not in output:
    print(f"FAIL: Agent didn't report file not found: {output!r}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
