# Beaconhill — Artifacts & References

Curated list of artifacts from local and web sources that are directly useful for implementing the beaconhill harness.

---

## 1. Ollama Python Library

**Source**: [ollama/ollama-python](https://github.com/ollama/ollama-python) (PyPI: `ollama`)
**Version**: 0.6.1+
**License**: MIT

The official Python client for Ollama. Provides everything needed for the LLM client layer.

### Key Capabilities

- Chat API with tool/function-calling support
- Sync (`Client`) and async (`AsyncClient`) interfaces
- Streaming responses via iterators / async generators
- Model management (pull, list, show, delete)
- Built on httpx — same HTTP library planned for beaconhill

### Tool Calling Support

Ollama natively supports tool calling via `/api/chat`. The flow matches beaconhill's agentic loop exactly:

```python
import ollama

# Define tools as JSON schema (OpenAI-compatible format)
tools = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read contents of a file",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"}
            }
        }
    }
}]

# Send with tools
response = ollama.chat(
    model="gemma4:26b",
    messages=[{"role": "user", "content": "Read the README.md file"}],
    tools=tools,
)

# Response contains tool_calls if model wants to use a tool
if response.message.tool_calls:
    for call in response.message.tool_calls:
        name = call.function.name
        args = call.function.arguments
        # Execute tool, then send result back as role="tool"
```

The Python SDK also auto-parses Python functions into tool schemas, reducing boilerplate.

### Relevance to Beaconhill

| Component | How It Helps |
|-----------|-------------|
| `LLMClient` protocol | Use `ollama.Client` or `ollama.AsyncClient` directly |
| Streaming | `stream=True` for real-time token display in REPL |
| Tool calling | Native support — no custom prompt hacking needed |
| Model management | `ollama.list()`, `ollama.pull()` for deployment scripts |
| Offline | Works entirely offline once model is pulled |

### Installation

```bash
pip install ollama
```

---

## 2. Local Skills — internal skill collection

A private collection of 32 Claude Code skills organized into 11 plugin packages. Several contain patterns, scripts, and frameworks directly applicable to beaconhill.

### 2a. `system-prompt-creator`

**Path**: `skills/system-prompt-creator/SKILL.md`
**Type**: Prompt engineering framework

A structured methodology for designing effective system prompts. Covers role definition, success criteria, safety rules, output contracts, and instruction hierarchy.

**Use in Beaconhill**: Foundation for crafting the system prompt that tells Gemma 4 how to behave as a coding agent — what tools are available, how to format tool calls, when to stop, and how to handle errors.

---

### 2b. `prompt-optimizer`

**Path**: `skills/prompt-optimizer/`
**Type**: Python scripts + methodology
**Key Files**:
- `scripts/token_counter.py` — Token counting across providers (tiktoken)
- `scripts/prompt_analyzer.py` — Analyze prompt structure and efficiency
- `scripts/cache_validator.py` — Validate cache-friendly prompt structure

**Use in Beaconhill**: Optimize system prompts for token efficiency. With Gemma 4's 256K context window, prompt size matters less than with smaller models, but efficient prompts still mean faster first-token latency and more room for conversation history.

---

### 2c. `skill-creator`

**Path**: `skills/skill-creator/`
**Type**: Python framework for skill development and evaluation
**Key Files**:
- `scripts/run_eval.py` — Execute test prompts against a skill
- `scripts/aggregate_benchmark.py` — Statistical analysis of eval results
- `scripts/generate_report.py` — Evaluation report generation
- `scripts/quick_validate.py` — SKILL.md schema validation
- `scripts/package_skill.py` — Package skills into .skill archives
- `scripts/utils.py` — Common helpers (error handling, JSON parsing)

**Use in Beaconhill**: Adapt the eval framework for testing beaconhill's tool-use reliability. Run scripted scenarios against the agent (e.g., "find all Python files and count lines"), compare expected vs actual tool calls, and benchmark across model quantizations.

---

### 2d. `mcp-builder`

**Path**: `skills/mcp-builder/SKILL.md`
**Type**: Guide + patterns for building MCP servers
**Content**: Tool design patterns, error handling, JSON-RPC lifecycle, transport options (stdio, SSE, HTTP)

**Use in Beaconhill**: Reference for when beaconhill adds MCP bridge support in Phase 4+. The tool design patterns (stateless JSON tools, input validation, error responses) are applicable even for builtin tools.

---

### 2e. `subagent-creator`

**Path**: `skills/subagent-creator/SKILL.md`
**Type**: Agent generation workflow

Generates repository-specific sub-agents with tailored tool permissions and instructions based on codebase analysis.

**Use in Beaconhill**: Pattern for spawning scoped child agents (e.g., a sub-agent that can only read files in `tests/` and run `pytest`). Useful for Phase 3 when adding sub-agent support.

---

### 2f. `claude-api`

**Path**: `skills/claude-api/`
**Type**: Multi-language API documentation
**Content**: Python, TypeScript, Java, Go, Ruby, C#, PHP, cURL examples for tool use, streaming, prompt caching, batches, agent SDK

**Use in Beaconhill**: While beaconhill uses Ollama (not Anthropic API), the tool-use patterns, message formatting, and agent loop examples are structurally similar. Good reference for how tool_calls and tool_results flow through a conversation.

---

### 2g. `webapp-testing`

**Path**: `skills/webapp-testing/`
**Type**: Playwright-based testing framework
**Key Files**:
- `SKILL.md` — Browser automation, screenshot capture, session auth
- Python scripts for server lifecycle, test execution, audit reporting

**Use in Beaconhill**: If beaconhill needs a browser tool (Phase 4+), this provides the Playwright integration pattern. Also useful as a reference for how to structure test harnesses with screenshot-based verification.

---

### 2h. `deploy-check`

**Path**: `skills/deploy-check/SKILL.md`
**Type**: Pre-merge safety analysis

Scans git diffs for destructive changes, breaking API contracts, missing migrations, environment dependencies, and rollback risks.

**Use in Beaconhill**: Pattern for building a `git_diff` or `code_review` tool. The risk assessment categories (breaking changes, security issues, migration gaps) are useful for an agent that modifies code.

---

### 2i. `debugging-retrospective`

**Path**: `skills/debugging-retrospective/SKILL.md`
**Type**: Session analysis workflow

Generates educational debugging postmortems — summarizes what happened, what was tried, what worked, and lessons learned.

**Use in Beaconhill**: Template for a `/retrospective` command that analyzes a beaconhill session log (JSONL) and produces a summary of what the agent did, what tools it used, and where it got stuck.

---

### 2j. Shared Office Processing Library

**Path**: `skills/{docx,xlsx,pptx}/scripts/office/`
**Type**: Reusable Python library
**Modules**: `pack.py`, `unpack.py`, `validate.py`, `soffice.py`, `validators/`, `helpers/`

**Use in Beaconhill**: Not directly needed for a coding agent, but the validation pipeline pattern (base validator class → format-specific validators → report) is a good model for beaconhill's tool input validation.

---

## 3. Web Resources

### 3a. Ollama Tool Calling Documentation

**Source**: [docs.ollama.com/capabilities/tool-calling](https://docs.ollama.com/capabilities/tool-calling)

Official reference for Ollama's tool calling API. Documents:
- Tool schema format (OpenAI-compatible JSON)
- Request/response format for `/api/chat` with tools
- Single, parallel, and multi-turn tool calling patterns
- Streaming with tool calls
- Sending tool results back as `role: "tool"` messages

**Critical for Beaconhill**: This is the API contract the agentic loop must implement.

---

### 3b. Ollama Claude Code Integration

**Source**: [docs.ollama.com/integrations/claude-code](https://docs.ollama.com/integrations/claude-code)

Documents how Ollama can serve as a backend for Claude Code CLI. While beaconhill builds its own harness rather than piggybacking on Claude Code, this shows that the Ollama API surface is compatible with agent harness patterns.

Key takeaway: Ollama recommends **at least 64K context** for agent workloads. Gemma 4 26B supports 256K — well within range.

---

### 3c. Langroid

**Source**: [github.com/langroid/langroid](https://github.com/langroid/langroid)

Multi-agent programming framework that works with Ollama. Relevant patterns:
- Agent-as-first-class-object with message routing
- Tool registration via Python decorators
- Conversation orchestration across multiple agents

**Use in Beaconhill**: Reference for multi-agent patterns if beaconhill grows beyond single-agent use. Not a dependency — beaconhill's custom harness is simpler and more controlled.

---

### 3d. MCP Bundles (MCPB)

**Source**: [modelcontextprotocol.io](https://modelcontextprotocol.io/docs/develop/build-with-agent-skills)

MCP Bundles package a local MCP server with its runtime as a single `.mcpb` archive. Useful for offline deployment since the server and all dependencies are self-contained.

**Use in Beaconhill**: Future consideration for distributing beaconhill tools as MCP servers that work in any compliant host, not just the beaconhill harness.

---

## Summary: What to Use First

| Priority | Artifact | Phase | Action |
|----------|----------|-------|--------|
| **P0** | `ollama` Python library | Phase 1 | `pip install ollama` — core LLM client |
| **P0** | Ollama tool calling docs | Phase 2 | API contract for tool dispatch |
| **P1** | `system-prompt-creator` | Phase 2 | Design Gemma 4 agent system prompt |
| **P1** | `skill-creator` eval scripts | Phase 3 | Adapt for agent testing |
| **P1** | `claude-api` tool-use patterns | Phase 2 | Reference for message flow design |
| **P2** | `prompt-optimizer` | Phase 3 | Optimize system prompt tokens |
| **P2** | `subagent-creator` | Phase 3 | Sub-agent spawning pattern |
| **P2** | `mcp-builder` | Phase 4 | MCP bridge reference |
| **P3** | `deploy-check` | Phase 4 | Code review tool patterns |
| **P3** | `webapp-testing` | Phase 4 | Browser tool reference |
| **P3** | Langroid / MCPB | Future | Multi-agent, portable deployment |
