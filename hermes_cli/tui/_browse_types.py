"""Browse-mode shared types — BrowseAnchorType, BrowseAnchor, helpers.

Extracted from app.py so _app_browse.py can import them without a circular
import (app.py → _app_browse.py → app.py).  app.py re-exports everything here.
"""
from __future__ import annotations

import dataclasses
import enum


class BrowseAnchorType(enum.Enum):
    TURN_START = "turn_start"   # UserMessagePanel
    CODE_BLOCK = "code_block"   # StreamingCodeBlock (completed)
    TOOL_BLOCK = "tool_block"   # ToolHeader
    MEDIA      = "media"        # InlineMediaWidget


# Status-bar glyph per anchor type (single-width Unicode)
_BROWSE_TYPE_GLYPH: dict[str, str] = {
    "turn_start": "▸",        # ▸
    "code_block": "‹›",  # ‹›
    "tool_block": "▣",        # ▣
    "media":      "▶",        # ▶
}


def _is_in_reasoning(widget: object) -> bool:
    """Return True if widget is a descendant of a ReasoningPanel."""
    try:
        from hermes_cli.tui.widgets import ReasoningPanel as _RP
        for ancestor in widget.ancestors_with_self:  # type: ignore[union-attr]
            if isinstance(ancestor, _RP):
                return True
    except Exception:
        pass
    return False


@dataclasses.dataclass
class BrowseAnchor:
    anchor_type: BrowseAnchorType
    widget: object  # Widget — typed as object to avoid forward-ref issues
    label: str
    turn_id: int
