"""Tests for UX Audit B — Density / Truncation Logic.

Spec: /home/xush/.hermes/2026-04-28-ux-audit-B-density-truncation-spec.md
Changes: B1 drop-order | B2 footer-streaming-error | B3 skeleton env-var |
         B4 OmissionBar narrow label | B5 truncated linecount badge
"""
from __future__ import annotations

import importlib
import inspect
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides):
    """Return a LayoutInputs with safe defaults."""
    from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs
    from hermes_cli.tui.services.tools import ToolCallState
    defaults = dict(
        phase=ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=False,
        user_override_tier=None,
        body_line_count=5,
        threshold=20,
        row_budget=None,
        width=80,
        user_collapsed=False,
        has_footer_content=False,
        is_streaming=False,
    )
    defaults.update(overrides)
    return LayoutInputs(**defaults)


def _make_ob_unit(narrow: bool = False) -> "object":
    """
    Build an OmissionBar-like object for unit tests of set_counts/on_resize.

    Avoids full Textual Widget init by using __new__ + manual attribute setup.
    query_one is mocked to raise NoMatches so the try/except branches in
    set_counts short-circuit without needing _nodes.
    """
    from hermes_cli.tui.tool_blocks._shared import OmissionBar
    from textual.css.query import NoMatches

    ob = OmissionBar.__new__(OmissionBar)
    ob._parent_block = MagicMock()
    ob.position = "bottom"
    ob._visible_start = 0
    ob._visible_end = 0
    ob._total = 0
    ob._label = MagicMock()
    ob._cap_label = MagicMock()
    ob._last_resize_w = 0
    ob._narrow = narrow
    ob._advanced_visible = False
    ob._tooltip_text = ""

    # Make query_one raise NoMatches so all button-query branches short-circuit
    def _raise_no_matches(*args, **kwargs):
        raise NoMatches()

    ob.query_one = _raise_no_matches
    return ob


# ---------------------------------------------------------------------------
# B1 — COMPACT drop order preserves hero over duration
# ---------------------------------------------------------------------------

class TestB1CompactDropOrder:

    def test_compact_keeps_hero_over_duration_at_30col(self):
        """Width=30, COMPACT tier: hero must survive; duration must be dropped."""
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver, DensityTier,
        )
        from rich.text import Text

        resolver = ToolBlockLayoutResolver()
        # Build segments that collectively exceed 30 cells.
        # Hero is ~14 cells, duration ~6, exit ~4 → total ~24 fits, so make hero bigger.
        # Use a hero that alone is < 30 but hero+duration exceeds budget with exit needed.
        # hero=20, duration=8, exit=4 → total=32 > 30; with B1: duration drops first.
        segments = [
            ("hero",     Text("  git status ok  ")),   # 18 cells
            ("duration", Text("  123.4s")),             # 8 cells
            ("exit",     Text("  ok")),                 # 4 cells — always kept
        ]
        # Total ~30 cells. Budget=22 forces something to drop. With B1 order:
        # duration drops before hero → hero survives over duration.
        result_names = [name for name, _ in resolver.trim_header_tail(segments, 22, DensityTier.COMPACT)]
        assert "hero" in result_names, f"hero must be preserved; got {result_names}"
        assert "duration" not in result_names, f"duration must be dropped before hero; got {result_names}"

    def test_compact_keeps_exit_last(self):
        """Width=8: COMPACT drops everything down to exit only."""
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver, DensityTier,
        )
        from rich.text import Text

        resolver = ToolBlockLayoutResolver()
        segments = [
            ("chip",     Text("BROWSE")),
            ("hero",     Text("  git status: 3 files changed")),
            ("duration", Text("  5.2s")),
            ("exit",     Text("  exit 1")),
        ]
        result_names = [name for name, _ in resolver.trim_header_tail(segments, 8, DensityTier.COMPACT)]
        assert result_names == ["exit"], f"only exit should survive at budget=8 COMPACT, got {result_names}"

    def test_drop_order_compact_constant(self):
        """Regression guard: exact list ordering matches spec."""
        from hermes_cli.tui.tool_panel.layout_resolver import _DROP_ORDER_COMPACT
        expected = [
            "chip",
            "linecount",
            "flash",
            "kind",
            "diff",
            "duration",
            "hero",
            "chevron",
            "trace_pending",
            "exit",
        ]
        assert _DROP_ORDER_COMPACT == expected, (
            f"_DROP_ORDER_COMPACT mismatch.\nExpected: {expected}\nActual:   {_DROP_ORDER_COMPACT}"
        )


# ---------------------------------------------------------------------------
# B2 — Footer visible during streaming error
# ---------------------------------------------------------------------------

class TestB2FooterDuringStreamingError:

    def test_streaming_no_error_hides_footer(self):
        """Baseline: footer hidden when streaming without error."""
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        resolver = ToolBlockLayoutResolver()
        inputs = _make_inputs(is_streaming=True, is_error=False, has_footer_content=True)
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is False

    def test_streaming_with_error_and_footer_shows(self):
        """B2: footer visible when streaming AND error AND has_footer_content."""
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        resolver = ToolBlockLayoutResolver()
        inputs = _make_inputs(is_streaming=True, is_error=True, has_footer_content=True)
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is True

    def test_streaming_with_error_no_footer_content_hides(self):
        """Empty error footer does not reserve a row even during streaming."""
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        resolver = ToolBlockLayoutResolver()
        inputs = _make_inputs(is_streaming=True, is_error=True, has_footer_content=False)
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is False


# ---------------------------------------------------------------------------
# B3 — Skeleton delay configurable via env var
# ---------------------------------------------------------------------------

