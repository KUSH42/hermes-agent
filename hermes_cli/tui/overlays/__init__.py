"""Overlay widgets package.

R3 consolidation migrates legacy widgets into:
- config.py → ConfigOverlay (replaces 5 pickers)
- interrupt.py → InterruptOverlay (replaces 7 interrupts, Phase B)

Aliased picker class names (ModelPickerOverlay, TabbedSkinOverlay, etc.)
are re-exported from ._aliases and resolve via CSS-type registration +
_AliasMeta. See 2026-04-22-tui-v2-R3-overlay-consolidation-spec.md §5.

Legacy-only symbols (HelpOverlay, UsageOverlay, CommandsOverlay,
WorkspaceOverlay, SessionOverlay, ToolPanelHelpOverlay, PickerOverlay
base, session banner/row, config helpers, FIXTURE_CODE) are still
re-exported from ._legacy during Phases A–C.
"""

from hermes_cli.tui.overlays._legacy import (
    CommandsOverlay,
    FIXTURE_CODE,
    HelpOverlay,
    PickerOverlay,
    SessionOverlay,
    ToolPanelHelpOverlay,
    UsageOverlay,
    WorkspaceOverlay,
    _cfg_get_hermes_home,
    _cfg_read_raw_config,
    _cfg_save_config,
    _cfg_set_nested,
    _SessionResumedBanner,
    _SessionRow,
    _dismiss_overlay_and_focus_input,
)

# ConfigOverlay first — it registers aliases into its _css_type_names on import.
from hermes_cli.tui.overlays.config import ConfigOverlay  # noqa: E402

# InterruptOverlay — registers interrupt-kind aliases into its _css_type_names.
from hermes_cli.tui.overlays.interrupt import (  # noqa: E402
    InputSpec,
    InterruptChoice,
    InterruptKind,
    InterruptOverlay,
    InterruptPayload,
)

# Aliases — these take precedence over the same-named classes in _legacy.
# Importers like `from hermes_cli.tui.overlays import ModelPickerOverlay`
# now get the alias (which resolves to ConfigOverlay at runtime).
from hermes_cli.tui.overlays._aliases import (  # noqa: E402
    ApprovalWidget,
    ClarifyWidget,
    MergeConfirmOverlay,
    ModelPickerOverlay,
    NewSessionOverlay,
    ReasoningPickerOverlay,
    SecretWidget,
    SkinPickerOverlay,
    SudoWidget,
    TabbedSkinOverlay,
    UndoConfirmOverlay,
    VerbosePickerOverlay,
    YoloConfirmOverlay,
)

__all__ = [
    "ApprovalWidget",
    "ClarifyWidget",
    "CommandsOverlay",
    "ConfigOverlay",
    "FIXTURE_CODE",
    "HelpOverlay",
    "InputSpec",
    "InterruptChoice",
    "InterruptKind",
    "InterruptOverlay",
    "InterruptPayload",
    "MergeConfirmOverlay",
    "ModelPickerOverlay",
    "NewSessionOverlay",
    "PickerOverlay",
    "ReasoningPickerOverlay",
    "SecretWidget",
    "SessionOverlay",
    "SkinPickerOverlay",
    "SudoWidget",
    "TabbedSkinOverlay",
    "ToolPanelHelpOverlay",
    "UndoConfirmOverlay",
    "UsageOverlay",
    "VerbosePickerOverlay",
    "WorkspaceOverlay",
    "YoloConfirmOverlay",
    "_SessionResumedBanner",
    "_SessionRow",
    "_dismiss_overlay_and_focus_input",
]
