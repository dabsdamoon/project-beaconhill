"""Shared helper: resolve a run directory (either explicit or the latest)."""
from __future__ import annotations

from pathlib import Path


def latest_run_dir(results_root: Path) -> Path | None:
    """Return the most recent versioned run folder, or None if none exist."""
    if not results_root.exists():
        return None
    candidates = [
        d for d in results_root.iterdir()
        if d.is_dir() and (d / "run_meta.json").exists()
    ]
    if not candidates:
        return None
    # Run IDs sort chronologically by their timestamp prefix.
    return sorted(candidates, key=lambda d: d.name)[-1]


def resolve_run_dir(results_root: Path, override: str | None) -> Path:
    if override:
        p = Path(override)
        if not p.exists():
            # Try interpreting override as a run-id inside results_root.
            fallback = results_root / override
            if fallback.exists():
                p = fallback
            else:
                raise SystemExit(f"run-dir not found: {override}")
        return p
    latest = latest_run_dir(results_root)
    if latest is None:
        raise SystemExit(
            f"no run folders with run_meta.json under {results_root}. "
            f"Run ab_test/run.sh first."
        )
    return latest
