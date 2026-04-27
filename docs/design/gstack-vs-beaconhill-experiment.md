# Experiment: Loop-First vs. Process-First Harnesses

**Branch**: `feat/gstack-and-haiku`
**Status**: Pre-registered design. No results yet.
**Related work**: [`docs/release_note/harness-convergence.md`](../release_note/harness-convergence.md)

---

## 1. Hypothesis

> **H1.** Holding model constant at Gemma 4 26B, the loop-first harness (Beaconhill) produces higher-quality Pomodoro implementations than the process-first harness (gstack), because closed-loop evaluation recovers reasoning failures that a weaker model makes on its first attempt.

> **H2.** Holding harness constant at gstack, Haiku 4.5 produces higher-quality implementations than Gemma 4 26B, because the harness's process discipline cannot compensate for raw reasoning gaps.

> **H3 (interaction).** Harness leverage is **inversely proportional to model strength**. The Sensors-heavy loop-first design wins more under weak models; the Guides-heavy process-first design wins more under strong models.

H3 is the interesting result. H1 and H2 are sanity checks — if either fails, the framing of the comparison is wrong.

---

## 2. Cells

Three-cell minimum-viable design. The full 2×2 is deferred (see §11).

| ID | Harness | Model | Status |
|----|---------|-------|--------|
| **A** | Beaconhill (loop-first) | Gemma 4 26B (local Ollama) | Existing — `main` runner reused |
| **B** | gstack (process-first) | Gemma 4 26B (local Ollama, via Claude Code → Ollama bridge) | New — requires bridge setup |
| **D** | gstack (process-first) | Haiku 4.5 (cloud, native) | New — gstack-native |

**Cells dropped from MVP**:
- **C** (Beaconhill + Haiku 4.5) — deferred. Beaconhill is local-first by design; porting it to Anthropic API is a non-trivial branch and not the cheapest cell to add. Run after MVP if H3 looks promising.

**Why this 3-cell set is sufficient for H3**:
- **A vs B** isolates harness contribution at weak-model regime.
- **B vs D** isolates model contribution under process-first.
- The interaction term H3 falls out by comparing (A − B) at Gemma against (C − D) at Haiku. Without C we can't fully prove H3, but we can falsify it: if B > A on Gemma, H3 is dead.

---

## 3. Task & prompt

