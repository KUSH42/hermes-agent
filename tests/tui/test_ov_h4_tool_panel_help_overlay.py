"""Tests for OV-H4: ToolPanelHelpOverlay modal arbiter integration."""
from __future__ import annotations

from unittest.mock import MagicMock

from textual.binding import Binding


def _make_fake_app():
    app = MagicMock()
    app.push_modal = MagicMock()
    app.pop_modal = MagicMock()
    mock_tool_panel = MagicMock()
    mock_tool_panel.is_mounted = True
    app.focused = mock_tool_panel
    return app, mock_tool_panel


def _make_overlay(app=None):
    """Return a ToolPanelHelpOverlay subclass instance wired to a stub app."""
    from hermes_cli.tui.overlays._legacy import ToolPanelHelpOverlay

    app, mock_tool_panel = _make_fake_app() if app is None else app

    _bt_store: dict = {"v": ""}

    class _Isolated(ToolPanelHelpOverlay):
        @property  # type: ignore[override]
        def border_title(self):
            return _bt_store["v"]

        @border_title.setter
        def border_title(self, value: str) -> None:
            _bt_store["v"] = value

    _Isolated.app = property(lambda self: app)  # type: ignore[method-assign]

    overlay = _Isolated.__new__(_Isolated)
    overlay._focus_caller = None
    overlay._classes: set[str] = set()

    def _has_class(*cls_names):
        return all(c in overlay._classes for c in cls_names)

    def _add_class(*cls_names):
        overlay._classes.update(cls_names)

    def _remove_class(*cls_names):
        overlay._classes -= set(cls_names)

    overlay.has_class = _has_class
    overlay.add_class = _add_class
    overlay.remove_class = _remove_class

    def _capture():
        overlay._focus_caller = app.focused

    overlay._capture_focus_caller = _capture

    def _restore():
        return overlay._focus_caller

    overlay._restore_focus_to = _restore
    overlay.focus = MagicMock()

    return overlay, app, mock_tool_panel


class TestShowOverlayCapturesFocusAndPushesModal:
    def test_show_overlay_captures_focus_and_pushes_modal(self):
        overlay, mock_app, mock_tool_panel = _make_overlay()

        overlay.show_overlay()

        mock_app.push_modal.assert_called_once_with(overlay)
        assert "--visible" in overlay._classes
        assert "--modal" in overlay._classes
        assert overlay._focus_caller is mock_tool_panel


class TestDismissOverlayPopsModalAndRestoresFocus:
    def test_dismiss_overlay_pops_modal_and_restores_focus(self):
        overlay, mock_app, mock_tool_panel = _make_overlay()

        overlay.show_overlay()
        overlay.dismiss_overlay()

        mock_app.pop_modal.assert_called_once_with(overlay)
        mock_tool_panel.focus.assert_called()
        assert "--visible" not in overlay._classes
        assert "--modal" not in overlay._classes


class TestDoubleShowOverlayDoesNotDoublePush:
    def test_double_show_overlay_does_not_double_push(self):
        overlay, mock_app, mock_tool_panel = _make_overlay()

        overlay.show_overlay()
        overlay.show_overlay()  # guard fires — already open

        mock_app.push_modal.assert_called_once_with(overlay)


class TestActionDismissDelegatesToDismissOverlay:
    def test_action_dismiss_delegates_to_dismiss_overlay(self):
        overlay, mock_app, mock_tool_panel = _make_overlay()

        mock_dismiss = MagicMock()
        overlay.dismiss_overlay = mock_dismiss

        overlay.action_dismiss()

        mock_dismiss.assert_called_once()


class TestBindingsContainEscapeAndQuestionMark:
    def test_bindings_contain_escape_and_question_mark(self):
        from hermes_cli.tui.overlays._legacy import ToolPanelHelpOverlay

        bindings = ToolPanelHelpOverlay.BINDINGS
        keys = {b.key: b.action for b in bindings if isinstance(b, Binding)}

        assert "escape" in keys, "escape binding missing"
        assert keys["escape"] == "dismiss", (
            f"escape action should be 'dismiss', got {keys['escape']!r}"
        )

        assert "question_mark" in keys, "question_mark binding missing"
        assert keys["question_mark"] == "dismiss", (
            f"question_mark action should be 'dismiss', got {keys['question_mark']!r}"
        )

        assert "on_key" not in ToolPanelHelpOverlay.__dict__, (
            "on_key must be deleted from ToolPanelHelpOverlay — use BINDINGS instead"
        )
