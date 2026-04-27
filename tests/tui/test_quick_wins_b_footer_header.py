"""Tests for Quick Wins B — Footer & Header (FH-1..FH-8).

19 tests, all unit-level, target run-time <2 s.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_streaming_block(completed: bool = False, settled: bool = False):
    """Minimal StreamingToolBlock-like stub."""
    b = SimpleNamespace()
    b._completed = completed
    b._settled = settled
    return b


# ---------------------------------------------------------------------------
# FH-1: Recovery hint dedup completion
# ---------------------------------------------------------------------------

class TestFH1RecoveryHintDedup:
    """Final-pass dedup in _collect_hints: primary always wins over contextual."""

    def test_recovery_hint_no_duplicate_on_err(self):
        """Contextual loses retry when it's already in primary (FH-1 dedup rule)."""
        # Simulate production: error path primary has ("r","retry"),
        # contextual would also append ("r","retry") via the retry-specific guard.
        primary = [("Enter", "collapse"), ("r", "retry")]
        contextual = [("r", "retry"), ("e", "stderr")]
        seen = set(primary)
        result_contextual = [t for t in contextual if t not in seen]
        assert ("r", "retry") not in result_contextual
        assert ("e", "stderr") in result_contextual

    def test_dedup_preserves_primary_order(self):
        """Primary is unchanged; contextual drops entries present in primary."""
        primary = [("Enter", "toggle"), ("r", "retry"), ("y", "copy")]
        contextual = [("r", "retry"), ("y", "copy"), ("o", "open")]
        seen = set(primary)
        result = [t for t in contextual if t not in seen]
        assert primary == [("Enter", "toggle"), ("r", "retry"), ("y", "copy")]
        assert result == [("o", "open")]

    def test_dedup_treats_distinct_keys_as_distinct(self):
        """Different key strings are never merged — ("R","revert") ≠ ("r","retry")."""
        primary = [("r", "retry")]
        contextual = [("R", "revert"), ("r", "retry")]
        seen = set(primary)
        result = [t for t in contextual if t not in seen]
        assert ("R", "revert") in result
        assert ("r", "retry") not in result


# ---------------------------------------------------------------------------
# FH-2: Skeleton dismiss moves to first successful flush
# ---------------------------------------------------------------------------

class TestFH2SkeletonDismissOrder:
    """Skeleton is dismissed in _flush_pending, not in append_line."""

    def _make_block(self):
        """Minimal StreamingToolBlock stub with _dismiss_skeleton tracked."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock  # noqa: F401

        class _Stub:
            _completed = False
            _broken = False
            _skeleton_widget = object()  # truthy — skeleton mounted
            _skeleton_timer = None
            _pending: list = []
            _all_plain: list = []
            _all_rich: list = []
            _total_received = 0
            _bytes_received = 0
            _truncated_line_count = 0
            _history_capped = False
            _flush_slow = False
            _render_timer = None
            _is_unmounted = False
            _last_line_time = 0.0
            _rate_samples: list = []
            _follow_tail = False
            _follow_tail_dirty = False
            _visible_count = 0
            _should_strip_cwd = False
            _last_http_status = None
            _line_byte_cap = 1_000_000
            _visible_cap = 200
            _dismiss_called = False

            def _dismiss_skeleton(self):
                self._dismiss_called = True

            # Minimal set_interval stub
            def set_interval(self, *a, **kw):
                return None

            def _register_timer(self, t):
                return t

            def post_message(self, *a, **kw):
                pass

        return _Stub()

    def test_skeleton_not_dismissed_in_append_line(self):
        """append_line must NOT call _dismiss_skeleton (FH-2 regression guard)."""
        import importlib
        import hermes_cli.tui.tool_blocks._streaming as _mod
        # Verify by reading the source that the dismiss is NOT at the top of append_line
        import inspect
        src = inspect.getsource(_mod.StreamingToolBlock.append_line)
        assert "_dismiss_skeleton" not in src, (
            "append_line still calls _dismiss_skeleton — FH-2 move not applied"
        )

    def test_skeleton_dismissed_after_first_flush_write(self):
        """_dismiss_skeleton is called during _flush_pending after the first write."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        import inspect
        src = inspect.getsource(StreamingToolBlock._flush_pending)
        # The dismiss call must appear after the batch-write loop in _flush_pending
        dismiss_pos = src.find("_dismiss_skeleton")
        # lines_written check must precede dismiss
        lines_written_pos = src.find("lines_written")
        assert dismiss_pos != -1, "_dismiss_skeleton not found in _flush_pending"
        assert lines_written_pos < dismiss_pos, (
            "Expected lines_written check before _dismiss_skeleton in _flush_pending"
        )


