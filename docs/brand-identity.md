# Beaconhill Brand Identity

## 1. Core Philosophy: "The Steady Light"

The name Beaconhill represents a small dot of light in the absence of "internet sunshine." The brand is built on three pillars:

- **Autonomy**: Total independence from cloud dependencies.
- **Resilience**: Reliability when connectivity is unavailable or restricted.
- **Focus**: A "Technical Brutalist" aesthetic that removes distraction to prioritize the code.

---

## 2. Brand Persona: "The Technical Doula"

Beaconhill is not a generic bot. It acts as a Technical Doula for the developer:

- **Supportive Presence**: Guides the developer through complex tasks with a calm, grounded voice.
- **Authenticity**: Provides direct, honest feedback about tool executions while maintaining a helpful peer-like attitude.
- **Vigilance**: Remains constantly available in the "darkness" of the offline world.

---

## 3. Visual Identity

High contrast and atmospheric focus, mirroring the "beacon" metaphor.

### Color Palette

| Element | Name | Hex | Purpose |
|---------|------|-----|---------|
| Background | Deep Obsidian | `#0D0D0D` | Represents the offline environment; minimizes eye strain |
| Primary Accent | Beacon Amber | `#FFB300` | The light source; cursors, status indicators, key actions |
| Success State | Safety Green | `#2ECC71` | Successful file writes, passing tests |
| Alert State | Signal Red | `#FF3B30` | Permission denials, execution errors |
| Metadata | Ghost Grey | `#7A7A7A` | Background logs, inactive JSONL data |

### Typography

- **Primary Font**: JetBrains Mono or Fira Code
- **Rationale**: Monospaced fonts prioritize technical legibility and align with the utilitarian nature of a coding tool.

### Terminal Color Mapping (ANSI)

| Brand Color | ANSI Escape | Used For |
|-------------|-------------|----------|
| Beacon Amber | `\033[33m` (yellow) | Startup banner, prompt marker, tool names, thinking pulse |
| Safety Green | `\033[32m` (green) | Success messages, tool completion |
| Signal Red | `\033[31m` (red) | Errors, denials, warnings |
| Ghost Grey | `\033[90m` (bright black) | Session IDs, timestamps, metadata, tool output truncation |

---

## 4. Voice & Tone

Calm, competent, and encouraging. Avoids conversational filler in favor of transparent, auditable communication.

| Scenario | Brand Voice |
|----------|-------------|
| Startup | "Igniting beacon. Scanning local perimeter for project context..." |
| Tool Execution | "Reading src/main.py to identify the function signature." |
| Permission Request | "I've prepared a fix for the bug. May I apply these changes?" |
| Error Handling | "I couldn't reach the local model. Let's check the Ollama status together." |
| Compaction | "Compacting context to keep the conversation focused..." |
| Shutdown | "Beacon extinguished. Session saved." |

---

## 5. UI/UX Signature Features

### The Pulse

A subtle amber dot (`*`) that displays while the agent is reasoning:

```
* thinking...
```

Provides a visual heartbeat so the user knows the agent is working during long model inference.

### Tool Trays

Encapsulated visual blocks for tool calls. Clear boundaries between tool name, arguments, and output:

```
--- read_file: src/main.py ---
1   def main():
2       print("hello")
------------------------------
```

### Status Line

A compact line showing session state:

```
[session: a3c4f2] [model: gemma4:26b] [tokens: 1247/32768]
```

### The Lantern Indicator

A status marker at startup confirming readiness:

```
[*] Beacon lit. Model loaded, air-gapped ready.
```

Changes to indicate degraded state:

```
[!] Beacon flickering. Cannot reach Ollama.
```

### Auditable Flow

Every interaction logged as structured JSONL. Tool calls and results are visually distinct from conversation text.

---

## 6. Metadata Summary

- **Project Spirit**: "A steady light in the digital dark."
- **Core Values**: Privacy, Autonomy, Resilience, Care.
- **Target Environment**: Air-gapped labs, secure facilities, offline travel.
