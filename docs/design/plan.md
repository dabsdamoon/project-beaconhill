# Beaconhill — Project Plan

## Purpose

Beaconhill is a local-first coding agent harness. It allows developers to work with code — editing, searching, executing, and reasoning — without any internet connection.

The name comes from "beacon": a small dot of light in the absence of the bright sunshine called "ask the internet." In environments where connectivity is unavailable, unreliable, or restricted (air-gapped labs, field deployments, offline travel, secure facilities), developers still need intelligent assistance. Beaconhill provides that.

## Goals

1. **Fully offline agent**: Once the model weights are downloaded, everything runs locally. No API keys, no cloud calls, no telemetry phoning home.
2. **Code-capable harness**: The agent can read files, write files, execute shell commands, search codebases, and reason about code — similar to what cloud-based coding agents provide.
3. **Deployable anywhere**: The agent should be packageable for deployment to machines and environments with no internet access.
4. **Extensible tool system**: Tools (file ops, bash, search) are modular and can be added without changing the core loop.
5. **Auditable sessions**: Every interaction is logged as structured data for review and replay.

## Non-Goals

- Not a general-purpose chatbot or personal assistant
- Not a cloud service or SaaS product
- Not a replacement for Claude Code — it's a complement for offline scenarios

## Architecture Overview

The harness follows a loop-based agent architecture inspired by claw-code and OpenClaw:

```
User Input
    │
    ▼
┌─────────────────────┐
│   System Prompt      │  (role, tools, project context)
│   Assembly           │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   LLM Call           │  Ollama API → Gemma 4 26B MoE
│   (localhost:11434)  │
└─────────┬───────────┘
          │
          ▼
    ┌─────────────┐
    │ Response     │
    │ has tool     │──── No ───▶ Display text response
    │ calls?       │
    └──────┬──────┘
           │ Yes
           ▼
┌─────────────────────┐
│   Tool Execution     │  (bash, read_file, write_file, grep, glob)
│   + Permission Check │
└─────────┬───────────┘
          │
          ▼
    Push tool results into conversation
          │
          ▼
    Loop back to LLM Call
```

## Phases

### Phase 1 — Foundation

Set up the project skeleton and get a basic chat loop working with the local LLM.

- [ ] Project scaffolding (pyproject.toml, src layout, virtual environment)
- [ ] Ollama API client using the `ollama` Python library (sync + async)
- [ ] Basic REPL loop (user input → LLM → display streamed response)
- [ ] Session persistence (JSONL — append each message as a JSON line)

**Deliverable**: Run `python -m beaconhill` and have a working chat with Gemma 4 in the terminal.

---

### Phase 1.5 — Tool-Calling Eval Spike

Before investing in the full tool system, validate that Gemma 4 can reliably produce
structured tool calls via Ollama. This is the highest-risk assumption in the project.

The eval uses synthetic fixtures — small, self-contained directories with known files,
a prompt, and a validation script. No real repos or heavy infrastructure needed.

#### Eval Structure

```
evals/
├── runner.py              # runs agent against each case, collects results
├── fixtures/
│   ├── t1_read_file/
│   │   ├── setup/         # files the agent will operate on
│   │   ├── prompt.txt     # what to ask the agent
│   │   └── validate.py    # checks the result (exit 0 = pass)
│   ├── t1_glob_search/
│   ├── t2_find_bug/
│   ├── t3_add_parameter/
│   └── ...
└── results/               # JSONL logs per run
```

#### Eval Tiers

**Tier 1 — Tool-calling mechanics** (can it produce valid calls?)

- [ ] Read a file and answer a question about its contents
- [ ] Glob for files matching a pattern, report results
- [ ] Run a shell command and return the output
- [ ] Chain 2-3 tool calls to answer a multi-step question
- [ ] Handle a tool call that returns an error gracefully

**Tier 2 — Code understanding** (can it reason about code via tools?)

- [ ] Read a function and explain what it does
- [ ] Find a planted bug in a file
- [ ] Identify dependencies from imports across multiple files
- [ ] Summarize a small project's structure using glob + read

