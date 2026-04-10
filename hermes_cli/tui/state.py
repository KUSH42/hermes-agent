"""Typed overlay state protocol for Hermes TUI.

All overlay state is typed via dataclasses — not raw dicts.
This catches key typos at write time instead of runtime KeyError.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field


@dataclass
class OverlayState:
    """Base for all timed overlay states.

    Attributes:
        deadline: time.monotonic() timestamp for auto-dismiss.
        response_queue: Put answer here to unblock the agent thread.
    """

    deadline: float
    response_queue: queue.Queue = field(repr=False)

    @property
    def remaining(self) -> int:
        """Seconds left before auto-dismiss (clamped to 0)."""
        return max(0, int(self.deadline - time.monotonic()))

    @property
    def expired(self) -> bool:
        """True when the deadline has passed."""
        return time.monotonic() >= self.deadline


@dataclass
class ChoiceOverlayState(OverlayState):
    """State for overlays with selectable choices (clarify, approval).

    Attributes:
        question: The prompt text shown to the user.
        choices: List of choice labels.
        selected: Index of the currently highlighted choice.
    """

    question: str = ""
    choices: list[str] = field(default_factory=list)
    selected: int = 0


@dataclass
class SecretOverlayState(OverlayState):
    """State for overlays with masked text input (sudo, secret).

    Attributes:
        prompt: The prompt text shown to the user.
    """

    prompt: str = ""
