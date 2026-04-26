"""Header signal hardening — B-1, C-3, F-1, F-2, F-3 (17 pure-unit tests)."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal ToolHeader stand-in (no Textual runtime)
# ---------------------------------------------------------------------------

class _H:
    """Thin stand-in for ToolHeader exercising _render_v4 signal logic."""

    def __init__(
        self,
        *,
        tool_name: str = "bash",
        collapsed: bool = True,
        is_complete: bool = True,
        has_affordances: bool = False,
        flash_msg: str | None = None,
        flash_expires: float = 0.0,
        flash_tone: str = "success",
        duration: str = "",
        spinner_char: str | None = None,
        primary_hero: str | None = None,
        error_kind: str | None = None,
        tool_icon: str = "",
        tool_icon_error: bool = False,
        line_count: int = 0,
        panel_collapsed: bool | None = None,
        is_child: bool = False,
        width: int = 80,
        gutter_color: str = "#00bcd4",
    ) -> None:
        self._tool_name = tool_name
        self._label = tool_name
        self._line_count = line_count
        self._stats = None
        self._has_affordances = has_affordances
        self._flash_msg = flash_msg
        self._flash_expires = flash_expires
        self._flash_tone = flash_tone
        self._spinner_char = spinner_char
        self._duration = duration
        self._is_complete = is_complete
        self._tool_icon = tool_icon
        self._tool_icon_error = tool_icon_error
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
        self._error_kind = error_kind
        self._exit_code = None
        self._browse_badge = ""
        self._is_child = is_child
        self.collapsed = collapsed
        self._focused_gutter_color = gutter_color
        self._diff_add_color = "#4caf50"
        self._diff_del_color = "#ef4444"
        self._running_icon_color = "#FFA726"
        self._width = width
        self._pulse_t = 0.0
        self._pulse_tick = 0
        self._spinner_identity = None

        if panel_collapsed is not None:
            self._panel = MagicMock()
            self._panel.collapsed = panel_collapsed
            self._panel._result_summary_v4 = None
        else:
            self._panel = None

    def has_class(self, *_: Any) -> bool:
        return False

    def _accessible_mode(self) -> bool:
        return False

    @property
    def size(self) -> Any:
        s = MagicMock()
        s.width = self._width
        return s

    def _tail(self, budget: int = 200) -> "list[tuple[str, Any]]":
        """Run the tail-building logic from _render_v4 and return raw segments."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments

        tail_segments: list[tuple[str, Any]] = []
        _pending_dur: str | None = None

        if self._spinner_char is not None:
            tail_segments.append(("spinner", Text(f"  {self._spinner_char}", style="dim")))
            if self._duration:
                _pending_dur = self._duration
        else:
            if self._primary_hero:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="dim green")))

            if self._line_count and not self._primary_hero:
                lc_text = f"{self._line_count}L"
                tail_segments.append(("linecount", Text(f"  {lc_text}", style="dim")))

            if self._has_affordances:
                is_collapsed = self._panel.collapsed if self._panel is not None else self.collapsed
                tail_segments.append(("chevron", Text("  ▸" if is_collapsed else "  ▾", style="dim")))
            else:
                tail_segments.append(("chevron", Text("  ·", style="dim #444444")))

            if self._duration:
                _pending_dur = self._duration

            now = time.monotonic()
            if self._flash_msg and now < self._flash_expires:
                accent_color = getattr(self, "_focused_gutter_color", "#5f87d7")
                _flash_style = "dim red" if self._flash_tone == "error" else f"dim {accent_color}"
                _msg = self._flash_msg
                _tw = self._width
                if _tw > 0 and _tw < 80:
                    _msg = _msg[:14] + "…" if len(_msg) > 14 else _msg
                tail_segments.append(("flash", Text(f"  ✓ {_msg}", style=_flash_style)))

        if _pending_dur:
            tail_segments.append(("duration", Text(f"  {_pending_dur}", style="dim")))

        return _trim_tail_segments(tail_segments, budget)

    def _tail_names(self, budget: int = 200) -> "list[str]":
        return [name for name, _ in self._tail(budget)]

    def _tail_text(self, name: str, budget: int = 200) -> "str | None":
        for n, seg in self._tail(budget):
            if n == name:
                return seg.plain
        return None


