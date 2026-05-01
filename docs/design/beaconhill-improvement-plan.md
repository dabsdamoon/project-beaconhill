# Beaconhill Improvement Plan — Grounded in Cell A/G Experiment Findings

**Branch**: `feat/gstack-and-haiku`
**Status**: Proposed. Forward-looking commitments — no code yet.
**Evidence base**:
- [Pilot: A vs D (loop-first vs process-first)](../analysis_note/loop-vs-process-pilot.md)
- [Harness ladder at Haiku (B vs C)](../analysis_note/harness-ladder-haiku.md)
- [Beaconhill loop on Haiku (G vs B/C/D)](../analysis_note/beaconhill-vs-cc-haiku.md)
- [Anthropic prompt caching analysis](../analysis_note/anthropic-prompt-caching.md)

---

## TL;DR

> Three sweeps of empirical data show Beaconhill's loop-first design has a **single-axis evaluator** (functional only) and a **costly architecture** (6× wallclock and ~5× $ vs bare Claude Code at the same model). It wins Layer-1 but loses every pairwise judge it's been in. The improvement plan prioritizes **(1) widening the evaluator's axes** to capture design/code-quality dimensions the model already produces variation on, **(2) tightening spec ground-truthing** so the evaluator checks the user's literal prompt, not just the planner's interpretation, and **(3) adaptive loop depth** so strong models on simple tasks don't pay the full orchestrator tax. Lower-priority items address operational reliability (cost caps, parallel tool execution, pivot-budget tuning).

---

## What the experiments told us

### Cell G has high Layer-1 (17.2 mean — highest of any Haiku cell) but the lowest judged quality

Direct head-to-head losses on n=5 each:

| | wins | losses | ties |
|---|---|---|---|
| G vs B | 0 | 5 | 0 |
| G vs C | 2 | 3 | 0 |
| G vs D | 2 | 3 | 0 |

Same artifact set, two scoring layers, opposite verdicts.

**Diagnosis (from un-blinded judge notes)**: Beaconhill's evaluator validates *functional* acceptance criteria — "Start button starts countdown", "MM:SS format", "border-radius ≥ 8px". It does not validate:

- **Design coherence** ("filled vs outlined button hierarchy", "uniform outline button language", "responsive `clamp()` sizing")
- **Code idiom** ("class-based architecture", "CSS custom properties", "no global `button:hover` overriding mode buttons")
- **Spec literalism** that the planner didn't enumerate ("must be three distinct buttons" — not in planner-generated criteria, so Start/Pause merge passes)

So Beaconhill's loop *raises the floor* on what its evaluator measures and *does not improve* what its evaluator doesn't measure. Strong models clear the functional floor on first shot anyway, leaving only design quality on the table — which Beaconhill ignores.

### Cell G is 6× the wallclock and 5× the dollar cost of bare CC for the same task on the same model

| Cell | Calls/run | Wall/run | Cost/run |
|---|---|---|---|
| B bare CC + Haiku | ~5–8 | 30–60s | $0.05 |
| D gstack + Haiku | ~10–15 | 67–164s | $0.25 |
| G Beaconhill + Haiku (cached) | 51–97 | ~5 min | $0.29 |

Drivers, in order of contribution:

1. **Plan-mode = always** forces a planner phase that's marginal at strong-model regime (5–10 extra calls).
2. **Generator's serial tool execution** — one tool_use → one API call → process → next API call. Claude Code's host emits multiple tool_use blocks per turn and dispatches them in parallel.
3. **Evaluator runs its own agentic loop** with read-only tools to verify each plan step (~20–30 calls).
4. **Retry iterations** — `max_eval_iterations=5` default; when first generation fails eval, the failed steps regenerate plus a re-eval (another full agentic loop).

Caching addresses the rate-limit ceiling but not the call count — a single Beaconhill run still issues 10× the API calls of bare CC for the same task.

### Without prompt caching, Cell G is not viable at the org's 50K input-tokens/min ceiling

Documented in [`anthropic-prompt-caching.md`](../analysis_note/anthropic-prompt-caching.md). Caching turned 0/3 → 3/3 completion rate with no other change. **This is now infrastructure, not optimization.**

---

## Proposed improvements

