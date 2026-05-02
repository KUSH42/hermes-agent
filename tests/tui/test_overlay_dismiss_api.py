"""Regression tests for the shared widget-overlay dismiss API."""

from __future__ import annotations

from unittest.mock import MagicMock

def test_widget_overlays_expose_dismiss_alias() -> None:
    from hermes_cli.tui.overlays._legacy import SessionOverlay, ToolPanelHelpOverlay
    from hermes_cli.tui.overlays.config import ConfigOverlay
    from hermes_cli.tui.overlays.interrupt import InterruptOverlay
    from hermes_cli.tui.overlays.reference import ReferenceModal
    from hermes_cli.tui.widgets.overlays import HistorySearchOverlay, KeymapOverlay
    import hermes_cli.tui.drawbraille_overlay  # noqa: F401
    from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel, AnimGalleryOverlay

    classes = [
        ReferenceModal,
        ConfigOverlay,
        SessionOverlay,
        ToolPanelHelpOverlay,
        InterruptOverlay,
        KeymapOverlay,
        HistorySearchOverlay,
        AnimConfigPanel,
        AnimGalleryOverlay,
    ]

    for cls in classes:
        overlay = cls.__new__(cls)
        overlay.action_dismiss = MagicMock()  # type: ignore[method-assign]

        overlay.dismiss()

        overlay.action_dismiss.assert_called_once_with()
