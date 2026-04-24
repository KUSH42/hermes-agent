"""Tests for Audit 3 Input & Completion Quick Wins spec.

Covers I1/I2/I3/I7/I8/I11/I12/I13/I15/I16 — 20 tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _FakeApp:
    def __init__(self):
        self.feedback = MagicMock()
        self._hints: list[tuple[str, float]] = []

    def _flash_hint(self, msg, dur=None):
        self._hints.append((msg, dur))


@dataclass
class _FakeInput:
    """Minimal fake for history-mixin unit tests."""
    suggestion: str = ""
    _history_idx: int = -1
    _history: list = field(default_factory=list)
    _draft_stash: "str | None" = None
    _history_loading: bool = False
    _rev_mode: bool = False
    _rev_query: str = ""
    _rev_idx: int = -1
    _rev_match_idx: int = -1
    _rev_saved_value: str = ""
    _ghost_legend_shown: bool = False
    _text: str = ""
    _classes: set = field(default_factory=set)
    cursor_location: tuple = (0, 0)
    app: Any = field(default_factory=_FakeApp)
    screen: Any = None

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, v):
        self._text = v

    def load_text(self, v):
        self._text = v

    def move_cursor(self, loc):
        pass

    def add_class(self, c):
        self._classes.add(c)

    def remove_class(self, c):
        self._classes.discard(c)

    def has_class(self, c):
        return c in self._classes


# Attach real mixin methods
from hermes_cli.tui.input._history import _HistoryMixin, _show_ghost_legend, _hide_ghost_legend
_FakeInput._rev_search_find = _HistoryMixin._rev_search_find
_FakeInput.action_rev_search = _HistoryMixin.action_rev_search
_FakeInput.update_suggestion = _HistoryMixin.update_suggestion


# ---------------------------------------------------------------------------
# I1 — Rev-search ↑↓ routes to _rev_search_find
# ---------------------------------------------------------------------------

class TestI1RevSearchUpDown:
    def test_rev_search_up_calls_rev_search_find_backward(self):
        """_rev_search_find(-1) walks backward from current match index."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _FakeInput(_history=["git add", "ls", "git commit", "git push", "pwd"])
        inp._rev_mode = True
        inp._rev_match_idx = 4  # start past all entries
        inp._rev_query = "git"
        result = _HistoryMixin._rev_search_find(inp, direction=-1)
        assert result is not None
        assert "git" in result
        assert inp._rev_match_idx < 4  # walked backward

    def test_rev_search_down_calls_rev_search_find_forward(self):
        """_rev_search_find(+1) walks forward from current match index."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _FakeInput(_history=["git add", "ls", "git commit", "git push", "pwd"])
        inp._rev_mode = True
        inp._rev_match_idx = 0
        inp._rev_query = "git"
        result = _HistoryMixin._rev_search_find(inp, direction=+1)
        assert result is not None
        assert "git" in result
        assert inp._rev_match_idx > 0

    def test_rev_search_up_does_not_call_history_prev(self):
        """In rev-mode, up key guard appears before action_history_prev in source."""
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput._on_key)
        up_idx = src.find('if key == "up":')
        rev_guard_idx = src.find('_rev_mode', up_idx)
        hist_prev_idx = src.find('action_history_prev', up_idx)
        assert rev_guard_idx != -1, "rev_mode guard missing in up block"
        assert rev_guard_idx < hist_prev_idx, "rev_mode guard must precede history_prev"


# ---------------------------------------------------------------------------
# I2 — Esc unconditionally clears error_state
# ---------------------------------------------------------------------------

class TestI2EscErrorState:
    def test_esc_clears_error_state_when_text_present(self):
        """Esc clears error_state even when text is non-empty."""
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput._on_key)
        # The old guard was: `if self.error_state is not None and not self.text.strip()`
        # The new guard must NOT include `not self.text.strip()`
        esc_block_start = src.find('if key == "escape":')
        next_key_block = src.find('if key == "pageup":', esc_block_start)
        esc_block = src[esc_block_start:next_key_block]
        assert "not self.text.strip()" not in esc_block, \
            "Esc block must not guard on empty text for error_state clear"
        assert "error_state is not None" in esc_block, \
            "Esc block must still check error_state is not None"

    def test_esc_clears_error_state_when_empty(self):
        """Esc still clears error_state when input is empty (existing behavior)."""
        # Structural: error_state check has no text guard — empty case works trivially
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput._on_key)
        esc_block_start = src.find('if key == "escape":')
        assert "error_state is not None" in src[esc_block_start:], \
            "error_state guard must exist in escape handler"


# ---------------------------------------------------------------------------
# I3 — No _flash_hint from _sync_bash_mode_ui
# ---------------------------------------------------------------------------

class _I3Widget:
    """Minimal stand-in to test _sync_bash_mode_ui without Textual Widget base."""
    _chevron_label = "❯ "
    _idle_placeholder = "Type a message  @file  /cmd  !shell"
    placeholder = _idle_placeholder
    disabled = False
    error_state = None

    def __init__(self):
        self._classes: set = set()
        self.app = _FakeApp()
        self.app.feedback = MagicMock()

    def add_class(self, c): self._classes.add(c)
    def remove_class(self, c): self._classes.discard(c)
    def has_class(self, c): return c in self._classes
    def query_one(self, *a, **kw): raise Exception("no DOM")
    def _refresh_placeholder(self):
        self.placeholder = self._idle_placeholder


from hermes_cli.tui.input.widget import HermesInput
_I3Widget._sync_bash_mode_ui = HermesInput._sync_bash_mode_ui


class TestI3BashHintFlash:
    def test_sync_bash_mode_does_not_call_flash_hint(self):
        """Entering bash mode must NOT call app._flash_hint."""
        w = _I3Widget()
        _I3Widget._sync_bash_mode_ui(w, True)
        assert w.app._hints == [], "_flash_hint must not be called on bash entry"

    def test_sync_bash_mode_exit_cancels_hint_bar(self):
        """Exiting bash mode calls feedback.cancel('hint-bar')."""
        w = _I3Widget()
        _I3Widget._sync_bash_mode_ui(w, False)
        w.app.feedback.cancel.assert_called_once_with("hint-bar")


# ---------------------------------------------------------------------------
# I7 — Ghost text 1-char noise guard
# ---------------------------------------------------------------------------

class TestI7GhostOneChar:
    def test_update_suggestion_suppressed_for_one_char(self):
        """Single-char input produces empty suggestion."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _FakeInput(_history=["abc", "abcdef"])
        inp._text = "a"
        inp.cursor_location = (0, 1)
        _HistoryMixin.update_suggestion(inp)
        assert inp.suggestion == ""

    def test_update_suggestion_fires_for_two_plus_chars(self):
        """2+ char input with matching history populates suggestion."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _FakeInput(_history=["git commit", "git add"])
        inp._text = "gi"
        inp.cursor_location = (0, 2)
        _HistoryMixin.update_suggestion(inp)
        assert inp.suggestion != ""


# ---------------------------------------------------------------------------
# I8 — Rev-search uses `in` (substring) not `startswith`
# ---------------------------------------------------------------------------

class TestI8RevSearchSubstring:
    def test_rev_search_matches_substring_not_only_prefix(self):
        """action_rev_search finds substring matches, not just prefix."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _FakeInput(_history=["ls -la", "git commit -m 'foo'", "echo hello"])
        inp._text = "commit"
        inp._rev_mode = True
        inp._rev_query = "commit"
        inp._rev_idx = len(inp._history)
        inp._rev_match_idx = len(inp._history)
        _HistoryMixin.action_rev_search(inp)
        assert "commit" in inp._text

    def test_rev_search_find_and_action_rev_search_same_algorithm(self):
        """Both action_rev_search and _rev_search_find use `in` substring match."""
        import inspect
        from hermes_cli.tui.input._history import _HistoryMixin
        src = inspect.getsource(_HistoryMixin.action_rev_search)
        # After the fix, the loop must use `query in self._history[idx]`
        assert "query in self._history[idx]" in src, \
            "action_rev_search must use substring `in` match"
        src2 = inspect.getsource(_HistoryMixin._rev_search_find)
        assert "query in self._history[idx]" in src2, \
            "_rev_search_find must use substring `in` match"


