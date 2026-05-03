"""Tests for CD-H1 (SLASH_SUBCOMMAND dispatch) and CD-H4 (picker desync fix).

Pure-Python stub tests — no Textual App runtime required.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
from hermes_cli.tui.input._assist import AssistKind, SKILL_PICKER_TRIGGER_PREFIX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_input(value: str = "", cursor_position: int = 0, **kwargs):
    """Return a minimal _FakeInput-like SimpleNamespace with common stubs."""
    obj = types.SimpleNamespace(
        _suppress_autocomplete_once=False,
        _current_trigger=None,
        _raw_candidates=[],
        _slash_commands=[],
        _slash_subcommands={},
        assist=AssistKind.NONE,
        suggestion="",
        value=value,
        cursor_position=cursor_position,
        **kwargs,
    )
    # Default no-op stubs so tests can override selectively.
    obj.app = types.SimpleNamespace(
        choice_overlay_active=False,
        _open_skill_picker=MagicMock(return_value=True),
        status_ghost_suggestion=False,
    )
    obj._show_slash_completions = MagicMock()
    obj._show_path_completions = MagicMock()
    obj._completion_overlay_visible = MagicMock(return_value=False)
    obj._resolve_assist = MagicMock()
    obj._set_overlay_mode = MagicMock()
    obj._push_to_list = MagicMock()
    return obj


# ---------------------------------------------------------------------------
# TestCDH1SubcommandDispatch
# ---------------------------------------------------------------------------

class TestCDH1SubcommandDispatch:
    """CD-H1: SLASH_SUBCOMMAND trigger must route to _show_subcommand_completions."""

    def test_subcommand_dispatch_routes_to_show_subcommand_completions(self):
        """'/reasoning ' → _show_subcommand_completions called with ('reasoning', '')."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin

        obj = _make_fake_input(value="/reasoning ", cursor_position=11)
        obj._show_subcommand_completions = MagicMock()

        # Patch detect_context to return SLASH_SUBCOMMAND trigger.
        fake_trigger = CompletionTrigger(
            context=CompletionContext.SLASH_SUBCOMMAND,
            fragment="",
            start=11,
            parent_command="reasoning",
        )

        with patch(
            "hermes_cli.tui.input._autocomplete.detect_context",
            return_value=fake_trigger,
        ), patch(
            "hermes_cli.tui.input._autocomplete._SKILL_RE"
        ) as mock_re:
            mock_re.match.return_value = None
            _AutocompleteMixin._update_autocomplete(obj)

        obj._show_subcommand_completions.assert_called_once_with("reasoning", "")

    def test_subcommand_dispatch_with_fragment_passes_fragment(self):
        """'/effects bin' → _show_subcommand_completions called with ('effects', 'bin')."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin

        obj = _make_fake_input(value="/effects bin", cursor_position=12)
        obj._show_subcommand_completions = MagicMock()

        fake_trigger = CompletionTrigger(
            context=CompletionContext.SLASH_SUBCOMMAND,
            fragment="bin",
            start=10,
            parent_command="effects",
        )

        with patch(
            "hermes_cli.tui.input._autocomplete.detect_context",
            return_value=fake_trigger,
        ), patch(
            "hermes_cli.tui.input._autocomplete._SKILL_RE"
        ) as mock_re:
            mock_re.match.return_value = None
            _AutocompleteMixin._update_autocomplete(obj)

        obj._show_subcommand_completions.assert_called_once_with("effects", "bin")

    def test_subcommand_dispatch_empty_subcommands_resolves_none(self):
        """When _slash_subcommands is empty, assist ends as NONE (not OVERLAY).

        Uses _HistoryMixin._show_subcommand_completions directly via unbound call.
        _apply_assist fallback (no _resolve_assist) sets suggestion="" and
        leaves assist as NONE.
        """
        from hermes_cli.tui.input._history import _HistoryMixin

        obj = types.SimpleNamespace(
            _slash_subcommands={},
            assist=AssistKind.NONE,
            suggestion="",
            _set_overlay_mode=MagicMock(),
            _push_to_list=MagicMock(),
        )

        # Call the real method unbound; no _resolve_assist → _apply_assist shim
        # leaves assist unchanged (NONE).
        _HistoryMixin._show_subcommand_completions(obj, "unknown_cmd", "")

        assert obj.assist is AssistKind.NONE
        obj._set_overlay_mode.assert_not_called()
        obj._push_to_list.assert_not_called()


# ---------------------------------------------------------------------------
# TestCDH4PickerDesync
# ---------------------------------------------------------------------------

class TestCDH4PickerDesync:
    """CD-H4: _resolve_assist(PICKER) must not write self.assist when blocked."""

    def _make_widget_for_resolve_assist(self, open_picker_result: bool) -> types.SimpleNamespace:
        """Build a stub widget with real _resolve_assist wired up."""
        from hermes_cli.tui.input.widget import HermesInput  # type: ignore[attr-defined]

        trigger = CompletionTrigger(
            context=CompletionContext.SKILL_INVOKE,
            fragment="foo",
            start=0,
        )
        obj = types.SimpleNamespace(
            assist=AssistKind.NONE,
            suggestion="",
            _current_trigger=trigger,
        )
        obj.app = types.SimpleNamespace(
            _open_skill_picker=MagicMock(return_value=open_picker_result),
            status_ghost_suggestion=False,
        )
        obj._dismiss_skill_picker = MagicMock()
        obj._hide_completion_overlay = MagicMock()
        obj._show_completion_overlay = MagicMock()
        return obj

    def test_picker_assist_not_written_when_open_skill_picker_returns_false(self):
        """When _open_skill_picker returns False, assist must stay NONE."""
        from hermes_cli.tui.input.widget import HermesInput

        obj = self._make_widget_for_resolve_assist(open_picker_result=False)
        HermesInput._resolve_assist(obj, AssistKind.PICKER)

        assert obj.assist is AssistKind.NONE
        obj.app._open_skill_picker.assert_called_once_with(
            seed_filter="foo",
            trigger_source=SKILL_PICKER_TRIGGER_PREFIX,
        )

    def test_picker_assist_written_when_open_skill_picker_returns_true(self):
        """When _open_skill_picker returns True, assist must be set to PICKER."""
        from hermes_cli.tui.input.widget import HermesInput

        obj = self._make_widget_for_resolve_assist(open_picker_result=True)
        HermesInput._resolve_assist(obj, AssistKind.PICKER)

        assert obj.assist is AssistKind.PICKER

    def test_open_skill_picker_returns_false_on_modal_block(self):
        """_open_skill_picker must return False when top_modal() returns a non-picker widget."""
        from hermes_cli.tui.app import HermesApp
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        from textual.css.query import NoMatches

        dummy_modal = types.SimpleNamespace()  # not a SkillPickerOverlay

        app = types.SimpleNamespace()
        app.top_modal = MagicMock(return_value=dummy_modal)
        app.mount = MagicMock()
        # query_one raises NoMatches (no existing picker), so we hit the guard path.
        app.query_one = MagicMock(side_effect=NoMatches("SkillPickerOverlay"))

        result = HermesApp._open_skill_picker(app, seed_filter="foo")

        assert result is False
        app.mount.assert_not_called()
