# Harness Convergence — Release Note

Target: `feat/apply_claude_harness` reaches parity with `main` on the Pomodoro-timer A/B benchmark.

## Summary

Six rounds of A/B testing (`ab_test/`) track how the plan-generate-evaluate harness evolved from losing against the bare agentic loop to matching it. Round 6 (commit `9d868e9`) is the first round with **no harness wins and no harness losses — three ties across three pairs** against main, with every output from both sides structurally complete and spec-compliant.

The journey traded catastrophic early regressions for steady quality gains by fixing one upstream failure at a time. The single most impactful change was the last one: including the verbatim original user request alongside the planner's paraphrased step prompt, so the generator no longer trusts a lossy summary as ground truth.

## Scoreboard

| Round | Commit | harness wins | harness file-produced | Break-button rate (harness) |
|---|---|---|---|---|
| 1 | `51d50e1` | 1/3 | 0.67 | 0/3 |
| 2 | `3de6081` | 0/3 | 1.0 | 0/3 |
| 3 | `44aaabd` | 1/3 | 1.0 | 1/3 |
| 4 | `fd1bf1a` | 0/3 | 0.67 (1 hang) | 0/3 |
| 5 | `8e1eb1d` | 0/3 | 1.0 | 0/3 |
| **6** | **`9d868e9`** | **0 wins / 3 ties / 0 losses** | **1.0** | **3/3** |

Main was steady across all rounds at ~1.0 produced, ~2–3 wins per round, always including the Break button.

## Change-by-change impact

### Round 2 — Hardened planner prompt, evaluator bash access (`3de6081`)

- Planner instructed to split tasks into ≥2 steps when behavioral logic and styling are both required.
- Planner lowered to `temperature=0.2`.
- Evaluator granted `bash` via `config.evaluator_tools`.

**Effect:** file-production rate for harness went from 0.67 → 1.0. The `format="json"` experiment was rolled back after it produced `/the/the/the/…` loops. Quality otherwise flat.

### Round 3 — Pivot signal + evaluator test-execution prompt (`44aaabd`)

- Added `_persistent_failures` — detects when the same issue string survives a retry.
- Added pivot-vs-refine prompt paths in `_build_step_prompt`.
- Evaluator prompt rewritten to mandate inline-bash verification before any verdict.
- Lifted `max_eval_iterations` from 3 → 5.
- Restructured results into versioned run folders with `run_meta.json`.

**Effect:** judge aesthetic score for harness jumped 2.67 → 6.67. One judge-win for harness (pair 2, on a case where main shipped a broken `</style>`).

### Round 4 — Artifact deletion on pivot (`fd1bf1a`)

- On pivot, `_delete_step_artifacts` removes the files that step produced so the generator starts from a clean slate.
- Emits `PIVOT_TRIGGERED` event.

**Effect:** neutral on quality — the pivot never fired in any round, because the evaluator rubber-stamped iteration 1. Machinery was correct but dormant. One harness run hung 12 minutes and had to be hand-killed, exposing the missing-timeout issue.

### Round 5 — Per-request timeout + asymmetric retry (`3231c07`, `8e1eb1d`)

- `OllamaClient` gained `request_timeout=120s` (down from unbounded).
- Asymmetric retry: 3 attempts for connection errors (transient), 2 attempts for timeouts with a 30-second pause between (wedged Ollama rarely recovers).
- Descriptive `TimeoutError` on final failure.

**Effect:** bounded worst-case wait at ~4.5 minutes per stuck call. No more manual `kill` rescues. Quality flat — outputs still lacked the Break button.

### Round 6 — Original request visible to the generator (`9d868e9`)

- `_build_step_prompt` now includes the verbatim `user_input` in a `## Original user request (ground truth)` section, with explicit instruction: when the planner's acceptance criteria conflict with or omit something from the original request, the original wins.

**Effect:** Break-button rate went 0/3 → 3/3 in a single release. First round with tied judge scores across all pairs.

## Why the last change was the biggest lever

Every harness round before 6 had the planner rewriting `"two modes toggled by a button"` into `"supports modes with a toggle"`. The generator interpreted "a toggle" as a JS state variable, not a UI button, and skipped the button. The evaluator's acceptance criteria came from the same paraphrase, so it had no basis to fail the output. Every downstream change (pivot, test-execution, artifact deletion, timeouts) was downstream of that bug.

The fix was one edit to `_build_step_prompt`. Rounds 2–5 improved reliability and infrastructure; round 6 closed the quality gap by fixing the upstream information-loss.

## What the harness still costs

Harness runs average **~500 seconds** vs main's **~130 seconds** in round 6. The 4× wall-time is the price of the plan + per-step evaluate + potential retry cycle. Output quality is now comparable for single-file tasks; the overhead is hard to justify on this benchmark alone. The harness is built for multi-file, longer-horizon tasks where decomposition and retry earn back the time.

## What remains unsolved

- **Evaluator still rubber-stamps.** In round 6, all 3 harness runs passed evaluation on iteration 1 with zero issues. The outputs happened to be genuinely good, but the evaluator isn't actually verifying required UI elements. Next improvement is making acceptance criteria concrete enough that grep-matching them is meaningful — or replacing regex-gated checks with generated test commands.
- **Pivot has never fired in a real run.** The machinery exists and is unit-tested, but the evaluator always approves the first attempt. Real exercise of pivot requires either a harder task or a stricter evaluator.
- **120s timeout is tight.** The planner call has been measured at 105s. One slow day and a legitimate plan call could time out. Splitting the timeout per call-site (longer for planner, shorter for generator chats) is the obvious next tune.

## Commits on this branch, in order

```
9d868e9 feat: inject original user request into every step prompt
8e1eb1d chore: tighten OllamaClient default timeout from 600s to 120s
3231c07 feat: bound OllamaClient with per-request timeout and asymmetric retry
fd1bf1a feat: delete prior step artifacts on pivot
44aaabd feat: add pivot signal, evaluator test-execution prompt, versioned runs
3de6081 feat: harden planner decomposition and evaluator read-only toolset
1cbc4de feat: add phase 4 config, t4 eval tier, and calibration guide
5b139d9 feat: add phase 3 evaluator and retry loop
34ad08b feat: add phase 2 orchestrator for plan-generate-evaluate architecture
cefc7a0 feat: add phase 1 planner for plan-generate-evaluate architecture
0dc9cf0 feat: add phase 0 foundation for plan-generate-evaluate architecture
```
