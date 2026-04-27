#!/usr/bin/env python3
"""Layer-1 deterministic rubric — Playwright-driven 18-item checklist.

Loads each cell's timer.html in headless Chromium and exercises it against
the spec rubric pre-registered in
docs/design/gstack-vs-beaconhill-experiment.md §4.

Per-run output:    {run_dir}/{cell}/run-{i}/score_layer1.json
Run-dir output:    {run_dir}/layer1_scores.json   (aggregate per cell)

Setup (once, in the project venv):
    pip install playwright==1.58.0
    playwright install chromium

Usage:
    python3 ab_test/score_layer1.py --run-dir <run_dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import Page, sync_playwright
except ImportError:
    sys.stderr.write(
        "playwright not installed. From the project venv run:\n"
        "    pip install playwright==1.58.0\n"
        "    playwright install chromium\n"
    )
    raise

AB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AB_DIR))
from _run_dir import resolve_run_dir  # noqa: E402

RESULTS_ROOT = AB_DIR / "results"

CHECK_NAMES = [
    "file_exists",
    "no_js_errors",
    "focus_25_00_initial",
    "break_button_clickable",
    "break_5_00",
    "start_starts_countdown",
    "pause_preserves",
    "reset_to_full_duration",
    "mm_ss_format",
    "space_toggles_start_pause",
    "audio_alert_capable",
    "bg_color_0d1117",
    "text_color_e6edf3",
    "accent_color_58a6ff",
    "monospace_countdown",
    "border_radius_8px",
    "centered_layout",
    "mobile_usable",
]
MAX_SCORE = len(CHECK_NAMES)

TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


@dataclass
class Score:
    checks: dict[str, bool] = field(default_factory=dict)
    raw_score: int = 0
    pct: float = 0.0
    notes: dict[str, str] = field(default_factory=dict)
    file_path: str = ""


def parse_time(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    m = TIME_RE.search(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def to_seconds(t: tuple[int, int]) -> int:
    return t[0] * 60 + t[1]


def normalize_color(c: str) -> str:
    c = (c or "").strip().lower()
    if c.startswith("#"):
        if len(c) == 4:
            return "#" + "".join(ch * 2 for ch in c[1:])
        return c
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", c)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return c


def find_button_by_text(page: Page, pattern: str):
    """Return locator for a button-like element whose visible text matches `pattern`.

    Tries button, [role=button], then any element with the text. Returns None
    if no candidate exists.
    """
    selectors = [
        f"button:has-text('{pattern}')",
        f"[role='button']:has-text('{pattern}')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except PWError:
            continue
    return None


def body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except PWError:
        return ""


def safe_click(loc, timeout: int = 2000) -> bool:
    if loc is None:
        return False
    try:
        loc.click(timeout=timeout)
        return True
    except PWError:
        return False


# JS helpers run inside the page.
JS_FIND_COUNTDOWN_FONT = r"""
() => {
    const re = /\b\d{1,2}:\d{2}\b/;
    const monoRe = /mono|menlo|consolas|courier/i;
    let bestSize = 0;
    let bestFamily = null;
    for (const el of document.querySelectorAll('*')) {
        if (el.children.length === 0 && re.test(el.textContent || '')) {
            const cs = getComputedStyle(el);
            const size = parseFloat(cs.fontSize) || 0;
            if (size > bestSize) {
                bestSize = size;
                bestFamily = cs.fontFamily;
            }
        }
    }
    return bestFamily ? monoRe.test(bestFamily) : false;
}
"""

JS_HAS_ACCENT_COLOR = r"""
() => {
    const target = '#58a6ff';
    const norm = c => {
        c = (c || '').toLowerCase().trim();
        if (c.startsWith('#') && c.length === 4) {
            return '#' + [...c.slice(1)].map(x => x + x).join('');
        }
        const m = c.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) {
            const hex = n => parseInt(n).toString(16).padStart(2, '0');
            return '#' + hex(m[1]) + hex(m[2]) + hex(m[3]);
        }
        return c;
    };
    for (const el of document.querySelectorAll('*')) {
        const cs = getComputedStyle(el);
        if (norm(cs.color) === target ||
            norm(cs.backgroundColor) === target ||
            norm(cs.borderColor) === target) {
            return true;
        }
    }
    return false;
}
"""

JS_BORDER_RADIUS_OK = r"""
() => {
    const btns = document.querySelectorAll('button, [role="button"]');
    if (!btns.length) return false;
    let pass = 0;
    for (const b of btns) {
        const r = parseFloat(getComputedStyle(b).borderRadius) || 0;
        if (r >= 8) pass++;
    }
    return pass / btns.length >= 0.8;
}
"""

JS_CENTERED = r"""
() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let bestArea = 0;
    let best = null;
    for (const el of document.body.children) {
        const r = el.getBoundingClientRect();
        const a = r.width * r.height;
        if (a > bestArea) { bestArea = a; best = r; }
    }
    if (!best) return false;
    const cx = best.left + best.width / 2;
    const cy = best.top + best.height / 2;
    return Math.abs(cx - vw / 2) < vw * 0.18 &&
           Math.abs(cy - vh / 2) < vh * 0.30;
}
"""

JS_MOBILE_USABLE = r"""
() => {
    const overflow = document.documentElement.scrollWidth > window.innerWidth + 5;
    const re = /\b\d{1,2}:\d{2}\b/;
    const text = document.body.innerText || '';
    return !overflow && re.test(text);
}
"""


def evaluate_one(html_path: Path) -> Score:
    score = Score(file_path=str(html_path))
    if not html_path.exists():
        score.checks["file_exists"] = False
        score.notes["file_exists"] = "missing"
        for c in CHECK_NAMES[1:]:
            score.checks[c] = False
        return score
    score.checks["file_exists"] = True

    js_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.on("pageerror", lambda e: js_errors.append(str(e)))
            page.goto(html_path.absolute().as_uri(), timeout=10000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(0.5)

            initial = body_text(page)
            score.checks["mm_ss_format"] = bool(TIME_RE.search(initial))
            t_initial = parse_time(initial)
            score.checks["focus_25_00_initial"] = (
                t_initial == (25, 0) or "25:00" in initial
            )
            score.notes["focus_25_00_initial"] = initial[:120]

            break_btn = find_button_by_text(page, "break")
            score.checks["break_button_clickable"] = False
            score.checks["break_5_00"] = False
            if safe_click(break_btn):
                score.checks["break_button_clickable"] = True
                time.sleep(0.5)
                after = body_text(page)
                t_break = parse_time(after)
                score.checks["break_5_00"] = (
                    t_break == (5, 0) or "5:00" in after or "05:00" in after
                )
                score.notes["break_5_00"] = after[:120]
                # Toggle back to focus so subsequent timer tests start at 25:00.
                focus_btn = find_button_by_text(page, "focus")
                if focus_btn is None:
                    # Some implementations re-use the same button to toggle.
                    focus_btn = break_btn
                safe_click(focus_btn, timeout=1000)
                time.sleep(0.3)

            start_btn = find_button_by_text(page, "start")
            pause_btn = find_button_by_text(page, "pause")
            reset_btn = find_button_by_text(page, "reset")

            score.checks["start_starts_countdown"] = False
            if start_btn is not None:
                t_before = parse_time(body_text(page))
                if safe_click(start_btn):
                    time.sleep(2.2)
                    t_after = parse_time(body_text(page))
                    if t_before and t_after:
                        score.checks["start_starts_countdown"] = (
                            to_seconds(t_after) < to_seconds(t_before)
                        )
                        score.notes["start_starts_countdown"] = (
                            f"{t_before} -> {t_after}"
                        )

            score.checks["pause_preserves"] = False
            if pause_btn is not None and safe_click(pause_btn):
                t1 = parse_time(body_text(page))
                time.sleep(1.5)
                t2 = parse_time(body_text(page))
                score.checks["pause_preserves"] = bool(t1 and t2 and t1 == t2)
                score.notes["pause_preserves"] = f"{t1} == {t2}"

            score.checks["reset_to_full_duration"] = False
            if reset_btn is not None and safe_click(reset_btn):
                time.sleep(0.4)
                t_reset = parse_time(body_text(page))
                score.checks["reset_to_full_duration"] = t_reset in {(25, 0), (5, 0)}
                score.notes["reset_to_full_duration"] = str(t_reset)

            # Space-key toggle: ensure paused/reset state, focus body, press Space.
            score.checks["space_toggles_start_pause"] = False
            try:
                page.locator("body").click(position={"x": 5, "y": 5}, timeout=1000)
            except PWError:
                pass
            t_ks_before = parse_time(body_text(page))
            try:
                page.keyboard.press("Space")
                time.sleep(2.2)
                t_ks_after = parse_time(body_text(page))
                if t_ks_before and t_ks_after:
                    score.checks["space_toggles_start_pause"] = (
                        to_seconds(t_ks_after) < to_seconds(t_ks_before)
                    )
                    score.notes["space_toggles_start_pause"] = (
                        f"{t_ks_before} -> {t_ks_after}"
                    )
            except PWError as e:
                score.notes["space_toggles_start_pause"] = str(e)[:120]

            # audio: cheap source-level check (don't wait 25 minutes for the alarm).
            html_source = html_path.read_text(errors="replace")
            score.checks["audio_alert_capable"] = bool(
                re.search(
                    r"<audio|AudioContext|webkitAudioContext|playbackRate|oscillator|new\s+Audio\b",
                    html_source,
                    re.I,
                )
            )

            bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            text_color = page.evaluate("getComputedStyle(document.body).color")
            score.checks["bg_color_0d1117"] = normalize_color(bg) == "#0d1117"
            score.checks["text_color_e6edf3"] = normalize_color(text_color) == "#e6edf3"
            score.notes["bg_color_0d1117"] = f"{bg} -> {normalize_color(bg)}"
            score.notes["text_color_e6edf3"] = (
                f"{text_color} -> {normalize_color(text_color)}"
            )

            score.checks["accent_color_58a6ff"] = bool(page.evaluate(JS_HAS_ACCENT_COLOR))
            score.checks["monospace_countdown"] = bool(page.evaluate(JS_FIND_COUNTDOWN_FONT))
            score.checks["border_radius_8px"] = bool(page.evaluate(JS_BORDER_RADIUS_OK))
            score.checks["centered_layout"] = bool(page.evaluate(JS_CENTERED))

            page.set_viewport_size({"width": 375, "height": 667})
            time.sleep(0.3)
            score.checks["mobile_usable"] = bool(page.evaluate(JS_MOBILE_USABLE))

            score.checks["no_js_errors"] = len(js_errors) == 0
            if js_errors:
                score.notes["no_js_errors"] = " | ".join(js_errors[:3])
        finally:
            browser.close()

    score.raw_score = sum(1 for v in score.checks.values() if v)
    score.pct = round(score.raw_score / MAX_SCORE, 3)
    return score


def cells_from_meta(run_dir: Path) -> list[str]:
    meta_path = run_dir / "run_meta.json"
    if not meta_path.exists():
        return sorted(
            d.name for d in run_dir.iterdir()
            if d.is_dir() and any(c.name.startswith("run-") for c in d.iterdir() if c.is_dir())
        )
    meta = json.loads(meta_path.read_text())
    return sorted(meta.get("config", {}).get("cells", {}).keys())


def aggregate(run_dir: Path) -> dict:
    out: dict = {"run_dir": str(run_dir), "max_score": MAX_SCORE, "cells": {}}
    for cell in cells_from_meta(run_dir):
        cell_dir = run_dir / cell
        if not cell_dir.is_dir():
            continue
        runs: list[dict] = []
        for rd in sorted(cell_dir.iterdir()):
            if not rd.is_dir() or not rd.name.startswith("run-"):
                continue
            score = evaluate_one(rd / "timer.html")
            (rd / "score_layer1.json").write_text(
                json.dumps(asdict(score), indent=2) + "\n"
            )
            runs.append({
                "run": rd.name,
                "raw_score": score.raw_score,
                "pct": score.pct,
                "checks": score.checks,
            })
        if runs:
            scores = [r["raw_score"] for r in runs]
            scores_sorted = sorted(scores)
            out["cells"][cell] = {
                "runs": runs,
                "n": len(scores),
                "mean": round(sum(scores) / len(scores), 2),
                "median": scores_sorted[len(scores_sorted) // 2],
                "min": min(scores),
                "max": max(scores),
            }
    (run_dir / "layer1_scores.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None, help="Specific run folder; default: latest")
    args = ap.parse_args()
    run_dir = resolve_run_dir(RESULTS_ROOT, args.run_dir)
    print(json.dumps(aggregate(run_dir), indent=2))


if __name__ == "__main__":
    main()
