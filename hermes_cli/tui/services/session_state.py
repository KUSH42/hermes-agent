"""Persistent TUI session state — user preferences that survive app restarts."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

_log = logging.getLogger(__name__)

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_STATE_FILE = _HERMES_HOME / ".tui_session_state.json"


@dataclass
class DiscoverabilityState:
    """Tracks first-use milestones for discoverability hints."""
    tools_filter_first_use: bool = False


def load_discoverability_state() -> DiscoverabilityState:
    """Load DiscoverabilityState from disk; returns defaults on missing or corrupt file."""
    try:
        if _STATE_FILE.exists():
            raw = json.loads(_STATE_FILE.read_text())
            disc = raw.get("discoverability", {})
            return DiscoverabilityState(
                tools_filter_first_use=bool(disc.get("tools_filter_first_use", False)),
            )
    except Exception:
        _log.debug("load_discoverability_state: could not read %s", _STATE_FILE, exc_info=True)
    return DiscoverabilityState()


def save_discoverability_state(state: DiscoverabilityState) -> None:
    """Write DiscoverabilityState to disk; silently swallows I/O errors."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _STATE_FILE.exists():
            try:
                existing = json.loads(_STATE_FILE.read_text())
            except Exception:
                # State file is corrupt or unreadable; start with empty dict to avoid
                # propagating the corruption. The write below will overwrite it.
                pass
        existing["discoverability"] = asdict(state)
        _STATE_FILE.write_text(json.dumps(existing, indent=2))
    except Exception:
        _log.debug("save_discoverability_state: could not write %s", _STATE_FILE, exc_info=True)
