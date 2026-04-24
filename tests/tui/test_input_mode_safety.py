"""Tests for Input Mode Safety spec (2026-04-23).

Covers: A-1 (Enter in rev-search), D-1 (ghost-text guard), F-4 (Ctrl+G abort),
C-1 (bash placeholder/glyph), C-2 (Ctrl+C in bash), F-1 (Ctrl+U/K), A-3 (Alt+Up/Down).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeInput:
    """Plain Python fake for HermesInput — no Textual reactives."""

    def __init__(self, text="", history=None):
        self._history: list = list(history or [])
        self._history_idx: int = -1
        self._draft_stash: "str | None" = None
        self._history_loading: bool = False
        self._idle_placeholder: str = "Type a message  @file  /  commands"
        self._chevron_label: str = "❯ "
        self._rev_mode: bool = False
        self._rev_query: str = ""
        self._rev_idx: int = -1
        self._rev_match_idx: int = -1
        self._rev_saved_value: str = ""
        self.suggestion: str = ""
        self.placeholder: str = self._idle_placeholder
        self._text: str = text
        self._cursor_location: tuple = (0, len(text))
        self.app: object = MagicMock()
        self.app.feedback = MagicMock()

    @property
    def text(self) -> str:
        return self._text

    @property
    def cursor_location(self) -> tuple:
        return self._cursor_location

    @property
    def value(self) -> str:
        return self._text

    @value.setter
    def value(self, v: str):
        self._text = v

    def load_text(self, text: str):
        self._text = text
        self._cursor_location = (0, len(text))

    def move_cursor(self, loc):
        self._cursor_location = loc

    def query_one(self, selector, cls=None):
        raise Exception("no widget")

    def has_class(self, cls: str) -> bool:
        return False

    def set_class(self, condition: bool, cls: str):
        pass

    def save_draft_stash(self) -> None:
        if self._history_idx == -1:
            self._draft_stash = self.text


def _make_input(text="", history=None) -> "_FakeInput":
    return _FakeInput(text=text, history=history)


def _set_text(inp, text: str):
    inp._text = text
    inp._cursor_location = (0, len(text))


def _text(inp) -> str:
    return inp._text


# ============================================================================
# Phase A — Rev-search
# ============================================================================

class TestRevSearchCorrectness:

    def test_enter_in_rev_mode_accepts_and_submits(self):
        """Enter in rev-mode calls _exit_rev_mode(accept=True) then submits."""
        from hermes_cli.tui.input._history import _HistoryMixin
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input(history=["hello world"])
        inp._rev_mode = True
        inp._rev_match_idx = 0
        inp._text = "hello world"

        exited = []
        posted = []

        def fake_exit(accept=True):
            exited.append(accept)
            inp._rev_mode = False

        def fake_save(text):
            pass

        from hermes_cli.tui.input.widget import HermesInput as _HI
        inp._exit_rev_mode = fake_exit
        inp._save_to_history = fake_save
        inp._hide_completion_overlay = lambda: None
        inp.post_message = lambda m: posted.append(m.value)
        inp.disabled = False
        inp._input_height_override = 3
        inp._last_slash_hint_fragment = ""
        inp.Submitted = _HI.Submitted

        HermesInput.action_submit(inp)

        assert exited == [True], "Should call _exit_rev_mode(accept=True)"
        assert "hello world" in posted

    def test_enter_normal_mode_unaffected(self):
        """Enter outside rev-mode proceeds normally without accessing _rev_mode."""
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input(text="hello")
        inp._rev_mode = False
        inp.disabled = False
        inp._input_height_override = 3
        inp._last_slash_hint_fragment = ""
        inp.Submitted = HermesInput.Submitted

        saved = []
        posted = []
        inp._save_to_history = lambda t: saved.append(t)
        inp._hide_completion_overlay = lambda: None
        inp.post_message = lambda m: posted.append(m.value)

        HermesInput.action_submit(inp)

        assert saved == ["hello"]
        assert posted == ["hello"]

    def test_ghost_text_cleared_on_rev_search_entry(self):
        """suggestion is cleared when rev-search starts."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(history=["hello world", "foo bar"])
        inp.suggestion = "some ghost"
        inp._rev_mode = False

        _HistoryMixin.action_rev_search(inp)

        assert inp.suggestion == ""

    def test_ghost_text_suppressed_during_rev_mode(self):
        """update_suggestion is a no-op when _rev_mode is True."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(text="hel", history=["hello"])
        inp._rev_mode = True
        inp.suggestion = "sentinel"

        _HistoryMixin.update_suggestion(inp)

        assert inp.suggestion == "sentinel", "Should not be modified in rev-mode"

    def test_ctrl_g_aborts_rev_search(self):
        """Ctrl+G calls _exit_rev_mode(accept=False) and sets _rev_mode=False."""
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input()
        inp._rev_mode = True
        inp._rev_saved_value = "original"

        exited_with = []

        def fake_exit(accept=True):
            exited_with.append(accept)
            inp._rev_mode = False

        inp._exit_rev_mode = fake_exit
        HermesInput.action_abort_rev_search(inp)

        assert exited_with == [False]
        assert not inp._rev_mode

    def test_ctrl_g_noop_outside_rev_mode(self):
        """Ctrl+G does nothing when _rev_mode is False or attr absent."""
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input()
        inp._rev_mode = False

        calls = []
        inp._exit_rev_mode = lambda accept=True: calls.append(accept)
        HermesInput.action_abort_rev_search(inp)

        assert calls == []

    def test_esc_accepts_rev_match(self):
        """_exit_rev_search (Esc path) calls _exit_rev_mode(accept=True)."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(history=["hello"])
        inp._rev_mode = True
        inp._rev_match_idx = 0

        exited_with = []

        def fake_exit(accept=True):
            exited_with.append(accept)
            inp._rev_mode = False

        inp._exit_rev_mode = fake_exit
        _HistoryMixin._exit_rev_search(inp)

        assert exited_with == [True]

    def test_rev_search_hint_shown(self):
        """feedback.flash called with duration=9999 when rev-search starts."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(history=["hello"])
        inp._rev_mode = False

        _HistoryMixin.action_rev_search(inp)

        inp.app.feedback.flash.assert_called_once()
        call_args = inp.app.feedback.flash.call_args
        assert call_args[0][0] == "hint-bar"
        assert call_args[1].get("duration") == 9999

    def test_rev_search_hint_cleared_on_accept(self):
        """feedback.cancel("hint-bar") called when accepting rev-search."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(history=["one", "two"])
        inp._rev_mode = True
        inp._rev_saved_value = ""
        inp._rev_match_idx = -1

        _HistoryMixin._exit_rev_mode(inp, accept=True)

        inp.app.feedback.cancel.assert_called_with("hint-bar")

    def test_rev_search_hint_cleared_on_abort(self):
        """feedback.cancel("hint-bar") called when aborting rev-search."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input()
        inp._rev_mode = True
        inp._rev_saved_value = "original"
        inp._history_idx = -1
        inp._history_loading = False

        _HistoryMixin._exit_rev_mode(inp, accept=False)

        inp.app.feedback.cancel.assert_called_with("hint-bar")

    def test_history_idx_synced_after_rev_accept(self):
        """After rev-search accept, _history_idx equals matched entry index."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp = _make_input(history=["one", "two", "three"])
        inp._rev_mode = True
        inp._rev_saved_value = ""
        inp._rev_match_idx = 1  # matched "two"

        _HistoryMixin._exit_rev_mode(inp, accept=True)

        assert inp._history_idx == 1


