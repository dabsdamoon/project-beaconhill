# Beaconhill Loop vs Claude Code on Haiku — G vs B vs C at n=5

**Branch**: `feat/gstack-and-haiku`
**Cell G run**: `20260430T040918-f26a60b_dirty` (data under [`data/20260430T040918-f26a60b_dirty/`](data/20260430T040918-f26a60b_dirty/))
**Cell B/C source**: `20260430T020135-31b0954_dirty` (the harness-ladder run)
**Model (all cells)**: `claude-haiku-4-5-20251001`
**G config**: Beaconhill orchestrator, plan-mode=always, max_eval_iterations=5, prompt-cache rolling

---

## TL;DR

> Cell G (Beaconhill loop-first harness driving Haiku) **wins on Layer-1 (mean 17.2/18 vs B 16.7, C 15.7) but loses on the blinded judge** to bare Claude Code 0–5–0 and to karpathy+CC 2–3–0. The loop-first evaluator catches *functional* spec-compliance issues better than no-loop, but Haiku without the loop produces more *aesthetically polished and design-coherent* output. The loop's value at strong-model regime is asymmetric: it raises the floor on functional correctness while not improving — and possibly hurting — design quality. n=5 here vs n=10 elsewhere; treat as directional.

---

## Setup

| Cell | Harness | Model | Source run |
|---|---|---|---|
| **B** bare CC | `claude --bare --disable-slash-commands --print` | Haiku 4.5 | n=10 from harness-ladder run, used run-3, 4, 6, 8, 9 |
| **C** karpathy + CC | B + `--append-system-prompt-file karpathy_guidelines.md` | Haiku 4.5 | n=10, same 5 runs by index |
| **G** Beaconhill loop | full plan→generate→evaluate orchestrator with rolling cache | Haiku 4.5 | n=5, fresh sweep |

G ran with `BEACONHILL_CACHE_MODE=rolling` (Option B caching from the prior analysis note); without caching, Cell G is not viable at the org's 50K input-tokens/min rate ceiling.

**Why n=5 for G**: cost per run averaged ~$0.30 (5–10× B and C), so the n=10 sweep was capped after 5 valid runs. run-6 was killed by user but had already produced a final `timer.html`; its `cell_meta.json` was patched from `usage.jsonl` and flagged `partial: true`. The 5 runs analyzed are run-{3,4,6,8,9} — same indices in B and C used for the pairwise judge.

**Cross-cell judge construction**: B and C `timer.html` files were copied into G's run_dir as synthetic cells, so `judge_prep.py` could pair them positionally. Mapping json + run_meta.json record this for reproducibility.

---

## Aggregate results

### Layer-1 deterministic (Playwright, 18-item rubric)

| Cell | n | Mean | Median | Min | Max | Per-run |
|---|---|---|---|---|---|---|
| **G** Beaconhill+Haiku | 5 | **17.20** | **18** | 16 | 18 | [18, 16, 18, 16, 18] |
| B bare CC+Haiku | 10 | 16.70 | 16 | 16 | 18 | [16, 16, 16, 18, 16, 18, 16, 17, 18, 16] |
| C karpathy+CC+Haiku | 10 | 15.70 | 16 | 13 | 18 | [16, 16, 16, 18, 15, 16, 16, 15, 13, 16] |
| D gstack+Haiku | 10 | 15.90 | 16 | 15 | 18 | (from pilot) |

**G has the highest Layer-1 mean and median of any Haiku cell.**

### Layer-2 blinded pairwise (Sonnet 4.6 judge)

#### G vs B (5 pairs)

| Pair | G run / B run | Winner | G feature/aes | B feature/aes |
|---|---|---|---|---|
| 1 | run-3 / run-3 | **B** | 9 / 8 | 10 / 9 |
| 2 | run-4 / run-4 | **B** | 10 / 8 | 10 / 9 |
| 3 | run-6 / run-6 | **B** | 10 / 9 | 10 / 9 |
| 4 | run-8 / run-8 | **B** | 10 / 9 | 10 / 9 |
| 5 | run-9 / run-9 | **B** | 10 / 9 | 10 / 9 |
| **total** | | **B 5, G 0** | mean 9.8 / 8.6 | mean 10.0 / 9.0 |

#### G vs C (5 pairs)

| Pair | G run / C run | Winner | G feature/aes | C feature/aes |
|---|---|---|---|---|
| 1 | run-3 / run-3 | **C** | 7 / 7 | 9 / 9 |
| 2 | run-4 / run-4 | **G** | 8 / 7 | 7 / 8 |
| 3 | run-6 / run-6 | **C** | 8 / 8 | 9 / 9 |
| 4 | run-8 / run-8 | **G** | 8 / 8 | 7 / 8 |
| 5 | run-9 / run-9 | **C** | 9 / 9 | 8 / 7 |
| **total** | | **C 3, G 2** | mean 8.0 / 7.8 | mean 8.0 / 8.2 |