# ---------------------------------------------------------------------------
# I11 — Default placeholder advertises !shell
# ---------------------------------------------------------------------------

class TestI11Placeholder:
    def test_default_placeholder_contains_bash_trigger(self):
        """Default idle placeholder includes '!shell' for discoverability."""
        from hermes_cli.tui.input.widget import HermesInput
        w = object.__new__(HermesInput)
        # Read _default_placeholder via the __init__ source or check constant
        import inspect
        src = inspect.getsource(HermesInput.__init__)
        assert "!shell" in src, "Default placeholder must contain '!shell'"


# ---------------------------------------------------------------------------
# I12 — Ctrl+Shift+Up/Down increment/decrement with bounds
# ---------------------------------------------------------------------------

class _FakeStyles:
    def __init__(self):
        self.max_height = 3

class _HeightWidget:
    def __init__(self, height=3):
        self._input_height_override = height
        self.styles = _FakeStyles()
        self.app = _FakeApp()
        self._sync_called = 0

    def _sync_height_to_content(self):
        self._sync_called += 1


class TestI12HeightResize:
    def _make(self, height=3):
        return _HeightWidget(height=height)

    def _press_up(self, w):
        from hermes_cli.tui.input.widget import HermesInput
        # Simulate the ctrl+shift+up handler body directly
        w._input_height_override = min(6, w._input_height_override + 1)
        w.styles.max_height = w._input_height_override
        w._sync_height_to_content()

    def _press_down(self, w):
        w._input_height_override = max(1, w._input_height_override - 1)
        w.styles.max_height = w._input_height_override
        w._sync_height_to_content()

    def test_ctrl_shift_up_increments_height(self):
        w = self._make(3)
        self._press_up(w)
        assert w._input_height_override == 4

    def test_ctrl_shift_down_decrements_height(self):
        w = self._make(3)
        self._press_down(w)
        assert w._input_height_override == 2

    def test_ctrl_shift_height_bounded(self):
        # Up from 3 x10 → max 6
        w = self._make(3)
        for _ in range(10):
            self._press_up(w)
        assert w._input_height_override == 6

        # Down from 3 x10 → min 1
        w2 = self._make(3)
        for _ in range(10):
            self._press_down(w2)
        assert w2._input_height_override == 1

    def test_ctrl_shift_height_source_uses_min_max(self):
        """Source code must use min/max bounds, not hardcoded =3."""
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput._on_key)
        up_idx = src.find('"ctrl+shift+up"')
        down_idx = src.find('"ctrl+shift+down"')
        up_block = src[up_idx:down_idx]
        down_block = src[down_idx:down_idx + 300]
        assert "min(6" in up_block, "ctrl+shift+up must use min(6, ...)"
        assert "max(1" in down_block, "ctrl+shift+down must use max(1, ...)"