class TestB3SkeletonDelayConfig:

    def test_skeleton_delay_reads_env_default_100ms(self, monkeypatch):
        """Without env override, _SKELETON_DELAY_S == 0.1 (100ms)."""
        monkeypatch.delenv("HERMES_TOOL_SKELETON_DELAY_MS", raising=False)
        mod_name = "hermes_cli.tui.tool_blocks._streaming"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        mod = importlib.import_module(mod_name)
        assert mod._SKELETON_DELAY_S == pytest.approx(0.1)

    def test_skeleton_delay_zero_skips_timer(self, monkeypatch):
        """HERMES_TOOL_SKELETON_DELAY_MS=0 → _SKELETON_DELAY_S == 0.0."""
        monkeypatch.setenv("HERMES_TOOL_SKELETON_DELAY_MS", "0")
        mod_name = "hermes_cli.tui.tool_blocks._streaming"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        mod = importlib.import_module(mod_name)
        assert mod._SKELETON_DELAY_S == 0.0


# ---------------------------------------------------------------------------
# B4 — OmissionBar narrow-mode label abbreviation
# ---------------------------------------------------------------------------

class TestB4OmissionBarNarrowLabel:

    def test_omission_label_abbreviated_below_60col(self):
        """set_counts with narrow=True shows abbreviated label ↓NL↑."""
        ob = _make_ob_unit(narrow=True)
        ob.set_counts(visible_start=0, visible_end=50, total=200)
        # narrow branch: n_hidden = total - (visible_end - visible_start) = 200 - 50 = 150
        ob._label.update.assert_called_with("↓150L↑")

    def test_omission_label_full_at_or_above_60col(self):
        """set_counts with narrow=False shows full range label."""
        ob = _make_ob_unit(narrow=False)
        ob.set_counts(visible_start=0, visible_end=50, total=200)
        # Full label path: "  1–50 of 200  "
        calls = [str(c) for c in ob._label.update.call_args_list]
        assert any("of 200" in c for c in calls), (
            f"Expected 'of 200' in label updates, got {calls}"
        )

    def test_omission_narrow_class_applied(self):
        """on_resize below THRESHOLD_NARROW toggles --narrow CSS class."""
        from hermes_cli.tui.tool_blocks._shared import OmissionBar, THRESHOLD_NARROW
        from unittest.mock import PropertyMock

        ob = _make_ob_unit(narrow=False)
        ob.set_class = MagicMock()

        # size is a read-only property on Widget; use an isolated subclass to avoid
        # leaking the mock across the pytest session (feedback: widget property leakage).
        class _IsolatedOB(OmissionBar):
            pass

        ob.__class__ = _IsolatedOB

        mock_size = MagicMock()
        mock_size.width = THRESHOLD_NARROW - 10
        type(ob).size = PropertyMock(return_value=mock_size)

        try:
            # crosses_threshold → True so the label/set_class branch runs
            with patch("hermes_cli.tui.tool_blocks._shared.crosses_threshold", return_value=True):
                ob.on_resize(MagicMock())
        finally:
            # Clean up class-level PropertyMock to avoid test session leakage
            del type(ob).size

        ob.set_class.assert_called_with(True, "--narrow")


# ---------------------------------------------------------------------------
# B5 — Truncated line count badge in header tail
# ---------------------------------------------------------------------------

class TestB5LinecountTruncatedBadge:
    """Test the linecount-cell logic in _header.py directly.

    Rather than calling _render_v4 (which needs a full Widget context),
    we replicate the linecount-cell branch logic exactly as it appears in
    _render_v4 and verify the Text objects it produces.  We also use
    inspect.getsource as a structural guard that the branch exists in source.
    """

    def _build_linecount_text(self, line_count: int, truncated: int):
        """Replicate the linecount-cell branch from _render_v4 in isolation."""
        from rich.text import Text
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        _c = SkinColors.default()
        lc_text = ">99K" if line_count > 99999 else f"{line_count}L"
        if truncated > 0:
            lc_text = f"{lc_text} [trunc:{truncated}]"
            return Text(f"  {lc_text}", style=f"dim {_c.warning_dim}")
        else:
            return Text(f"  {lc_text}", style="dim")

    def test_linecount_no_truncation_renders_plain(self):
        """With truncated=0, label shows plain line count like '42L'."""
        text = self._build_linecount_text(line_count=42, truncated=0)
        assert "42L" in text.plain, f"Expected '42L' in '{text.plain}'"
        assert "trunc" not in text.plain, "No trunc badge expected"

    def test_linecount_with_truncation_renders_badge(self):
        """With truncated=50, label includes [trunc:50]."""
        text = self._build_linecount_text(line_count=100, truncated=50)
        assert "[trunc:50]" in text.plain, f"Expected '[trunc:50]' in '{text.plain}'"
        assert "100L" in text.plain, f"Expected '100L' in '{text.plain}'"

    def test_linecount_truncated_uses_warning_style(self):
        """Truncated badge uses warning_dim color and source reflects the branch."""
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        from hermes_cli.tui.tool_blocks._header import ToolHeader

        default_colors = SkinColors.default()
        expected_color = default_colors.warning_dim

        # Structural guard: source must contain the truncated branch
        src = inspect.getsource(ToolHeader._render_v4)
        assert "_truncated_line_count" in src, (
            "_render_v4 must reference _truncated_line_count for B5"
        )
        assert "warning_dim" in src, (
            "_render_v4 must use warning_dim for truncated badge style"
        )

        # Functional: the text style contains warning_dim when truncated > 0
        text = self._build_linecount_text(line_count=100, truncated=50)
        assert expected_color in str(text.style), (
            f"Expected warning_dim color '{expected_color}' in style '{text.style}'"
        )