#### Synthesis across all four Haiku cells

Combining this run's G results with the prior B-vs-C and A-vs-D pairwise judges:

| Cell | Layer-1 mean | Judge feature mean | Judge aesthetic mean | Judge wins (across all pairings) |
|---|---|---|---|---|
| **B** bare CC+Haiku | 16.70 | 8.4 (vs C), 10.0 (vs G) | 7.8 (vs C), 9.0 (vs G) | 6 (vs C) + 5 (vs G) = **11** |
| C karpathy+CC+Haiku | 15.70 | 7.1 (vs B), 8.0 (vs G) | 7.0 (vs B), 8.2 (vs G) | 3 (vs B) + 3 (vs G) = 6 |
| D gstack+Haiku | 15.90 | 8.4 (vs A) | 7.8 (vs A) | 9 (vs A); not directly compared to B/C/G |
| **G** Beaconhill+Haiku | **17.20** | 9.8 (vs B), 8.0 (vs C) | 8.6 (vs B), 7.8 (vs C) | 0 (vs B) + 2 (vs C) = 2 |

**Bare CC dominates the pairwise judge across all comparisons made**. Beaconhill's loop scores highest on Layer-1 but lowest on judge wins.

---

## The L1-vs-judge inversion

G has the **highest Layer-1** (17.2) and the **lowest judge wins** (2/10 across both pairings). Same data, opposite verdicts. This is the same pattern as the original A-vs-D pilot — Layer-1 over-credits structural presence, the judge picks up semantic spec compliance and design coherence — but here it inverts in the *other* direction.

### Why Layer-1 likes G

The 18-item rubric is heavily functional: distinct buttons, color values, MM:SS format, audio capability, mobile resize. Beaconhill's evaluator is *literally checking these acceptance criteria* before declaring done. So when G's evaluator passes, the artifact passes Layer-1 by construction. The loop is co-trained on the same axis Layer-1 measures.

In G's per-run scores, the only failed checks were `start_starts_countdown` (1 of 5) and `space_toggles_start_pause` (1 of 5) — same scoring-window artifact we see across all cells. No genuine spec violations slipped past the evaluator.

### Why the judge prefers B

The judge weighs *design coherence* and *aesthetic polish* heavily. Verbatim from un-blinded notes on G vs B:

> Pair 2: "B earns the aesthetic edge with filled vs. outlined button hierarchy, a live status line, and a class-based architecture."
> Pair 3: "B's 120px accent-colored timer is more visually impactful and its uniform outline button language is more internally consistent."
> Pair 4: "B's `clamp(60px, 15vw, 120px)` timer sizing is elegantly responsive and its filled-Start / outlined-Pause-Reset hierarchy is clearer."
> Pair 5: "A [G] has a better visual hierarchy ... but B has cleaner typography and consistent transitions" — judged for B on close call.

The pattern: **B's outputs have a single coherent design language. G's outputs are functional but visually less unified.** This isn't a Beaconhill defect per se; it's that Beaconhill's evaluator never asked "is the design coherent?" — only "does Reset return the timer to full duration?" So the model's first-pass design is the design that ships.

### Why karpathy (C) sometimes beats G

C's "Simplicity First" injunction makes it sometimes *underbuild*, which we saw cost it in the prior B-vs-C judge (C lost 3-6 to B by collapsing Start/Pause). But against G, C's restraint occasionally paid off:

> G vs C pair 1: "B [G] wires both Start and Pause to the same toggleStartPause function (redundant), countdown smaller, ..." (lost to C)
> G vs C pair 3: "A [G] silently auto-resets after the alert fires (not in spec); B [C] has all buttons correctly separated..." (lost to C)
> G vs C pair 5: "B [C] has no media query, so countdown does not adapt at mobile widths" (G won)

Notable: in pairs 1 and 3, **G violated the spec** (redundant function wiring; auto-reset behavior). Beaconhill's evaluator passed these. So the loop is not a perfect spec filter — it has its own blind spots, often around behaviors Layer-1's `start_starts_countdown` check doesn't probe deeply.

---

## Cost & wallclock comparison

| Cell | n | Total cost | Per-run cost | Per-run wall | Per-run calls |
|---|---|---|---|---|---|
| B bare CC | 10 | $0.49 | $0.049 | 30–60s | ~5–8 |
| C karpathy+CC | 10 | $0.53 | $0.053 | 30–60s | ~5–8 |
| **G Beaconhill** | **5** | **$1.43** | **$0.286** | **~5 min** | **51–97** |

