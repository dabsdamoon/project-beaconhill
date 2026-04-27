#!/usr/bin/env python3
"""Assemble blinded pairwise judge packets for a specific run folder.

Multi-cell aware: takes --pair CELL1,CELL2 (e.g. --pair A,B) and produces a packet
pairing run-i from each side with randomized A/B labelling. Run multiple times
for the three pairs in {A, B, D}.

Default --pair: the first two cells (sorted) found in run_meta.json.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AB_DIR))
from _run_dir import resolve_run_dir  # noqa: E402

RESULTS_ROOT = AB_DIR / "results"
PROMPT = (AB_DIR / "prompt.md").read_text()

TEMPLATE = """\
# Pairwise Judge Packet — {pair_label}

You are judging two LLM-generated `timer.html` outputs against the spec below. \
You do not know which output came from which system.

For each pair, rate both outputs on two axes and pick a winner:

1. **Feature completeness** (0-10): did it implement every required feature correctly?
2. **Aesthetic quality** (0-10): does it meet the color/typography/layout spec and feel polished?
3. **Winner**: A, B, or TIE.

Respond with a single JSON object matching this schema:

```json
{
  "pairs": [
    {
      "pair_id": 1,
      "A": {"feature": 0, "aesthetic": 0},
      "B": {"feature": 0, "aesthetic": 0},
      "winner": "A|B|TIE",
      "notes": "one short sentence"
    }
  ]
}
```

---

## Spec

{prompt}

---

{pairs}
"""


def cells_from_meta(run_dir: Path) -> list[str]:
    meta_path = run_dir / "run_meta.json"
    if not meta_path.exists():
        return sorted(
            d.name for d in run_dir.iterdir()
            if d.is_dir() and any(c.name.startswith("run-") for c in d.iterdir() if c.is_dir())
        )
    meta = json.loads(meta_path.read_text())
    cells = meta.get("config", {}).get("cells", {})
    return sorted(cells.keys())


def resolve_pair(run_dir: Path, pair_arg: str | None) -> tuple[str, str]:
    cells = cells_from_meta(run_dir)
    if pair_arg:
        parts = [p.strip() for p in pair_arg.split(",") if p.strip()]
        if len(parts) != 2:
            raise SystemExit(f"--pair must be 'CELL1,CELL2'; got {pair_arg!r}")
        for p in parts:
            if p not in cells:
                raise SystemExit(f"cell {p!r} not in run; available: {cells}")
        return parts[0], parts[1]
    if len(cells) < 2:
        raise SystemExit(f"need at least 2 cells in run; found {cells}")
    return cells[0], cells[1]


def build_packet(run_dir: Path, cell_x: str, cell_y: str, seed: int) -> tuple[str, list[dict]]:
    pair_label = f"{cell_x} vs {cell_y}"
    pairs: list[dict] = []
    pair_md_chunks: list[str] = []

    x_runs = sorted((run_dir / cell_x).glob("run-*")) if (run_dir / cell_x).exists() else []
    y_runs = sorted((run_dir / cell_y).glob("run-*")) if (run_dir / cell_y).exists() else []

    rng = random.Random(seed)
    for i, (x, y) in enumerate(zip(x_runs, y_runs), start=1):
        x_html = (x / "timer.html").read_text(errors="replace") if (x / "timer.html").exists() else "(no file produced)"
        y_html = (y / "timer.html").read_text(errors="replace") if (y / "timer.html").exists() else "(no file produced)"

        x_as_a = rng.random() < 0.5
        if x_as_a:
            a_source, b_source = cell_x, cell_y
            a_html, b_html = x_html, y_html
        else:
            a_source, b_source = cell_y, cell_x
            a_html, b_html = y_html, x_html

        pairs.append({
            "pair_id": i,
            "A_source": a_source,
            "B_source": b_source,
            f"{cell_x}_run": x.name,
            f"{cell_y}_run": y.name,
        })

        pair_md_chunks.append(
            f"## Pair {i}\n\n"
            f"### Output A\n\n```html\n{a_html}\n```\n\n"
            f"### Output B\n\n```html\n{b_html}\n```\n"
        )

    packet = (
        TEMPLATE
        .replace("{pair_label}", pair_label)
        .replace("{prompt}", PROMPT)
        .replace("{pairs}", "\n\n".join(pair_md_chunks))
    )
    return packet, pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None, help="Specific run folder; default: latest")
    ap.add_argument("--pair", default=None, help="CELL1,CELL2 (default: first two cells in run)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for A/B blinding")
    args = ap.parse_args()
    run_dir = resolve_run_dir(RESULTS_ROOT, args.run_dir)

    cell_x, cell_y = resolve_pair(run_dir, args.pair)
    packet, mapping = build_packet(run_dir, cell_x, cell_y, args.seed)

    suffix = f"{cell_x}_vs_{cell_y}"
    packet_path = run_dir / f"judge_packet_{suffix}.md"
    mapping_path = run_dir / f"judge_mapping_{suffix}.json"
    packet_path.write_text(packet)
    mapping_path.write_text(json.dumps(mapping, indent=2) + "\n")

    print(f"Wrote judge packet ({cell_x} vs {cell_y}) with {len(mapping)} pair(s).")
    print(f"  {packet_path}")
    print(f"  {mapping_path} (keep private until judging is done)")


if __name__ == "__main__":
    main()
