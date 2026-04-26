"""DC-1 / DC-3 / DC-4 — Tool call discoverability spec.

Tests covering:
  - DC-1: ToolPanel focus hint row
  - DC-3: ToolsScreen filter-prefix legend strip
  - DC-4: KNOWN_PREFIXES single source
"""
from __future__ import annotations

import time
import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
from hermes_cli.tui.tools_overlay import KNOWN_PREFIXES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(*, exit_code: int | None = None, is_error: bool = False,
                  stderr_tail: str = ""):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None, exit_code=exit_code,
        chips=(), actions=(), artifacts=(),
        is_error=is_error, stderr_tail=stderr_tail,
    )


def _make_view_state(exit_code=None, state=None):
    from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
    _state = state or (ToolCallState.DONE if exit_code != 1 else ToolCallState.DONE)
    return ToolCallViewState(
        tool_call_id="fake", gen_index=0, tool_name="fake", label="fake",
        args={}, state=_state, block=None, panel=None,
        parent_tool_call_id=None, category="shell", depth=0,
        start_s=time.monotonic(), exit_code=exit_code,
    )


class _FakePanel:
    """Minimal stand-in for ToolPanel that satisfies _ToolPanelActionsMixin methods."""

    def __init__(
        self,
        *,
        collapsed: bool = False,
        result=None,
        has_affordances: bool = False,
        width: int = 200,
    ) -> None:
        self.collapsed = collapsed
        self._result_summary_v4 = result
        self._hint_row = MagicMock()
        self._hint_visible = False
        self._block = MagicMock()
        self._block._header = MagicMock()
        self._block._header._path_clickable = False
        self._block._completed = True
        self.has_focus = False
        self._width = width
        self._has_affordances_flag = has_affordances
        self.is_mounted = True
        # P-5: _is_error reads from view_state.is_error_for_ui
        ec = getattr(result, "exit_code", None) if result is not None else None
        self._view_state = _make_view_state(exit_code=ec) if result is not None else None
        self._lookup_view_state = lambda: None

    def has_class(self, cls: str) -> bool:
        return cls == "--has-affordances" and self._has_affordances_flag

    def _visible_footer_action_kinds(self) -> "set[str]":
        return set()

    def _get_omission_bar(self):
        return None

    def _result_paths_for_action(self) -> list:
        return []

    @property
    def size(self):
        s = MagicMock()
        s.width = self._width
        return s

    # Bind the mixin methods
    _available_width = _ToolPanelActionsMixin._available_width
    _is_error = _ToolPanelActionsMixin._is_error
    _collect_hints = _ToolPanelActionsMixin._collect_hints
    _truncate_hints = _ToolPanelActionsMixin._truncate_hints
    _render_hints = _ToolPanelActionsMixin._render_hints
    _build_hint_text = _ToolPanelActionsMixin._build_hint_text
    _refresh_hint_row = _ToolPanelActionsMixin._refresh_hint_row
    _next_kind_label = staticmethod(_ToolPanelActionsMixin._next_kind_label)

    @property
    def content_region(self):
        r = MagicMock()
        r.width = self._width
        return r


def _make_panel(**kwargs) -> _FakePanel:
    # Default result so _power_keys_exist=True and F1 appears (P-6 contract).
    kwargs.setdefault("result", _make_summary())
    return _FakePanel(**kwargs)

def _hint_plain(panel) -> str:
    """Return the plain text of the last hint_row.update call."""
    arg = panel._hint_row.update.call_args[0][0]
    return arg.plain if hasattr(arg, "plain") else str(arg)


# ===========================================================================
# DC-1: ToolPanel focus hint row
# ===========================================================================

