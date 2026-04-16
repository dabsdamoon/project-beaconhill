# Task: Pomodoro Timer Webpage

Create a single-file webpage named `timer.html` in the current working directory implementing a Pomodoro timer. Everything (CSS and JS) must be inline in `<style>` and `<script>` blocks. No build step. It must work when opened directly in a browser.

## Features (required)

1. Two modes toggled by a button: **Focus (25:00)** and **Break (5:00)**. The active mode is visually distinct.
2. **Start**, **Pause**, and **Reset** buttons. Pause preserves elapsed time; Reset returns to the current mode's full duration.
3. A large countdown display in `MM:SS` format that updates at least once per second.
4. When the timer reaches 00:00, play an audible alert (Web Audio API or an inline `<audio>` element with a data-URI sound).
5. Keyboard shortcut: pressing **Space** toggles start/pause.

## Aesthetic (required)

- Dark theme with these colors:
  - Background: `#0d1117`
  - Primary text: `#e6edf3`
  - Accent (buttons, active mode, highlights): `#58a6ff`
- The countdown numerals use a monospace font stack, e.g. `ui-monospace, SF Mono, Menlo, monospace`.
- Buttons have `border-radius` of at least 8px and no default browser styling.
- Hover or active states use a CSS `transition`.
- Layout is centered both vertically and horizontally on the viewport and remains usable at mobile widths.

## Deliverable

Only the file `timer.html` in the current working directory. Do not create any other files.