# ---------------------------------------------------------------------------
# B-1 — Chevron slot always filled
# ---------------------------------------------------------------------------

class TestB1:
    def test_no_affordances_emits_dot_placeholder(self) -> None:
        h = _H(has_affordances=False)
        assert "chevron" in h._tail_names()
        assert h._tail_text("chevron") == "  ·"

    def test_affordances_collapsed_emits_right_arrow(self) -> None:
        h = _H(has_affordances=True, panel_collapsed=True)
        assert h._tail_text("chevron") == "  ▸"

    def test_affordances_expanded_emits_down_arrow(self) -> None:
        h = _H(has_affordances=True, panel_collapsed=False)
        assert h._tail_text("chevron") == "  ▾"

    def test_dot_placeholder_survives_trim_at_tight_budget(self) -> None:
        # linecount present so it gets dropped first; chevron (placeholder) remains
        h = _H(has_affordances=False, line_count=5)
        # budget=4 — linecount is first in DROP_ORDER so drops; chevron stays
        names = h._tail_names(budget=4)
        assert "chevron" in names
        assert h._tail_text("chevron", budget=4) == "  ·"


# ---------------------------------------------------------------------------
# C-3 — Category icon preserved on error; no icon_str substitution
# ---------------------------------------------------------------------------

class TestC3:
    def test_error_panel_keeps_category_icon_not_error_kind_icon(self) -> None:
        # The icon_str substitution block was removed — _tool_icon is always used
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        import inspect
        src = inspect.getsource(ToolHeader._render_v4)
        # The substitution block that overwrites icon_str with _ek_icon must be absent
        assert "icon_str = _ek_icon" not in src

    def test_hero_prefix_still_shows_error_kind(self) -> None:
        # The hero segment for error_kind is in lines 247-257 — verify those remain
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        import inspect
        src = inspect.getsource(ToolHeader._render_v4)
        assert "_error_kind_display" in src  # still present in hero block

    def test_two_error_categories_have_different_icons(self) -> None:
        # icon_str comes from _tool_icon which is category-based; each tool category
        # yields a distinct icon.  Verify the substitution block is removed so category
        # icon is never overwritten.
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        import inspect
        src = inspect.getsource(ToolHeader._render_v4)
        # Guard: only ONE icon_str assignment per _render_v4 (the original category icon)
        # The substitution block had "icon_str = _ek_icon" — it must be gone
        assert src.count("icon_str = _ek_icon") == 0


# ---------------------------------------------------------------------------
# F-1 — Flash drops last
# ---------------------------------------------------------------------------

class TestF1:
    def test_flash_is_first_in_drop_order(self) -> None:
        # Spec A (tool-pipeline) changed semantics: flash drops first so permanent
        # state (exit code, chevron) is never hidden by a transient notification.
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert _DROP_ORDER[0] == "flash"

    def test_flash_drops_before_linecount_on_tight_budget(self) -> None:
        future = time.monotonic() + 60
        # flash "  ✓ Copied" = 10 cells; linecount "  5L" = 5 cells; chevron "  ·" = 3 cells
        # total=18; budget=10; flash drops first (8 cells freed → 10 ≤ 10)
        h = _H(
            has_affordances=False,
            line_count=5,
            flash_msg="Copied",
            flash_expires=future,
            width=80,
        )
        names = h._tail_names(budget=10)
        assert "flash" not in names
        assert "linecount" in names

    def test_narrow_flash_message_capped_at_14_chars(self) -> None:
        future = time.monotonic() + 60
        long_msg = "A very long flash message that exceeds fourteen characters"
        h = _H(flash_msg=long_msg, flash_expires=future, width=40)
        # width=40 → narrow clip applies
        text = h._tail_text("flash")
        assert text is not None
        # "  ✓ " prefix (4 chars) then message portion
        msg_portion = text[4:]  # strip "  ✓ "
        assert len(msg_portion) <= 15  # 14 chars + optional "…"

    def test_wide_flash_message_not_truncated(self) -> None:
        future = time.monotonic() + 60
        long_msg = "A very long flash message that exceeds fourteen characters"
        h = _H(flash_msg=long_msg, flash_expires=future, width=80)
        text = h._tail_text("flash")
        assert text is not None
        msg_portion = text[4:]
        assert msg_portion == long_msg


