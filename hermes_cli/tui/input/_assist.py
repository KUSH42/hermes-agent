"""Persistent ASSIST-state vocabulary for HermesInput."""
from __future__ import annotations

from enum import Enum, auto

SKILL_PICKER_TRIGGER_PREFIX = "prefix"


class AssistKind(Enum):
    """Persistent composer assist states.

    Flash hints and error flashes are transient channels, not persistent assist
    states, so they are intentionally excluded here.
    """

    NONE = auto()
    GHOST = auto()
    OVERLAY = auto()
    PICKER = auto()
