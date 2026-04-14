# Plan-Generate-Evaluate Architecture for Beaconhill

## Background

Beaconhill is currently a single-agent, single-loop system. The model controls its own workflow: it decides what to do, executes tools, and decides when it is done. There is no planning step, no separate evaluation, and no quality gates.

This document proposes adding a **planner-generator-evaluator** architecture inspired by Anthropic's harness design for long-running application development. The goal is to bring structured workflow discipline to beaconhill while preserving its local-first, offline-capable design.

### Why this matters

The current single-loop architecture has a known weakness: the model judges its own work. As Anthropic's research confirms, "agents reliably skew positive when grading their own work." Separating generation from evaluation is "far more tractable than making a generator critical of its own work."

For single-turn tasks (quick file reads, simple edits), the existing loop is sufficient. The three-phase architecture targets **multi-step tasks** where planning reduces wasted effort and evaluation catches mistakes the generator won't self-report.

### References

- Anthropic Engineering: [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- arXiv 2511.15755: Multi-agent orchestration achieves zero quality variance with deterministic workflow steps
- arXiv 2603.15676: Automated self-testing as a quality gate for LLM applications

---

## Current State (as-is)

```
User input
    |
    v
[run_agentic_loop]  (single loop, up to 50 iterations)
    |
    +---> [OllamaClient] ---> model response
    |         |
    |    tool_calls? ----NO----> stream text, done
    |         |
    |        YES
    |         |
    |         v
    +---- [ToolRegistry.execute] ---> append result, loop back
```

**Files involved:**
- `runtime.py` (209 lines) -- single agentic loop
- `client.py` (174 lines) -- OllamaClient
- `tools.py` (297 lines) -- 6 tools, permission model
- `agent.py` (91 lines) -- system prompt, MAX_ITERATIONS=50

**What works well and must be preserved:**
- `LLMClient` protocol -- pluggable provider abstraction
- `ToolRegistry` with permission model -- clean separation of tool spec from policy
- `EventSink` pattern -- decoupled observability
- JSONL session persistence -- append-only, replayable
- Context compaction -- LLM-based summarization with fallback
- Image support -- base64 encoding in `Message.to_ollama()`
- Eval framework -- tiered fixtures in `evals/`

---

## Proposed Architecture (to-be)

```
User input
    |
    v
[Orchestrator]
    |
    |  Phase 1: PLAN
    |  +--> [Planner] uses LLM to decompose task into steps
    |  |    output: Plan (list of steps with acceptance criteria)
    |  |
    |  |  (optional) user approval gate
    |  |
    |  Phase 2: GENERATE
    |  +--> [Generator] executes steps via existing agentic loop
    |  |    one step at a time, sequential
    |  |    output: modified files, tool results per step
    |  |
    |  Phase 3: EVALUATE
    |  +--> [Evaluator] reviews generator output against plan criteria
    |       output: pass/fail per step, issues list, overall verdict
    |       |
    |       +-- PASS --> done
    |       +-- FAIL --> feed issues back to Generator, re-enter Phase 2
    |                    (up to max_retries)
```

### Key design decisions

**1. Single model, three system prompts -- not three processes.**
Beaconhill runs on local Ollama with one model (gemma4:26b). Spawning three separate model instances is impractical on consumer hardware. Instead, the three "agents" are three distinct system prompts and conversation contexts passed to the same OllamaClient. Each phase gets a fresh message list with its own system prompt.

**2. The existing `run_agentic_loop` becomes the generator.**
No rewrite needed. The current loop already does tool-calling well. The orchestrator wraps it with planning before and evaluation after.

**3. Evaluation is a separate LLM call, not self-evaluation.**
The evaluator operates on a fresh context. It receives: the original plan, the generator's final state (files changed, tool outputs), and optionally screenshots or test results. It does not see the generator's reasoning trace. This prevents the positivity bias documented by Anthropic.

**4. The plan is a data structure, not free text.**
Plans are structured as a list of steps with fields the evaluator can check against. This enables deterministic pass/fail on concrete criteria rather than subjective LLM judgment.

**5. Opt-in, not mandatory.**
Simple tasks bypass planning and evaluation. The orchestrator decides based on task complexity, or the user can force it with a flag (`--plan`) or REPL command (`/plan`).

---

## Data Model

### Plan

```python
@dataclass
class PlanStep:
    id: int
    description: str
    acceptance_criteria: list[str]
    files: list[str]           # expected files to touch
    status: StepStatus         # pending | in_progress | done | failed

class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"

@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    created_at: str
    approved: bool = False     # set after user approval (if required)
```

### EvaluationResult

```python
@dataclass
class StepVerdict:
    step_id: int
    passed: bool
    issues: list[str]          # concrete failure descriptions

@dataclass
class EvaluationResult:
    overall_passed: bool
    verdicts: list[StepVerdict]
    summary: str               # one-paragraph assessment
    iteration: int             # which evaluate cycle this is
```

### Orchestrator state

```python
class OrchestratorPhase(StrEnum):
    PLANNING = "planning"
    PLAN_APPROVAL = "plan_approval"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"

@dataclass
class OrchestratorState:
    phase: OrchestratorPhase
    plan: Plan | None
    evaluation_results: list[EvaluationResult]
    current_iteration: int
    max_iterations: int        # default: 3
```

---

## Implementation Plan

### Phase 0: Foundation (no behavior change)

New files, no modification to existing behavior. All existing tests must continue to pass.

**0.1 Add data models**
- File: `src/beaconhill/plan.py` (new)
- Contents: `PlanStep`, `Plan`, `StepVerdict`, `EvaluationResult`, `StepStatus`
- Serializable to/from dict for JSONL persistence
- Include `Plan.to_prompt()` method that renders the plan as text for LLM consumption

**0.2 Add orchestrator state**
- File: `src/beaconhill/orchestrator.py` (new, skeleton only)
- Contents: `OrchestratorPhase`, `OrchestratorState`
- No logic yet, just the state container

**0.3 Add plan persistence to session**
- Extend `Session` to optionally persist plan alongside messages
- Plan is written as a JSONL line with `{"_plan": true, ...}` marker
- `Session.load()` reconstructs plan from JSONL

**0.4 Tests**
- Unit tests for plan data model serialization
- Unit tests for session plan persistence

### Phase 1: Planner

The planner takes a user prompt and produces a structured plan.

**1.1 Planner system prompt**
- File: `src/beaconhill/prompts.py` (new)
- Dedicated prompt that instructs the model to:
  - Analyze the user's request
  - Break it into 1-7 concrete steps
  - Define acceptance criteria per step (observable, testable conditions)
  - List files each step will likely touch
  - Output structured JSON matching `Plan` schema
- The prompt must discourage over-specification. Quoting Anthropic: focus on "deliverables and high-level technical design rather than granular implementation details."

**1.2 Planner function**
- File: `src/beaconhill/planner.py` (new)
- `create_plan(client: OllamaClient, user_input: str, project_context: str) -> Plan`
- Calls `client.chat()` with planner system prompt
- Parses structured JSON from model response
- Falls back to single-step plan if parsing fails (graceful degradation)
- No tool access -- planning is pure reasoning

**1.3 Plan approval gate**
- In interactive mode: display plan to user, prompt for approval
  - `y` -- approve and proceed
  - `n` -- reject, user can revise request
  - `e` -- edit (user modifies steps before proceeding)
- In one-shot mode with `--plan`: auto-approve (user opted in)
- Add `ui.display_plan()` and `ui.plan_approval_prompt()` to `ui.py`

**1.4 Tests**
- Mock LLM responses for plan generation
- Test JSON parsing with valid/malformed outputs
- Test graceful fallback to single-step plan
- Test approval gate flow

### Phase 2: Orchestrator

The orchestrator wires planner -> generator -> evaluator in sequence.

**2.1 Orchestrator core**
- File: `src/beaconhill/orchestrator.py` (extend skeleton from 0.2)
- `run_orchestrated(client, registry, session, tools, allow_all, context_limit, user_input) -> OrchestratorState`
- Flow:
  1. Call planner to produce Plan
  2. If interactive and plan has >1 step: show plan, prompt approval
  3. For each step in plan:
     a. Construct a scoped user message: step description + acceptance criteria + context from prior steps
     b. Call existing `run_agentic_loop()` as the generator
     c. Mark step as done
  4. After all steps: call evaluator
  5. If evaluator fails: feed issues back, re-enter step 3 for failed steps
  6. Repeat until pass or max_iterations reached

**2.2 Step-scoped generation**
- Each step runs in a fresh message context (system prompt + step instruction + relevant file contents)
- The generator session is separate from the top-level session
- After each step, persist a checkpoint: files changed, tool calls made, final assistant text
- These checkpoints feed into the evaluator

**2.3 Event emission**
- Add new EventTypes: `PLAN_CREATED`, `PLAN_APPROVED`, `STEP_STARTED`, `STEP_COMPLETED`, `EVALUATION_STARTED`, `EVALUATION_COMPLETED`, `ORCHESTRATOR_RETRY`
- Emit through existing `EventSink` pattern

**2.4 CLI integration**
- Add `--plan` flag to CLI: forces orchestrated mode
- Add `/plan` REPL command: next user input enters orchestrated mode
- Without flag: existing `run_agentic_loop` behavior is unchanged (backward compatible)
- Add complexity heuristic (optional, later): auto-detect when planning would help based on prompt length, question words, multi-file keywords

**2.5 Tests**
- End-to-end orchestrator flow with mocked LLM
- Test retry loop on evaluation failure
- Test max_iterations enforcement
- Test backward compatibility: without `--plan`, behavior is identical to current

### Phase 3: Evaluator

The evaluator reviews the generator's work against the plan.

**3.1 Evaluator system prompt**
- File: extend `src/beaconhill/prompts.py`
- Dedicated prompt that instructs the model to:
  - Review each plan step's acceptance criteria
  - Check concrete conditions: file exists, function defined, test passes, etc.
  - Report pass/fail per step with specific failure descriptions
  - Be skeptical by default. Include calibration language: "Only mark a step as passed if ALL acceptance criteria are demonstrably met."
  - Output structured JSON matching `EvaluationResult` schema

**3.2 Evaluator function**
- File: `src/beaconhill/evaluator.py` (new)
- `evaluate(client: OllamaClient, plan: Plan, evidence: list[StepEvidence]) -> EvaluationResult`
- The evaluator gets tool access (read-only): `read_file`, `glob`, `grep`, `bash` (read-only commands only)
- This allows it to independently verify: does the file exist? does it contain the expected function? does the test pass?
- Fresh message context -- no access to generator's reasoning trace
- Parse structured JSON response

**3.3 Evidence collection**
- After the generator finishes, collect evidence per step:
  - Files created/modified (via git diff or file timestamps)
  - Tool call history (from session messages)
  - Final assistant text per step
- `StepEvidence` dataclass packages this for the evaluator

**3.4 Read-only tool policy for evaluator**
- The evaluator's `ToolRegistry` uses a restricted policy:
  - READ tools: ALLOW
  - WRITE tools: DENY
  - EXECUTE tools: ALLOW (but bash commands are prefixed with verification: `test -f`, `grep -c`, `python -m pytest`)
- This prevents the evaluator from "fixing" issues itself -- it can only observe and report

**3.5 Feedback loop**
- On evaluation failure, the orchestrator constructs a feedback message for the generator:
  - Which steps failed
  - Specific issues from the evaluator
  - "Fix the following issues: ..."
- Generator re-runs only failed steps (not the entire plan)
- Maximum 3 evaluation cycles (configurable via `Config`)

**3.6 Tests**
- Mock evaluator with pass/fail scenarios
- Test evidence collection from generator output
- Test feedback loop: fail -> fix -> re-evaluate -> pass
- Test max retry enforcement
- Test read-only policy prevents evaluator from writing

### Phase 4: Configuration and Tuning

**4.1 Config extensions**
- Add to `Config`:
  - `plan_mode: str = "auto"` -- `"auto"`, `"always"`, `"never"`
  - `max_eval_iterations: int = 3`
  - `plan_approval: bool = True` -- require user approval in interactive mode
  - `evaluator_tools: list[str] = ["read_file", "glob", "grep", "bash"]`

**4.2 Prompt tuning**
- Planner and evaluator prompts will need iterative calibration
- Store prompts in `src/beaconhill/prompts.py` as constants, not in config files
- Document the calibration process: run evals, read evaluator logs, adjust wording
- Per Anthropic: "It took several rounds of this development loop before the evaluator was grading in a way that I found reasonable."

**4.3 Eval framework extension**
- Add t4 tier to `evals/`: multi-step tasks that require planning
- Each t4 fixture includes:
  - `prompt.txt` -- task description
  - `expected_plan.json` -- reference plan (for plan quality evaluation)
  - `setup/` -- initial project state
  - `validate.py` -- final state validation
- Measure: plan quality, generation correctness, evaluator accuracy, total iterations

---

## File Map (new and modified)

### New files

| File | Purpose | Estimated LOC |
|------|---------|---------------|
| `src/beaconhill/plan.py` | Plan, PlanStep, StepStatus, StepVerdict, EvaluationResult | ~80 |
| `src/beaconhill/planner.py` | `create_plan()` -- LLM-based task decomposition | ~100 |
| `src/beaconhill/evaluator.py` | `evaluate()` -- independent verification with read-only tools | ~120 |
| `src/beaconhill/orchestrator.py` | `run_orchestrated()` -- plan->generate->evaluate loop | ~180 |
| `src/beaconhill/prompts.py` | System prompts for planner, generator, evaluator | ~120 |
| `tests/test_plan.py` | Plan model tests | ~60 |
| `tests/test_planner.py` | Planner function tests | ~80 |
| `tests/test_evaluator.py` | Evaluator function tests | ~100 |
| `tests/test_orchestrator.py` | Orchestrator integration tests | ~150 |

### Modified files

| File | Changes |
|------|---------|
| `cli.py` | Add `--plan` flag, `/plan` REPL command, plan display/approval UI calls |
| `state.py` | Add orchestrator-related EventTypes and OrchestratorPhase |
| `config.py` | Add `plan_mode`, `max_eval_iterations`, `plan_approval` fields |
| `session.py` | Add plan persistence in JSONL |
| `ui.py` | Add `display_plan()`, `plan_approval_prompt()`, step progress display |
| `agent.py` | Extract system prompt to `prompts.py`, keep `build_system_prompt()` as wrapper |

### Unchanged files

| File | Reason |
|------|--------|
| `runtime.py` | The agentic loop is the generator. No changes needed. |
| `client.py` | OllamaClient is already generic enough. |
| `tools.py` | Tool registry supports restricted policies via constructor. |
| `models.py` | Message dataclass is sufficient. |
| `context.py` | Compaction works per-session; orchestrator creates scoped sessions. |

---

## Constraints

1. **Single model, single GPU.** No assumption of parallel inference. All three phases use the same OllamaClient sequentially.
2. **Backward compatible.** Without `--plan`, the system behaves exactly as it does today.
3. **No external dependencies.** No new pip packages. Everything built on existing `ollama` and `rich` dependencies.
4. **Offline-first.** No network calls beyond localhost Ollama.
5. **Session format stable.** Existing JSONL sessions remain loadable. New plan entries use distinct markers.
6. **Existing tests pass.** Every phase of implementation must keep the existing 12 test files green.

---

## Risk and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| gemma4:26b produces poor structured JSON for plans | Plans are unparseable, system falls back to single-step | Graceful fallback: treat entire user input as a single-step plan |
| Evaluator is too lenient (Anthropic's documented problem) | False passes, quality regression | Calibrate with few-shot examples in evaluator prompt; tune iteratively using eval framework |
| Evaluator is too strict | Infinite retry loops, user frustration | Hard cap at `max_eval_iterations`; on final failure, present issues to user and let them decide |
| Planning overhead for simple tasks | Slower response for trivial requests | Auto-detection heuristic; user can disable with `plan_mode: never` |
| Context exhaustion across three phases | Each phase needs fresh context; prior phases consume tokens | Each phase gets its own message list; only structured outputs (Plan, EvaluationResult) cross phase boundaries, not full conversation history |
| Model hallucination in plan step descriptions | Steps don't match what the generator can actually do | Constrain plan steps to operations the tool set supports; include tool list in planner prompt |

---

## Implementation Order

```
Phase 0  [Foundation]      -- data models, no behavior change
  |
Phase 1  [Planner]         -- plan generation + approval gate
  |
Phase 2  [Orchestrator]    -- wire plan -> generate -> evaluate
  |
Phase 3  [Evaluator]       -- independent verification with read-only tools
  |
Phase 4  [Config + Tuning] -- prompt calibration, eval extension
```

Each phase is independently testable and shippable. Phase 0+1 can be merged as a useful feature (plan display) even before the evaluator exists. Phase 2 can initially run without evaluation (plan + generate only) and add the evaluator when Phase 3 is ready.

---

## Success Criteria

The architecture is successful when:

1. Multi-step tasks (t3/t4 eval tier) show higher completion rate with planning than without
2. The evaluator catches at least 60% of issues that the generator misses in self-evaluation
3. Simple tasks (t1/t2) show no latency regression when `plan_mode: auto` correctly bypasses planning
4. The feedback loop (evaluate -> fix -> re-evaluate) converges within 3 iterations for 80% of failing cases
5. All existing tests pass without modification
