"""
Tests for composer completion acceptance and Enter-selection behavior.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
from hermes_cli.tui.path_search import PathCandidate, SlashCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_autocomplete_inp(value: str, cursor_pos: int, highlighted_cmd: str | None = None):
    """Build a SimpleNamespace that satisfies _AutocompleteMixin.action_accept_autocomplete."""
    inp = types.SimpleNamespace()
    inp.value = value
    inp.cursor_position = cursor_pos

    inp.app = types.SimpleNamespace()
    inp.app._flash_hint = MagicMock()

    inp._completion_overlay_visible = lambda: True
    inp._hide_completion_overlay = MagicMock()
    inp._resolve_assist = MagicMock()

    mock_clist = MagicMock()
    if highlighted_cmd is not None:
        mock_clist.highlighted = 0
        mock_clist.items = [SlashCandidate(display=highlighted_cmd, command=highlighted_cmd)]
    else:
        mock_clist.highlighted = -1
        mock_clist.items = []
    inp.screen = types.SimpleNamespace()
    inp.screen.query_one = lambda cls: mock_clist

    inp._current_trigger = CompletionTrigger(CompletionContext.SLASH_COMMAND, "help", 1)

    inp.action_accept_autocomplete = _AutocompleteMixin.action_accept_autocomplete.__get__(inp)
    return inp, mock_clist


def _make_path_autocomplete_inp(
    value: str,
    cursor_pos: int,
    *,
    display: str,
    insert_text: str | None = None,
    trigger: CompletionTrigger,
):
    inp = types.SimpleNamespace()
    inp.value = value
    inp.cursor_position = cursor_pos
    inp.app = types.SimpleNamespace()
    inp.app._flash_hint = MagicMock()
    inp._completion_overlay_visible = lambda: True
    inp._resolve_assist = MagicMock()

    candidate = PathCandidate(display=display, insert_text=insert_text, abs_path=f"/tmp/{display}")
    mock_clist = MagicMock()
    mock_clist.highlighted = 0
    mock_clist.items = [candidate]
    inp.screen = types.SimpleNamespace()
    inp.screen.query_one = lambda cls: mock_clist
    inp._current_trigger = trigger
    inp.action_accept_autocomplete = _AutocompleteMixin.action_accept_autocomplete.__get__(inp)
    return inp


def _make_enter_inp(
    value: str,
    slash_commands: list[str] | None = None,
    highlighted_cmd: str | None = None,
    highlighted_idx: int = 0,
    completion_visible: bool = True,
):
    """Build a SimpleNamespace that satisfies HermesInput._on_key Enter branch."""
    inp = types.SimpleNamespace()
    inp.value = value
    inp.text = value
    inp.cursor_position = len(value)
    inp.disabled = False

    inp._slash_commands = slash_commands if slash_commands is not None else []

    if highlighted_cmd is not None:
        items = [SlashCandidate(display=highlighted_cmd, command=highlighted_cmd + " ")]
        highlighted = highlighted_idx
    else:
        items = []
        highlighted = -1

    mock_clist = MagicMock()
    mock_clist.highlighted = highlighted
    mock_clist.items = items

    inp._completion_overlay_visible = lambda: completion_visible
    inp.screen = types.SimpleNamespace()
    inp.screen.query_one = lambda cls: mock_clist

    inp.action_accept_autocomplete = MagicMock()
    inp.action_submit = MagicMock()

    # Attributes read earlier in _on_key that we must stub
    inp.error_state = None
    # _on_key also reads these before Enter block in some paths; guard with defaults
    inp._rev_mode = False

    return inp, mock_clist


def _make_key_event(key: str) -> MagicMock:
    event = MagicMock()
    event.key = key
    event.character = key if len(key) == 1 else ""
    event.is_printable = False
    event.prevent_default = MagicMock()
    event.stop = MagicMock()
    return event


# ---------------------------------------------------------------------------
# I4 — Mid-string Tab: accept splice
# ---------------------------------------------------------------------------

class TestI4MidStringTab:
    def test_slash_mid_string_replaces_value(self):
        """Slash candidates replace the whole value even with a mid-string cursor."""
        inp, mock_clist = _make_autocomplete_inp("foobar", cursor_pos=3, highlighted_cmd="/help")
        inp.action_accept_autocomplete()
        assert inp.value == "/help "
        inp._resolve_assist.assert_called_once()

    def test_tab_mid_string_no_flash(self):
        """Mid-string acceptance no longer flashes a move-cursor hint."""
        inp, _ = _make_autocomplete_inp("/hel tail", cursor_pos=3, highlighted_cmd="/help")
        inp.action_accept_autocomplete()
        inp.app._flash_hint.assert_not_called()

    def test_accept_autocomplete_path_mid_word_single_line(self):
        trigger = CompletionTrigger(CompletionContext.PLAIN_PATH_REF, "src/fi", 0)
        inp = _make_path_autocomplete_inp(
            "src/fi trailing",
            cursor_pos=6,
            display="file.txt",
            trigger=trigger,
        )
        inp.action_accept_autocomplete()
        assert inp.value == "src/file.txt trailing"

    def test_accept_autocomplete_path_end_of_value(self):
        trigger = CompletionTrigger(CompletionContext.PLAIN_PATH_REF, "src/fi", 0)
        inp = _make_path_autocomplete_inp(
            "src/fi",
            cursor_pos=6,
            display="file.txt",
            trigger=trigger,
        )
        inp.action_accept_autocomplete()
        assert inp.value == "src/file.txt "

    def test_accept_autocomplete_path_trailing_text_preserved(self):
        trigger = CompletionTrigger(CompletionContext.PATH_REF, "fi", 6)
        inp = _make_path_autocomplete_inp(
            "copy @fi later",
            cursor_pos=8,
            display="file.txt",
            trigger=trigger,
        )
        inp.action_accept_autocomplete()
        assert inp.value == "copy @file.txt later"


# ---------------------------------------------------------------------------
# I10 — Enter respects highlighted candidate for exact-slash bypass
# ---------------------------------------------------------------------------

class TestI10EnterHighlightRespect:
    @pytest.mark.asyncio
    async def test_enter_accepts_highlighted_different_slash(self):
        """/help typed, /help-me highlighted → accept /help-me."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, _ = _make_enter_inp(
            value="/help",
            slash_commands=["/help", "/help-me"],
            highlighted_cmd="/help-me",
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_called_once()
        inp.action_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_enter_submits_when_highlighted_is_typed_slash(self):
        """/help typed, /help highlighted (exact match) → submit."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, mock_clist = _make_enter_inp(
            value="/help",
            slash_commands=["/help", "/help-me"],
            highlighted_cmd="/help",
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_not_called()
        inp.action_submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_enter_accepts_when_no_exact_slash(self):
        """/foo typed (not in slash_commands), /foobar highlighted → accept."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, _ = _make_enter_inp(
            value="/foo",
            slash_commands=["/help", "/foobar"],
            highlighted_cmd="/foobar",
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_called_once()
        inp.action_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_enter_submits_when_no_highlight(self):
        """Overlay visible but highlighted == -1 → submit."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, _ = _make_enter_inp(
            value="/help",
            slash_commands=["/help"],
            highlighted_cmd=None,
            completion_visible=True,
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_not_called()
        inp.action_submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_enter_submits_plain_text(self):
        """Plain text, overlay not visible → submit (no completion intercept)."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, _ = _make_enter_inp(
            value="plain text",
            slash_commands=["/help"],
            highlighted_cmd=None,
            completion_visible=False,
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_not_called()
        inp.action_submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_enter_with_moved_highlight_honors_user_selection(self):
        """/run typed, user arrowed to /run-all → accept /run-all."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, _ = _make_enter_inp(
            value="/run",
            slash_commands=["/run", "/run-all"],
            highlighted_cmd="/run-all",
        )
        event = _make_key_event("enter")
        await HermesInput._on_key(inp, event)
        inp.action_accept_autocomplete.assert_called_once()
        inp.action_submit.assert_not_called()
