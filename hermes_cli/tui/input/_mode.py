"""InputMode — display state enum for HermesInput chevron + affordances."""
from __future__ import annotations
from enum import Enum


class InputMode(Enum):
    NORMAL     = "normal"
    BASH       = "bash"
    REV_SEARCH = "rev_search"
    COMPLETION = "completion"
    LOCKED     = "locked"
