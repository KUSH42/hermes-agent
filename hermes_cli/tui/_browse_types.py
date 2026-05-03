"""Browse-mode shared types — BrowseAnchorType, BrowseAnchor, helpers.

Extracted from app.py so _app_browse.py can import them without a circular
import (app.py → _app_browse.py → app.py).  app.py re-exports everything here.
"""
from __future__ import annotations

import dataclasses
import enum
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widget import Widget

logger = logging.getLogger(__name__)


class BrowseAnchorType(enum.Enum):
    TURN_START   = "turn_start"    # UserMessagePanel
    CODE_BLOCK   = "code_block"    # StreamingCodeBlock (completed)
    TOOL_BLOCK   = "tool_block"    # ToolHeader
    MEDIA        = "media"         # InlineMediaWidget
    SUBAGENT_ROOT = "subagent_root"  # SubAgentPanel (depth 0)


# Status-bar glyph per anchor type (single-width Unicode)
_BROWSE_TYPE_GLYPH: dict[str, str] = {
    "turn_start":    "▸",        # ▸
    "code_block":    "‹›",       # ‹›
    "tool_block":    "▣",        # ▣
    "media":         "▶",        # ▶
    "subagent_root": "🤖",       # robot face
}

# Single-cell variants for the 1-column minimap. Width-2 glyphs collapsed to
# their lead char; emoji collapsed to a single-cell BMP fallback.
_BROWSE_TYPE_GLYPH_NARROW: dict[str, str] = {
    "turn_start":    "▸",
    "code_block":    "‹",
    "tool_block":    "▣",
    "media":         "▶",
    "subagent_root": "◆",   # narrow stand-in for 🤖
}


def _is_in_reasoning(widget: object) -> bool:
    """Return True if widget is a descendant of a ReasoningPanel."""
    try:
        from hermes_cli.tui.widgets import ReasoningPanel as _RP
        for ancestor in widget.ancestors_with_self:  # type: ignore[union-attr]
            if isinstance(ancestor, _RP):
                return True
    except Exception:
        logger.debug("_is_in_reasoning: ancestry check failed", exc_info=True)
    return False


@dataclasses.dataclass
class BrowseAnchor:
    anchor_type: BrowseAnchorType
    widget: "Widget"
    label: str
    turn_id: int
