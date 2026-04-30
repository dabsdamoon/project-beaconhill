# Harness Ladder at Haiku 4.5 — B vs C (and D for context)

**Branch**: `feat/gstack-and-haiku`
**Pre-registered design**: [`docs/design/gstack-vs-beaconhill-experiment.md`](../design/gstack-vs-beaconhill-experiment.md) (revised after the pilot — see §2 revision note)
**Run ID**: `20260430T020135-31b0954_dirty` (data under [`data/20260430T020135-31b0954_dirty/`](data/20260430T020135-31b0954_dirty/))
**Sweep wallclock**: 12m 34s (2026-04-30 02:01 UTC → 02:14 UTC), serial
**Total cost**: $1.02 (B: $0.49, C: $0.53)
**Prior pilot** (A vs D): [`loop-vs-process-pilot.md`](loop-vs-process-pilot.md)

---

## TL;DR

> At Haiku 4.5 on the Pomodoro task, **bare Claude Code (B) beats karpathy-guidelines + Claude Code (C) 6-3-1** in blinded pairwise judging. **More harness overlay does not improve quality**; in this case the karpathy "Simplicity First" injunction appears to push the model toward dropping spec-required features (most often: merging Start/Pause into one toggle button, violating the explicit three-button requirement). Layer-1 mean: B 16.7, C 15.7, D 15.9 — within ±1 point, but the judge breaks the tie cleanly for B.

---

## Setup recap

Two new cells, both at fixed model = Haiku 4.5:

| Cell | Harness | Auth | Per-run cmd |
|---|---|---|---|
| **B** | bare Claude Code (`--bare --disable-slash-commands`, no skills/hooks/auto-memory/CLAUDE.md) | `ANTHROPIC_API_KEY` (1Password) | `claude --bare --disable-slash-commands --print --model claude-haiku-4-5-20251001` |
| **C** | karpathy-guidelines (~70-line system-prompt overlay) on bare Claude Code | same | as B + `--append-system-prompt-file ab_test/cells/karpathy_guidelines.md` |

**C differs from B by exactly one CLI flag.** Same model, same prompt, same auth, same wrapper, same JSON output mode. The only injected difference is the karpathy CLAUDE.md content (frozen vendored copy at upstream SHA `2c606141`, MIT-licensed).

Reference cells from prior pilot for context:
- **A**: Beaconhill (loop-first) + Gemma 4 26B local
- **D**: gstack (process-first, ~25 skills + browser daemon + learnings store) + Haiku 4.5

n=10 per cell, shuffled order (seed 42). All 20 trials produced `timer.html` cleanly. Same Pomodoro spec as the pilot (`ab_test/prompt.md`).

---

## Aggregate results

### Layer-1 deterministic (Playwright, 18-item rubric)

| Cell | n | mean | median | min | max | per-run |
|---|---|---|---|---|---|---|
| **B** bare | 10 | **16.70** | 16 | 16 | 18 | [16, 16, 16, 18, 16, 18, 16, 17, 18, 16] |
| **C** karpathy | 10 | **15.70** | 16 | 13 | 18 | [16, 16, 16, 18, 15, 16, 16, 15, 13, 16] |
| D gstack (prior pilot) | 10 | 15.90 | 16 | 15 | 18 | [18, 15, 15, 18, 16, 15, 16, 15, 16, 15] |

**Where checks failed** (out of 10):

| Check | B | C | D (prior) |
|---|---|---|---|
| `start_starts_countdown` | 6 | **9** | not reported in pilot at this granularity |
| `space_toggles_start_pause` | 6 | **9** | — |
| `pause_preserves` | 0 | 3 | — |
| `border_radius_8px` | 1 | 0 | — |
| `break_button_clickable` | 0 | 1 | — |
| `break_5_00` | 0 | 1 | — |

The `start_starts_countdown` and `space_toggles_start_pause` failures are likely the same scoring artifact we noted in the pilot (the rubric clicks Start, waits 2.2s, checks display changed) — a tight timing window that races on slower JS init. They affect both cells roughly proportionally.