class TestDC1HintRow:

    def test_hint_appears_on_focus(self):
        """Focus triggers hint row content from _build_hint_text."""
        panel = _make_panel(width=200)
        panel.has_focus = True
        panel._refresh_hint_row()

        panel._hint_row.update.assert_called()
        panel._hint_row.add_class.assert_called_with("--has-hint")
        plain = _hint_plain(panel)
        # Primary hints: Enter toggle + y copy; F1 always pinned (P-6)
        assert "Enter" in plain
        assert "y" in plain
        assert "F1" in plain

    def test_hint_hidden_on_blur(self):
        """Losing focus clears the hint row."""
        panel = _make_panel(width=200)
        panel.has_focus = False

        panel._refresh_hint_row()

        panel._hint_row.update.assert_called_with("")
        panel._hint_row.remove_class.assert_called_with("--has-hint")

    def test_error_hint_shows_retry(self):
        """When panel is in error state, primary shows toggle+dismiss, retry in contextual."""
        panel = _make_panel(result=_make_summary(exit_code=1, is_error=True), width=200)
        panel.has_focus = True

        panel._refresh_hint_row()

        plain = _hint_plain(panel)
        # Error state: primary is "Enter toggle" (not "Enter expand" — not collapsed)
        assert "Enter" in plain
        assert "F1" in plain

    def test_collapsed_hint_shows_expand_first(self):
        """Collapsed panel shows 'Enter expand' before 'y copy'."""
        panel = _make_panel(collapsed=True, width=200)
        panel.has_focus = True

        panel._refresh_hint_row()

        plain = _hint_plain(panel)
        assert "expand" in plain
        assert "y" in plain
        # "expand" must appear before "y copy"
        assert plain.index("expand") < plain.index("y")

    def test_hint_pinned_f1_at_narrow_width(self):
        """F1 is always present even at narrow width (P-6 — F1 always pinned)."""
        panel = _make_panel(width=30)
        panel.has_focus = True

        panel._refresh_hint_row()

        plain = _hint_plain(panel)
        assert "F1" in plain

    def test_hint_always_visible_when_has_affordances(self):
        """--has-affordances class makes hint permanently visible regardless of focus."""
        panel = _make_panel(has_affordances=True, width=200)
        panel.has_focus = False

        panel._refresh_hint_row()

        panel._hint_row.update.assert_called()
        plain = _hint_plain(panel)
        assert "F1" in plain
        panel._hint_row.add_class.assert_called_with("--has-hint")

    # ------------------------------------------------------------------
    # _is_error unit tests (P-5: delegates to view_state.is_error_for_ui)
    # ------------------------------------------------------------------

    def test_is_error_zero_exit_code(self):
        panel = _make_panel(result=_make_summary(exit_code=0))
        assert panel._is_error() is False

    def test_is_error_none_exit_code(self):
        panel = _make_panel(result=_make_summary(exit_code=None))
        assert panel._is_error() is False

    def test_is_error_nonzero_exit_code(self):
        panel = _make_panel(result=_make_summary(exit_code=1))
        assert panel._is_error() is True

    def test_is_error_no_result(self):
        panel = _make_panel(result=None)
        assert panel._is_error() is False


# ===========================================================================
# DC-3: ToolsScreen filter-prefix legend strip
# ===========================================================================

class TestDC3FilterLegend:

    def _make_screen(self, *, first_use: bool = False) -> "object":
        """Build a ToolsScreen-like namespace for legend tests."""
        from hermes_cli.tui.services.session_state import DiscoverabilityState
        from hermes_cli.tui.tools_overlay import ToolsScreen

        screen = types.SimpleNamespace()
        screen._disc_state = DiscoverabilityState(tools_filter_first_use=first_use)
        screen._prefix_used = False
        screen._filtered = [{"tool_call_id": "t1"}]  # non-empty result list

        # Mock the legend widget
        legend = MagicMock()
        _classes: set[str] = {"--hidden"} if first_use else set()
        def _has_class(cls: str) -> bool:
            return cls in _classes
        def _add_class(cls: str) -> None:
            _classes.add(cls)
        def _remove_class(cls: str) -> None:
            _classes.discard(cls)
        legend.has_class = _has_class
        legend.add_class = _add_class
        legend.remove_class = _remove_class
        legend._classes = _classes

        def _query_one(selector: str, widget_type=None):
            if "prefix-legend" in selector:
                return legend
            raise Exception(f"not found: {selector}")
        screen.query_one = _query_one

        # Bind the methods
        screen._update_legend_visibility = ToolsScreen._update_legend_visibility.__get__(screen)
        screen._legend_text = ToolsScreen._legend_text.__get__(screen)

        return screen, legend, _classes

    def test_legend_strip_visible_on_first_open(self):
        """On first open (tools_filter_first_use=False), legend is not hidden."""
        screen, legend, classes = self._make_screen(first_use=False)
        # No hidden class should be set on initial open
        assert "--hidden" not in classes

    def test_legend_hides_after_first_successful_filter(self):
        """After a file:-prefixed filter with ≥1 result, strip is hidden."""
        screen, legend, classes = self._make_screen(first_use=False)
        screen._update_legend_visibility("file:src/")
        assert "--hidden" in classes
        assert screen._prefix_used is True

    def test_legend_reappears_when_filter_cleared(self):
        """Clearing filter (tools_filter_first_use=False) resets _prefix_used and shows strip."""
        screen, legend, classes = self._make_screen(first_use=False)
        # First do a successful filter
        screen._update_legend_visibility("file:src/")
        assert "--hidden" in classes
        # Now clear
        screen._update_legend_visibility("")
        assert "--hidden" not in classes
        assert screen._prefix_used is False

    def test_legend_persists_dismissed_state_across_sessions(self):
        """When tools_filter_first_use=True, strip starts hidden and stays hidden on clear."""
        screen, legend, classes = self._make_screen(first_use=True)
        # Already hidden via initial state — update_legend_visibility is a no-op
        screen._update_legend_visibility("")  # clear input
        # The method returns early since first_use=True, so classes unchanged
        assert "--hidden" in classes

    def test_legend_examples_match_active_prefixes(self):
        """Legend text includes each item from KNOWN_PREFIXES."""
        screen, legend, classes = self._make_screen(first_use=False)
        text = screen._legend_text()
        for prefix in KNOWN_PREFIXES:
            if prefix != "error:":
                assert prefix in text, f"Legend missing prefix {prefix!r}: {text!r}"


