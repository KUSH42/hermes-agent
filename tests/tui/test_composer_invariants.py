from __future__ import annotations

import ast
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
from hermes_cli.tui.input._assist import AssistKind, SKILL_PICKER_TRIGGER_PREFIX
from hermes_cli.tui.input._history import _HistoryMixin
from hermes_cli.tui.input._mode import InputMode
from hermes_cli.tui.input._path_completion import _PathCompletionMixin
from hermes_cli.tui.input.widget import HermesInput, _CHEVRON_GLYPHS


class _FakePicker:
    def __init__(self) -> None:
        self.dismiss = MagicMock()
        self._trigger = SKILL_PICKER_TRIGGER_PREFIX


class _FakeInput:
    def __init__(self) -> None:
        self.disabled = False
        self._locked = False
        self._pre_lock_disabled = False
        self._rev_mode = False
        self._rev_query = ""
        self._completion_overlay_active = False
        self.error_state = None
        self._idle_placeholder = "idle"
        self.placeholder = "idle"
        self.is_mounted = True
        self._classes: set[str] = set()
        self.suggestion = ""
        self._history = ["hello world", "other entry"]
        self._history_idx = -1
        self._history_loading = False
        self._rev_idx = -1
        self._rev_match_idx = -1
        self._rev_saved_value = ""
        self._draft_stash = None
        self._current_trigger = CompletionTrigger(CompletionContext.SKILL_INVOKE, "git", 0)
        self._path_debounce_timer = None
        self._mode = InputMode.NORMAL
        self.app = MagicMock()
        self.app._open_skill_picker = MagicMock()
        self.app.feedback = MagicMock()
        self._picker: _FakePicker | None = None

    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)

    def has_class(self, cls: str) -> bool:
        return cls in self._classes

    def set_class(self, enabled: bool, cls: str) -> None:
        if enabled:
            self.add_class(cls)
        else:
            self.remove_class(cls)

    def _show_completion_overlay(self) -> None:
        self._completion_overlay_active = True

    def _hide_completion_overlay(self) -> None:
        self._completion_overlay_active = False

    def _dismiss_skill_picker(self) -> None:
        if self._picker is not None:
            self._picker.dismiss()

    def _compute_mode(self) -> InputMode:
        return HermesInput._compute_mode(self)

    def _refresh_placeholder(self) -> None:
        HermesInput._refresh_placeholder(self)

    def _resolve_assist(self, kind: AssistKind, suggestion: str = "") -> None:
        HermesInput._resolve_assist(self, kind, suggestion)

    def load_text(self, text: str) -> None:
        self.text = text

    def move_cursor(self, loc: tuple[int, int]) -> None:
        self.cursor_location = loc


def test_set_input_locked_without_disabled_resolves_locked_mode() -> None:
    inp = _FakeInput()
    HermesInput._set_input_locked(inp, True)
    assert inp.disabled is True
    assert inp._compute_mode() is InputMode.LOCKED
    assert inp.placeholder.startswith("running")


def test_unlock_restores_prior_disabled_state() -> None:
    inp = _FakeInput()
    inp.disabled = True
    HermesInput._set_input_locked(inp, True)
    HermesInput._set_input_locked(inp, False)
    assert inp.disabled is True


def test_refresh_placeholder_completion_branch_shows_completion_text() -> None:
    inp = _FakeInput()
    inp._completion_overlay_active = True
    HermesInput._refresh_placeholder(inp)
    assert inp.placeholder == "↑↓ select  ·  Tab accept  ·  Esc close"


def test_refresh_placeholder_completion_branch_beats_bash_text() -> None:
    inp = _FakeInput()
    inp._completion_overlay_active = True
    inp.add_class("--bash-mode")
    HermesInput._refresh_placeholder(inp)
    assert "select" in inp.placeholder


def test_watch_error_state_adds_error_class_to_host() -> None:
    inp = _FakeInput()
    inp.error_state = "boom"
    HermesInput.watch_error_state(inp, "boom")
    assert inp.has_class("--error")