The genuinely interesting failures are **C-only**: `pause_preserves` and `break_5_00` — both signal the model produced something that doesn't behave per spec.

### Layer-2 blinded pairwise (B vs C, judged by Sonnet 4.6)

| Cell | Feature (/10) | Aesthetic (/10) | Wins | Ties | Losses |
|---|---|---|---|---|---|
| **B** | **8.4** | **7.8** | **6** | 1 | 3 |
| **C** | 7.1 | 7.0 | 3 | 1 | 6 |

The judge picks B 6 times, C 3 times, ties once. Decisively B-leaning.

### Cross-pilot reference

| Comparison | Layer-1 mean | Judge feature | Judge aesthetic | Judge wins |
|---|---|---|---|---|
| A vs D (pilot) | A=13.1, D=15.9 | A=5.3, D=8.4 | A=5.0, D=7.8 | D 9–1 |
| B vs C (this run) | B=16.7, C=15.7 | B=8.4, C=7.1 | B=7.8, C=7.0 | B 6–3–1 |

D's prior judge scores (8.4 / 7.8) and B's current judge scores (8.4 / 7.8) are **identical**. We don't have a direct B-vs-D pairwise judge, but on absolute judge scores the bare Haiku and gstack-Haiku stacks are indistinguishable on this task. Adding gstack on top of Haiku gives no measured uplift; adding karpathy gives a measured downlift.

---

## Why does karpathy hurt?

The karpathy guidelines push four behaviors:

1. **Think Before Coding** — surface assumptions, ask when ambiguous
2. **Simplicity First** — no features beyond ask, no abstractions for single-use
3. **Surgical Changes** — every changed line traces to the request
4. **Goal-Driven Execution** — define success criteria, loop until verified

In `claude --print` mode (single-shot, no follow-up), principles 1 and 4 are largely inert — there's no human to ask, no verification loop. Principles 2 and 3 are the active ingredients here, and they appear to over-fire on a task where the spec actually requires multiple distinct features.

Specific failure patterns the judge flagged on C runs (verbatim from un-blinded notes):

| C run | Judge note |
|---|---|
| C/run-1 | "uses `setInterval(tick, 100)` but decrements `timeRemaining` every call, making the countdown 10× too fast — a fatal timing bug" (paired against B/run-1, which was correct) |
| C/run-4 | "merges Start and Pause into a single toggle button, violating the spec's requirement for separate Start and Pause controls" |
| C/run-7 | "merges Start/Pause into one button violating the three-button requirement" |
| C/run-8 | "uses a single cycling mode button (ambiguous which mode is active at a glance), merges Start/Pause, and applies `word-spacing:100vw` which can cause layout artifacts" |

The Start/Pause merge is the dominant pattern — appears in 3 of C's 4 spec-compliance failures. The spec literally says "**Start**, **Pause**, and **Reset** buttons" and "Pause preserves elapsed time; Reset returns to the current mode's full duration." A model interpreting "Simplicity First" as "fewer buttons better" can plausibly read three buttons as redundant and collapse them.

C also occasionally added polish B did not (text-shadow glow, hover-lift, generous letter-spacing on a couple of pairs the judge gave to C), so the overlay isn't uniformly negative — it just biases toward different tradeoffs that, on this rubric, score lower.

**Hypothesis to test next**: karpathy may help on tasks where the spec is itself ambiguous or under-specified (where "ask before assuming" pays off) and hurt on tasks with a precise, fully-specified feature list.

---

## What this run does and doesn't say

### Says (with reasonable confidence at n=10):
- **At Haiku 4.5 on the Pomodoro task, more prompt-level harness ≠ better quality.** Bare CC tied or beat both karpathy-overlay and (cross-pilot) gstack on every metric.
- **Karpathy guidelines reduce spec compliance** at this prompt mode, primarily by encouraging the model to merge spec-distinct features under a "simplicity" rationale.
- **Layer-1 is still over-generous** — separated B and C by only 1 point (16.7 vs 15.7) where the judge separated them 6-3-1. Confirms the pilot's finding that semantic spec compliance needs LLM judging.