G costs **5–6× more per run** and takes **~6× longer wallclock** than B/C, despite running on the same model. The architectural overhead (planner phase + per-step generator agentic loop + evaluator phase + retry iterations) issues 10× more API calls per task.

Caching is what makes G economically viable at all — without it, the runs hit rate limits before completing (see prior analysis note). With caching, ~84% of input tokens are read from cache, but the call *count* is still 10× B's, so wallclock scales accordingly.

---

## What this run does and doesn't say

### Says (with directional confidence at n=5):
- **Beaconhill's loop on Haiku improves functional spec compliance** (Layer-1 +0.5 over B, +1.5 over C) — the evaluator phase catches functional defects the model would otherwise ship.
- **Beaconhill's loop on Haiku does not improve design quality** — judge prefers bare CC unanimously over G; even karpathy edges G out 3-2.
- **The loop has cost. ~6× wall, ~5× cost vs bare CC** for the same task on the same model. Caching is necessary but not sufficient to close the gap.
- **The pilot's A-vs-D result conflated harness with model.** When you isolate harness on Haiku, Beaconhill's loop does not beat bare CC on judged quality. The pilot's "loop-first underperforms process-first 9-1" was largely the **Gemma-vs-Haiku gap**, not a harness-design verdict.

### Doesn't say:
- **Whether G's evaluator could be tuned for design coherence.** Beaconhill's acceptance criteria today are functional. Adding aesthetic checks could close the judge gap — at the cost of more iterations.
- **Whether Beaconhill's loop helps on harder tasks.** Pomodoro is a single-file UI task with well-defined spec — favors models that can one-shot it. The loop's value should be larger on multi-file or longer-horizon work where first-shot success drops.
- **Whether n=5 is enough.** The G-vs-B 0-5-0 result is unambiguous direction; n=10 might smooth slightly but unlikely to flip. G-vs-C 2-3-0 is closer to a coin flip and would benefit from n=10.
- **Whether Beaconhill's plan-mode "always" is the right setting.** Forcing the planner adds calls that may not pay back at strong-model regime. Comparing G with `plan-mode=never` would isolate the planner's contribution.

---

## Updated four-Haiku-cell picture

Layer-1 ranks G > B > D > C. Judge ranks B > {C ≈ G ≈ D, with B winning every direct comparison}. This is the **same divergence between L1 and judge that the pilot already flagged**, but now with much sharper resolution: the loop helps Layer-1 specifically because Layer-1 is functional and the loop is functionally tuned. The judge cares about things the loop doesn't optimize.

**For agentic harness design**, this argues for either:
- (a) Adding non-functional acceptance criteria to Beaconhill's evaluator (design coherence, code quality, idiomatic patterns) — turning the loop into a multi-axis filter.
- (b) Using simpler harnesses on strong models and reserving loop-first design for weak models / harder tasks where the marginal call value is higher.

The strict experimental answer for this task: **on Haiku, do less harness, not more.** The loop's value is in the *functional floor* it raises, but a strong model's first-shot output often clears that floor anyway.

---

## Reproduction

```bash
# Pre-flight
git checkout f26a60b
set -a; source .env; set +a    # ANTHROPIC_API_KEY into env

# Run G n=5 (will overshoot to n=5+ depending on shuffle order; kill with Ctrl-C after 5 valid)
BEACONHILL_CACHE_MODE=rolling bash ab_test/run.sh --cells G --n 10 --seed 42

# Score G with Layer-1
.venv/bin/python ab_test/score_layer1.py --run-dir ab_test/results/<G_run_id>

# Cross-cell judge: copy B/C timer.htmls in
RD_G=ab_test/results/<G_run_id>
RD_BC=ab_test/results/20260430T020135-31b0954_dirty
for run in run-3 run-4 run-6 run-8 run-9; do
  for cell in B C; do
    mkdir -p $RD_G/$cell/$run
    cp $RD_BC/$cell/$run/timer.html $RD_G/$cell/$run/
  done
done
# Register synthetic cells in run_meta.json (see commit f26a60b for the patch script)

.venv/bin/python ab_test/judge_prep.py --run-dir $RD_G --pair G,B
.venv/bin/python ab_test/judge_prep.py --run-dir $RD_G --pair G,C
# Submit each packet to Sonnet 4.6 via `claude --print`, extract JSON, save as judge_scores_G_vs_B.json etc.
```

Expect: G n=5 ~$1.40, ~25 min wall (sequential), no rate-limit errors with caching enabled.