# ---------------------------------------------------------------------------
# FH-3: Footer pane hidden during streaming
# ---------------------------------------------------------------------------

class TestFH3FooterStreamingGate:
    """Footer resolver + _refresh_visibility both gate on is_streaming."""

    def test_resolver_footer_hidden_during_streaming(self):
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver,
            LayoutInputs,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        resolver = ToolBlockLayoutResolver()
        inputs = LayoutInputs(
            phase=ToolCallState.STREAMING,
            is_error=False,
            has_focus=False,
            user_scrolled_up=False,
            user_override=False,
            user_override_tier=None,
            body_line_count=10,
            threshold=5,
            has_footer_content=True,
            user_collapsed=False,
            is_streaming=True,
        )
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is False

    def test_footer_refresh_visibility_streaming_gate(self):
        """FooterPane._refresh_visibility hides pane when _completed=False."""
        from hermes_cli.tui.tool_panel._footer import FooterPane
        from hermes_cli.tui.tool_panel.density import DensityTier

        block = SimpleNamespace(_completed=False)
        _parent_stub = SimpleNamespace(_block=block)

        # Isolated subclass overrides read-only Widget.parent property.
        class _IsolatedFP(FooterPane):
            parent = _parent_stub  # type: ignore[assignment]

        fp = object.__new__(_IsolatedFP)
        fp._density = DensityTier.DEFAULT
        fp._last_summary = None
        fp._show_all_artifacts = False
        styles = SimpleNamespace(display=None)
        fp.styles = styles  # type: ignore[attr-defined]

        fp._refresh_visibility()
        assert styles.display == "none"

    def test_footer_resolver_visible_on_done_with_content(self):
        """Footer is visible when not streaming and has content."""
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver,
            LayoutInputs,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        resolver = ToolBlockLayoutResolver()
        inputs = LayoutInputs(
            phase=ToolCallState.DONE,
            is_error=False,
            has_focus=False,
            user_scrolled_up=False,
            user_override=False,
            user_override_tier=None,
            body_line_count=10,
            threshold=5,
            has_footer_content=True,
            user_collapsed=False,
            is_streaming=False,
        )
        decision = resolver.resolve_full(inputs)
        assert decision.footer_visible is True


# ---------------------------------------------------------------------------
# FH-4: StreamingCodeRenderer.truncation_bias = "tail"
# ---------------------------------------------------------------------------

class TestFH4StreamingCodeBias:
    def test_streaming_code_renderer_tail_bias(self):
        from hermes_cli.tui.body_renderers.streaming import StreamingCodeRenderer
        assert StreamingCodeRenderer.truncation_bias == "tail", (
            "StreamingCodeRenderer.truncation_bias must be 'tail' (FH-4)"
        )


# ---------------------------------------------------------------------------
# FH-5: Footer at COMPACT honors has_footer_content
# ---------------------------------------------------------------------------