# ============================================================================
# Phase B — Bash mode
# ============================================================================

class TestBashModeUI:

    def test_bash_mode_placeholder_set(self):
        """_sync_bash_mode_ui(True) sets bash placeholder."""
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input()
        HermesInput._sync_bash_mode_ui(inp, True)
        assert "shell mode" in inp.placeholder

    def test_bash_mode_placeholder_cleared_on_exit(self):
        """_sync_bash_mode_ui(False) restores _idle_placeholder."""
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_input()
        inp.placeholder = "! shell mode  ·  Enter runs  ·  Ctrl+C clear"
        HermesInput._sync_bash_mode_ui(inp, False)
        assert inp.placeholder == inp._idle_placeholder

    def test_bash_mode_chevron_is_dollar_sign(self):
        """_sync_bash_mode_ui(True) updates #input-chevron label to '$'."""
        from hermes_cli.tui.input.widget import HermesInput
        mock_label = MagicMock()
        inp = _make_input()
        inp.query_one = lambda *a, **kw: mock_label
        HermesInput._sync_bash_mode_ui(inp, True)
        mock_label.update.assert_called_with("$ ")

    def test_bash_mode_chevron_restored_on_exit(self):
        """_sync_bash_mode_ui(False) restores _chevron_label."""
        from hermes_cli.tui.input.widget import HermesInput
        mock_label = MagicMock()
        inp = _make_input()
        inp._chevron_label = "❯ "
        inp.query_one = lambda *a, **kw: mock_label
        HermesInput._sync_bash_mode_ui(inp, False)
        mock_label.update.assert_called_with("❯ ")

    def test_ctrl_c_clears_input_in_bash_mode(self):
        """Ctrl+C in bash mode (no running cmd) calls inp.clear()."""
        from hermes_cli.tui.services.keys import KeyDispatchService
        from textual.css.query import NoMatches

        mock_app = MagicMock()
        mock_app._get_selected_text.return_value = ""
        mock_app._svc_bash = MagicMock()
        mock_app._svc_bash.is_running = False

        mock_inp = MagicMock()
        mock_inp.has_class = lambda cls: cls == "--bash-mode"

        mock_app.query_one.return_value = mock_inp

        svc = object.__new__(KeyDispatchService)
        svc.app = mock_app

        event = MagicMock()
        event.key = "ctrl+c"

        svc.dispatch_key(event)

        mock_inp.clear.assert_called_once()
        event.prevent_default.assert_called()

    def test_ctrl_c_kills_running_bash_cmd(self):
        """Ctrl+C with running bash cmd calls _svc_bash.kill()."""
        from hermes_cli.tui.services.keys import KeyDispatchService

        mock_app = MagicMock()
        mock_app._get_selected_text.return_value = ""
        mock_app._svc_bash = MagicMock()
        mock_app._svc_bash.is_running = True

        mock_inp = MagicMock()
        mock_inp.has_class = lambda cls: cls == "--bash-mode"
        mock_app.query_one.return_value = mock_inp

        svc = object.__new__(KeyDispatchService)
        svc.app = mock_app

        event = MagicMock()
        event.key = "ctrl+c"

        svc.dispatch_key(event)

        mock_app._svc_bash.kill.assert_called_once()
        event.prevent_default.assert_called()

    def test_ctrl_c_normal_mode_unaffected(self):
        """Ctrl+C outside bash mode does not call inp.clear() via bash path."""
        from hermes_cli.tui.services.keys import KeyDispatchService

        mock_app = MagicMock()
        mock_app._get_selected_text.return_value = ""
        mock_app._svc_bash = MagicMock()
        mock_app._svc_bash.is_running = False

        mock_inp = MagicMock()
        mock_inp.has_class = lambda cls: False  # not in bash mode
        mock_app.query_one.return_value = mock_inp
        mock_app.agent_running = False
        # Simulate input with no content
        mock_inp_area = MagicMock()
        mock_inp_area.content = ""
        mock_app.query_one.return_value = mock_inp_area
        mock_inp_area.has_class = lambda cls: False

        svc = object.__new__(KeyDispatchService)
        svc.app = mock_app

        event = MagicMock()
        event.key = "ctrl+c"

        svc.dispatch_key(event)

        # clear() should NOT have been called as bash intercept
        # (agent_running=False path may call it for empty input → exit)
        # Verify _svc_bash.kill was NOT called (not a bash command)
        mock_app._svc_bash.kill.assert_not_called()

    def test_ctrl_c_empty_bash_mode_noop(self):
        """Ctrl+C with empty input in bash mode: clear() called, no crash."""
        from hermes_cli.tui.services.keys import KeyDispatchService

        mock_app = MagicMock()
        mock_app._get_selected_text.return_value = ""
        mock_app._svc_bash = MagicMock()
        mock_app._svc_bash.is_running = False

        mock_inp = MagicMock()
        mock_inp.has_class = lambda cls: cls == "--bash-mode"
        mock_app.query_one.return_value = mock_inp

        svc = object.__new__(KeyDispatchService)
        svc.app = mock_app

        event = MagicMock()
        event.key = "ctrl+c"

        # Should not raise
        svc.dispatch_key(event)
        mock_inp.clear.assert_called_once()


