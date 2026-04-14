#!/usr/bin/env python3
"""Combine deterministic + judge scores into a final report.

Inputs:
  results/deterministic_scores.json   (from evaluate.py)
  results/judge_scores.json           (manually placed: the JSON the judge returned)
  results/judge_mapping.json          (from judge_prep.py; un-blinds A/B)

Output:
  results/report.md
"""
from __future__ import annotations

import json
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
RESULTS = AB_DIR / "results"


def load(name: str):
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def unblind(judge_scores: dict, mapping: list[dict]) -> dict:
    """Convert blinded A/B scores into per-branch aggregates."""
    by_pair = {p["pair_id"]: p for p in mapping}
    branch_scores: dict[str, dict[str, list[float]]] = {
        "main": {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
        "harness": {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
    }
    for pair in judge_scores.get("pairs", []):
        pid = pair["pair_id"]
        info = by_pair.get(pid)
        if info is None:
            continue
        a_src = info["A_source"]
        b_src = info["B_source"]
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


def build_report(det: dict, judge: dict | None, mapping: list[dict] | None) -> str:
    lines = ["# A/B Test Report", ""]
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
        lines.append("into Claude, save the returned JSON to `results/judge_scores.json`, then re-run."  )
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    det = load("deterministic_scores.json")
    if det is None:
        raise SystemExit("run evaluate.py first")
    judge = load("judge_scores.json")
    mapping = load("judge_mapping.json")
    report = build_report(det, judge, mapping)
    (RESULTS / "report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