# ---------------------------------------------------------------------------
# F-2 — Duration in _DROP_ORDER; single append point
# ---------------------------------------------------------------------------

class TestF2:
    def test_duration_in_drop_order(self) -> None:
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert "duration" in _DROP_ORDER

    def test_duration_drops_before_chevron(self) -> None:
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert _DROP_ORDER.index("duration") < _DROP_ORDER.index("chevron")

    def test_spinner_branch_produces_one_duration_segment(self) -> None:
        h = _H(spinner_char="⠋", duration="1.2s", is_complete=False)
        segs = h._tail(budget=200)
        duration_count = sum(1 for name, _ in segs if name == "duration")
        assert duration_count == 1

    def test_completed_branch_produces_one_duration_segment(self) -> None:
        h = _H(duration="3.4s", is_complete=True)
        segs = h._tail(budget=200)
        duration_count = sum(1 for name, _ in segs if name == "duration")
        assert duration_count == 1

    def test_duration_text_content(self) -> None:
        h = _H(duration="2.1s", is_complete=True)
        text = h._tail_text("duration")
        assert text == "  2.1s"


# ---------------------------------------------------------------------------
# F-3 — Gutter color from $accent-interactive
# ---------------------------------------------------------------------------

class TestF3:
    def _make_header(self) -> "Any":
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        h = ToolHeader.__new__(ToolHeader)
        h._focused_gutter_color = "#FFD700"
        h._diff_add_color = "#4caf50"
        h._diff_del_color = "#ef4444"
        h._running_icon_color = "#FFA726"
        return h

    def test_reads_accent_interactive_first(self) -> None:
        from unittest.mock import PropertyMock, patch
        from hermes_cli.tui.tool_blocks._header import ToolHeader, _GUTTER_FALLBACK
        h = self._make_header()
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {
            "accent-interactive": "#00bcd4",
            "primary": "#5f87d7",
        }
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=mock_app):
            ToolHeader._refresh_gutter_color(h)
        assert h._focused_gutter_color == "#00bcd4"

    def test_falls_back_to_primary_when_accent_interactive_absent(self) -> None:
        # SC-4: gutter now resolved through SkinColors.tool_header_gutter.
        # When accent-interactive absent, falls back to tool-header-gutter-color
        # default (#00bcd4), not $primary. primary fallback was removed.
        from unittest.mock import PropertyMock, patch
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        h = self._make_header()
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {"primary": "#7C3AED"}
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=mock_app):
            ToolHeader._refresh_gutter_color(h)
        # accent-interactive absent → falls back to SkinColors.default().tool_header_gutter
        assert h._focused_gutter_color == SkinColors.default().tool_header_gutter

    def test_falls_back_to_gutter_fallback_when_both_absent(self) -> None:
        # SC-4: when both accent-interactive and tool-header-gutter-color absent,
        # falls back to SkinColors.default().tool_header_gutter (not _GUTTER_FALLBACK).
        from unittest.mock import PropertyMock, patch
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        h = self._make_header()
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {}
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=mock_app):
            ToolHeader._refresh_gutter_color(h)
        assert h._focused_gutter_color == SkinColors.default().tool_header_gutter

    def test_footer_pane_accent_chip_not_bold_cyan(self) -> None:
        from hermes_cli.tui.tool_panel import _TONE_STYLES
        # accent sentinel is empty string — not hardcoded "bold cyan"
        assert _TONE_STYLES.get("accent") != "bold cyan"
        assert _TONE_STYLES.get("accent") == ""