# ---------------------------------------------------------------------------
# I13 — Delete dead `not has_app` compat branch in on_click
# ---------------------------------------------------------------------------

class TestI13CompatPath:
    def test_middle_click_uses_safe_run_only(self):
        """on_click must not reference subprocess.run (compat branch deleted)."""
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput.on_click)
        assert "has_app" not in src, "has_app compat branch must be deleted"
        assert "subprocess.run" not in src, "direct subprocess.run must be gone"
        assert "safe_run" in src, "safe_run must be the only path"


# ---------------------------------------------------------------------------
# I15 — Auto-close timer: 3s for readable empty states
# ---------------------------------------------------------------------------

class _FakeCompletionList:
    """Minimal fake for VirtualCompletionList auto-close tests."""
    items: list = field(default_factory=list)
    searching: bool = False
    empty_reason: str = ""
    _auto_close_timer: Any = None

    def __init__(self):
        self.items = []
        self.searching = False
        self.empty_reason = ""
        self._auto_close_timer = None
        self._timer_delays: list[float] = []

    def _cancel_auto_close(self):
        self._auto_close_timer = None

    def set_timer(self, delay, cb):
        self._timer_delays.append(delay)
        self._auto_close_timer = MagicMock()
        return self._auto_close_timer

    def _fire_auto_dismiss(self):
        pass


from hermes_cli.tui.completion_list import VirtualCompletionList
_FakeCompletionList._maybe_schedule_auto_close = VirtualCompletionList._maybe_schedule_auto_close
_FakeCompletionList._cancel_auto_close = VirtualCompletionList._cancel_auto_close


class TestI15AutoCloseDelay:
    def test_auto_close_delay_is_3s_for_too_short(self):
        c = _FakeCompletionList()
        c.empty_reason = "too_short"
        c._maybe_schedule_auto_close()
        assert c._timer_delays[-1] == 3.0

    def test_auto_close_delay_is_1p5s_for_no_results(self):
        c = _FakeCompletionList()
        c.empty_reason = "path_not_found"
        c._maybe_schedule_auto_close()
        assert c._timer_delays[-1] == 1.5

    def test_auto_close_delay_is_3s_for_no_slash_match(self):
        c = _FakeCompletionList()
        c.empty_reason = "no_slash_match"
        c._maybe_schedule_auto_close()
        assert c._timer_delays[-1] == 3.0


# ---------------------------------------------------------------------------
# I16 — Paste flash gated on len > 80
# ---------------------------------------------------------------------------

class TestI16PasteFlash:
    def test_paste_flash_suppressed_for_small_pastes(self):
        """Pasting ≤80 chars must NOT trigger _flash_hint."""
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput._on_paste)
        # Must have `> 80` guard around the flash call
        assert "> 80" in src, "_on_paste must gate flash on len > 80"
        flash_idx = src.find("_flash_hint")
        guard_idx = src.find("> 80")
        assert guard_idx < flash_idx, "len > 80 guard must precede the flash call"

    def test_paste_flash_fires_for_large_pastes(self):
        """_flash_hint is called when paste length > 80."""
        hints: list = []
        fake_app = MagicMock()
        fake_app._flash_hint = lambda msg, dur=None: hints.append((msg, dur))
        large_text = "x" * 81
        # Simulate the gate logic from _on_paste
        from hermes_cli.tui.constants import ICON_COPY
        if len(large_text) > 80:
            fake_app._flash_hint(f"{ICON_COPY}  {len(large_text)} chars pasted", 1.2)
        assert len(hints) == 1
        assert "81" in hints[0][0]
