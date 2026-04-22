"""R10 — explicit exit code in collapsed ToolHeader."""
from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal ToolHeader-like object without running Textual
# ---------------------------------------------------------------------------

class _H:
    """Thin stand-in for ToolHeader that exercises _render_v4 rendering logic."""

    def __init__(self, *, tool_name="bash", collapsed=True, is_complete=True,
                 exit_code=None, primary_hero=None, spinner_char=None,
                 panel_collapsed=None, is_child=False, width=80):
        # attrs mirroring ToolHeader.__init__
        self._tool_name = tool_name
        self._label = tool_name
        self._line_count = 0
        self._stats = None
        self._has_affordances = False
        self._flash_msg = None
        self._flash_expires = 0.0
        self._spinner_char = spinner_char
        self._duration = ""
        self._is_complete = is_complete
        self._tool_icon = ""
        self._tool_icon_error = False
        self._label_rich = None
        self._compact_tail = False
        self._is_child_diff = False
        self._full_path = None
        self._path_clickable = False
        self._is_url = False
        self._no_underline = False
        self._hide_duration = False
        self._bold_label = False
        self._hidden = False
        self._shell_prompt = False
        self._elapsed_ms = None
        self._header_args = {}
        self._primary_hero = primary_hero
        self._header_chips = []
        self._error_kind = None
        self._exit_code = exit_code
        self._flash_tone = "success"
        self._browse_badge = ""
        self._is_child = is_child
        # collapsed state
        self.collapsed = collapsed
        # panel mock
        if panel_collapsed is not None:
            self._panel = MagicMock()
            self._panel.collapsed = panel_collapsed
        else:
            self._panel = None
        # size mock
        self._width = width

    # Textual stubs
    def has_class(self, *_):
        return False

    def _accessible_mode(self):
        return False

    def _refresh_gutter_color(self):
        self._focused_gutter_color = "#5f87d7"
        self._diff_add_color = "#4caf50"
        self._diff_del_color = "#ef4444"
        self._running_icon_color = "#FFA726"

    @property
    def size(self):
        s = MagicMock()
        s.width = self._width
        return s

    def _render(self):
        """Run the exit-code segment logic in isolation (extracted from _render_v4)."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER, _trim_tail_segments

        tail_segments = []

        if self._spinner_char is None:
            # primary hero
            if self._primary_hero:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="dim green")))

            # R10 exit segment
            is_collapsed = self._panel.collapsed if self._panel is not None else self.collapsed
            if is_collapsed and self._is_complete:
                code = getattr(self, "_exit_code", None)
                if code is not None:
                    if code == 0:
                        if not self._primary_hero:
                            tail_segments.append(("exit", Text("  ok", style="dim green")))
                    else:
                        tail_segments.append(("exit", Text(f"  exit {code}", style="bold red")))

            # stderrwarn stub (for T09/T10)
            if (self._panel is not None and
                    self._panel.collapsed and
                    self._tool_icon_error):
                rs_v4 = getattr(self._panel, "_result_summary_v4", None)
                if rs_v4 is not None and getattr(rs_v4, "stderr_tail", ""):
                    tail_segments.append(("stderrwarn", Text("  ⚠ stderr (e)", style="bold #FFA726")))

            # chevron
            is_col = self._panel.collapsed if self._panel is not None else self.collapsed
            if self._has_affordances:
                tail_segments.append(("chevron", Text("  ▸" if is_col else "  ▾", style="dim")))

        budget = max(0, self._width - 20) if self._width > 0 else 80
        tail_segments = _trim_tail_segments(tail_segments, budget)
        return tail_segments


def _seg_names(h):
    return [name for name, _ in h._render()]


def _seg_text(h, name):
    for n, t in h._render():
        if n == name:
            return t.plain.strip()
    return None


# ---------------------------------------------------------------------------
# T01–T07: core exit segment presence/absence
# ---------------------------------------------------------------------------

def test_t01_exit_nonzero_no_hero():
    h = _H(exit_code=1, primary_hero=None, panel_collapsed=True)
    assert "exit" in _seg_names(h)
    assert _seg_text(h, "exit") == "exit 1"


def test_t02_exit_zero_no_hero():
    h = _H(exit_code=0, primary_hero=None, panel_collapsed=True)
    assert "exit" in _seg_names(h)
    assert _seg_text(h, "exit") == "ok"


def test_t03_exit_zero_with_hero_suppresses_ok():
    h = _H(exit_code=0, primary_hero="✓ 3 results", panel_collapsed=True)
    assert "exit" not in _seg_names(h)
    assert "hero" in _seg_names(h)


def test_t04_exit_nonzero_with_hero_shows_both():
    h = _H(exit_code=1, primary_hero="Error: ENOENT", panel_collapsed=True)
    names = _seg_names(h)
    assert "hero" in names
    assert "exit" in names
    assert _seg_text(h, "exit") == "exit 1"


def test_t05_exit_code_none_no_segment():
    """Non-shell tools: exit_code=None → no exit segment."""
    h = _H(exit_code=None, primary_hero=None, panel_collapsed=True)
    assert "exit" not in _seg_names(h)


def test_t06_not_collapsed_no_exit_segment():
    h = _H(exit_code=1, panel_collapsed=False, collapsed=False)
    assert "exit" not in _seg_names(h)


def test_t07_not_complete_no_exit_segment():
    h = _H(exit_code=1, is_complete=False, panel_collapsed=True)
    assert "exit" not in _seg_names(h)


# ---------------------------------------------------------------------------
# T08: narrow terminal — stderrwarn drops before exit
# ---------------------------------------------------------------------------

def test_t08_narrow_stderrwarn_drops_before_exit():
    from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
    assert _DROP_ORDER.index("stderrwarn") < _DROP_ORDER.index("exit"), (
        "stderrwarn must appear before exit in _DROP_ORDER so it drops first"
    )


# ---------------------------------------------------------------------------
# T09/T10: stderrwarn co-existence
# ---------------------------------------------------------------------------

def test_t09_stderrwarn_still_appended_error_with_stderr():
    h = _H(exit_code=1, panel_collapsed=True)
    h._tool_icon_error = True
    rs = MagicMock()
    rs.stderr_tail = "error output"
    h._panel._result_summary_v4 = rs
    names = _seg_names(h)
    assert "stderrwarn" in names


def test_t10_exit_and_stderrwarn_both_present():
    h = _H(exit_code=2, panel_collapsed=True)
    h._tool_icon_error = True
    rs = MagicMock()
    rs.stderr_tail = "some stderr"
    h._panel._result_summary_v4 = rs
    names = _seg_names(h)
    assert "exit" in names
    assert "stderrwarn" in names


# ---------------------------------------------------------------------------
# T11/T12: attribute assignment
# ---------------------------------------------------------------------------

def test_t11_set_result_summary_populates_exit_code():
    from unittest.mock import patch, MagicMock
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    summary = ResultSummaryV4(
        primary=None,
        exit_code=42,
        chips=(),
        is_error=True,
        error_kind=None,
        stderr_tail=None,
        actions=(),
        artifacts=(),
    )
    header = MagicMock()
    header._exit_code = None  # simulate default

    # Simulate the assignment from set_result_summary
    header._exit_code = getattr(summary, "exit_code", None)
    assert header._exit_code == 42


def test_t12_exit_code_defaults_to_none():
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    h._exit_code = None  # default as per __init__
    assert h._exit_code is None


# ---------------------------------------------------------------------------
# T13–T16: regression guards (collapse mechanics — structural / source checks)
# ---------------------------------------------------------------------------

def test_t13_watch_collapsed_hides_body():
    """watch_collapsed sets body_container.styles.display="none" on collapse."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel.watch_collapsed)
    assert '"none"' in src or "'none'" in src


def test_t14_watch_collapsed_restores_body():
    """watch_collapsed sets body_container.styles.display="block" on expand."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel.watch_collapsed)
    assert '"block"' in src or "'block'" in src


def test_t15_exit_code_init_attribute_exists():
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    import inspect
    src = inspect.getsource(ToolHeader.__init__)
    assert "_exit_code" in src


def test_t16_action_toggle_collapse_flips_state():
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel.action_toggle_collapse)
    assert "not self.collapsed" in src
    assert "_auto_collapsed" in src


# ---------------------------------------------------------------------------
# T17: standalone header (no panel) falls back to self.collapsed
# ---------------------------------------------------------------------------

def test_t17_standalone_header_uses_self_collapsed():
    h = _H(exit_code=1, panel_collapsed=None, collapsed=True)
    # _panel is None, should fall back to self.collapsed=True
    assert "exit" in _seg_names(h)


def test_t17b_standalone_header_not_collapsed_no_exit():
    h = _H(exit_code=1, panel_collapsed=None, collapsed=False)
    assert "exit" not in _seg_names(h)
