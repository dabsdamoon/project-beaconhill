#!/usr/bin/env python3
"""Eval runner for Beaconhill tool-calling validation.

Usage:
    python evals/runner.py                          # run all tiers
    python evals/runner.py --tier 1                  # run only tier 1
    python evals/runner.py --threshold t1=80,t2=60   # override thresholds
    python evals/runner.py --report results/report.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path so we can import beaconhill
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from beaconhill.agent import run_agent_turn
from beaconhill.client import OllamaClient
from beaconhill.orchestrator import run_orchestrated
from beaconhill.session import Session
from beaconhill.tools import create_default_registry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

DEFAULT_THRESHOLDS = {"t1": 90, "t2": 70, "t3": 50, "t4": 40}


@dataclass
class CaseResult:
    fixture: str
    tier: int
    passed: bool
    duration: float
    error: str | None = None
    agent_response: str = ""


def _last_assistant_text(messages: list) -> str:
    for m in reversed(messages):
        if str(m.role) == "assistant" and m.content:
            return m.content
    return ""


def discover_fixtures(tier: int | None = None) -> list[Path]:
    """Find all fixture directories, optionally filtered by tier."""
    if not FIXTURES_DIR.exists():
        return []
    fixtures = sorted(
        d for d in FIXTURES_DIR.iterdir()
        if d.is_dir() and d.name.startswith("t")
    )
    if tier is not None:
        fixtures = [f for f in fixtures if f.name.startswith(f"t{tier}_")]
    return fixtures


def get_tier(fixture: Path) -> int:
    """Extract tier number from fixture directory name (e.g., t1_read_file -> 1)."""
    return int(fixture.name[1])


def run_fixture(fixture: Path, client: OllamaClient) -> CaseResult:
    """Run a single eval fixture in an isolated temp directory."""
    tier = get_tier(fixture)
    start = time.time()

    prompt_file = fixture / "prompt.txt"
    validate_file = fixture / "validate.py"
    setup_dir = fixture / "setup"

    if not prompt_file.exists():
        return CaseResult(
            fixture=fixture.name, tier=tier, passed=False,
            duration=0, error="Missing prompt.txt",
        )

    # Create isolated working directory
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp) / "workspace"
        work_dir.mkdir()

        # Copy setup files if they exist
        if setup_dir.exists():
            shutil.copytree(setup_dir, work_dir, dirs_exist_ok=True)

        prompt = prompt_file.read_text().strip()

        # Run agent with working directory set
        orig_cwd = os.getcwd()
        try:
            os.chdir(work_dir)
            registry = create_default_registry()
            if tier >= 4:
                session = Session(model=client.model, session_dir=work_dir)
                run_orchestrated(
                    client=client,
                    registry=registry,
                    session=session,
                    tools=registry.to_ollama(),
                    allow_all=True,
                    context_limit=32768,
                    user_input=prompt,
                    interactive=False,
                )
                messages = session.messages
                response = _last_assistant_text(session.messages)
            else:
                messages, response = run_agent_turn(prompt, client, registry)
        except Exception as e:
            return CaseResult(
                fixture=fixture.name, tier=tier, passed=False,
                duration=time.time() - start, error=f"Agent error: {e}",
            )
        finally:
            os.chdir(orig_cwd)

        # Run validation
        if not validate_file.exists():
            return CaseResult(
                fixture=fixture.name, tier=tier, passed=False,
                duration=time.time() - start, error="Missing validate.py",
            )

        # Write agent output and messages for validator
        output_file = work_dir / "_agent_output.txt"
        output_file.write_text(response)

        messages_file = work_dir / "_agent_messages.json"
        messages_file.write_text(json.dumps(
            [m.to_dict() for m in messages], indent=2, ensure_ascii=False
        ))

        try:
            result = subprocess.run(
                [sys.executable, str(validate_file), str(work_dir)],
                capture_output=True, text=True, timeout=30,
            )
            passed = result.returncode == 0
            error = result.stderr.strip() if not passed else None
        except subprocess.TimeoutExpired:
            passed = False
            error = "Validation timed out"

        return CaseResult(
            fixture=fixture.name, tier=tier, passed=passed,
            duration=time.time() - start, error=error,
            agent_response=response,
        )


def parse_thresholds(threshold_str: str) -> dict[str, int]:
    """Parse threshold overrides like 't1=80,t2=60'."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    for part in threshold_str.split(","):
        key, value = part.strip().split("=")
        thresholds[key.strip()] = int(value.strip())
    return thresholds