**Tier 3 — Code editing** (can it modify code correctly?)

- [ ] Add a parameter to an existing function
- [ ] Fix an off-by-one error (validated by running the file's tests)
- [ ] Rename a variable across a project using grep + edit
- [ ] Write a new function that passes provided test cases

#### Validation

Each fixture's `validate.py` checks one or more of:
- File contents match expected state (diff or grep)
- Test suite passes (`subprocess.run(["python", "test_*.py"])`)
- Agent output contains expected information
- Tool calls were well-formed (parsed from session JSONL)

#### Success Criteria

- **Tier 1**: ≥90% pass rate (if this fails, the model can't do basic tool use)
- **Tier 2**: ≥70% pass rate
- **Tier 3**: ≥50% pass rate (stretch goal for a 26B model)

If Tier 1 falls below 80%, evaluate mitigations before proceeding:
- Try constrained decoding / grammar-guided output
- Try a different model (Qwen 2.5 Coder 32B, DeepSeek Coder V2)
- Add an output repair layer that re-parses malformed tool calls

#### CI/CD Integration

The eval runner (`runner.py`) must be CI-ready from day one:

- [ ] `runner.py` exits with non-zero status when any tier falls below its threshold
- [ ] Output a machine-readable report (`results/report.json`) with per-tier and per-case pass/fail
- [ ] Print a human-readable summary table to stdout (tier, passed, failed, rate, status)
- [ ] Support `--tier` flag to run a single tier (e.g., `python runner.py --tier 1`)
- [ ] Support `--threshold` override for experimentation (e.g., `--threshold t1=80,t2=60`)
- [ ] Each fixture runs in an isolated temp directory (no cross-contamination between cases)
- [ ] Total runtime target: under 10 minutes for all tiers (parallelize independent fixtures)

Example CI step:

```yaml
# .github/workflows/eval.yml
eval:
  runs-on: self-hosted  # needs Ollama + model weights
  steps:
    - uses: actions/checkout@v4
    - run: python evals/runner.py --report results/report.json
    # exits non-zero if any tier misses its threshold
```

Note: this requires a self-hosted runner with Ollama and the model weights pre-installed.
Cloud CI runners won't have the hardware or the model.

**Deliverable**: A pass/fail report showing Gemma 4's tool-calling reliability, with
enough data to decide whether to proceed with Phase 2 as planned or pivot the model choice.
Runnable as `python evals/runner.py` locally or in CI.

---

### Phase 2 — Tool System + Agentic Loop

The `ollama` Python library has native tool-calling support. Tools are defined as
OpenAI-compatible JSON schemas and passed to `ollama.chat(tools=...)`. When Gemma 4
wants to use a tool, the response contains `tool_calls` with the function name and
arguments. Tool results are sent back as `role: "tool"` messages.

This means we do NOT need:
- Custom prompt hacking to make the model output tool calls
- Manual parsing of free-text tool invocations
- A separate "tool-use prompt engineering" step

The tool system and agentic loop can be built together in one phase.

#### 2a. Tool Abstractions

- [ ] `ToolSpec` dataclass: name, description, parameters (JSON Schema), permission level
- [ ] `ToolRegistry`: register tools, list tools, dispatch by name
- [ ] `ToolResult` dataclass: output string, is_error flag

#### 2b. Core Tools

Six tools to start — enough for a useful coding agent:

| Tool | Permission | What It Does |
|------|-----------|--------------|
| `bash` | EXECUTE | Run a shell command, return stdout/stderr |
| `read_file` | READ | Read file contents (with line range support) |
| `write_file` | WRITE | Create or overwrite a file |
| `edit_file` | WRITE | Find-and-replace within a file |
| `glob` | READ | Find files matching a glob pattern |
| `grep` | READ | Search file contents with regex |

Each tool is a Python function that:
1. Receives a dict of arguments (parsed from the model's tool call)
2. Executes the operation
3. Returns a string result (or error message)

#### 2c. Agentic Loop

The core loop — model calls tools until it decides it's done:

```
def run_turn(user_message):
    messages.append(user_message)

    while True:
        response = ollama.chat(
            model="gemma4:26b",
            messages=messages,
            tools=registry.tool_specs(),
        )
        messages.append(response.message)

        if not response.message.tool_calls:
            break  # model is done — display final text

        for call in response.message.tool_calls:
            permission = check_permission(call)
            result = execute_or_deny(call, permission)
            messages.append({"role": "tool", "content": result})

    save_session(messages)
```

- [ ] Implement the loop with the `ollama` library's native tool calling
- [ ] Wire tool_calls → ToolRegistry.dispatch → tool result → back to model
- [ ] Add basic permission checks (ALLOW / ASK / DENY per tool)
- [ ] Handle tool execution errors gracefully (send error text back to model)
- [ ] Guard against infinite loops (max iterations, e.g., 50 turns)

#### 2d. System Prompt

- [ ] Write system prompt defining the agent's role, available tools, and behavior rules
- [ ] Include project context injection (working directory, key files)
- [ ] Reference `system-prompt-creator` skill from my-little-skills for design patterns

**Deliverable**: Ask the agent "find all Python files in this project and count total lines of code" and watch it chain glob → bash tools autonomously.

---

### Phase 3 — Robustness & Session Management

Harden the agent for real-world use.

- [ ] Session resume: reload a JSONL session and continue the conversation
- [ ] Session replay: re-display a past session as read-only output
- [ ] Context window management: track token count, warn when approaching limit
- [ ] Context compaction: summarize older messages when context fills up
- [ ] Streaming display: show tokens as they arrive (using `stream=True`)
- [ ] Improved permission UX: prompt user with tool name + args, accept/reject
- [ ] Error recovery: if Ollama crashes or model unloads, reconnect gracefully

**Deliverable**: Resume yesterday's session and continue working on the same codebase.

---

### Phase 4 — CLI & Deployment

Make it usable beyond a dev setup.

- [ ] CLI with argument parsing (`--model`, `--session`, `--resume`, `--prompt`)
- [ ] One-shot mode: `beaconhill --prompt "refactor this function"` (non-interactive)
- [ ] Config file support (~/.beaconhill/config.json, project-level overrides)
- [ ] Packaging for offline deployment:
  - Bundle harness code + dependencies (pip wheel or zipapp)
  - Script to copy Ollama + model weights to a target machine
  - Single-command setup on a fresh Mac
- [ ] Documentation and usage guide

**Deliverable**: Hand someone a USB drive with everything needed. They run one setup script and have a working coding agent — no internet required.

---

### Future — Phase 5+

Ideas for after the core is solid:

- [ ] Sub-agent spawning (scoped child agents for parallel tasks)
- [ ] MCP bridge (expose/consume tools via Model Context Protocol)
- [ ] Hook system (shell-based pre/post tool hooks, from claw-code pattern)
- [ ] Multi-model support (fall back to Gemma 4 E4B for simple tasks)
- [ ] Browser tool (Playwright integration, from webapp-testing skill)
- [ ] Eval harness (adapt skill-creator eval scripts for agent benchmarking)

## Dependencies

| Dependency | Purpose | Offline? |
|------------|---------|----------|
| Python 3.12 | Runtime | Yes |
| Ollama | LLM inference server | Yes (after model pull) |
| Gemma 4 26B MoE | Language model | Yes (weights stored locally) |
| `ollama` (PyPI) | Python client for Ollama — chat, streaming, tool calling | Yes |
| `rich` (optional) | Terminal UI — syntax highlighting, markdown rendering | Yes |

Note: The `ollama` Python library uses `httpx` internally. No need to add `httpx`
as a separate dependency unless we need custom HTTP behavior.

## Success Criteria

- Agent can navigate an unfamiliar codebase, find relevant files, and make edits — all offline
- Tool-use loop runs reliably with Gemma 4 using native Ollama tool calling
- No infinite loops — model decides when to stop, with a hard max-iteration safety net
- Full session can be replayed from JSONL logs
- Sessions can be resumed across separate runs
- Deployable to a fresh Mac with only: Python 3.12, Ollama, model weights, and the harness code
