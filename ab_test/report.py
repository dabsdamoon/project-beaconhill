#!/usr/bin/env python3
"""Combine deterministic + judge scores into a markdown report inside a run folder.

Inputs (all under the run dir):
  run_meta.json
  deterministic_scores.json   (from evaluate.py)
  judge_scores.json           (manually placed: JSON returned by the judge)
  judge_mapping.json          (from judge_prep.py; un-blinds A/B)

Output:
  {run_dir}/report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AB_DIR))
from _run_dir import resolve_run_dir  # noqa: E402

RESULTS_ROOT = AB_DIR / "results"


def load(run_dir: Path, name: str):
    p = run_dir / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def unblind(judge_scores: dict, mapping: list[dict]) -> dict:
    by_pair = {p["pair_id"]: p for p in mapping}
    branch_scores: dict[str, dict] = {
        "main": {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
        "harness": {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
    }
    for pair in judge_scores.get("pairs", []):
        info = by_pair.get(pair["pair_id"])
        if info is None:
            continue
        a_src, b_src = info["A_source"], info["B_source"]
        branch_scores[a_src]["feature"].append(float(pair["A"]["feature"]))
        branch_scores[a_src]["aesthetic"].append(float(pair["A"]["aesthetic"]))
        branch_scores[b_src]["feature"].append(float(pair["B"]["feature"]))
        branch_scores[b_src]["aesthetic"].append(float(pair["B"]["aesthetic"]))
        winner = pair.get("winner", "TIE").upper()
        if winner == "A":
            branch_scores[a_src]["wins"] += 1
            branch_scores[b_src]["losses"] += 1
        elif winner == "B":
            branch_scores[b_src]["wins"] += 1
            branch_scores[a_src]["losses"] += 1
        else:
            branch_scores[a_src]["ties"] += 1
            branch_scores[b_src]["ties"] += 1
    return branch_scores


def mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def build_report(meta: dict | None, det: dict, judge: dict | None, mapping: list | None) -> str:
    lines = ["# A/B Test Report", ""]

    if meta:
        g = meta.get("git", {})
        c = meta.get("config", {})
        lines.append(f"**Run ID:** `{meta.get('run_id', '?')}`")
        lines.append(f"**Started:** {meta.get('started_at', '?')}")
        if meta.get("finished_at"):
            lines.append(f"**Finished:** {meta['finished_at']}")
        lines.append(
            f"**Git:** `{g.get('commit', '?')[:8]}` on `{g.get('branch', '?')}`"
            + (" (dirty)" if g.get("dirty") else "")
        )
        lines.append(
            f"**Config:** model=`{c.get('model')}` "
            f"plan_mode=`{c.get('plan_mode')}` "
            f"max_eval_iterations={c.get('max_eval_iterations')} "
            f"n_runs={c.get('n_runs')}"
        )
        lines.append("")

    lines.append("## Deterministic scores")
    lines.append("")
    lines.append("| Branch | Feature | Aesthetic | Combined | File produced |")
    lines.append("|---|---|---|---|---|")
    for branch, stats in det.get("branches", {}).items():
        lines.append(
            f"| {branch} | {stats['mean_feature']} | {stats['mean_aesthetic']} "
            f"| {stats['mean_combined']} | {stats['file_produced_rate']} |"
        )
    lines.append("")

    if judge and mapping:
        lines.append("## Judge (blinded pairwise) scores")
        lines.append("")
        ub = unblind(judge, mapping)
        lines.append("| Branch | Feature (/10) | Aesthetic (/10) | Wins | Ties | Losses |")
        lines.append("|---|---|---|---|---|---|")
        for branch, s in ub.items():
            lines.append(
                f"| {branch} | {mean(s['feature'])} | {mean(s['aesthetic'])} "
                f"| {s['wins']} | {s['ties']} | {s['losses']} |"
            )
        lines.append("")
    else:
        lines.append("_Judge scores not yet provided. Run `judge_prep.py`, paste the packet")
        lines.append("into Claude, save the returned JSON to `judge_scores.json` in this run dir, then re-run._")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None, help="Specific run folder; default: latest")
    args = ap.parse_args()
    run_dir = resolve_run_dir(RESULTS_ROOT, args.run_dir)

    meta = load(run_dir, "run_meta.json")
    det = load(run_dir, "deterministic_scores.json")
    if det is None:
        raise SystemExit("run evaluate.py first")
    judge = load(run_dir, "judge_scores.json")
    mapping = load(run_dir, "judge_mapping.json")
    report = build_report(meta, det, judge, mapping)
    (run_dir / "report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
