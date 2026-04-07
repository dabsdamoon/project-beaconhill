# Beaconhill — Harness Architecture

## Design Philosophy

Beaconhill's harness is a **local-first agentic loop** — a process that mediates between a human developer and a locally-running LLM, giving the model access to tools (file I/O, shell, search) so it can act on a codebase autonomously.

The architecture draws from two reference implementations:

- **claw-code** — A Rust-based agentic loop with trait-driven runtime abstraction, 40+ tools, layered permissions, and hook-based extensibility
- **OpenClaw** — A Node.js personal AI assistant with gateway-routed multi-channel sessions and device-node execution

Beaconhill takes the structural rigor of claw-code's loop design and the deployment simplicity of OpenClaw's local-first model, adapted for Python and offline LLM inference.

---

## Reference: claw-code

Source: `/Users/dabsdamoon/projects/claw-code`

### What It Is

A production-grade agentic coding harness built in Rust (~20K LOC, 9 crates). Designed for autonomous agent coordination — agents (called "claws") are orchestrated via external systems, not by humans in terminals.

### Key Patterns Borrowed

**1. Two-Trait Loop Abstraction**

claw-code's core loop (`ConversationRuntime<C, T>`) is generic over two traits:
- `ApiClient` — abstracts the LLM call (HTTP, mock, sub-agent proxy)
- `ToolExecutor` — abstracts tool dispatch (builtin, MCP bridge, plugin)

This decoupling means the same loop engine works for real inference, testing with mocks, and sub-agent spawning. Beaconhill adopts this pattern using Python protocols/ABCs.

**2. Model-Driven Termination**

The agentic loop has no hardcoded iteration limit. The model decides when to stop by returning a response with no tool calls. This is critical — the agent controls its own workflow depth.

**3. Permission Layering**

Three layers of permission enforcement:
- Tools declare their required permission level (read-only, workspace-write, full-access)
- Hooks can override permissions per invocation
- An enforcer applies contextual checks (workspace boundaries, destructive command blocking)

Beaconhill implements a simplified version: per-tool permission declarations with an ask/allow/deny policy.

**4. Session as Immutable Log**

Sessions are persisted as JSONL — append-only, structured, replayable. This enables resume, compaction, and external analysis without re-running the loop.

**5. Hook System**

Shell-based hooks at three lifecycle points (PreToolUse, PostToolUse, PostToolUseFailure) allow out-of-process customization without modifying harness code.

### claw-code Key Files for Reference

| File | What to Study |
|------|---------------|
| `rust/crates/runtime/src/conversation.rs` | Core agentic loop pattern |
| `rust/crates/runtime/src/permissions.rs` | Permission mode hierarchy |
| `rust/crates/runtime/src/session.rs` | Session message model |
| `rust/crates/runtime/src/hooks.rs` | Hook lifecycle |
| `rust/crates/tools/src/lib.rs` | Tool spec format and dispatch |
| `rust/crates/api/src/client.rs` | Provider abstraction |

---

## Reference: OpenClaw

Source: `https://github.com/openclaw/openclaw`

### What It Is

A self-hosted personal AI assistant (Node.js/TypeScript) that operates across 23+ messaging platforms. Emphasizes local-first deployment with a gateway-based architecture.

### Key Patterns Borrowed

**1. Local-First by Default**

Gateway binds to loopback (`127.0.0.1`). No cloud dependency for core operation. Remote access is opt-in via Tailscale or explicit configuration. Beaconhill follows this: localhost Ollama, no outbound network calls.

**2. Session Isolation**

Each conversation runs in an isolated agent session with its own context, tools, and permission state. Sessions don't leak state to each other.

**3. Device-Node Execution**

OpenClaw separates "where to reason" from "where to execute." The gateway runs the LLM; device nodes execute local actions (shell, filesystem). Beaconhill simplifies this since reasoning and execution happen on the same machine, but the separation is preserved in the code for future remote deployment.

**4. Tool Permission Toggle**

Tools have granular enable/disable controls. Elevated access (e.g., unrestricted bash) is explicitly toggled. Beaconhill adopts this with per-tool permission declarations.

---

## Beaconhill Architecture

### Component Overview

