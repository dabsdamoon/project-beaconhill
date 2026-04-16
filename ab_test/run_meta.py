#!/usr/bin/env python3
"""Compute a run ID and write run_meta.json for an A/B test execution.

Used by run.sh at the start of a run. Run ID format:
    {YYYYMMDDTHHMMSS}-{short_sha}[_dirty]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


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


def compute_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    short = _git("rev-parse", "--short", "HEAD") or "nogit"
    suffix = "_dirty" if _is_dirty() else ""
    return f"{ts}-{short}{suffix}"


def build_meta(
    run_id: str,
    model: str,
    plan_mode: str,
    n_runs: int,
    max_eval_iterations: int | None,
    prompt_file: Path,
) -> dict:
    commit = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    base = _git("merge-base", "HEAD", "main") or ""
    ahead = 0
    if base:
        ahead_s = _git("rev-list", "--count", f"{base}..HEAD")
        ahead = int(ahead_s) if ahead_s.isdigit() else 0

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
            "ahead_of_main": ahead,
        },
        "config": {
            "model": model,
            "plan_mode": plan_mode,
            "max_eval_iterations": max_eval_iterations,
            "n_runs": n_runs,
            "prompt_file": str(prompt_file),
            "prompt_sha1_12": prompt_sha,
        },
        "env": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "ollama": _ollama_version(),
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
    p.add_argument("--model", default="gemma4:26b")
    p.add_argument("--plan-mode", default="always")
    p.add_argument("--n-runs", type=int, default=3)
    p.add_argument("--max-eval-iterations", type=int, default=5)
    p.add_argument("--prompt-file", default="ab_test/prompt.md")
    args = p.parse_args()

    results_dir = Path(args.results_dir)

    if args.command == "new":
        run_id = compute_run_id()
        run_dir = results_dir / run_id
        meta = build_meta(
            run_id=run_id,
            model=args.model,
            plan_mode=args.plan_mode,
            n_runs=args.n_runs,
            max_eval_iterations=args.max_eval_iterations,
            prompt_file=Path(args.prompt_file),
        )
        write_meta(run_dir / "run_meta.json", meta)

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
