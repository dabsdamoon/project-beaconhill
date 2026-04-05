# Project Beaconhill

## What Is This

Beaconhill is a local-first agent harness that enables developers to work with code, run agentic workflows, and build software — all without an internet connection. The name "beacon" reflects its purpose: a small, reliable light in the absence of the bright sunshine called "ask the internet."

## Tech Stack

- **Language**: Python 3.12
- **LLM Runtime**: Ollama (MLX backend on Apple Silicon)
- **Model**: Gemma 4 26B MoE (google/gemma-4-26b-a4b-it)
- **Target Platform**: macOS on Apple Silicon (M-series chips)

## Key Directories

- `docs/` — Project plans, architecture, guides
- `src/` — Agent harness source code (Python)
- `tests/` — Test suite

## Development Rules

- All code must work fully offline once model weights are downloaded
- No hard dependencies on cloud APIs — external providers are optional, not required
- Tool execution must be sandboxed with explicit permission policies
- Sessions are persisted as structured logs (JSONL) for auditability
- Python 3.12+ only; use type hints throughout
- Use `python3.12` at `/opt/homebrew/opt/python@3.12/libexec/bin/python3`

## Running the LLM

```bash
brew services start ollama      # start server
ollama run gemma4:26b           # interactive chat
# API available at http://localhost:11434
brew services stop ollama       # stop when not in use
```

## Reference Architectures

- **claw-code** (`/Users/dabsdamoon/projects/claw-code`) — Rust/Python agentic loop harness with trait-driven runtime, 40+ tools, hook system, and permission layering
- **OpenClaw** (`https://github.com/openclaw/openclaw`) — Node.js personal AI assistant with gateway-based multi-channel routing and device-node execution model
