"""Audit 3 I5 — Draft Unification tests.

_history_draft removed; _draft_stash is the single draft field.
All tests use _FakeInput (no Textual reactives needed).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fake input for pure-unit testing
# ---------------------------------------------------------------------------

class _FakeInput:
    def __init__(self, history=None, text=""):
        self._history: list[str] = list(history or [])
        self._history_idx: int = -1
        self._draft_stash: str | None = None
        self._history_loading: bool = False
        self._text: str = text
        self.suggestion: str = ""
        self.placeholder: str = ""
        self._idle_placeholder: str = ""
        self.disabled: bool = False

    @property
    def text(self) -> str:
        return self._text

    @property
    def value(self) -> str:
        return self._text

    @value.setter
    def value(self, v: str) -> None:
        self._text = v

    def load_text(self, text: str) -> None:
        self._text = text

    def move_cursor(self, pos: object) -> None:
        pass

    def save_draft_stash(self) -> None:
        from hermes_cli.tui.input.widget import HermesInput
        HermesInput.save_draft_stash(self)  # type: ignore[arg-type]


def _bind(inp: _FakeInput) -> _FakeInput:
    """Bind widget.py / _history.py methods onto _FakeInput instance."""
    from hermes_cli.tui.input.widget import HermesInput
    from hermes_cli.tui.input._history import _HistoryMixin

    inp.action_history_prev = lambda: HermesInput.action_history_prev(inp)  # type: ignore[attr-defined]
    inp.action_history_next = lambda: HermesInput.action_history_next(inp)  # type: ignore[attr-defined]
    inp._history_load = lambda t: _HistoryMixin._history_load(inp, t)  # type: ignore[attr-defined]
    inp._history_navigate_skip_cmds = lambda d: _HistoryMixin._history_navigate_skip_cmds(inp, d)  # type: ignore[attr-defined]
    # completion overlay helpers — not used in these tests
    inp._completion_overlay_slash_only = lambda: False  # type: ignore[attr-defined]
    inp._completion_overlay_visible = lambda: False  # type: ignore[attr-defined]
    inp._hide_completion_overlay = lambda: None  # type: ignore[attr-defined]
    inp._suppress_autocomplete_once = False  # type: ignore[attr-defined]
    inp._move_highlight = lambda d: None  # type: ignore[attr-defined]
    return inp


def _make(history=None, text="") -> _FakeInput:
    return _bind(_FakeInput(history=history, text=text))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDraftUnification:

    def test_history_draft_field_removed(self):
        """HermesInput instance must have no _history_draft attribute."""
        from unittest.mock import MagicMock
        from hermes_cli.tui.app import HermesApp
        # Import only; don't run app. Check the __init__ source.
        import inspect
        from hermes_cli.tui.input.widget import HermesInput
        src = inspect.getsource(HermesInput.__init__)
        assert "_history_draft" not in src, "_history_draft still in HermesInput.__init__"

    def test_history_prev_saves_draft_stash(self):
        """↑ on fresh input (idx==-1, no stash) saves text into _draft_stash."""
        inp = _make(history=["cmd1", "cmd2"], text="foo")
        assert inp._draft_stash is None
        inp.action_history_prev()
        assert inp._draft_stash == "foo"

    def test_history_next_restores_from_draft_stash(self):
        """↑ then ↓ restores the original text from _draft_stash."""
        inp = _make(history=["cmd1"], text="foo")
        inp.action_history_prev()
        inp.action_history_next()
        assert inp.text == "foo"
        assert inp._draft_stash is None

    def test_overlay_stash_not_overwritten_by_history_prev(self):
        """If _draft_stash is already set (by overlay), ↑ must not overwrite it."""
        inp = _make(history=["cmd1", "cmd2"], text="overlay-text")
        inp._draft_stash = "real-user-text"  # simulate overlay pre-save
        inp.action_history_prev()
        assert inp._draft_stash == "real-user-text"
        assert inp._history_idx == 1  # moved into history

    def test_overlay_stash_restored_after_history_prev_and_next(self):
        """↑ then ↓ restores the overlay-saved stash, not the overlay-loaded text."""
        inp = _make(history=["cmd1"], text="overlay-text")
        inp._draft_stash = "real-user-text"
        inp.action_history_prev()
        inp.action_history_next()
        assert inp.text == "real-user-text"
        assert inp._draft_stash is None

    def test_empty_input_draft_is_empty_string_restores_empty(self):
        """Empty text before ↑ → _draft_stash="" (non-None), ↓ restores empty."""
        inp = _make(history=["cmd1"], text="")
        assert inp._draft_stash is None
        inp.action_history_prev()
        assert inp._draft_stash == ""  # non-None, empty string
        inp.action_history_next()
        assert inp.text == ""

    def test_save_draft_stash_no_effect_during_history_nav(self):
        """save_draft_stash() is a no-op when _history_idx != -1."""
        inp = _make(history=["cmd1", "cmd2"], text="foo")
        inp.action_history_prev()  # _history_idx = 1, stash = "foo"
        stash_before = inp._draft_stash
        # Manually call save_draft_stash while in history nav
        from hermes_cli.tui.input.widget import HermesInput
        inp._text = "modified-during-nav"
        inp.save_draft_stash()
        assert inp._draft_stash == stash_before  # unchanged

    def test_history_search_overlay_accept_still_works(self):
        """save_draft_stash() + load + history_next restores original stash."""
        inp = _make(history=["cmd1", "cmd2"], text="foo")
        # Simulate overlay: stash real text, load search result
        inp.save_draft_stash()
        assert inp._draft_stash == "foo"
        inp._text = "/search-result"
        # Navigate forward (past end → restore stash)
        inp._history_idx = len(inp._history) - 1
        inp.action_history_next()
        assert inp.text == "foo"
        assert inp._draft_stash is None

    def test_skip_cmds_saves_and_restores_draft(self):
        """_history_navigate_skip_cmds backward saves stash; forward restores."""
        inp = _make(history=["hello", "/model x", "world"], text="original")
        inp._history_navigate_skip_cmds(-1)  # backward, lands on "world"
        assert inp._draft_stash == "original"
        assert inp.text == "world"
        inp._history_idx = 2
        inp._history_navigate_skip_cmds(+1)  # forward past end → restore
        assert inp.text == "original"
        assert inp._draft_stash is None

    def test_draft_invalidated_on_text_change_at_idx_minus_one(self):
        """Changing text at idx==-1 to something different clears _draft_stash."""
        inp = _make(history=["cmd1"], text="foo")
        inp._draft_stash = "foo"
        inp._history_idx = -1
        # Simulate on_text_area_changed invalidation logic
        if inp._draft_stash is not None and inp._history_idx == -1:
            if inp.text != inp._draft_stash:
                inp._draft_stash = None
        # text still "foo" == stash, so NOT invalidated yet
        assert inp._draft_stash == "foo"
        # Now user types something different
        inp._text = "bar"
        if inp._draft_stash is not None and inp._history_idx == -1:
            if inp.text != inp._draft_stash:
                inp._draft_stash = None
        assert inp._draft_stash is None

    def test_draft_not_invalidated_during_history_nav(self):
        """_draft_stash is preserved while actively navigating history (idx != -1)."""
        inp = _make(history=["cmd1", "cmd2"], text="foo")
        inp._draft_stash = "foo"
        inp.action_history_prev()  # _history_idx = 1
        assert inp._history_idx != -1
        # Simulate on_text_area_changed: idx != -1, so stash is untouched
        inp._text = inp._history[inp._history_idx]  # text matches history entry
        if inp._draft_stash is not None and inp._history_idx == -1:
            if inp.text != inp._draft_stash:
                inp._draft_stash = None
        assert inp._draft_stash == "foo"

    def test_forward_past_end_clears_draft_after_restore(self):
        """After restoring stash by navigating past end, _draft_stash is None."""
        inp = _make(history=["cmd1"], text="my-draft")
        inp.action_history_prev()   # saves stash="my-draft", idx=0
        inp.action_history_next()   # past end → restores "my-draft", stash=None
        assert inp._draft_stash is None
        assert inp.text == "my-draft"

    def test_multiple_navigate_cycles_consistent(self):
        """type → ↑×5 → ↓×5 always returns to original text."""
        hist = ["h1", "h2", "h3", "h4", "h5"]
        inp = _make(history=hist, text="original")
        for _ in range(5):
            inp.action_history_prev()
        for _ in range(5):
            inp.action_history_next()
        assert inp.text == "original"
        assert inp._history_idx == -1

    def test_skip_cmds_draft_not_overwritten_on_second_backward(self):
        """Second Alt+Up (idx already non-(-1)) must not overwrite _draft_stash."""
        inp = _make(history=["hello", "world"], text="original")
        inp._history_navigate_skip_cmds(-1)  # saves stash="original", idx=1
        stash_after_first = inp._draft_stash
        inp._history_navigate_skip_cmds(-1)  # idx=0, stash should be unchanged
        assert inp._draft_stash == stash_after_first == "original"

    def test_skip_cmds_forward_noop_when_at_draft(self):
        """Alt+Down at idx==-1 (draft position) does nothing."""
        inp = _make(history=["hello"], text="draft text")
        loaded = []
        original_load = inp._history_load
        def tracking_load(t):
            loaded.append(t)
            original_load(t)
        inp._history_load = tracking_load  # type: ignore[attr-defined]
        inp._history_navigate_skip_cmds(+1)  # forward at draft pos
        assert loaded == []
        assert inp._history_idx == -1
