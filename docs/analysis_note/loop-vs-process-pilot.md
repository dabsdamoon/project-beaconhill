# Loop-First vs. Process-First — Pilot Analysis

**Branch**: `feat/gstack-and-haiku`
**Pre-registered design**: [`docs/design/gstack-vs-beaconhill-experiment.md`](../design/gstack-vs-beaconhill-experiment.md)
**Run ID**: `20260428T234639-53c165c` (data under [`data/20260428T234639-53c165c/`](data/20260428T234639-53c165c/))
**Sweep wallclock**: 2h 20m (2026-04-28 23:46 UTC → 2026-04-29 02:07 UTC)

---

## TL;DR

> **gstack + Haiku 4.5** wins on every quality axis except Layer-1 median, with **9/10 blinded pairwise wins** over **Beaconhill + Gemma 4 26B** at the Pomodoro-timer task. The Layer-1 deterministic rubric (Playwright + computed-style checks) is too generous to discriminate at this task scale; the LLM judge catches semantic spec violations the regex/DOM checks miss. Cell A's two zero-score trials are operational failures (Ollama hang, evaluator pivot loop), not quality failures.

---

## Setup recap

Two-cell pilot, n=10 each, shuffled order:

| Cell | Harness | Model | Auth |
|---|---|---|---|
| **A** | Beaconhill (loop-first, plan→generate→evaluate retries) | Gemma 4 26B (local Ollama) | n/a |
| **D** | gstack (process-first, skill-driven) | Haiku 4.5 | OAuth (Max subscription) |

Cells **B** (gstack+Gemma) and **C** (Beaconhill+Haiku) deferred. Without them, H3 (interaction effect) cannot be proved — only the natural-deployment comparison A-vs-D is testable.

Three scoring layers:
- **Layer 1a — regex** (`evaluate.py`): grep over HTML source for spec strings/colors. Cheap, fast, generous.
- **Layer 1b — Playwright** (`score_layer1.py`): 18-item rubric, real Chromium, exercises Start/Pause/Reset/Space, computed styles, mobile resize. Pre-registered as primary metric.
- **Layer 2 — blinded pairwise judge** (`judge_prep.py`, judged by Sonnet 4.6): randomized A/B labelling, scores feature + aesthetic on /10, picks winner.

---

## Aggregate results

### Layer-1 deterministic

| Cell | regex feature | regex aesthetic | regex combined | files produced | Playwright mean (/18) | Playwright median |
|---|---|---|---|---|---|---|
| **A** Beaconhill+Gemma | 0.711 | 0.800 | 0.756 | **8/10** | **13.1** | 17 |
| **D** gstack+Haiku | 0.989 | 1.000 | 0.994 | **10/10** | **15.9** | 16 |

Per-run Playwright scores:
- A: [14, 17, 17, 14, 17, 17, 17, **0**, 18, **0**]
- D: [18, 15, 15, 18, 16, 15, 16, 15, 16, 15]

A's distribution is bimodal (14-18 with two 0s); D's is tightly clustered (15-18).

### Layer-2 blinded pairwise

| Cell | Feature (/10) | Aesthetic (/10) | Wins | Ties | Losses |
|---|---|---|---|---|---|
| **A** | 5.3 | 5.0 | **1** | 0 | 9 |
| **D** | 8.4 | 7.8 | **9** | 0 | 1 |

D wins 9/10 pairs.

### Operational

| | Cell A | Cell D |
|---|---|---|
| Wallclock per successful run | 375–1452s (mean ~640s, ~10.7 min) | 67–164s (mean ~106s, ~1.8 min) |
| Failures | 2 (run-7 hung, run-9 pivot loop) | 0 |
| Cost (USD) | $0 (local) | $2.51 total ($0.17–0.49/run) |

---

## The Layer-1 vs. judge divergence

Cell A's median is *higher* than D's on Layer-1 (17 vs 16) but A loses the judge 9-1. Why?

The Layer-1 rubric has known generosity. Specific failure modes the judge flags but Layer-1 misses:

| Judge note (un-blinded to cell A) | Layer-1 outcome |
|---|---|
| "places its script in `<head>` and captures DOM references before the DOM exists, crashing on every page load" (pair 4) | `no_js_errors`: false (caught), but the rest of the rubric still scores generously on text matches the regex finds anyway → 14/18 |
| "Space shortcut silently fails when any button holds focus (`activeElement === document.body` guard)" (pair 2) | `space_toggles_start_pause`: false (caught), but only counts as 1 of 18 |
| "combines Start/Pause" — i.e., one toggle button instead of three separate buttons per spec (pairs 3, 6, 7) | Layer-1 finds "start" + "pause" text and passes both checks |
| "calls `window.alert()` on completion" (pair 7) | `audio_alert_capable` matches `<audio>` regex and passes |

The judge picks up *spec compliance and code quality*; Layer-1 picks up *structural presence*. They're complementary metrics, not redundant. **Layer-1 alone would have called this a tie or A-leaning; the judge calls it decisively for D.**

Implication for future experiments: tighten Layer-1 to count Start/Pause/Reset as **distinct** buttons (not just any element with that text), and weight functional checks higher than aesthetic checks. Or accept that Layer-1 is a coarse pre-filter and the judge is the final word.

---

## Cell A's failure modes (the operational story)

Two zero-score trials. Both reproducible signatures:

