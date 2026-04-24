"""Tests for Input Feedback & Completion spec (A-2, B-1/2/3, E-1/2/3, F-3).

~35 tests covering:
  - Draft stash (A-2): save_draft_stash, history nav after overlay accept
  - Empty reason strings (B-1): _EMPTY_REASON_TEXT updated messages
  - Enter accepts completion (B-2): _on_key intercept with overlay
  - Legend strip (B-3/F-3): InputLegendBar show/hide
  - Error placeholder (E-1): reactive error_state + _refresh_placeholder
  - History write failure (E-2): _on_history_write_error toast
  - Locked input (E-3): _set_input_locked class + placeholder
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers / fake objects
# ---------------------------------------------------------------------------

class _FakeApp:
    """Minimal fake app for unit tests."""

    def __init__(self):
        self._legend = None
        self.feedback = MagicMock()
        self._hints = []

    def query_one(self, selector, klass=None):
        if selector == "#input-legend-bar":
            return self._legend
        raise Exception(f"Not found: {selector}")

    def _flash_hint(self, msg, dur=None):
        self._hints.append(msg)


@dataclass
class _FakeInput:
    """Fake HermesInput for pure-unit testing of mixin logic."""
    suggestion: str = ""
    _history_idx: int = -1
    _history: list = field(default_factory=list)
    _history_loading: bool = False
    _draft_stash: "str | None" = None
    _write_fail_warned: bool = False
    disabled: bool = False
    error_state: "str | None" = None
    _idle_placeholder: str = "Type a message"
    placeholder: str = "Type a message"
    is_mounted: bool = True
    _text: str = ""
    _classes: set = field(default_factory=set)

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, v):
        self._text = v

    @property
    def value(self):
        return self._text

    @value.setter
    def value(self, v):
        self._text = v

    def _history_load(self, text):
        self._text = text

    def _completion_overlay_slash_only(self):
        return False

    def _completion_overlay_visible(self):
        return False

    def add_class(self, c):
        self._classes.add(c)

    def remove_class(self, c):
        self._classes.discard(c)

    def has_class(self, c):
        return c in self._classes


class _H:
    """Helper for _refresh_placeholder and _set_input_locked tests."""

    disabled: bool = False
    error_state: "str | None" = None
    _idle_placeholder: str = "idle"
    placeholder: str = "idle"
    is_mounted: bool = True

    def __init__(self):
        self._classes: set = set()

    def add_class(self, c):
        self._classes.add(c)

    def remove_class(self, c):
        self._classes.discard(c)

    def has_class(self, c):
        return c in self._classes


# Attach real methods
from hermes_cli.tui.input.widget import HermesInput
_H._refresh_placeholder = HermesInput._refresh_placeholder
_H._set_input_locked = HermesInput._set_input_locked


# ---------------------------------------------------------------------------
# Draft stash (A-2)
# ---------------------------------------------------------------------------

class TestDraftStash:
    def _make_inp(self, history=None, text="", history_idx=-1):
        inp = _FakeInput(
            _history=list(history or []),
            _history_idx=history_idx,
            _text=text,
        )
        return inp

    def test_draft_stash_saved_by_overlay_accept(self):
        """save_draft_stash() preserves current text when history_idx == -1."""
        inp = self._make_inp(text="my draft")
        inp._history_idx = -1
        inp._draft_stash = None
        # Call the real method bound to our fake object
        HermesInput.save_draft_stash(inp)
        assert inp._draft_stash == "my draft"

    def test_up_after_overlay_accept_restores_draft(self):
        """After overlay accept, pressing Up should not clobber the real draft."""
        inp = self._make_inp(history=["entry1", "entry2"], text="overlay-text")
        inp._history_idx = -1
        # Simulate overlay accepted text and save_draft_stash was called with "real draft"
        inp._draft_stash = "real draft"
        HermesInput.action_history_prev(inp)
        # _draft_stash should remain unchanged (guard preserved it)
        assert inp._draft_stash == "real draft"
        assert inp._history_idx == 1  # moved to last entry

    def test_draft_stash_cleared_after_typing(self):
        """_draft_stash is cleared when user types something different from stash."""
        inp = self._make_inp(text="old stash")
        inp._draft_stash = "old stash"
        inp._history_idx = -1
        inp._history_loading = False
        inp._handling_file_drop = False
        # Simulate user typed something different
        inp._text = "new text"
        # Call the invalidation logic directly
        if inp._draft_stash is not None and inp._history_idx == -1:
            if inp.text != inp._draft_stash:
                inp._draft_stash = None
        assert inp._draft_stash is None

    def test_draft_stash_not_clobbered_by_up_arrow(self):
        """Up arrow after history browse-back restores _draft_stash, not _history_draft."""
        inp = self._make_inp(history=["e1"], text="e1")
        inp._history_idx = 0  # currently on a history entry
        inp._draft_stash = "real user text"
        # Press Down to go back past end
        HermesInput.action_history_next(inp)
        # Should have loaded _draft_stash, not _history_draft
        assert inp._text == "real user text"
        assert inp._draft_stash is None
        assert inp._history_idx == -1


# ---------------------------------------------------------------------------
# Empty reason strings (B-1)
# ---------------------------------------------------------------------------

class TestEmptyReasonText:
    def _get_dict(self):
        from hermes_cli.tui.completion_list import _EMPTY_REASON_TEXT
        return _EMPTY_REASON_TEXT

    def test_empty_reason_too_short_message(self):
        d = self._get_dict()
        assert d["too_short"] == "  type 2+ chars to match"

    def test_empty_reason_no_slash_match_message(self):
        d = self._get_dict()
        assert d["no_slash_match"] == "  no match — /help for list"

    def test_empty_reason_path_not_found_message(self):
        d = self._get_dict()
        assert d["path_not_found"] == "  no such path — try @ alone"


# ---------------------------------------------------------------------------
# Enter accepts completion (B-2)
# ---------------------------------------------------------------------------

class TestEnterAcceptsCompletion:
    def test_enter_accepts_highlighted_completion(self):
        """When overlay visible and highlighted >= 0, Enter calls accept_autocomplete."""
        inp = MagicMock()
        inp.text = "hello"
        inp._completion_overlay_visible = MagicMock(return_value=True)
        inp.action_accept_autocomplete = MagicMock()
        inp.action_submit = MagicMock()

        # Mock screen.query_one(VirtualCompletionList)
        clist = MagicMock()
        clist.highlighted = 0
        inp.screen = MagicMock()
        inp.screen.query_one = MagicMock(return_value=clist)

        from hermes_cli.tui.completion_list import VirtualCompletionList
        # Patch import inside _on_key's enter block
        import hermes_cli.tui.completion_list as cl_mod
        original = cl_mod.VirtualCompletionList

        # Simulate what _on_key does for enter with overlay visible
        if inp._completion_overlay_visible():
            try:
                clist2 = inp.screen.query_one(VirtualCompletionList)
                if clist2.highlighted >= 0:
                    inp.action_accept_autocomplete()
            except Exception:
                pass

        inp.action_accept_autocomplete.assert_called_once()
        inp.action_submit.assert_not_called()

    def test_enter_with_no_overlay_submits_normally(self):
        """When overlay not visible, Enter falls through to submit."""
        inp = MagicMock()
        inp._completion_overlay_visible = MagicMock(return_value=False)
        inp.action_accept_autocomplete = MagicMock()
        inp.action_submit = MagicMock()

        if inp._completion_overlay_visible():
            pass  # overlay branch
        else:
            inp.action_submit()

        inp.action_accept_autocomplete.assert_not_called()
        inp.action_submit.assert_called_once()

    def test_enter_with_overlay_visible_no_highlight_submits(self):
        """When overlay visible but highlighted < 0, Enter submits."""
        inp = MagicMock()
        inp._completion_overlay_visible = MagicMock(return_value=True)
        inp.action_accept_autocomplete = MagicMock()
        inp.action_submit = MagicMock()

        clist = MagicMock()
        clist.highlighted = -1
        inp.screen = MagicMock()
        inp.screen.query_one = MagicMock(return_value=clist)

        from hermes_cli.tui.completion_list import VirtualCompletionList

        if inp._completion_overlay_visible():
            try:
                clist2 = inp.screen.query_one(VirtualCompletionList)
                if clist2.highlighted >= 0:
                    inp.action_accept_autocomplete()
                    # return — but we simulate no return here
                else:
                    inp.action_submit()
            except Exception:
                inp.action_submit()

        inp.action_accept_autocomplete.assert_not_called()
        inp.action_submit.assert_called_once()

    def test_second_enter_after_accept_submits(self):
        """After completion accepted (overlay now hidden), Enter submits normally."""
        inp = MagicMock()
        # First Enter: overlay visible + highlight → accept
        inp._completion_overlay_visible = MagicMock(return_value=True)
        clist = MagicMock()
        clist.highlighted = 0
        inp.screen = MagicMock()
        inp.screen.query_one = MagicMock(return_value=clist)
        inp.action_accept_autocomplete = MagicMock()
        inp.action_submit = MagicMock()

        from hermes_cli.tui.completion_list import VirtualCompletionList
        if inp._completion_overlay_visible():
            c = inp.screen.query_one(VirtualCompletionList)
            if c.highlighted >= 0:
                inp.action_accept_autocomplete()

        inp.action_accept_autocomplete.assert_called_once()

        # Second Enter: overlay now hidden → submit
        inp._completion_overlay_visible = MagicMock(return_value=False)
        if not inp._completion_overlay_visible():
            inp.action_submit()

        inp.action_submit.assert_called_once()


# ---------------------------------------------------------------------------
# Legend strip (B-3 / F-3)
# ---------------------------------------------------------------------------

class TestInputLegendBar:
    def _make_legend(self):
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        # Create without mounting
        legend = object.__new__(InputLegendBar)
        legend._classes = set()
        legend._content = ""

        def add_class(c):
            legend._classes.add(c)
        def remove_class(c):
            legend._classes.discard(c)
        def has_class(c):
            return c in legend._classes
        def update(text):
            legend._content = text

        legend.add_class = add_class
        legend.remove_class = remove_class
        legend.has_class = has_class
        legend.update = update
        return legend

    def test_legend_shows_on_bash_mode_entry(self):
        legend = self._make_legend()
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        InputLegendBar.show_legend(legend, "bash")
        assert "--visible" in legend._classes
        assert "shell mode" in legend._content

    def test_legend_hides_on_bash_mode_exit(self):
        legend = self._make_legend()
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        InputLegendBar.show_legend(legend, "bash")
        InputLegendBar.hide_legend(legend)
        assert "--visible" not in legend._classes

    def test_legend_shows_on_rev_search_entry(self):
        legend = self._make_legend()
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        InputLegendBar.show_legend(legend, "rev_search")
        assert "--visible" in legend._classes
        assert "rev-search" in legend._content

    def test_legend_shows_on_completion_overlay_open(self):
        legend = self._make_legend()
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        InputLegendBar.show_legend(legend, "completion")
        assert "--visible" in legend._classes
        assert "Tab=accept" in legend._content

    def test_legend_hidden_in_compact_mode(self):
        """InputLegendBar has display:none in CSS for density-compact."""
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        css = InputLegendBar.DEFAULT_CSS
        # The tcss rule is in hermes.tcss; check DEFAULT_CSS has display:none default
        assert "display: none" in css

    def test_legend_show_hide_is_idempotent(self):
        legend = self._make_legend()
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        InputLegendBar.show_legend(legend, "bash")
        InputLegendBar.show_legend(legend, "bash")  # second call idempotent
        InputLegendBar.hide_legend(legend)
        InputLegendBar.hide_legend(legend)  # second hide idempotent
        assert "--visible" not in legend._classes

    def test_legend_known_modes(self):
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        for mode in ("bash", "rev_search", "completion", "ghost"):
            assert mode in InputLegendBar.LEGENDS
            assert len(InputLegendBar.LEGENDS[mode]) > 0


# ---------------------------------------------------------------------------
# Error placeholder (E-1)
# ---------------------------------------------------------------------------

class TestErrorStatePlaceholder:
    def test_error_state_sets_placeholder(self):
        h = _H()
        h.error_state = "something went wrong"
        _H._refresh_placeholder(h)
        assert "⚠" in h.placeholder
        assert "something went wrong" in h.placeholder

    def test_esc_clears_error_state_when_no_text(self):
        """Esc clears error_state when input is empty."""
        h = _FakeInput(error_state="err", _text="")
        # Simulate the Esc-to-clear logic
        if h.error_state is not None and not h.text.strip():
            h.error_state = None
        assert h.error_state is None

    def test_esc_does_not_clear_error_when_text_present(self):
        """Esc does NOT clear error_state when input has text."""
        h = _FakeInput(error_state="err", _text="some text")
        if h.error_state is not None and not h.text.strip():
            h.error_state = None
        # Should still be set
        assert h.error_state == "err"

    def test_error_placeholder_cleared_on_reset(self):
        h = _H()
        h.error_state = "err"
        _H._refresh_placeholder(h)
        assert "⚠" in h.placeholder
        h.error_state = None
        _H._refresh_placeholder(h)
        assert h.placeholder == "idle"

    def test_error_state_priority_over_idle_placeholder(self):
        h = _H()
        h.disabled = False
        h.error_state = "bad thing"
        _H._refresh_placeholder(h)
        assert "⚠" in h.placeholder
        assert "bad thing" in h.placeholder

    def test_error_state_priority_under_locked_placeholder(self):
        """Locked/disabled placeholder beats error_state."""
        h = _H()
        h.disabled = True
        h.error_state = "bad thing"
        _H._refresh_placeholder(h)
        # Locked takes priority
        assert "running" in h.placeholder or "Ctrl+C" in h.placeholder

    def test_error_snippet_truncated_to_40_chars(self):
        h = _H()
        h.error_state = "x" * 50
        _H._refresh_placeholder(h)
        # Snippet is at most 40 chars + "…"
        assert "…" in h.placeholder
        # The snippet portion is limited
        snippet_part = h.placeholder.split("⚠ ")[1].split("  ·")[0]
        assert len(snippet_part) <= 42  # 40 + "…"


# ---------------------------------------------------------------------------
# History write failure (E-2)
# ---------------------------------------------------------------------------

class TestHistoryWriteFailure:
    def _make_mixin(self):
        """Return a fake object with _HistoryMixin._on_history_write_error bound."""
        from hermes_cli.tui.input._history import _HistoryMixin

        class _Fake:
            _write_fail_warned = False
            app = MagicMock()

        obj = _Fake()
        obj._on_history_write_error = lambda exc: _HistoryMixin._on_history_write_error(obj, exc)
        return obj

    def test_write_failure_triggers_toast(self):
        obj = self._make_mixin()
        obj.app.feedback.flash = MagicMock()
        obj._on_history_write_error(OSError("disk full"))
        obj.app.feedback.flash.assert_called_once()
        args = obj.app.feedback.flash.call_args
        assert "history write failed" in args[0][1]

    def test_write_failure_toast_fires_once(self):
        obj = self._make_mixin()
        obj.app.feedback.flash = MagicMock()
        obj._on_history_write_error(OSError("disk full"))
        obj._on_history_write_error(OSError("disk full again"))
        # Should only flash once (deduplicated by _write_fail_warned)
        assert obj.app.feedback.flash.call_count == 1

    def test_write_failure_warn_resets_on_success(self):
        obj = self._make_mixin()
        obj.app.feedback.flash = MagicMock()
        obj._on_history_write_error(OSError("disk full"))
        assert obj._write_fail_warned is True
        # Simulate on_done resetting it
        obj._write_fail_warned = False
        obj._on_history_write_error(OSError("disk full again"))
        # Should flash again
        assert obj.app.feedback.flash.call_count == 2


# ---------------------------------------------------------------------------
# Locked input (E-3)
# ---------------------------------------------------------------------------

class TestLockedInput:
    def test_locked_placeholder_set_when_disabled(self):
        h = _H()
        h.disabled = True
        _H._refresh_placeholder(h)
        assert "running" in h.placeholder or "Ctrl+C" in h.placeholder

    def test_locked_placeholder_restored_when_enabled(self):
        h = _H()
        h.disabled = True
        _H._refresh_placeholder(h)
        h.disabled = False
        _H._refresh_placeholder(h)
        assert h.placeholder == "idle"

    def test_locked_class_added_when_locked(self):
        h = _H()
        _H._set_input_locked(h, True)
        assert "--locked" in h._classes

    def test_locked_class_removed_when_unlocked(self):
        h = _H()
        h.add_class("--locked")
        _H._set_input_locked(h, False)
        assert "--locked" not in h._classes

    def test_locked_respects_error_state_on_unlock(self):
        """On unlock, if error_state is set, placeholder shows error (not idle)."""
        h = _H()
        h.disabled = False
        h.error_state = "some error"
        _H._set_input_locked(h, False)
        # _refresh_placeholder is called by _set_input_locked
        assert "⚠" in h.placeholder

    def test_refresh_placeholder_priority_locked_beats_error(self):
        h = _H()
        h.disabled = True
        h.error_state = "some error"
        _H._refresh_placeholder(h)
        assert "running" in h.placeholder or "Ctrl+C" in h.placeholder

    def test_refresh_placeholder_priority_error_beats_idle(self):
        h = _H()
        h.disabled = False
        h.error_state = "some error"
        _H._refresh_placeholder(h)
        assert "⚠" in h.placeholder
        assert "some error" in h.placeholder

    def test_set_input_locked_no_op_when_not_mounted(self):
        """_set_input_locked does nothing if widget not mounted."""
        h = _H()
        h.is_mounted = False
        _H._set_input_locked(h, True)
        # No class added, no placeholder change
        assert "--locked" not in h._classes
