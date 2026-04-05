"""Validate that the agent chained multiple tools and got the correct answer.

instructions.txt says to read data.txt, sort alphabetically, report the 3rd item.
Sorted: apple, banana, cherry, date, elderberry, fig, grape
3rd item: cherry
"""
import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = (workspace / "_agent_output.txt").read_text()
messages = json.loads((workspace / "_agent_messages.json").read_text())

# Check that at least 2 different tools were called
tool_names = set()
for m in messages:
    if m.get("role") == "assistant" and m.get("tool_calls"):
        for tc in m["tool_calls"]:
            tool_names.add(tc["name"])

if len(tool_names) < 2:
    print(f"FAIL: Expected at least 2 tools, used: {tool_names}", file=sys.stderr)
    sys.exit(1)

# The answer is "cherry"
if "cherry" not in output.lower():
    print(f"FAIL: Expected 'cherry' in output, got: {output!r}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