def print_summary(results: list[CaseResult], thresholds: dict[str, int]) -> bool:
    """Print summary table. Returns True if all tiers pass."""
    tiers: dict[int, list[CaseResult]] = {}
    for r in results:
        tiers.setdefault(r.tier, []).append(r)

    print()
    print(f"{'Tier':<6} {'Passed':<8} {'Failed':<8} {'Rate':<8} {'Threshold':<10} {'Status'}")
    print("-" * 56)

    all_pass = True
    for tier_num in sorted(tiers):
        cases = tiers[tier_num]
        passed = sum(1 for c in cases if c.passed)
        failed = len(cases) - passed
        rate = (passed / len(cases) * 100) if cases else 0
        threshold = thresholds.get(f"t{tier_num}", 0)
        status = "PASS" if rate >= threshold else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {tier_num:<4} {passed:<8} {failed:<8} {rate:<7.0f}% {threshold:<9}% {status}")

    print()

    # Print individual failures
    failures = [r for r in results if not r.passed]
    if failures:
        print("Failed cases:")
        for r in failures:
            err = f" -- {r.error}" if r.error else ""
            print(f"  {r.fixture}{err}")
        print()

    return all_pass


def write_report(results: list[CaseResult], thresholds: dict[str, int], path: Path) -> None:
    """Write machine-readable report."""
    path.parent.mkdir(parents=True, exist_ok=True)

    tiers: dict[int, list[CaseResult]] = {}
    for r in results:
        tiers.setdefault(r.tier, []).append(r)

    report: dict[str, Any] = {"tiers": {}, "cases": []}
    for tier_num in sorted(tiers):
        cases = tiers[tier_num]
        passed = sum(1 for c in cases if c.passed)
        rate = (passed / len(cases) * 100) if cases else 0
        threshold = thresholds.get(f"t{tier_num}", 0)
        report["tiers"][f"t{tier_num}"] = {
            "passed": passed,
            "failed": len(cases) - passed,
            "total": len(cases),
            "rate": round(rate, 1),
            "threshold": threshold,
            "status": "pass" if rate >= threshold else "fail",
        }

    for r in results:
        report["cases"].append({
            "fixture": r.fixture,
            "tier": r.tier,
            "passed": r.passed,
            "duration": round(r.duration, 2),
            "error": r.error,
        })

    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Beaconhill eval runner")
    parser.add_argument("--tier", type=int, help="Run only this tier (1-4)")
    parser.add_argument("--threshold", type=str, help="Override thresholds (e.g., t1=80,t2=60)")
    parser.add_argument("--report", type=str, help="Path to write JSON report")
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model name")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama API host")
    args = parser.parse_args()

    thresholds = parse_thresholds(args.threshold) if args.threshold else dict(DEFAULT_THRESHOLDS)

    fixtures = discover_fixtures(tier=args.tier)
    if not fixtures:
        print("No fixtures found.")
        sys.exit(1)

    print(f"Beaconhill Eval | model: {args.model}")
    print(f"Fixtures: {len(fixtures)}")
    print()

    client = OllamaClient(model=args.model, host=args.host)
    results: list[CaseResult] = []

    for fixture in fixtures:
        print(f"  Running {fixture.name}...", end=" ", flush=True)
        result = run_fixture(fixture, client)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} ({result.duration:.1f}s)")

    all_pass = print_summary(results, thresholds)

    if args.report:
        report_path = Path(args.report)
        write_report(results, thresholds, report_path)
        print(f"Report written to {report_path}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