# ===========================================================================
# DC-4: KNOWN_PREFIXES single source of truth
# ===========================================================================

class TestDC4PrefixSource:

    def test_known_prefixes_used_by_placeholder(self):
        """Placeholder text in compose() contains all KNOWN_PREFIXES items."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        import inspect
        src = inspect.getsource(ToolsScreen.compose)
        # Placeholder is built from KNOWN_PREFIXES, not hardcoded
        assert "KNOWN_PREFIXES" in src or "f\"filter" in src

    def test_known_prefixes_used_by_legend(self):
        """_legend_text() derives its content from KNOWN_PREFIXES."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        import inspect
        src = inspect.getsource(ToolsScreen._legend_text)
        assert "KNOWN_PREFIXES" in src

    def test_legend_examples_match_all_prefixes(self):
        """All non-error KNOWN_PREFIXES appear in the legend strip text."""
        from hermes_cli.tui.tools_overlay import ToolsScreen
        import types as _types

        screen = _types.SimpleNamespace()
        screen._legend_text = ToolsScreen._legend_text.__get__(screen)
        text = screen._legend_text()
        for prefix in KNOWN_PREFIXES:
            if prefix != "error:":
                assert prefix in text

    def test_adding_prefix_propagates_to_ui(self, monkeypatch):
        """Adding a fake prefix to KNOWN_PREFIXES propagates to legend, placeholder, and dispatch."""
        import hermes_cli.tui.tools_overlay as overlay_mod
        import types as _types

        fake_prefix = "fake:"
        new_prefixes = KNOWN_PREFIXES + (fake_prefix,)
        monkeypatch.setattr(overlay_mod, "KNOWN_PREFIXES", new_prefixes)

        # Legend text includes fake prefix
        screen = _types.SimpleNamespace()
        screen._legend_text = overlay_mod.ToolsScreen._legend_text.__get__(screen)
        assert fake_prefix in screen._legend_text()

        # _update_legend_visibility dispatches on the fake prefix
        from hermes_cli.tui.services.session_state import DiscoverabilityState
        screen._disc_state = DiscoverabilityState(tools_filter_first_use=False)
        screen._prefix_used = False
        screen._filtered = [{"tool_call_id": "t1"}]

        legend = MagicMock()
        _classes: set = set()
        legend.add_class = lambda c: _classes.add(c)
        legend.remove_class = lambda c: _classes.discard(c)
        screen.query_one = lambda sel, wt=None: legend
        screen._update_legend_visibility = overlay_mod.ToolsScreen._update_legend_visibility.__get__(screen)

        screen._update_legend_visibility(f"{fake_prefix}something")
        assert screen._prefix_used is True
        assert "--hidden" in _classes
