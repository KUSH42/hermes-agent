"""Shared constants, helpers, and tiny utilities used by HermesApp and its mixins."""
from __future__ import annotations

import os as _os_mod


# ── Output queue threading ────────────────────────────────────────────────────

# Always use call_soon_threadsafe for cross-thread queue access.
# asyncio.Queue is not thread-safe: put_nowait from a non-event-loop thread
# won't wake the selector, so the consumer only discovers items on the next
# timer tick rather than immediately.
_CPYTHON_FAST_PATH = False


# ── Helix spinner constants ───────────────────────────────────────────────────

_HELIX_DELAY_S = 3.0
_HELIX_FRAME_COUNT = 24
_HELIX_MIN_CELLS = 6


# ── Diagnostics ──────────────────────────────────────────────────────────────

def _log_lag(msg: str) -> None:
    """Append a timestamped lag diagnostic to $HERMES_HOME/logs/lag.log."""
    import datetime as _dt
    from hermes_constants import get_hermes_home
    ts = _dt.datetime.now().strftime("%H:%M:%S.%f")[:12]
    try:
        log_dir = get_hermes_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "lag.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── Animation guards ─────────────────────────────────────────────────────────

def _animations_enabled_check() -> bool:
    """Return False if the user has opted out of animations via env vars."""
    for key in ("NO_ANIMATIONS", "REDUCE_MOTION"):
        val = _os_mod.environ.get(key, "").strip().lower()
        if val in ("1", "true", "yes"):
            return False
    return True


def _run_effect_sync(effect_name: str, text: str, params: dict | None = None) -> bool:
    """Run a TTE animation synchronously.

    Must be called after the Textual TUI has been suspended (i.e. inside
    ``App.suspend()``).  Runs in a thread-pool executor so it does not
    block the event loop.
    """
    from hermes_cli.tui.tte_runner import run_effect
    print()
    rendered = run_effect(effect_name, text, params=params)
    print()
    return rendered
