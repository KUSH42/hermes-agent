"""tool_panel subpackage — backward-compatible re-export layer.

All names previously importable from ``hermes_cli.tui.tool_panel`` remain
importable from this package; no callers need to change.
"""
from ._footer import (
    _format_age,
    _TONE_STYLES,
    _IMPLEMENTED_ACTIONS,
    _ArtifactButton,
    _build_collapsed_actions_map,
    _get_collapsed_actions,
    _CollapsedActionStrip,
    _artifact_icon,
    BodyPane,
    FooterPane,
)
from ._completion import _ToolPanelCompletionMixin, _DISCOVERY_SHOWN_CATEGORIES
from ._actions import _ToolPanelActionsMixin
from ._core import ToolPanel
from ._child import ChildPanel

# Also expose DiffAffordance here as it was previously importable via tool_panel
from hermes_cli.tui.diff_affordance import DiffAffordance

__all__ = [
    "ToolPanel",
    "FooterPane",
    "BodyPane",
    "ChildPanel",
    "DiffAffordance",
    "_format_age",
    "_TONE_STYLES",
    "_IMPLEMENTED_ACTIONS",
    "_ArtifactButton",
    "_build_collapsed_actions_map",
    "_get_collapsed_actions",
    "_CollapsedActionStrip",
    "_artifact_icon",
    "_ToolPanelCompletionMixin",
    "_ToolPanelActionsMixin",
    "_DISCOVERY_SHOWN_CATEGORIES",
]