# ============================================================================
# Phase C — Readline bindings
# ============================================================================

class TestReadlineBindings:

    def _make_ta_inp(self, text: str, row: int, col: int):
        """Make input with mocked cursor/delete/get_line."""
        inp = _make_input(text=text)
        inp._cursor_location = (row, col)

        deleted_ranges = []
        inp.delete = lambda start, end: deleted_ranges.append((start, end))

        def fake_get_line(r):
            lines = text.split("\n")
            m = MagicMock()
            m.plain = lines[r] if r < len(lines) else ""
            return m

        inp.get_line = fake_get_line
        return inp, deleted_ranges

    def test_ctrl_u_kills_to_line_start(self):
        """Ctrl+U deletes from col 0 to cursor col on same row."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("hello world", 0, 5)
        HermesInput.action_kill_line_start(inp)
        assert deleted == [((0, 0), (0, 5))]

    def test_ctrl_u_at_line_start_noop(self):
        """Ctrl+U at col=0 does nothing."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("hello", 0, 0)
        HermesInput.action_kill_line_start(inp)
        assert deleted == []

    def test_ctrl_u_multiline_kills_current_line_prefix(self):
        """Ctrl+U on row 1 deletes only that row's prefix."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("line one\nline two", 1, 4)
        HermesInput.action_kill_line_start(inp)
        assert deleted == [((1, 0), (1, 4))]

    def test_ctrl_k_kills_to_line_end(self):
        """Ctrl+K deletes from cursor to end of line."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("hello world", 0, 5)
        HermesInput.action_kill_line_end(inp)
        assert deleted == [((0, 5), (0, 11))]

    def test_ctrl_k_at_line_end_noop(self):
        """Ctrl+K at end of line does nothing."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("hello", 0, 5)
        HermesInput.action_kill_line_end(inp)
        assert deleted == []

    def test_ctrl_k_multiline_kills_current_line_suffix(self):
        """Ctrl+K on row 0 deletes only that row's suffix."""
        from hermes_cli.tui.input.widget import HermesInput
        inp, deleted = self._make_ta_inp("line one\nline two", 0, 4)
        HermesInput.action_kill_line_end(inp)
        assert deleted == [((0, 4), (0, 8))]

    # --- Alt+Up/Down ---

    def _make_hist_inp(self, history, idx=-1):
        inp = _make_input(history=history)
        inp._history_idx = idx
        inp._draft_stash = None
        loaded = []

        def fake_load(text):
            inp._history_loading = True
            loaded.append(text)
            inp._text = text
            inp._history_loading = False

        inp._history_load = fake_load
        return inp, loaded

    def test_alt_up_skips_slash_commands(self):
        """Alt+Up lands on first non-slash entry going backward."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["hello", "/model gpt", "world"])
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        assert loaded == ["world"], f"Expected 'world', got {loaded}"
        assert inp._history_idx == 2

    def test_alt_up_skips_bang_commands(self):
        """Alt+Up skips !cmd entries."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["ask me", "!ls -la", "hello"])
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        assert loaded == ["hello"]
        assert inp._history_idx == 2

    def test_alt_up_saves_draft(self):
        """Alt+Up saves current text as draft before first nav."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["hello"])
        inp._text = "my draft"
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        assert inp._draft_stash == "my draft"

    def test_alt_up_draft_saved_once(self):
        """Draft not overwritten on subsequent Alt+Up presses."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["hello", "world"])
        inp._text = "original"
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        draft_after_first = inp._draft_stash
        # Second nav (idx now 1, not -1)
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        assert inp._draft_stash == draft_after_first == "original"

    def test_alt_up_no_prompts_stays_put(self):
        """If all entries are slash/bang, _history_idx stays unchanged."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["/model x", "!ls"])
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=-1)
        assert loaded == [], "Should not load anything"
        assert inp._history_idx == -1

    def test_alt_down_skips_commands(self):
        """Alt+Down forward navigation also skips slash/bang entries."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["ask", "/density", "real prompt", "!cmd"], idx=0)
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=+1)
        assert loaded == ["real prompt"]
        assert inp._history_idx == 2

    def test_alt_down_restores_draft(self):
        """Alt+Down past most-recent entry restores draft."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["hello"], idx=0)
        inp._draft_stash = "my draft"
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=+1)
        assert loaded == ["my draft"]
        assert inp._history_idx == -1

    def test_alt_down_noop_at_draft_position(self):
        """Alt+Down at _history_idx == -1 (draft) does nothing."""
        from hermes_cli.tui.input._history import _HistoryMixin
        inp, loaded = self._make_hist_inp(["hello"])
        _HistoryMixin._history_navigate_skip_cmds(inp, direction=+1)
        assert loaded == []
        assert inp._history_idx == -1
