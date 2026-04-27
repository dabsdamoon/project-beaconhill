#!/usr/bin/env python3
"""Combine deterministic + judge scores into a markdown report inside a run folder.

Multi-cell aware: discovers cells from run_meta.json. Picks up every
judge_packet_{X}_vs_{Y}.md / judge_scores_{X}_vs_{Y}.json / judge_mapping_{X}_vs_{Y}.json
triplet present in the run directory.

Inputs (under the run dir):
  run_meta.json
  deterministic_scores.json                  (from evaluate.py)
  judge_packet_{X}_vs_{Y}.md                 (from judge_prep.py)
  judge_mapping_{X}_vs_{Y}.json              (from judge_prep.py; un-blinds)
  judge_scores_{X}_vs_{Y}.json               (manually placed: judge response JSON)

Output:
  {run_dir}/report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AB_DIR))
from _run_dir import resolve_run_dir  # noqa: E402

RESULTS_ROOT = AB_DIR / "results"
PAIR_RE = re.compile(r"judge_mapping_([A-Za-z0-9]+)_vs_([A-Za-z0-9]+)\.json")


def load(run_dir: Path, name: str):
    p = run_dir / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def discover_pairs(run_dir: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for f in sorted(run_dir.iterdir()):
        m = PAIR_RE.fullmatch(f.name)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def unblind(judge_scores: dict, mapping: list[dict], cells: tuple[str, str]) -> dict:
    by_pair = {p["pair_id"]: p for p in mapping}
    cell_x, cell_y = cells
    cell_scores: dict[str, dict] = {
        cell_x: {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
        cell_y: {"feature": [], "aesthetic": [], "wins": 0, "ties": 0, "losses": 0},
    }
    for pair in judge_scores.get("pairs", []):
        info = by_pair.get(pair["pair_id"])
        if info is None:
            continue
        a_src, b_src = info["A_source"], info["B_source"]
        cell_scores[a_src]["feature"].append(float(pair["A"]["feature"]))
        cell_scores[a_src]["aesthetic"].append(float(pair["A"]["aesthetic"]))
        cell_scores[b_src]["feature"].append(float(pair["B"]["feature"]))
        cell_scores[b_src]["aesthetic"].append(float(pair["B"]["aesthetic"]))
        winner = pair.get("winner", "TIE").upper()
        if winner == "A":
            cell_scores[a_src]["wins"] += 1
            cell_scores[b_src]["losses"] += 1
        elif winner == "B":
            cell_scores[b_src]["wins"] += 1
            cell_scores[a_src]["losses"] += 1
        else:
            cell_scores[a_src]["ties"] += 1
            cell_scores[b_src]["ties"] += 1
    return cell_scores


def mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def build_report(run_dir: Path, meta: dict | None, det: dict) -> str:
    lines = ["# A/B Test Report", ""]

    if meta:
        g = meta.get("git", {})
        c = meta.get("config", {})
        cells = c.get("cells", {})
        lines.append(f"**Run ID:** `{meta.get('run_id', '?')}`")
        lines.append(f"**Started:** {meta.get('started_at', '?')}")
        if meta.get("finished_at"):
            lines.append(f"**Finished:** {meta['finished_at']}")
        lines.append(
            f"**Git:** `{g.get('commit', '?')[:8]}` on `{g.get('branch', '?')}`"
            + (" (dirty)" if g.get("dirty") else "")
        )
        lines.append(f"**Config:** n_runs={c.get('n_runs')}  seed={c.get('seed')}")
        lines.append("")
        lines.append("**Cells:**")
        lines.append("")
        lines.append("| Cell | Name | Harness | Model |")
        lines.append("|---|---|---|---|")
        for cid, cfg in sorted(cells.items()):
            lines.append(
                f"| {cid} | {cfg.get('name', '?')} | {cfg.get('harness', '?')} | "
                f"`{cfg.get('model', '?')}` |"
            )
        lines.append("")

    lines.append("## Deterministic scores")
    lines.append("")
    lines.append("| Cell | Feature | Aesthetic | Combined | File produced |")
    lines.append("|---|---|---|---|---|")
    for cell, stats in det.get("cells", {}).items():
        lines.append(
            f"| {cell} | {stats['mean_feature']} | {stats['mean_aesthetic']} "
            f"| {stats['mean_combined']} | {stats['file_produced_rate']} |"
        )
    lines.append("")

    pairs = discover_pairs(run_dir)
    if pairs:
        lines.append("## Judge (blinded pairwise) scores")
        lines.append("")
        for cell_x, cell_y in pairs:
            suffix = f"{cell_x}_vs_{cell_y}"
            mapping = load(run_dir, f"judge_mapping_{suffix}.json")
            scores = load(run_dir, f"judge_scores_{suffix}.json")
            lines.append(f"### {cell_x} vs {cell_y}")
            lines.append("")
            if not mapping or not scores:
                lines.append(
                    f"_judge_scores_{suffix}.json missing — paste judge JSON "
                    f"output to that path and re-run._"
                )
                lines.append("")
                continue
            ub = unblind(scores, mapping, (cell_x, cell_y))
            lines.append("| Cell | Feature (/10) | Aesthetic (/10) | Wins | Ties | Losses |")
            lines.append("|---|---|---|---|---|---|")
            for cell, s in ub.items():
                lines.append(
                    f"| {cell} | {mean(s['feature'])} | {mean(s['aesthetic'])} "
                    f"| {s['wins']} | {s['ties']} | {s['losses']} |"
                )
            lines.append("")
    else:
        lines.append("_No judge packets found. Run `judge_prep.py --pair X,Y`")
        lines.append("for each cell pair, paste each packet into Claude, then save the")
        lines.append("returned JSON as `judge_scores_X_vs_Y.json` in this run dir._")
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
    report = build_report(run_dir, meta, det)
    (run_dir / "report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