Three tiers by ROI. Each item has: rationale, sketch of change, risk, and rough effort.

### Tier 1 — High ROI (close the L1-vs-judge gap)

#### 1.1. Multi-axis evaluator

**Rationale**: Single-axis (functional) evaluator misses everything the judge cares about. The model produces design variation on first shot; the evaluator just doesn't ask about it.

**Sketch**:
- Extend `evaluator.evaluate()` with a second pass that rates the artifact on `code_quality`, `design_coherence`, and `idiomatic_patterns`.
- Each axis returns 0–10 + a list of issues (same shape as current functional verdicts).
- Plan-step-aware: the multi-axis pass runs once after functional pass, generates issues that feed back into `_persistent_failures()`.
- Make the axis weights configurable (`evaluator_axes` in Config) so users can disable design checks for non-UI tasks.

**Risk**: Subjective axes may not converge — the model could oscillate between "more polish" and "simpler is better". Mitigate by capping multi-axis retries at 1 (single shot at design feedback, not iterative refinement).

**Effort**: ~1 day. ~200 LOC across `evaluator.py`, `plan.py` (add `quality_verdicts` to `EvaluationResult`), and `orchestrator.py` (wire feedback).

#### 1.2. Tighten spec ground-truthing in the evaluator

**Rationale**: Planner-generated acceptance criteria are the planner's *interpretation* of the user's prompt. The Start/Pause merge cases that lost G pairs to C and D are exactly cases where the planner didn't enumerate "must be three distinct buttons" — even though the spec literally said so. The evaluator never re-reads the original prompt.

**Sketch**:
- Pass the original user prompt to `evaluate()` alongside the plan steps.
- Evaluator system prompt: "Verify the artifact against BOTH (a) the planner's acceptance criteria and (b) the user's literal request. If the user's request explicitly states a requirement the criteria don't cover, generate an issue for it."
- Already partially in place via `original_request` in `_build_step_prompt()` for the *generator*; replicate for the evaluator.

**Risk**: Increases evaluator prompt length, slightly more token cost. Cache absorbs most of it.

**Effort**: ~2 hours. ~30 LOC in `evaluator.py` + `orchestrator.py`.

#### 1.3. Adaptive plan-mode for strong models

**Rationale**: Plan mode adds 5–10 calls per run for the planner phase. On strong models with simple specs, the planner adds little — the generator could plan inside the agentic loop. Cell G ran with plan-mode=always; Cell B ran without any planner and matched/beat G on judged quality.

**Sketch**:
- Add a model-strength heuristic: `model.startswith("claude-")` → "strong"; `gemma4:*` → "weak".
- New plan-mode option `auto-by-model`: skip planner if model is strong AND `should_plan(prompt)` heuristic returns False (short, no multi-step keywords).
- Default for cloud models: `auto-by-model`. Default for local Gemma: keep `always` (current behavior).

**Risk**: Skipping the planner may degrade on tasks the heuristic mis-labels as "simple". Mitigate by making the heuristic conservative (default to planning unless clearly trivial).

**Effort**: ~3 hours. ~50 LOC in `config.py` + `cli.py`.

---

### Tier 2 — Medium ROI (reduce architectural overhead)

#### 2.1. Parallel tool execution within a turn

**Rationale**: When the model emits multiple `tool_use` blocks in one response, Beaconhill processes them serially. Anthropic's tool-use protocol is designed for parallel execution (`tool_choice: {"type": "auto"}` allows multiple per turn).

**Sketch**:
- In `runtime.py`, replace the `for tc in response.tool_calls:` loop with a `concurrent.futures.ThreadPoolExecutor.map()` for tools whose `Permission` is auto-allowed (Bash, Read are I/O-bound — perfect for threads).
- Keep ASK-permission tools serial (each needs user prompt).
- Tool ordering preserved in the resulting tool_result blocks (Anthropic accepts any order as long as each `tool_use_id` is matched).

**Risk**: Tools with side effects on filesystem can race. Mitigate by serializing Write/Edit on the same path. Read/Bash that don't modify state can parallelize freely.

**Effort**: ~1 day. ~100 LOC in `runtime.py` + thread-safe ToolRegistry guard.

**Estimated savings**: 30% wallclock on tool-heavy turns (currently the dominant phase).