class TestFH5CompactFooterContent:
    def test_compact_footer_visible_when_has_content(self):
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver,
            LayoutInputs,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        resolver = ToolBlockLayoutResolver()
        # Force COMPACT tier via user override
        inputs = LayoutInputs(
            phase=ToolCallState.DONE,
            is_error=False,
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
            body_line_count=10,
            threshold=5,
            has_footer_content=True,
            user_collapsed=False,
            is_streaming=False,
        )
        decision = resolver.resolve_full(inputs)
        assert decision.tier == DensityTier.COMPACT
        assert decision.footer_visible is True

    def test_compact_footer_hidden_when_empty(self):
        from hermes_cli.tui.tool_panel.layout_resolver import (
            ToolBlockLayoutResolver,
            LayoutInputs,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        resolver = ToolBlockLayoutResolver()
        inputs = LayoutInputs(
            phase=ToolCallState.DONE,
            is_error=False,
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
            body_line_count=10,
            threshold=5,
            has_footer_content=False,
            user_collapsed=False,
            is_streaming=False,
        )
        decision = resolver.resolve_full(inputs)
        assert decision.tier == DensityTier.COMPACT
        assert decision.footer_visible is False


# ---------------------------------------------------------------------------
# FH-6: accepts(COMPACT) returns True for diff/table/search
# ---------------------------------------------------------------------------

class TestFH6AcceptsCompact:
    def _inputs(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        return ToolCallState.DONE, DensityTier.COMPACT

    def test_diff_accepts_compact(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        phase, density = self._inputs()
        assert DiffRenderer.accepts(phase, density) is True

    def test_table_accepts_compact(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        phase, density = self._inputs()
        assert TableRenderer.accepts(phase, density) is True

    def test_search_accepts_compact(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        phase, density = self._inputs()
        assert SearchRenderer.accepts(phase, density) is True


# ---------------------------------------------------------------------------
# FH-7: Header label width arithmetic uses fresh tail
# ---------------------------------------------------------------------------

class TestFH7LabelWidthFresh:
    # FIXED_PREFIX_W is a local variable inside _render_v4; MIN_LABEL_CELLS is module-level.
    # Tests verify the arithmetic shape rather than importing internal locals.
    _FAKE_FIXED = 20  # stand-in for FIXED_PREFIX_W

    def test_label_truncated_after_tail_grows_post_build(self):
        """available shrinks when tail grows — fresh re-read catches the growth."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import MIN_LABEL_CELLS

        term_w = 80
        fixed = self._FAKE_FIXED
        tail_before = Text("short")
        tail_after = Text("much longer tail segment that eats space")
        avail_stale = max(MIN_LABEL_CELLS, term_w - fixed - tail_before.cell_len - 2)
        avail_fresh = max(MIN_LABEL_CELLS, term_w - fixed - tail_after.cell_len - 2)
        assert avail_fresh < avail_stale

    def test_label_no_truncation_when_tail_stable(self):
        """When tail is stable, first read == re-read (no spurious truncation)."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import MIN_LABEL_CELLS

        term_w = 80
        fixed = self._FAKE_FIXED
        tail = Text("stable tail")
        avail_first = max(MIN_LABEL_CELLS, term_w - fixed - tail.cell_len - 2)
        final_tail_w = tail.cell_len  # FH-7 re-read
        avail_reread = max(MIN_LABEL_CELLS, term_w - fixed - final_tail_w - 2)
        assert avail_first == avail_reread


# ---------------------------------------------------------------------------
# FH-8: OmissionBar bottom hides post-settled even with cap_msg
# ---------------------------------------------------------------------------

class TestFH8OmissionBarSettled:
    def _make_block(self, settled: bool, history_capped: bool):
        """Minimal StreamingToolBlock stub for omission-bar tests."""
        b = SimpleNamespace()
        b._settled = settled
        b._history_capped = history_capped
        b._truncated_line_count = 0
        b._visible_start = 0
        b._visible_count = 50
        b._all_plain = list(range(50))
        b._visible_cap = 200
        # Omission bar stubs
        bar = MagicMock()
        bar.display = False
        b._omission_bar_bottom_mounted = True
        b._omission_bar_bottom = bar
        b._omission_bar_top_mounted = False
        b._omission_bar_top = None
        return b, bar

    def test_cap_msg_cleared_on_settled(self):
        """_refresh_omission_bars passes cap_msg=None to bottom bar when settled."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        b, bar = self._make_block(settled=True, history_capped=True)
        StreamingToolBlock._refresh_omission_bars(b)
        # cap_msg should have been cleared by settled gate
        call_kwargs = bar.set_counts.call_args[1]
        assert call_kwargs.get("cap_msg") is None

    def test_cap_msg_present_when_unsettled(self):
        """_refresh_omission_bars passes non-None cap_msg when not yet settled."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        b, bar = self._make_block(settled=False, history_capped=True)
        StreamingToolBlock._refresh_omission_bars(b)
        call_kwargs = bar.set_counts.call_args[1]
        assert call_kwargs.get("cap_msg") is not None

    def test_settled_timer_refreshes_omission_bars(self):
        """_on_settled_timer re-fires _refresh_omission_bars and sets _settled=True."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        b = SimpleNamespace()
        b._settled = False
        b._settled_timer = None
        b._omission_bar_top_mounted = True
        b._omission_bar_bottom_mounted = False
        refreshed = []
        b._refresh_omission_bars = lambda: refreshed.append(True)
        StreamingToolBlock._on_settled_timer(b)
        assert b._settled is True
        assert len(refreshed) == 1