Reuse `ab_test/prompt.md` verbatim across all cells. No edits. The Pomodoro spec is well-defined, has a finite feature checklist, and we already have prior runs with it (cells A's history).

**Why Pomodoro**:
- Single-file deliverable (`timer.html`) — easy to compare.
- Mix of computational features (timer arithmetic, keyboard handler, audio) and aesthetic features (color palette, monospace, layout) — exposes both reasoning and instruction-following failures.
- Existing rubric and prior runs give us baseline statistics.

---

## 4. Metrics

Three layers. Layer 1 is the primary outcome. Layers 2 and 3 are supporting.

### Layer 1 — Deterministic feature checklist (primary)

A scriptable rubric over `timer.html` produced by each run. 0 or 1 per item. Pre-registered list:

| # | Feature | Detection |
|---|---------|-----------|
| 1 | File exists at `timer.html` | filesystem |
| 2 | Page loads without JS errors | Playwright `page.on("pageerror")` |
| 3 | "Focus" mode displays `25:00` initially | DOM text match |
| 4 | "Break" mode toggle button exists and is clickable | Playwright locator |
| 5 | Toggling to Break shows `5:00` | DOM text after click |
| 6 | Start button starts countdown (text changes within 2s) | DOM text diff |
| 7 | Pause preserves elapsed time | DOM text after pause+wait+resume |
| 8 | Reset returns to current mode's full duration | DOM text after reset |
| 9 | Display in `MM:SS` format | regex `\d{2}:\d{2}` |
| 10 | Space key toggles start/pause | Playwright keyboard event |
| 11 | Audio alert at 00:00 | Web Audio API call OR `<audio>` element present |
| 12 | Background color `#0d1117` | computed style |
| 13 | Primary text color `#e6edf3` | computed style on body/main |
| 14 | Accent color `#58a6ff` on buttons or active mode | computed style |
| 15 | Monospace font on countdown | computed style |
| 16 | Button border-radius ≥ 8px | computed style |
| 17 | Centered layout | viewport position check |
| 18 | Usable at mobile width (375px) | Playwright resize + interaction |

**Score**: 0–18. Reported as raw count and percentage.

### Layer 2 — Blinded pairwise judge

Same `judge_prep.py` infrastructure already built. Claude (Sonnet 4.6) sees two anonymized `timer.html` files and the spec; emits A/B/tie verdict per pair. All within-cell runs vs. all between-cell runs. No identifying tokens (file headers, comments) leaked.

### Layer 3 — Operational metrics

Per-run side data, not used for primary verdict but logged for context:

- Wallclock seconds to completion
- Token count (input + output) where reportable
- Number of evaluator pivots (Beaconhill only)
- Number of skill invocations (gstack only)
- Did the run complete or time out?

---

## 5. Pre-registered win criteria

Decided before any runs. **Do not adjust after seeing data.**

With **n=5 per cell** this is a **pilot study**, not a powered experiment. Mann–Whitney U on 5-vs-5 can hit p < 0.10 only when distributions barely overlap. Frame results as **directional signal**, not statistical proof.

- **H1 directionally supported** if median Layer-1 score for cell **A ≥ B + 3 points** AND blinded pairwise win rate A-vs-B ≥ 60%.
- **H2 directionally supported** if median Layer-1 score for cell **D ≥ B + 3 points** AND blinded pairwise win rate D-vs-B ≥ 60%.
- **H3 directionally supported** (partial) if (A − B) > 0 on Gemma. Full support needs cell C in a follow-up.
- **Layer-2 tiebreaker**: if Layer-1 medians are within 2 points, blinded pairwise win rate decides.
- **Falsification trigger**: if any cell shows ≥ 1 run with Layer-1 < 6/18 (catastrophic failure), pause and investigate before drawing conclusions — likely a setup bug, not a harness signal.

If the pilot shows promising directional signal, scale to n=15 per cell in a follow-up before claiming results.

---

## 6. Run plan

### Per cell

- **n = 5 runs** per cell (pilot study). Executed in shuffled order across cells to neutralize time-of-day and thermal effects.
- Same prompt file, same allowed tools where possible.
- Results land under `ab_test/results/{run_id}/{cell_id}/run-{1..5}/`.

### Wallclock budget

| Cell | Per-run estimate | Cell total |
|------|------------------|------------|
| A — Beaconhill+Gemma | ~10 min | ~50 min |
| B — gstack+Gemma | ~15 min | ~75 min |
| D — gstack+Haiku | ~5 min | ~25 min |

Total: ~2.5 hours wallclock serialized, **15 trials**. The Haiku cell can interleave with local runs (cloud-side, doesn't compete for GPU).

### Order

Shuffle (A, B, D) × 5 = 15 trials, randomized order. Pre-generate the order with a fixed seed and commit the order list as `ab_test/results/{run_id}/run_order.txt` so post-hoc claims about "we ran them randomly" are auditable.

---

## 7. Setup requirements

### Cell A — Beaconhill + Gemma

No new work. Use existing `ab_test/run.sh` adapted to write into the new multi-cell layout.

### Cell B — gstack + Gemma (the hard cell)

Two viable paths:

**Path B-1 (preferred): Claude Code → Ollama bridge**
- Install Claude Code CLI.
- Configure `ANTHROPIC_BASE_URL` to point at an Ollama-fronted Anthropic-compatible proxy (Ollama's docs cover this integration).
- Pull gstack's relevant skills into the workspace.
- Risks: tool-calling format differences, prompt-caching assumptions in gstack that don't hold for Gemma, context-window mismatch (Haiku ~200K, Gemma 4 26B 256K — fine, but caching behavior diverges).

**Path B-2 (fallback): OpenCode or another gstack host pointed at Ollama**
- gstack supports multiple hosts (`hosts/opencode.ts`, `codex.ts`).
- OpenCode reportedly supports OpenAI-compatible endpoints, which Ollama exposes.
- May require less bridging than Claude Code, but gstack's most-tuned host is Claude — running on a different host is its own confound.

**Decision**: try B-1 first. If gstack workflows don't run cleanly within ~2 hours of bridge debugging, fall back to B-2 and document the host swap as a known confound.

### Cell D — gstack + Haiku

- Install Claude Code CLI (already present at `/Users/dabsdamoon/.local/bin/claude`, v2.1.119+).
- Configure with Anthropic API key (read from 1Password per global rules).
- Install gstack per its README, pin to specific commit SHA (record in `run_meta.json`).
- **Force Haiku 4.5 explicitly** — do not rely on user defaults:

```bash
ANTHROPIC_MODEL=claude-haiku-4-5-20251001 \
  claude --model claude-haiku-4-5-20251001 \
         --print \
         --permission-mode bypassPermissions \
         --max-budget-usd 2.00 \
         --output-format json \
         "$(cat ab_test/prompt.md)"
```

- `--model` flag (per-call) is highest precedence; `ANTHROPIC_MODEL` env is defensive in case any sub-process spawns a child `claude` without re-passing the flag.
- Use the **full model ID** `claude-haiku-4-5-20251001`, not the alias `haiku`, so logs record which version actually ran.
- `--output-format json` returns the model identifier in the response payload — parse and write to `model_used.txt` per run to verify Haiku actually answered.
- `--max-budget-usd 2.00` caps per-run cost; protects against tool-call loops.
- gstack invokes Claude Code via skills (`/think`, `/plan-eng`, `/build`, etc.). The runner script has to chain these. See M3/M4 in §12.

---

## 8. Confound controls

- **Same prompt** verbatim for all cells. SHA-pinned in `run_meta.json`.
- **Same target file** (`timer.html`) and **same working directory layout** per run.
- **Same allowed tools** where the harness exposes the choice. Document deltas in `run_meta.json`.
- **Cells run on isolated working directories** (`ab_test/results/{run_id}/{cell}/run-N/`) — no shared state.
- **Random run order** across cells (shuffle the 30-trial list).
- **Pinned versions**: Beaconhill SHA (current branch), gstack SHA (record at start), Haiku model ID, Gemma model digest (`ollama show gemma4:26b` digest line).
- **Network gate**: cell A and cell B cut external network at the OS level (preserve local-first claim). Cell D allows network because Haiku is cloud-served — record this asymmetry.

---

## 9. Judging procedure

Reuse existing infrastructure with cell-aware extensions:

1. `ab_test/evaluate.py --run-dir <run_id>` produces Layer 1 deterministic scores per run, per cell.
2. `ab_test/judge_prep.py --run-dir <run_id> --cells A,B,D` builds anonymized pairwise comparison bundles.
3. Submit pairwise bundles to Sonnet 4.6 for blinded judgment. **Important**: judge sees only `timer.html` content and the spec — no `run_meta.json`, no session logs, no cell IDs.
4. `ab_test/report.py --run-dir <run_id>` aggregates Layer 1, Layer 2, Layer 3 into a single results table.

---

## 10. Risks & open questions

| Risk | Mitigation |
|------|------------|
| **gstack-on-Ollama bridge fails or runs degraded** | Time-box B-1 setup to 2 hours. Fall back to B-2 (OpenCode host). If both fail, run with cells A and D only and acknowledge confounded result. |
| **Haiku vs. Gemma token-context mismatch** | Both have generous context for this task (timer.html is small). Should not bind. |
| **gstack skills assume cloud-only features** (prompt caching, web search, sub-agent calls) | Skills that touch cloud-only features get disabled or stubbed for cell B. Document in `run_meta.json`. |
| **Layer-1 rubric overweights aesthetics** | Aesthetics are 7/18 items (~39%). Reasonable balance. Sensitivity-check by reporting score broken into "functional" (1–11) vs "aesthetic" (12–18) sub-totals. |
| **Pomodoro is too narrow a task to generalize** | Acknowledged. Result claims will be scoped to "Pomodoro-class single-file UI tasks." A broader task suite is future work. |
| **Run order randomization confounds with thermal state** | Add 60s pause between local Gemma runs. Log GPU temperature if accessible. |
| **Judge model bias** | Sonnet 4.6 is the same family as Haiku 4.5. May favor Haiku-style output. Counterbalance by also using a different judge model (e.g. Opus 4.7) on a 20% sample to detect bias. |

---

## 11. Out of scope (deferred)

- **Cell C** (Beaconhill + Haiku) — deferred to a follow-on if H3 looks supported.
- **Tasks beyond Pomodoro** — e.g., a CLI tool, a small CRUD API, a state-machine UI. Each adds ~1 day of rubric work.
- **Cost analysis** — Haiku token cost vs. Gemma electricity cost. Worth a back-of-envelope but not gating.
- **Latency-to-first-meaningful-output** — interesting but requires instrumentation each harness doesn't currently emit.
- **Human evaluation** — current judge is LLM-based. A human spot-check on 10% of runs would be the next reliability layer.

---

## 12. Implementation milestones

In order. Each is a separate commit.

1. **M1 — Multi-cell run layout**: extend `ab_test/run.sh` and `run_meta.py` to accept a list of cells and write `results/{run_id}/{cell_id}/run-{N}/`. Backwards-compatible with existing cell A invocation. (~2 hr)
2. **M2 — Layer-1 deterministic scorer**: `ab_test/score_layer1.py` runs Playwright against each `timer.html`, emits `score.json` with the 18-item checklist. (~3 hr)
3. **M3 — Cell B setup**: configure Claude Code → Ollama bridge, install gstack, smoke-test one Pomodoro run with gstack+Gemma. (~3 hr, may stretch)
4. **M4 — Cell D setup**: install gstack pointed at Haiku via `--model claude-haiku-4-5-20251001`. Smoke-test one run; verify model ID in JSON output. (~1 hr)
5. **M5 — Run the 15-trial sweep**: pre-generate shuffled order, execute the run list. (~2.5 hr unattended)
6. **M6 — Judge pass**: run `judge_prep` and submit pairs. (~1 hr active + cloud time)
7. **M7 — Report**: aggregate, write retrospective in `docs/release_note/`. (~2 hr)

Total active engineering: ~12 hr. Total wallclock with run time: ~17 hr.

---

## 13. Decision points before execution

Locked decisions:

- [x] **n = 5 runs per cell** (pilot study; scale to 15 in follow-up if directional).
- [x] **Haiku model ID** = `claude-haiku-4-5-20251001` (full ID, not alias).
- [x] **Cell C deferred** until after pilot.

Still to lock before M1:

- [ ] Confirm Path B-1 (Claude Code → Ollama bridge) as the first attempt for cell B; budget 2 hours before falling back to B-2.
- [ ] Confirm gstack version SHA to pin (record at experiment start; document in `run_meta.json`).
- [ ] Confirm directional thresholds (Δ ≥ 3 points and pairwise win ≥ 60% — see §5).