### run-7 — Ollama hang (silent, 31 min)
- Beaconhill wrote system prompt to `session.jsonl` (1414 bytes), then never sent a single Ollama HTTP request
- CPU consumption near zero; process in `S` (sleep) state
- The 120s `OllamaClient` timeout and asymmetric retry policy did not fire — suggesting the hang was *before* HTTP, possibly in client initialization or session-handshake state
- Killed manually after 31 min; no `timer.html` produced (wall=1894s)

### run-9 — Evaluator pivot loop (4.5 min, fast give-up)
- Orchestrator entered, generator wrote `timer.html`, evaluator returned persistent failures
- Pivot triggered → step artifacts deleted (per design) → new attempt → another pivot
- Hit max iterations and exited cleanly without final `timer.html` (wall=271s)
- This is **the pivot mechanism working as designed** — but the result is a missing deliverable rather than a recovered one

### run-1 — pivot loop that *eventually* converged (24+ min)
- Same pattern as run-9 initially: timer.html appeared, then disappeared during a pivot
- But this run *did* converge, then sat in some final-flush state without exiting; killed manually after 24 min once timer.html stabilized
- Counted as a successful trial (timer.html present at score time) but a real-world deployment would call this a hang

So 3 of 10 A trials hit the orchestrator's hard cases. 1 recovered, 2 didn't.

---

## What this pilot does and doesn't say

### Says (with high confidence at n=10):
- **gstack+Haiku is the more reliable + higher-quality stack** for single-file UI tasks at this scale. 100% completion, judge wins 9/10, mean Layer-1 (Playwright) +2.8.
- **Beaconhill+Gemma's failures are operational, not quality**: when it produces a file, the judge rates it ~5.3/10 vs D's ~8.4/10. The 0-score trials drag the raw mean but the conditional mean (excluding zeros) is 16.4 — within 0.5 of D's 15.9.
- **Layer-1 over-credits structural presence**. Future Layer-1 iterations should weight functional spec compliance more heavily.

### Doesn't say:
- Whether Beaconhill's loop-first design adds value when paired with a *strong* model (cell C deferred)
- Whether gstack's process-first discipline survives a *weak* model (cell B deferred)
- Whether the harness × model interaction effect (H3) holds. The experiment as run conflates harness and model.
- Whether results generalize beyond Pomodoro to multi-file or repo-scale tasks. gstack is documented for repo-scale work; this pilot may underrate gstack's intended strengths.

### Failed pre-registered thresholds (transparency):
- "H1/H2 directional support: Δmedian ≥ 3 AND pairwise win-rate ≥ 60%"
  - D vs A: Δmedian Playwright = -1 (A leads). **Fails Δ test on Playwright.**
  - D vs A: pairwise win-rate = 90%. **Passes pairwise test by a wide margin.**
- "Falsification trigger: any run < 6/18 — pause and investigate"
  - A had two 0/18 runs. **Triggered.** Investigation findings are above (operational, not quality).

The pre-registered logic was conjunctive ("AND"), so D does not hit *strict* directional support. The pairwise win rate is so lopsided, however, that the conjunctive failure is ambivalent — Layer-1 simply isn't the right instrument at this scale.

---

## What's deferred / open questions

1. **Cell C (Beaconhill+Haiku)**: would the closed-loop evaluator add or subtract value when the underlying model is already strong? Real open question.
2. **Cell B (gstack+Gemma)**: requires Anthropic-API → Ollama proxy + `--bare` mode bypass, which kills CLAUDE.md auto-discovery and undermines what gstack tests. Unlikely to be clean.
3. **Larger task suite**: Pomodoro is single-file; gstack's multi-skill review pipeline can't fully fire here. A 2-3 file CRUD-app benchmark would be more ecologically valid for gstack.
4. **Tighter Layer-1 rubric**: Start/Pause/Reset as distinct buttons; weighted functional checks; tool-use frequency.
5. **Beaconhill's run-7 hang root cause**: the 120s HTTP timeout didn't fire. Either the hang was pre-HTTP (orchestrator init?) or the timeout was bypassed on a code path. Worth `py-spy` next time the pattern repeats.
6. **Beaconhill's pivot policy**: deleting step artifacts on persistent failure is the intended design, but in 1 of 10 trials it never recovered. Consider a "pivot budget" — N pivots before giving up vs. unbounded.

---

## Reproduction

Data lives under [`data/20260428T234639-53c165c/`](data/20260428T234639-53c165c/):
- `run_meta.json` — git SHA `53c165c`, env, full per-cell config
- `run_order.txt` — pre-shuffled trial sequence (seed 42)
- `layer1_scores.json` — Playwright rubric aggregates
- `deterministic_scores.json` — regex rubric aggregates
- `judge_mapping_A_vs_D.json` — un-blinding key for the pairwise packet
- `judge_scores_A_vs_D.json` — Sonnet 4.6's verdict

The original `timer.html` files (20 of them) and full session JSONLs live under `ab_test/results/20260428T234639-53c165c/` — gitignored. To reproduce the analysis from scratch:

```bash
# Pre-flight
ollama pull gemma4:26b
brew services start ollama
git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
(cd ~/.claude/skills/gstack && ./setup --host claude)

# Run
git checkout 53c165c
bash ab_test/run.sh --cells A,D --n 10 --seed 42

# Score
.venv/bin/python ab_test/score_layer1.py
.venv/bin/python ab_test/judge_prep.py --pair A,D
claude --print --model claude-sonnet-4-6 --output-format json \
    < ab_test/results/<run_id>/judge_packet_A_vs_D.md \
    > ab_test/results/<run_id>/judge_response_raw.json
.venv/bin/python ab_test/report.py
```

Expect the pivot-loop and Ollama-hang failure modes to recur; sweep variability is real at n=10.