### Doesn't say:
- **Whether karpathy helps on different task classes** (under-specified features, multi-step refactors, debugging). This was a fully-specified single-file UI task.
- **Whether B or D would win head-to-head.** Their judge feature/aesthetic averages from independent pairings are identical (8.4 / 7.8); a direct B-vs-D pairwise would resolve this.
- **Whether gstack's other affordances (browser daemon, learnings store, multi-skill review) would surface on a multi-file or longer-horizon task.** gstack's documented strength is repo-scale work, which Pomodoro doesn't exercise.
- **Whether the karpathy effect is stable across temperatures, prompt phrasings, or other models.** Same model, same temperature, same prompt — all confounded with the karpathy-vs-not flag.
- **Whether `--bare --disable-slash-commands` is exactly equivalent to "out-of-box default Claude Code."** It strips hooks, auto-memory, plugin sync, CLAUDE.md auto-discovery — which are how a real fresh Claude Code install behaves on a clean machine, but not how this user's actively-customized install behaves.

### Pre-registered thresholds (transparency):

The original design's H1/H2/H3 hypotheses were written for the A/B/D pilot and don't apply cleanly to this B-vs-C ablation. Treating B-vs-C as a fresh sub-experiment:

- **Δ ≥ 3 points on Layer-1 median**: B-C = 0 (both 16). **Fails.**
- **Pairwise win rate ≥ 60%**: B wins 6/9 decided pairs = 67%. **Passes.**

Same conjunctive failure as the pilot. The pairwise margin is real (and reaches the 60% threshold even discounting the tie); Layer-1 just isn't the right instrument at this scale.

---

## What's next

Concrete and worth running:

1. **Direct B vs D pairwise judge.** Same task, same model — does any cross-cell signal emerge between bare and gstack on Haiku? Cheap (the data exists; just re-run `judge_prep --pair B,D` against a combined run dir, or judge across runs).
2. **Cell C variant: karpathy minus "Simplicity First."** Strip principle 2 and re-run. If C's deficit collapses, "Simplicity First" was the active ingredient. If not, look at "Surgical Changes" or interaction effects.
3. **Multi-file task.** Pomodoro is single-file — gstack's process-first apparatus (skill chain, learnings store, browser daemon) can't fully fire. A 2-3-file CRUD-app benchmark would be ecologically more valid for D and would likely change the harness ladder.
4. **Cells E and F (Gemma).** Defer until the Claude Code → Ollama bridge story is clean. Without those, H3 (interaction: harness-leverage × model-strength) remains untestable.

Lower priority but useful:

5. **Investigate the `start_starts_countdown` / `space_toggles_start_pause` 2.2s timing window** in `score_layer1.py`. 60-90% failure rates on what should be a simple check suggest the rubric is over-sensitive, not the implementations being broken.
6. **Tighten the rubric** as discussed in the prior pilot note: distinct Start/Pause/Reset buttons (not just any element with that text), weighted functional checks. The Start/Pause merge that C does most often slips past Layer-1 entirely.

---

## Reproduction

```bash
# Pre-flight
git checkout 31b0954  # or the analysis-note commit
export ANTHROPIC_API_KEY="$(op read 'op://Dev/Anthropic API/credential')"  # or use .env

# Run
bash ab_test/run.sh --cells B,C --n 10 --seed 42

# Score
.venv/bin/python ab_test/evaluate.py    --run-dir ab_test/results/<run_id>
.venv/bin/python ab_test/score_layer1.py --run-dir ab_test/results/<run_id>

# Judge
.venv/bin/python ab_test/judge_prep.py --run-dir ab_test/results/<run_id> --pair B,C
claude --print --model claude-sonnet-4-6 --output-format json \
    < ab_test/results/<run_id>/judge_packet_B_vs_C.md \
    > ab_test/results/<run_id>/judge_response_raw.json
# extract result -> judge_scores_B_vs_C.json (one-liner via python json.load + json.loads)

# Aggregate
.venv/bin/python ab_test/report.py --run-dir ab_test/results/<run_id>
```

Expect ~12 minutes wall, ~$1 cost, no hangs, all 20 timer.html files produced.
