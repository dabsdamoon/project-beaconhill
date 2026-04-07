# UI/UX Enhancement Plan

Applies the brand identity from `docs/reference/brand-identity.md` to the Beaconhill CLI.

## Current State

The CLI uses plain `print()` and `input()`. No colors, no status indicators, no visual
hierarchy between tool calls, agent responses, and metadata.

## Approach

Use ANSI escape codes for color. No external dependency required -- Python's built-in
terminal capabilities are sufficient. Optionally use `rich` (already listed as an
optional dependency) for advanced formatting if the user installs it, but the core
experience must work without it.

---

## Phase A -- Color System (`src/beaconhill/ui.py`)

Create a `ui.py` module that centralizes all terminal output formatting.

### A1. ANSI Color Helpers

```python
AMBER = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
GREY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

def amber(text: str) -> str: ...
def green(text: str) -> str: ...
def red(text: str) -> str: ...
def grey(text: str) -> str: ...
```

Detect `NO_COLOR` env var and `sys.stdout.isatty()` to disable colors when piping
or when the user opts out.

### A2. Branded Output Functions

Replace raw `print()` calls throughout `cli.py` with semantic functions:

| Function | What it prints | Color |
|----------|---------------|-------|
| `ui.banner(model, session_id)` | Startup message | Amber header, grey metadata |
| `ui.tool_start(name, args)` | Tool execution start | Amber tool name, grey args |
| `ui.tool_result(output, is_error)` | Tool output | Green success, red error |
| `ui.permission_prompt(name, args)` | Permission request | Amber name, default text |
| `ui.assistant(text)` | Agent's text response | Default (white/terminal default) |
| `ui.info(text)` | Status messages | Grey |
| `ui.error(text)` | Error messages | Red |
| `ui.warning(text)` | Warnings | Amber |
| `ui.goodbye()` | Exit message | Grey |

---

## Phase B -- Thinking Pulse

### B1. Pulse During Inference

While waiting for the LLM response, show a pulsing indicator:

```
* thinking...
```

Implementation: run the pulse in a background thread. The thread prints and overwrites
a single line (`\r`). When the LLM response arrives, stop the thread and clear the line.

```python
class ThinkingPulse:
    def start(self) -> None: ...
    def stop(self) -> None: ...
```

Wire into the agentic loop: `pulse.start()` before `client.chat()`, `pulse.stop()` after.

### B2. Pulse Variants

| State | Display |
|-------|---------|
| Thinking | `* thinking...` (amber) |
| Tool executing | `* running bash...` (amber, shows tool name) |
| Compacting | `* compacting context...` (grey) |

---

## Phase C -- Tool Trays

### C1. Visual Encapsulation

Wrap tool calls and their output in bordered blocks:

```
--- read_file: src/main.py -----------
1   def main():
2       print("hello")
--------------------------------------
```

- Tool name and key arg in amber
- Border lines in grey
- Output in default color
- Error output in red
- Truncation notice in grey: `[truncated at 10000 chars]`

### C2. Permission Prompt Redesign

```
--- bash (requires approval) ---------
  command: rm -rf /tmp/test
--
  Allow? [y/N] _
--------------------------------------
```

Amber header, grey border, clear argument display.

---

## Phase D -- Status Line

### D1. Startup Banner

Replace the current plain text with a branded banner:

```
  Beaconhill v0.1.0
  [*] Beacon lit. Model loaded.
  model: gemma4:26b | session: a3c4f2
```

- First line in bold amber
- Lantern indicator `[*]` in green (ready) or red (error)
- Metadata line in grey

### D2. Token Counter (Optional)

Show token usage after each turn:

```
[tokens: 1247/32768]
```

In grey, after the agent's response. Uses `client.last_prompt_tokens` for actual count.

---

## Phase E -- Voice Integration

### E1. Branded Messages

Update hardcoded strings throughout the codebase to match the brand voice:

| Current | Branded |
|---------|---------|
| `"Type /quit to exit."` | `"Type /quit to extinguish the beacon."` |
| `"Goodbye."` | `"Beacon extinguished. Session saved."` |
| `"[compacting context...]"` | `"Compacting context to stay focused..."` |
| `"[error] Cannot connect..."` | `"Beacon flickering. Cannot reach Ollama."` |
| `"[warning] Max iterations..."` | `"Stepping back. Maximum iteration depth reached."` |

### E2. System Prompt Update

Align the system prompt persona with the "Technical Doula" voice:
- Calm, supportive tone
- First person when referring to actions ("I'm reading the file..." not "Reading file...")
- Acknowledge errors with empathy ("Let's check the Ollama status together.")

---

## Implementation Order

1. **Phase A** (color system) -- foundation, everything else depends on it
2. **Phase D1** (startup banner) -- immediate visual impact
3. **Phase C** (tool trays) -- most frequent visual element during use
4. **Phase B** (thinking pulse) -- quality of life during inference waits
5. **Phase E** (voice) -- polish pass
6. **Phase D2** (token counter) -- nice-to-have

## Files Modified

| File | Changes |
|------|---------|
| `src/beaconhill/ui.py` | **New** -- color helpers, branded output functions, ThinkingPulse |
| `src/beaconhill/cli.py` | Replace `print()` calls with `ui.*` functions |
| `src/beaconhill/agent.py` | Update system prompt for brand voice |

## Constraints

- No new required dependencies. ANSI colors only.
- Must degrade gracefully: no colors when `NO_COLOR` is set or stdout is not a TTY.
- `rich` is optional enhancement, not required.
- All output changes are cosmetic -- no behavioral changes to the agentic loop.
