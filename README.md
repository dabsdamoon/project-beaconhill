# Beaconhill

Local-first coding agent harness. Works fully offline on Apple Silicon Macs.

## Prerequisites

- macOS on Apple Silicon (M-series)
- Python 3.12+
- [Ollama](https://ollama.com)

## Setup

### 1. Install Ollama and pull the model

```bash
brew install ollama
ollama pull gemma4:26b
```

This downloads ~15GB of model weights. Only needed once.

### 2. Install Beaconhill

```bash
cd /Users/dabsdamoon/projects/project-beaconhill
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

### Start Ollama

Ollama must be running before using Beaconhill.

```bash
# Start as a background service
brew services start ollama

# Or run in the foreground
ollama serve
```

Verify it's running:

```bash
curl -s http://localhost:11434/api/tags
```

### Interactive mode

```bash
beaconhill
```

The agent starts a REPL where you can ask it to read, write, search, and reason about code. It has access to tools (`bash`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`) and will chain them autonomously.

- `--allow-all` skips permission prompts for write/execute tools
- `--model <name>` uses a different Ollama model

```bash
beaconhill --allow-all
beaconhill --model qwen2.5:32b
```

### One-shot mode

Run a single prompt and exit:

```bash
beaconhill --prompt "find all TODO comments in this project"
```

### Session management

Sessions are saved as JSONL files in `~/.beaconhill/sessions/`.

```bash
# Resume a previous session
beaconhill --resume <session-id>

# Replay a session (read-only, no Ollama needed)
beaconhill --replay <session-id>
```

Session IDs support prefix matching, so `beaconhill --replay a3c` works if there's only one session starting with `a3c`.

### REPL commands

| Command | Action |
|---------|--------|
| `/quit` or `/exit` | Exit the session |
| `/session` | Print the current session file path |

### Configuration

Create a config file to set defaults:

```bash
# Global defaults
~/.beaconhill/config.json

# Project-level overrides
<project>/.beaconhill/config.json
```

```json
{
  "model": "gemma4:26b",
  "host": "http://localhost:11434",
  "allow_all": false,
  "context_limit": 8192
}
```

CLI arguments override config file values.

## Stopping Ollama

```bash
brew services stop ollama
```

## Running tests

```bash
# Unit tests
.venv/bin/pytest tests/ -v

# Eval suite (requires Ollama running)
.venv/bin/python evals/runner.py
.venv/bin/python evals/runner.py --tier 1
```

## Project structure

```
src/beaconhill/
  __main__.py   Entry point (python -m beaconhill)
  cli.py        REPL and argument parsing
  client.py     Ollama API client (LLMClient protocol)
  agent.py      Agentic loop and system prompt
  tools.py      Tool registry and 6 core tools
  session.py    JSONL session persistence
  context.py    Token estimation and context compaction
  config.py     Config file loading
  models.py     Message, Role, ToolCall data types
evals/
  runner.py     Eval harness with CI support
  fixtures/     Test cases (tiers 1-3)
tests/          Unit tests
scripts/        Deployment packaging
```
