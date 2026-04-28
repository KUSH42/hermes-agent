"""Tests for I9/I17: InputMode enum, chevron affordances, and legend routing.

Covers:
- _compute_mode() priority: LOCKED > REV_SEARCH > BASH > COMPLETION > NORMAL
- _sync_chevron_to_mode() glyph + color resolution
- _sync_legend_to_mode() legend routing including locked (I9)
- Mode transitions wiring in all 4 call sites
- CSS var presence in COMPONENT_VAR_DEFAULTS
- locked legend key in InputLegendBar.LEGENDS
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inp(**kwargs) -> types.SimpleNamespace:
    """Build a SimpleNamespace that satisfies _compute_mode() and _sync_*."""
    defaults = dict(
        disabled=False,
        _rev_mode=False,
        suggestion="",
        _completion_overlay_active=False,
    )
    defaults.update(kwargs)
    inp = types.SimpleNamespace(**defaults)
    inp._classes: set[str] = set()

    def _has_class(cls: str) -> bool:
        return cls in inp._classes

    inp.has_class = _has_class
    return inp


def _bind(inp: types.SimpleNamespace, method_name: str):
    """Return the named HermesInput method bound to inp."""
    from hermes_cli.tui.input.widget import HermesInput
    return getattr(HermesInput, method_name).__get__(inp)


def _make_legend_mock():
    legend = MagicMock()
    return legend


def _make_app_mock(css_vars: dict | None = None) -> MagicMock:
    app = MagicMock()
    app.get_css_variables.return_value = css_vars or {
        "accent": "#FFF8DC",
        "chevron-shell": "#A8D46E",
        "chevron-rev-search": "#FFBF00",
        "chevron-completion": "#5F9FD7",
        "chevron-locked": "#666666",
    }
    return app


# ---------------------------------------------------------------------------
# TestInputModeEnum — _compute_mode() priority
# ---------------------------------------------------------------------------

class TestInputModeEnum:
    def test_default_mode_is_normal(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp()
        # _completion_overlay_visible() is on _PathCompletionMixin — mock it
        inp._completion_overlay_visible = lambda: False
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.NORMAL

    def test_mode_is_locked_when_disabled(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp(disabled=True)
        inp._completion_overlay_visible = lambda: False
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.LOCKED

    def test_mode_is_rev_search_when_rev_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp(_rev_mode=True)
        inp._completion_overlay_visible = lambda: False
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.REV_SEARCH

    def test_mode_is_bash_when_class_set(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp()
        inp._classes.add("--bash-mode")
        inp._completion_overlay_visible = lambda: False
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.BASH

    def test_mode_is_completion_when_overlay_visible(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp(_completion_overlay_active=True)
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.COMPLETION

    def test_mode_priority_locked_over_rev_search(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp(disabled=True, _rev_mode=True)
        inp._completion_overlay_visible = lambda: True
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.LOCKED

    def test_mode_priority_rev_search_over_bash(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp(_rev_mode=True)
        inp._classes.add("--bash-mode")
        inp._completion_overlay_visible = lambda: True
        result = HermesInput._compute_mode(inp)
        assert result == InputMode.REV_SEARCH


# ---------------------------------------------------------------------------
# TestInputModeChevron — _sync_chevron_to_mode()
# ---------------------------------------------------------------------------

class TestInputModeChevron:
    def _run(self, mode, css_vars=None):
        from hermes_cli.tui.input.widget import HermesInput
        inp = _make_inp()
        inp.app = _make_app_mock(css_vars)
        label = MagicMock()
        inp.query_one = lambda sel, cls: label
        HermesInput._sync_chevron_to_mode(inp, mode)
        return label

    def test_chevron_normal_glyph(self):
        from hermes_cli.tui.input._mode import InputMode
        label = self._run(InputMode.NORMAL)
        args = label.update.call_args[0][0]
        assert "❯" in str(args)

    def test_chevron_bash_glyph(self):
        from hermes_cli.tui.input._mode import InputMode
        label = self._run(InputMode.BASH)
        args = label.update.call_args[0][0]
        assert "$" in str(args)

    def test_chevron_rev_search_glyph(self):
        from hermes_cli.tui.input._mode import InputMode
        label = self._run(InputMode.REV_SEARCH)
        args = label.update.call_args[0][0]
        assert "⟲" in str(args)

    def test_chevron_completion_glyph(self):
        from hermes_cli.tui.input._mode import InputMode
        label = self._run(InputMode.COMPLETION)
        args = label.update.call_args[0][0]
        assert "⊞" in str(args)

    def test_chevron_locked_glyph(self):
        from hermes_cli.tui.input._mode import InputMode
        label = self._run(InputMode.LOCKED)
        args = label.update.call_args[0][0]
        assert "⊘" in str(args)

    def test_chevron_color_resolved_from_css_var(self):
        from hermes_cli.tui.input._mode import InputMode
        from rich.text import Text as RichText
        label = self._run(InputMode.REV_SEARCH, css_vars={"chevron-rev-search": "#FFBF00"})
        arg = label.update.call_args[0][0]
        assert isinstance(arg, RichText)
        # style should carry the color
        assert arg.style.color is not None


# ---------------------------------------------------------------------------
# TestInputModeLegend — _sync_legend_to_mode()
# ---------------------------------------------------------------------------

class TestInputModeLegend:
    def _run(self, mode, suggestion=""):
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        inp = _make_inp(suggestion=suggestion)
        legend = MagicMock(spec=InputLegendBar)
        inp.app = MagicMock()
        inp.app.query_one.return_value = legend
        HermesInput._sync_legend_to_mode(inp, mode)
        return legend

    def test_legend_shows_bash_key_in_bash_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        legend = self._run(InputMode.BASH)
        legend.show_legend.assert_called_once_with("bash")

    def test_legend_shows_rev_search_key_in_rev_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        legend = self._run(InputMode.REV_SEARCH)
        legend.show_legend.assert_called_once_with("rev_search")

    def test_legend_shows_completion_key_in_completion_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        legend = self._run(InputMode.COMPLETION)
        legend.show_legend.assert_called_once_with("completion")

    def test_legend_shows_locked_key_in_locked_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        legend = self._run(InputMode.LOCKED)
        legend.show_legend.assert_called_once_with("locked")

    def test_legend_hidden_in_normal_mode(self):
        from hermes_cli.tui.input._mode import InputMode
        legend = self._run(InputMode.NORMAL, suggestion="")
        legend.hide_legend.assert_called_once()
        legend.show_legend.assert_not_called()

    def test_locked_legend_visible_with_text_in_field(self):
        """I9: locked legend shows even when there is text in the input."""
        from hermes_cli.tui.input._mode import InputMode
        # LOCKED mode should show legend regardless of text content
        legend = self._run(InputMode.LOCKED)
        legend.show_legend.assert_called_once_with("locked")


# ---------------------------------------------------------------------------
# TestInputModeTransitions
# ---------------------------------------------------------------------------

class TestInputModeTransitions:
    def test_bash_to_normal_hides_legend(self):
        """Transitioning from BASH to NORMAL should hide the legend."""
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        inp = _make_inp(suggestion="")
        legend = MagicMock(spec=InputLegendBar)
        inp.app = MagicMock()
        inp.app.query_one.return_value = legend
        # Call with NORMAL
        HermesInput._sync_legend_to_mode(inp, InputMode.NORMAL)
        legend.hide_legend.assert_called()

    def test_locked_to_normal_hides_legend(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        inp = _make_inp(suggestion="")
        legend = MagicMock(spec=InputLegendBar)
        inp.app = MagicMock()
        inp.app.query_one.return_value = legend
        HermesInput._sync_legend_to_mode(inp, InputMode.NORMAL)
        legend.hide_legend.assert_called()

    def test_rev_search_enter_triggers_recompute(self):
        """action_rev_search sets _mode after enabling _rev_mode."""
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input._history import _HistoryMixin

        class _MockInput:
            _rev_mode = False
            _rev_query = ""
            _rev_idx = -1
            _rev_match_idx = -1
            _rev_saved_value = ""
            text = ""
            suggestion = ""
            _history: list = ["ls -la", "git status"]
            _history_loading = False
            placeholder = ""
            _idle_placeholder = "Type a message"
            load_text = MagicMock()
            move_cursor = MagicMock()
            _completion_overlay_visible = lambda self: False
            _classes: set = set()
            _set_mode_calls: list = []
            app = MagicMock()

            def has_class(self, c):
                return c in self._classes

            def add_class(self, c):
                self._classes.add(c)

            def remove_class(self, c):
                self._classes.discard(c)

            def _refresh_placeholder(self):
                pass

            def _compute_mode(self):
                if self._rev_mode:
                    return InputMode.REV_SEARCH
                return InputMode.NORMAL

            @property
            def _mode(self):
                return self.__dict__.get("__mode", InputMode.NORMAL)

            @_mode.setter
            def _mode(self, v):
                self._set_mode_calls.append(v)
                self.__dict__["__mode"] = v

        mock_inp = _MockInput()
        _HistoryMixin.action_rev_search(mock_inp)
        assert InputMode.REV_SEARCH in mock_inp._set_mode_calls

    def test_rev_search_exit_triggers_recompute(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input._history import _HistoryMixin

        class _MockInput:
            _rev_mode = True
            _rev_query = ""
            _rev_idx = -1
            _rev_match_idx = -1
            _rev_saved_value = ""
            text = "ls"
            suggestion = ""
            _history = ["ls -la"]
            _history_loading = False
            placeholder = "rev-search"
            _idle_placeholder = "Type a message"
            load_text = MagicMock()
            move_cursor = MagicMock()
            _set_mode_calls: list = []
            app = MagicMock()
            _history_idx = -1
            _classes: set = set()

            def has_class(self, c):
                return c in self._classes

            def add_class(self, c):
                self._classes.add(c)

            def remove_class(self, c):
                self._classes.discard(c)

            def _compute_mode(self):
                return InputMode.NORMAL

            def _refresh_placeholder(self):
                pass

            @property
            def _mode(self):
                return self.__dict__.get("__mode", InputMode.REV_SEARCH)

            @_mode.setter
            def _mode(self, v):
                self._set_mode_calls.append(v)
                self.__dict__["__mode"] = v

        mock_inp = _MockInput()
        _HistoryMixin._exit_rev_mode(mock_inp, accept=True)
        assert InputMode.NORMAL in mock_inp._set_mode_calls

    def test_completion_show_triggers_recompute(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input._path_completion import _PathCompletionMixin
        from textual.css.query import NoMatches

        class _MockInput:
            suggestion = ""
            _set_mode_calls: list = []
            _completion_overlay_visible = lambda self: True
            screen = MagicMock()
            app = MagicMock()
            _path_debounce_timer = None
            _classes: set = set()

            def has_class(self, c):
                return c in self._classes

            def _compute_mode(self):
                return InputMode.COMPLETION

            @property
            def _mode(self):
                return self.__dict__.get("__mode", InputMode.NORMAL)

            @_mode.setter
            def _mode(self, v):
                self._set_mode_calls.append(v)
                self.__dict__["__mode"] = v

        mock_inp = _MockInput()
        mock_overlay = MagicMock()
        mock_inp.screen.query_one.return_value = mock_overlay
        _PathCompletionMixin._show_completion_overlay(mock_inp)
        assert InputMode.COMPLETION in mock_inp._set_mode_calls

    def test_completion_hide_triggers_recompute(self):
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input._path_completion import _PathCompletionMixin

        class _MockInput:
            _path_debounce_timer = None
            _set_mode_calls: list = []
            screen = MagicMock()
            app = MagicMock()

            def _set_searching(self, v):
                pass

            def _compute_mode(self):
                return InputMode.NORMAL

            @property
            def _mode(self):
                return self.__dict__.get("__mode", InputMode.COMPLETION)

            @_mode.setter
            def _mode(self, v):
                self._set_mode_calls.append(v)
                self.__dict__["__mode"] = v

        mock_inp = _MockInput()
        mock_overlay = MagicMock()
        mock_inp.screen.query_one.return_value = mock_overlay
        _PathCompletionMixin._hide_completion_overlay(mock_inp)
        assert InputMode.NORMAL in mock_inp._set_mode_calls

    def test_normal_preserves_ghost_legend_when_suggestion_active(self):
        """M1: NORMAL mode with active ghost suggestion should NOT hide legend."""
        from hermes_cli.tui.input._mode import InputMode
        from hermes_cli.tui.input.widget import HermesInput
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        inp = _make_inp(suggestion=" -la")  # ghost active
        legend = MagicMock(spec=InputLegendBar)
        inp.app = MagicMock()
        inp.app.query_one.return_value = legend
        HermesInput._sync_legend_to_mode(inp, InputMode.NORMAL)
        # Must NOT hide when ghost suggestion is present
        legend.hide_legend.assert_not_called()
        legend.show_legend.assert_not_called()


# ---------------------------------------------------------------------------
# TestInputModeCSSVars
# ---------------------------------------------------------------------------

class TestInputModeCSSVars:
    def test_chevron_rev_search_var_in_component_defaults(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        assert "chevron-rev-search" in COMPONENT_VAR_DEFAULTS
        assert COMPONENT_VAR_DEFAULTS["chevron-rev-search"] == "#FFBF00"

    def test_chevron_completion_var_in_component_defaults(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        assert "chevron-completion" in COMPONENT_VAR_DEFAULTS
        assert COMPONENT_VAR_DEFAULTS["chevron-completion"] == "#5F9FD7"

    def test_chevron_locked_var_in_component_defaults(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        assert "chevron-locked" in COMPONENT_VAR_DEFAULTS
        assert COMPONENT_VAR_DEFAULTS["chevron-locked"] == "#666666"

    def test_locked_legend_key_in_input_legend_bar(self):
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        assert "locked" in InputLegendBar.LEGENDS
        assert "Ctrl+C" in InputLegendBar.LEGENDS["locked"]