def test_action_rev_search_toggles_rev_search_class() -> None:
    inp = _FakeInput()
    _HistoryMixin.action_rev_search(inp)
    assert inp.has_class("--rev-search")
    _HistoryMixin._exit_rev_mode(inp, accept=True)
    assert not inp.has_class("--rev-search")


def test_draft_stash_cleared_on_exit_rev_mode() -> None:
    inp = _FakeInput()
    inp._rev_mode = True
    inp._draft_stash = "draft"
    _HistoryMixin._exit_rev_mode(inp, accept=True)
    assert inp._draft_stash is None


def test_compute_mode_reads_mirror_flag_not_dom() -> None:
    inp = _FakeInput()
    inp._completion_overlay_active = True
    mock_screen = MagicMock()
    inp.screen = mock_screen
    assert HermesInput._compute_mode(inp) is InputMode.COMPLETION
    assert mock_screen.query_one.call_count == 0


def test_resolve_none_clears_all_three() -> None:
    inp = _FakeInput()
    inp.suggestion = "ghost"
    inp._completion_overlay_active = True
    inp._picker = _FakePicker()
    inp._resolve_assist(AssistKind.NONE)
    assert inp.suggestion == ""
    assert inp._completion_overlay_active is False
    inp._picker.dismiss.assert_called_once()


def test_resolve_overlay_when_picker_open_dismisses_picker() -> None:
    inp = _FakeInput()
    inp._picker = _FakePicker()
    inp._resolve_assist(AssistKind.OVERLAY)
    assert inp._completion_overlay_active is True
    inp._picker.dismiss.assert_called_once()


def test_resolve_picker_hides_overlay_and_opens_picker() -> None:
    inp = _FakeInput()
    inp._completion_overlay_active = True
    inp._resolve_assist(AssistKind.PICKER)
    assert inp._completion_overlay_active is False
    inp.app._open_skill_picker.assert_called_once_with(
        seed_filter="git",
        trigger_source=SKILL_PICKER_TRIGGER_PREFIX,
    )


def test_mode_stable_after_overlay_show() -> None:
    overlay = MagicMock()
    widget = types.SimpleNamespace()
    widget.app = types.SimpleNamespace(_completion_hint="")
    widget._completion_overlay_active = False
    widget._mode = InputMode.NORMAL
    widget.screen = MagicMock()
    widget.screen.query_one.return_value = overlay
    widget._compute_mode = lambda: HermesInput._compute_mode(widget)
    widget._show_completion_overlay = _PathCompletionMixin._show_completion_overlay.__get__(widget)
    widget.disabled = False
    widget._rev_mode = False
    widget._classes = set()
    widget.has_class = lambda cls: cls in widget._classes

    widget._show_completion_overlay()

    assert widget._mode is InputMode.COMPLETION
    assert widget.screen.query_one.call_count == 1


@pytest.mark.parametrize(
    ("mode", "expected_class"),
    [
        (InputMode.BASH, "--bash-mode"),
        (InputMode.REV_SEARCH, "--rev-search"),
        (InputMode.COMPLETION, None),
        (InputMode.LOCKED, "--locked"),
    ],
)
def test_each_mode_has_at_least_two_channels(mode: InputMode, expected_class: str | None) -> None:
    inp = _FakeInput()
    if mode is InputMode.BASH:
        inp.add_class("--bash-mode")
    elif mode is InputMode.REV_SEARCH:
        inp._rev_mode = True
        inp.add_class("--rev-search")
        inp._rev_query = "foo"
    elif mode is InputMode.COMPLETION:
        inp._completion_overlay_active = True
    elif mode is InputMode.LOCKED:
        HermesInput._set_input_locked(inp, True)
    HermesInput._refresh_placeholder(inp)

    channels = 0
    if _CHEVRON_GLYPHS[mode] != _CHEVRON_GLYPHS[InputMode.NORMAL]:
        channels += 1
    if expected_class and inp.has_class(expected_class):
        channels += 1
    if inp.placeholder != inp._idle_placeholder:
        channels += 1
    assert channels >= 2


def test_trigger_prefix_constant_used_for_picker_dismiss() -> None:
    source = Path("hermes_cli/tui/input/_autocomplete.py").read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "SKILL_PICKER_TRIGGER_PREFIX" in names
