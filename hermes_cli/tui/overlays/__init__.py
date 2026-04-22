"""Overlay widgets package.

R3 consolidation migrates legacy widgets into:
- config.py → ConfigOverlay (replaces 5 pickers)
- interrupt.py → InterruptOverlay (replaces 7 interrupts)

Legacy symbols are re-exported from ._legacy during the alias window
(Phases A–C). See 2026-04-22-tui-v2-R3-overlay-consolidation-spec.md §5.
"""

from hermes_cli.tui.overlays._legacy import (
    CommandsOverlay,
    FIXTURE_CODE,
    HelpOverlay,
    ModelPickerOverlay,
    PickerOverlay,
    ReasoningPickerOverlay,
    SessionOverlay,
    SkinPickerOverlay,
    TabbedSkinOverlay,
    ToolPanelHelpOverlay,
    UsageOverlay,
    VerbosePickerOverlay,
    WorkspaceOverlay,
    YoloConfirmOverlay,
    _SessionResumedBanner,
    _SessionRow,
    _dismiss_overlay_and_focus_input,
)

__all__ = [
    "CommandsOverlay",
    "FIXTURE_CODE",
    "HelpOverlay",
    "ModelPickerOverlay",
    "PickerOverlay",
    "ReasoningPickerOverlay",
    "SessionOverlay",
    "SkinPickerOverlay",
    "TabbedSkinOverlay",
    "ToolPanelHelpOverlay",
    "UsageOverlay",
    "VerbosePickerOverlay",
    "WorkspaceOverlay",
    "YoloConfirmOverlay",
    "_SessionResumedBanner",
    "_SessionRow",
    "_dismiss_overlay_and_focus_input",
]
