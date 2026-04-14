#!/usr/bin/env python3
"""Pull plan + evaluations from a Beaconhill session JSONL into readable sidecar files."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: extract_plan.py <session.jsonl> <out_dir>", file=sys.stderr)
        sys.exit(2)

    session_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    plans: list[dict] = []
    evaluations: list[dict] = []

    for line in session_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("_plan"):
            plans.append(data)
        elif data.get("_evaluation"):
            evaluations.append(data)

    # Keep only the most recent plan (plans are written multiple times as status updates).
    if plans:
        (out_dir / "plan.json").write_text(json.dumps(plans[-1], indent=2) + "\n")
        (out_dir / "plan_history.json").write_text(
            json.dumps(plans, indent=2) + "\n"
        )
    if evaluations:
        (out_dir / "evaluations.json").write_text(
            json.dumps(evaluations, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
