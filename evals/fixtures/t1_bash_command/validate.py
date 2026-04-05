"""Validate that the agent ran bash and got 42."""
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text()
messages = json.loads((workspace / "_agent_messages.json").read_text())

# Check that bash was called
tool_calls = [
    m for m in messages
    if m.get("role") == "assistant" and m.get("tool_calls")
]
used_bash = any(
    tc["name"] == "bash"
    for m in tool_calls
    for tc in m.get("tool_calls", [])
)
if not used_bash:
    print("FAIL: bash tool was not called", file=sys.stderr)
    sys.exit(1)

if "42" not in output:
    print(f"FAIL: Expected '42' in output, got: {output!r}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
