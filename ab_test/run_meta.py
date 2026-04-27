#!/usr/bin/env python3
"""Compute a run ID and write run_meta.json for an A/B test execution.

Used by run.sh at the start of a run. Run ID format:
    {YYYYMMDDTHHMMSS}-{short_sha}[_dirty]

Multi-cell aware: --cells A,B,D records per-cell config in the meta file
by reading ab_test/cells.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
CELLS_FILE = AB_DIR / "cells.json"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True
        ).stdout.strip()
        return out
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def _ollama_version() -> str:
    try:
        out = subprocess.run(
            ["ollama", "--version"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return out.splitlines()[0] if out else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"


def _claude_version() -> str:
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return out or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"


def compute_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    short = _git("rev-parse", "--short", "HEAD") or "nogit"
    suffix = "_dirty" if _is_dirty() else ""
    return f"{ts}-{short}{suffix}"


def load_cell_registry() -> dict:
    if not CELLS_FILE.exists():
        raise SystemExit(f"cells.json not found at {CELLS_FILE}")
    return json.loads(CELLS_FILE.read_text())


def resolve_cells(cells_arg: str, registry: dict) -> dict:
    """Return {cell_id: cell_config} for the requested cells."""
    requested = [c.strip() for c in cells_arg.split(",") if c.strip()]
    missing = [c for c in requested if c not in registry]
    if missing:
        raise SystemExit(f"unknown cell(s): {missing}. Known: {sorted(registry)}")
    return {c: registry[c] for c in requested}


def build_run_order(cells: list[str], n_runs: int, seed: int) -> list[tuple[str, int]]:
    """Pre-generate a shuffled (cell, run_idx) trial sequence."""
    trials = [(c, i + 1) for c in cells for i in range(n_runs)]
    random.Random(seed).shuffle(trials)
    return trials


def build_meta(
    run_id: str,
    cells: dict,
    n_runs: int,
    seed: int,
    prompt_file: Path,
) -> dict:
    commit = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")

    prompt_sha = ""
    if prompt_file.exists():
        prompt_sha = hashlib.sha1(prompt_file.read_bytes()).hexdigest()[:12]

    return {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git": {
            "commit": commit,
            "branch": branch,
            "dirty": _is_dirty(),
        },
        "config": {
            "cells": cells,
            "n_runs": n_runs,
            "seed": seed,
            "prompt_file": str(prompt_file),
            "prompt_sha1_12": prompt_sha,
        },
        "env": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "ollama": _ollama_version(),
            "claude_code": _claude_version(),
            "hostname": platform.node(),
        },
    }


def write_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n")


def update_finished(path: Path) -> None:
    if not path.exists():
        return
    meta = json.loads(path.read_text())
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(meta, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["new", "finish"])
    p.add_argument("--results-dir", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--cells", default="A", help="Comma-separated cell IDs, e.g. A,B,D")
    p.add_argument("--n-runs", type=int, default=5)
    p.add_argument("--seed", type=int, default=42, help="RNG seed for run order")
    p.add_argument("--prompt-file", default="ab_test/prompt.md")
    args = p.parse_args()

    results_dir = Path(args.results_dir)

    if args.command == "new":
        registry = load_cell_registry()
        cells = resolve_cells(args.cells, registry)
        run_id = compute_run_id()
        run_dir = results_dir / run_id
        meta = build_meta(
            run_id=run_id,
            cells=cells,
            n_runs=args.n_runs,
            seed=args.seed,
            prompt_file=Path(args.prompt_file),
        )
        write_meta(run_dir / "run_meta.json", meta)

        # Pre-generate shuffled trial order so post-hoc randomization claims are auditable.
        order = build_run_order(list(cells), args.n_runs, args.seed)
        order_lines = [f"{c} {i}" for c, i in order]
        (run_dir / "run_order.txt").write_text("\n".join(order_lines) + "\n")

        # If dirty, capture the working-tree diff so the experiment is reproducible.
        if meta["git"]["dirty"]:
            try:
                diff = subprocess.run(
                    ["git", "diff", "HEAD"],
                    capture_output=True, text=True, check=True,
                ).stdout
                (run_dir / "diff.patch").write_text(diff)
            except subprocess.CalledProcessError:
                pass

        print(run_id)
    elif args.command == "finish":
        if not args.run_id:
            print("finish requires --run-id", file=sys.stderr)
            sys.exit(2)
        update_finished(results_dir / args.run_id / "run_meta.json")


if __name__ == "__main__":
    main()
