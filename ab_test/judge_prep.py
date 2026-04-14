#!/usr/bin/env python3
"""Assemble blinded pairwise judge packets.

For each run index i in [1..N], pair `main/run-i` vs `harness/run-i`. Randomize
whether the main output is shown as A or B, and save the mapping separately so
the reporter can un-blind scores later.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

AB_DIR = Path(__file__).resolve().parent
RESULTS = AB_DIR / "results"
PROMPT = (AB_DIR / "prompt.md").read_text()

TEMPLATE = """\
# Pairwise Judge Packet

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


def build_packet() -> tuple[str, list[dict]]:
    pairs: list[dict] = []
    pair_md_chunks: list[str] = []

    main_runs = sorted((RESULTS / "main").glob("run-*")) if (RESULTS / "main").exists() else []
    harness_runs = sorted((RESULTS / "harness").glob("run-*")) if (RESULTS / "harness").exists() else []

    rng = random.Random(42)
    for i, (m, h) in enumerate(zip(main_runs, harness_runs), start=1):
        m_html = (m / "timer.html").read_text(errors="replace") if (m / "timer.html").exists() else "(no file produced)"
        h_html = (h / "timer.html").read_text(errors="replace") if (h / "timer.html").exists() else "(no file produced)"

        main_as_a = rng.random() < 0.5
        if main_as_a:
            a_source, b_source = "main", "harness"
            a_html, b_html = m_html, h_html
        else:
            a_source, b_source = "harness", "main"
            a_html, b_html = h_html, m_html

        pairs.append({
            "pair_id": i,
            "A_source": a_source,
            "B_source": b_source,
            "main_run": m.name,
            "harness_run": h.name,
        })

        pair_md_chunks.append(
            f"## Pair {i}\n\n"
            f"### Output A\n\n```html\n{a_html}\n```\n\n"
            f"### Output B\n\n```html\n{b_html}\n```\n"
        )

    packet = TEMPLATE.replace("{prompt}", PROMPT).replace(
        "{pairs}", "\n\n".join(pair_md_chunks)
    )
    return packet, pairs


def main() -> None:
    packet, mapping = build_packet()
    (RESULTS / "judge_packet.md").write_text(packet)
    (RESULTS / "judge_mapping.json").write_text(json.dumps(mapping, indent=2) + "\n")
    print(f"Wrote judge packet with {len(mapping)} pair(s).")
    print(f"  {RESULTS / 'judge_packet.md'}")
    print(f"  {RESULTS / 'judge_mapping.json'} (keep private until judging is done)")


if __name__ == "__main__":
    main()
