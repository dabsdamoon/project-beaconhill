# Prompt Calibration

The planner and evaluator prompts live in `src/beaconhill/prompts.py` as constants. Their wording directly shapes agent behavior and typically needs iteration — the first version that compiles is rarely the one that ships.

This document captures the calibration loop for Beaconhill.

## When to calibrate

- Planner output is frequently unparseable or fenced incorrectly.
- Planner produces too many steps (>7) or over-specifies implementation details.
- Evaluator passes work that the t4 `validate.py` rejects (false positive).
- Evaluator rejects work that `validate.py` accepts (false negative).
- Retry loop fails to converge for tasks humans would consider easy.

## Loop

1. **Run the t4 tier.**
   ```bash
   python evals/runner.py --tier 4 --report evals/results/t4.json
   ```
2. **Read the session JSONLs.** Each fixture runs in a temp dir; the session path is logged inside the run. Inspect the planner output and evaluator verdicts.
3. **Classify failures.**
   - Planner JSON malformed -> tighten the output-format rule in `PLANNER_SYSTEM_PROMPT`.
   - Planner too granular -> strengthen the "deliverables not instructions" line.
   - Evaluator false positive -> add calibration language ("only if ALL criteria are demonstrably met").
   - Evaluator false negative -> loosen acceptance phrasing or add examples of valid evidence.
4. **Make one change per iteration.** Re-run the tier. Note the delta.
5. **Stop** when the failure mode is no longer dominant. Accept some residual noise; chasing zero is a trap.

## Anti-patterns

- Do not write prompts that reference specific tool names or code structures — the model drifts as tools change.
- Do not encode domain-specific guidance (e.g., "always use pytest"). Put that in `docs/design/` or the user's CLAUDE.md.
- Do not add few-shot examples longer than ~50 lines; they dominate the context budget.
- Do not hand-tune for a single fixture. If a change helps one case and hurts two, revert.

## Reference

- Anthropic: *Harness design for long-running application development* — on evaluator positivity bias and the generator/evaluator split.
- `docs/guidelines/plan-generate-evaluate-architecture.md` section "Risk and Mitigation" — the failure modes this loop addresses.