```
┌─────────────────────────────────────────────────┐
│                  CLI / REPL                      │
│  (user input, display, session management)       │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│              Agent Runtime                       │
│                                                  │
│  ┌───────────┐  ┌───────────┐  ┌─────────────┐ │
│  │  Prompt    │  │  Agentic  │  │  Session     │ │
│  │  Assembly  │  │  Loop     │  │  Manager     │ │
│  └───────────┘  └─────┬─────┘  └─────────────┘ │
│                       │                          │
│            ┌──────────┴──────────┐               │
│            ▼                     ▼               │
│  ┌──────────────┐     ┌──────────────────┐      │
│  │  LLM Client  │     │  Tool Executor   │      │
│  │  (Protocol)  │     │  (Protocol)      │      │
│  └──────┬───────┘     └────────┬─────────┘      │
└─────────┼──────────────────────┼────────────────┘
          │                      │
          ▼                      ▼
┌──────────────────┐   ┌──────────────────────┐
│  Ollama API      │   │  Tool Registry       │
│  localhost:11434 │   │                      │
│                  │   │  - bash              │
│  Gemma 4 26B MoE │   │  - read_file         │
│                  │   │  - write_file        │
└──────────────────┘   │  - edit_file         │
                       │  - glob              │
                       │  - grep              │
                       │  - ...               │
                       └──────────────────────┘
```

### Core Abstractions (Python Protocols)

```python
class LLMClient(Protocol):
    """Abstracts the LLM provider. Default: Ollama."""
    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> Response: ...
    def stream(self, messages: list[Message], tools: list[ToolSpec]) -> Iterator[Event]: ...

class ToolExecutor(Protocol):
    """Abstracts tool dispatch. Enables mocking and sandboxing."""
    def execute(self, tool_name: str, tool_input: dict) -> ToolResult: ...
    def list_tools(self) -> list[ToolSpec]: ...
```

### Agentic Loop (Pseudocode)

```
function run_turn(user_message):
    session.append(user_message)

    loop:
        response = llm_client.chat(session.messages, tools)
        session.append(response)

        if response has no tool_calls:
            break  # model decided it's done

        for each tool_call in response.tool_calls:
            permission = check_permission(tool_call)
            if permission == DENY:
                result = ToolResult(error="Permission denied")
            elif permission == ASK:
                result = prompt_user_for_approval(tool_call)
            else:
                result = tool_executor.execute(tool_call)

            session.append(result)

    session.save()
    return response.text
```

### Tool Specification Format

Each tool declares:

```python
@dataclass
class ToolSpec:
    name: str                          # e.g., "read_file"
    description: str                   # shown to the model
    parameters: dict                   # JSON Schema for input
    required_permission: Permission    # READ, WRITE, EXECUTE
```

### Permission Model

Simplified from claw-code's three-layer system:

```
Permission Levels:
  READ      — file reading, search (glob, grep)
  WRITE     — file creation, editing
  EXECUTE   — shell commands (bash)

Policy per tool:
  ALLOW     — always permitted
  ASK       — prompt user for each invocation
  DENY      — never permitted
```

Default policy: READ=allow, WRITE=ask, EXECUTE=ask.

### Session Format (JSONL)

Each line is a JSON object representing one message:

```jsonl
{"role": "user", "content": "Find all Python files in src/", "timestamp": "..."}
{"role": "assistant", "content": null, "tool_calls": [{"name": "glob", "input": {"pattern": "src/**/*.py"}}]}
{"role": "tool", "name": "glob", "content": "src/main.py\nsrc/utils.py\n..."}
{"role": "assistant", "content": "I found 5 Python files in src/..."}
```

### Configuration

```
~/.beaconhill/config.json          # user-global defaults
<project>/.beaconhill/config.json  # project-level overrides
```

Config sections:
- `model` — Ollama model name (default: `gemma4:26b`)
- `ollama_url` — API endpoint (default: `http://localhost:11434`)
- `permissions` — per-tool permission policy
- `context_limit` — max tokens before compaction
- `session_dir` — where to store JSONL sessions

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Python over Rust | Faster iteration for a new project; Gemma 4 tool-use prompting needs experimentation |
| Ollama over direct MLX | Ollama handles model lifecycle, memory management, and provides a stable API |
| Protocol-based abstractions | Enables swapping LLM providers and mocking tools for testing |
| JSONL sessions | Append-only, streamable, easy to parse; proven pattern from claw-code |
| No MCP initially | Keep it simple; tools are builtin. MCP bridge can be added later |
| Permission ASK by default for writes | Safety first — especially important for offline agents where undo may not be possible |

## Future Considerations

- **MCP bridge**: Add support for external tool servers via MCP protocol
- **Sub-agents**: Spawn scoped child agents for parallel tasks (pattern from claw-code)
- **Remote deployment**: Package as a Docker container with Ollama + model weights baked in
- **Multi-model**: Support falling back to smaller models (Gemma 4 E4B) for simple tasks
- **Hook system**: Shell-based pre/post tool hooks for customization without code changes
