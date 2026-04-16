#!/usr/bin/env python3
"""Deterministic scoring of each A/B run inside a specific run folder.

Writes `scores.json` per run and `deterministic_scores.json` at the run-dir root.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AB_DIR))
from _run_dir import resolve_run_dir  # noqa: E402

RESULTS_ROOT = AB_DIR / "results"


@dataclass
class Score:
    feature: dict[str, bool] = field(default_factory=dict)
    aesthetic: dict[str, bool] = field(default_factory=dict)
    feature_score: float = 0.0
    aesthetic_score: float = 0.0
    combined_score: float = 0.0
    file_exists: bool = False
    size_bytes: int = 0
    notes: list[str] = field(default_factory=list)


FEATURE_CHECKS = [
    ("has_focus_mode", r"\b25[:\s]?00\b|\b25\s*minute"),
    ("has_break_mode", r"\b05[:\s]?00\b|\b5[:\s]?00\b|\b5\s*minute"),
    ("has_start_button", r"\bstart\b"),
    ("has_pause_button", r"\bpause\b"),
    ("has_reset_button", r"\breset\b"),
    ("has_mm_ss_format", r"\d{2}\s*:\s*\d{2}"),
    ("has_timer_loop", r"\bset(Interval|Timeout)\s*\("),
    ("has_audio_alert", r"AudioContext|<audio|playbackRate|oscillator"),
    ("has_space_shortcut", r"['\"]\s*(Space|\s|\s+)\s*['\"]|keyCode\s*===?\s*32|code\s*===?\s*['\"]Space"),
]

AESTHETIC_CHECKS = [
    ("color_background", r"#0d1117"),
    ("color_text", r"#e6edf3"),
    ("color_accent", r"#58a6ff"),
    ("monospace_font", r"monospace|SF Mono|ui-monospace|Menlo"),
    ("border_radius", r"border-radius\s*:\s*([8-9]|[1-9]\d)px"),
    ("transition", r"\btransition\s*:"),
    ("centering", r"flex|grid|justify-content|align-items|margin\s*:\s*auto"),
    ("responsive", r"@media|vw|vh|max-width"),
]


def score_html(text: str) -> Score:
    score = Score()
    score.size_bytes = len(text)
    for name, pattern in FEATURE_CHECKS:
        score.feature[name] = bool(re.search(pattern, text, re.IGNORECASE))
    for name, pattern in AESTHETIC_CHECKS:
        score.aesthetic[name] = bool(re.search(pattern, text, re.IGNORECASE))
    if score.feature:
        score.feature_score = sum(score.feature.values()) / len(score.feature)
    if score.aesthetic:
        score.aesthetic_score = sum(score.aesthetic.values()) / len(score.aesthetic)
    score.combined_score = (score.feature_score + score.aesthetic_score) / 2
    return score


def eval_run(run_dir: Path) -> Score:
    html_path = run_dir / "timer.html"
    if not html_path.exists():
        score = Score()
        score.notes.append("timer.html not produced")
        return score
    score = score_html(html_path.read_text(errors="replace"))
    score.file_exists = True
    return score


def run(run_dir: Path) -> dict:
    aggregate: dict = {"run_dir": str(run_dir), "branches": {}}
    for branch in ("main", "harness"):
        branch_dir = run_dir / branch
        if not branch_dir.is_dir():
            continue
        runs: list[dict] = []
        for rd in sorted(branch_dir.iterdir()):
            if not rd.is_dir() or not rd.name.startswith("run-"):
                continue
            score = eval_run(rd)
            (rd / "scores.json").write_text(json.dumps(asdict(score), indent=2) + "\n")
            runs.append({"run": rd.name, **asdict(score)})
        if runs:
            feat = [r["feature_score"] for r in runs]
            aes = [r["aesthetic_score"] for r in runs]
            comb = [r["combined_score"] for r in runs]
            aggregate["branches"][branch] = {
                "runs": runs,
                "mean_feature": round(sum(feat) / len(feat), 3),
                "mean_aesthetic": round(sum(aes) / len(aes), 3),
                "mean_combined": round(sum(comb) / len(comb), 3),
                "file_produced_rate": round(
                    sum(1 for r in runs if r["file_exists"]) / len(runs), 3
                ),
            }
    (run_dir / "deterministic_scores.json").write_text(
        json.dumps(aggregate, indent=2) + "\n"
    )
    return aggregate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None, help="Specific run folder; default: latest")
    args = ap.parse_args()
    run_dir = resolve_run_dir(RESULTS_ROOT, args.run_dir)
    print(json.dumps(run(run_dir), indent=2))


if __name__ == "__main__":
    main()