#### 2.2. Cost / budget bounds

**Rationale**: AnthropicClient tracks `cumulative_cost_usd` but doesn't enforce a cap. The smoke test before caching ran $0.20 in 51 calls; with retries on a stuck loop, cost could balloon.

**Sketch**:
- Add `--max-budget-usd` flag (already exists in design doc; not implemented).
- AnthropicClient checks `cumulative_cost_usd >= budget` before each `chat()` call. If exceeded, raise a `BudgetExceededError`.
- Orchestrator catches and exits cleanly with whatever artifacts exist.

**Risk**: Hard exit mid-run could leave inconsistent state (e.g., evaluator saw a failure but couldn't retry). Mitigate by treating budget exit as "best-effort — finish current step".

**Effort**: ~2 hours. ~40 LOC in `anthropic_client.py` + `cli.py` + `orchestrator.py`.

#### 2.3. Adaptive eval iterations

**Rationale**: `max_eval_iterations=5` default. Most successful runs pass on iteration 1; the cap is for hard cases. But the orchestrator runs the *entire* eval loop each iteration even if no failures — wasted call.

**Sketch**:
- After `evaluate()` returns, check `result.overall_passed` BEFORE the iteration counter increments. (Currently does this — verify no edge case.)
- Add early-stop: if iteration N's failures are a strict superset of iteration N-1's failures (no progress), stop without further retries.
- Surface a `--max-eval-iterations` CLI flag (currently config-only).

**Risk**: False early-stops on tasks where the model needs more pivots to converge. Mitigate by gating early-stop on a minimum 2 iterations.

**Effort**: ~1 hour. ~20 LOC in `orchestrator.py`.

---

### Tier 3 — Lower ROI (operational reliability)

#### 3.1. Pivot-budget tuning

**Rationale**: Pivot logic deletes step artifacts on "persistent failure" (issue-set intersection over 2+ evaluations). Pilot showed 1 of 10 cell A trials hit the pivot trigger and never recovered. The signal is brittle.

**Sketch**:
- Add a per-step pivot count cap (default 1 pivot per step per run).
- After cap exhausted, fall back to "patch-don't-rewrite" instructions in the regen prompt.
- Track pivot history in `plan.json` for post-hoc analysis.

**Risk**: Capping pivots could let bad architectures linger past where a pivot would have rescued them. Mitigate by surfacing the cap in `--max-pivots-per-step`.

**Effort**: ~3 hours. ~50 LOC in `orchestrator.py`.

#### 3.2. Context compaction telemetry

**Rationale**: `context.compact_messages()` exists but we have no data on when/how often it fires in cloud-mode runs. Compaction could be a hidden cost driver if over-aggressive (too many full re-summarization calls).

**Sketch**:
- Log compaction events to `session.jsonl` as `_meta` entries with before/after token counts.
- After a sweep, aggregate compaction stats per cell.

**Risk**: None — pure telemetry.

**Effort**: ~1 hour.

#### 3.3. Streaming output during agentic loop

**Rationale**: `chat_or_stream` exists. Currently used in interactive mode. One-shot mode (used by ab_test runners) doesn't stream — just waits silently. Streaming wouldn't save cost but would help operators monitor long Beaconhill runs.

**Sketch**:
- In `runtime.py::run_agentic_loop`, when in one-shot mode, stream the final assistant message text to stdout as it arrives.

**Risk**: None.

**Effort**: ~2 hours.

#### 3.4. Prompt-cache-aware planning

**Rationale**: The planner's call uses a different system prompt than the generator/evaluator. Planner output is not cached for reuse later. Could share system-prompt prefix to warm the cache for downstream phases.

**Sketch**:
- Refactor `planner.py::create_plan()` and `agent.py::build_system_prompt()` to share a common prefix (the loop-first behavior description), with phase-specific suffixes.
- Cache breakpoint on the shared prefix.

**Risk**: Prompt rewrites may shift planner behavior subtly. Test before/after on the existing rubric.

**Effort**: ~4 hours including regression check.

---

### Tier 4 — Experimental / research

#### 4.1. Multi-task benchmark

The Pomodoro task is single-file UI. Beaconhill's loop should be more valuable on:
- Multi-file projects (where the planner's step decomposition pays off)
- Tasks with non-obvious failure modes (where the evaluator catches what first-shot misses)
- Long-horizon work (where pivots prevent dead-end implementations)

**Proposed benchmark suite** (3 tasks):
1. **CRUD API**: Flask + SQLite, 3 endpoints, tests. ~300 LOC across 4 files.
2. **State-machine UI**: a multi-step form with validation, persistence. ~200 LOC, 1 file.
3. **Bug-fix from issue text**: small reproducer + failing test + fix + re-run.

The harness comparison repeated on these would tell us whether Beaconhill's loop is "worse on Pomodoro specifically" vs "worse universally on strong models".

**Effort**: 2–3 days for all three task suites + scoring rubrics.

#### 4.2. Make evaluator optional via CLI

`run_orchestrated()` already accepts `skip_evaluation: bool`. Not exposed at CLI. Adding `--skip-evaluation` would let users run Beaconhill as a pure planner+generator (no closed loop) for tasks where they trust the model.

**Effort**: ~30 minutes.

#### 4.3. Pluggable evaluator backends

Today's evaluator is the same model that did the generation, evaluating itself. This is a known weak signal. Future option: use a different (possibly stronger) model for evaluation, or use deterministic checks (lint, type-check, tests) before invoking model evaluation.

**Effort**: 2–3 days for a clean abstraction. Bigger architectural change.

---

## Suggested roadmap

A pragmatic 1–2 week path. Each milestone is one commit.

| # | Milestone | Tier | Estimated effort |
|---|---|---|---|
| 1 | **Tighten spec ground-truthing** (1.2) | T1 | 2h |
| 2 | **Adaptive plan-mode for strong models** (1.3) | T1 | 3h |
| 3 | **Cost / budget bounds** (2.2) | T2 | 2h |
| 4 | **Adaptive eval iterations + CLI flag** (2.3) | T2 | 1h |
| 5 | **Multi-axis evaluator** (1.1) | T1 | 1d |
| 6 | **Re-run Cell G with all the above** (n=5, same seed) | — | 30 min wall + analysis |
| 7 | **Parallel tool execution** (2.1) | T2 | 1d |
| 8 | **Re-run Cell G with parallel tools** | — | 30 min wall + analysis |

After milestone 8, expect:
- G judge wins to recover toward parity with B/C (the multi-axis evaluator should pick up some of the design-quality gap).
- G wallclock to drop ~30% from parallel tools + adaptive iterations.
- G cost per run to drop ~20% from skipped planner phase on strong models.

Realistic stretch goal: **G judge-vs-B win rate ≥ 4/10** (from current 0/5) without sacrificing Layer-1 ≥ 16. That would represent the loop "earning its keep" at strong-model regime.

If milestones 1–8 don't move the needle materially, the experiments will have shown that **Beaconhill's value is concentrated at weak-model regime and the loop architecture should not be the default path for strong-model tasks**. That's also a real finding — and shapes the project's positioning as "local-first agent harness for the cases where you can't / don't want a frontier-API loop".

---

## Out of scope here

- **Switching to LangChain / LangGraph**: would replace Beaconhill's loop with a different state machine, defeating the experimental subject. Tracking infrastructure (LangSmith) without LangGraph is theoretically possible but adds a SaaS dependency.
- **Multi-tool concurrency at the model level** (parallel tool_use): handled at the runtime in 2.1; no model API change.
- **Sub-agents / delegation**: would change Beaconhill's identity. Worth considering after multi-task benchmark (4.1) shows where simpler loops fall short.
- **UI/UX work**: this plan is harness-internal. The CLI's interactive REPL and image attachment paths are unchanged.

---

## Decision points before starting

- [ ] Confirm Tier 1 ordering: ground-truthing → adaptive plan-mode → multi-axis. (Or: multi-axis first if you believe judge gap is the priority.)
- [ ] Confirm parallel-tool scope: thread-pool only (safe for I/O), not asyncio (would touch more code).
- [ ] Confirm budget cap target: $0.50/run? $1.00/run? (User-tunable; pick a default.)
- [ ] Confirm whether to keep plan-mode=always as the default for backward compat, or flip to auto-by-model.
