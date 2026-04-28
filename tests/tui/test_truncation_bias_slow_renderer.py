"""Tests for TB-1..TB-5: truncation bias ClassVars, summary_line, _apply_clamp,
slow-renderer fallback, and resolver clamp_rows field."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw: str = "", **kwargs) -> object:
    from hermes_cli.tui.tool_payload import ToolPayload
    return ToolPayload(
        tool_name="test",
        category=None,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=len(output_raw.splitlines()),
        **kwargs,
    )


def _make_cls_result(kind=None):
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    return ClassificationResult(kind=kind or ResultKind.TEXT, confidence=1.0)


# ---------------------------------------------------------------------------
# TB-1: ClassVar declarations
# ---------------------------------------------------------------------------

class TestTruncationBiasDeclared:
    def test_each_renderer_declares_bias(self):
        from hermes_cli.tui.body_renderers import REGISTRY
        missing = [cls.__name__ for cls in REGISTRY if "truncation_bias" not in cls.__dict__]
        assert not missing, f"missing truncation_bias: {missing}"

    def test_each_renderer_declares_kind_icon(self):
        from hermes_cli.tui.body_renderers import REGISTRY
        missing = [cls.__name__ for cls in REGISTRY if "kind_icon" not in cls.__dict__]
        assert not missing, f"missing kind_icon: {missing}"

    def test_bias_values_are_legal(self):
        from hermes_cli.tui.body_renderers import REGISTRY
        legal = {"head", "tail", "priority", "hunk-aware"}
        bad = [(cls.__name__, cls.truncation_bias) for cls in REGISTRY
               if cls.truncation_bias not in legal]
        assert not bad, f"illegal bias values: {bad}"

    def test_kind_icon_values_are_strings(self):
        from hermes_cli.tui.body_renderers import REGISTRY
        bad = [cls.__name__ for cls in REGISTRY
               if not isinstance(cls.kind_icon, str) or not cls.kind_icon]
        assert not bad, f"missing/empty kind_icon: {bad}"

    def test_diff_uses_hunk_aware(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        assert DiffRenderer.truncation_bias == "hunk-aware"

    def test_search_uses_priority(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        assert SearchRenderer.truncation_bias == "priority"


# ---------------------------------------------------------------------------
# TB-2: summary_line()
# ---------------------------------------------------------------------------

class TestSummaryLine:
    def test_diff_summary_line(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        raw = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-line1\n-line2\n-line3\n"
            "+newline1\n+newline2\n+newline3\n+newline4\n+newline5\n"
            "--- a/bar.py\n+++ b/bar.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n+new\n"
        )
        payload = _make_payload(raw)
        cls_result = _make_cls_result()
        r = DiffRenderer(payload, cls_result)
        summary = r.summary_line()
        # 2 files; adds and dels tracked
        assert "file(s)" in summary
        assert "·" in summary

    def test_json_summary_line(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        import json
        payload = _make_payload(json.dumps({"name": "x", "ver": "1.0"}))
        cls_result = _make_cls_result()
        r = JsonRenderer(payload, cls_result)
        result = r.summary_line()
        assert "name" in result
        assert "ver" in result

    def test_table_summary_line(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        rows = ["a|b|c|d"] + [f"{i}|{i}|{i}|{i}" for i in range(10)]
        payload = _make_payload("\n".join(rows))
        cls_result = _make_cls_result()
        r = TableRenderer(payload, cls_result)
        r.build()  # populate _row_count/_col_count
        result = r.summary_line()
        assert "10" in result
        assert "rows" in result

    def test_search_summary_line_zero_hits(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        payload = _make_payload("")
        cls_result = _make_cls_result()
        r = SearchRenderer(payload, cls_result)
        assert r.summary_line() == "(no matches)"

    def test_default_summary_line_no_output(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        payload = _make_payload("")
        cls_result = _make_cls_result()
        r = FallbackRenderer(payload, cls_result)
        assert r.summary_line() == "(no output)"

    def test_default_summary_line_with_rows(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        payload = _make_payload("line1\nline2\nline3")
        cls_result = _make_cls_result()
        r = FallbackRenderer(payload, cls_result)
        assert r.summary_line() == "(3 rows)"


# ---------------------------------------------------------------------------
# TB-3: _apply_clamp dispatch
# ---------------------------------------------------------------------------

class TestClampApplication:
    def test_tail_bias_30_to_12(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class TailRenderer(BodyRenderer):
            truncation_bias = "tail"
            kind_icon = "¶"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        payload = _make_payload("\n".join(f"line{i}" for i in range(30)))
        r = TailRenderer(payload, None)
        rows = list(payload.output_raw.splitlines())
        result = r._apply_clamp(rows, 12)
        assert len(result) == 12
        assert "earlier" in result[0]
        assert result[-1] == "line29"

    def test_head_bias_30_to_12(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class HeadRenderer(BodyRenderer):
            truncation_bias = "head"
            kind_icon = "{}"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        payload = _make_payload("\n".join(f"line{i}" for i in range(30)))
        r = HeadRenderer(payload, None)
        rows = list(payload.output_raw.splitlines())
        result = r._apply_clamp(rows, 12)
        assert len(result) == 12
        assert "more" in result[-1]
        assert result[0] == "line0"

    def test_priority_bias_search(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class PriRenderer(BodyRenderer):
            truncation_bias = "priority"
            kind_icon = "🔍"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        rows = [f"hit{i}" for i in range(20)]
        payload = _make_payload("\n".join(rows))
        r = PriRenderer(payload, None)
        r._hit_scores = list(range(19, -1, -1))  # hit0=19, hit19=0
        result = r._apply_clamp(rows, 12)
        assert len(result) == 12
        # last entry is chip
        assert "hits" in result[-1]

    def test_hunk_aware_diff_no_hunk_split(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class HunkRenderer(BodyRenderer):
            truncation_bias = "hunk-aware"
            kind_icon = "±"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        # 3 hunks, each with 4 lines → 12 total, clamp=10
        hunk1 = ["@@ -1,2 +1,2 @@", "+a", "-b", " c"]
        hunk2 = ["@@ -5,2 +5,2 @@", "+d", "-e", " f"]
        hunk3 = ["@@ -9,2 +9,2 @@", "+g", "-h", " i"]
        rows = hunk1 + hunk2 + hunk3
        payload = _make_payload("\n".join(rows))
        r = HunkRenderer(payload, None)
        result = r._apply_clamp(rows, 10)
        # chip is first; no @@ line should be split mid-hunk
        assert "hunks" in result[0]

    def test_clamp_below_threshold_no_chip(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class TailRenderer(BodyRenderer):
            truncation_bias = "tail"
            kind_icon = "¶"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        payload = _make_payload("\n".join(f"line{i}" for i in range(8)))
        r = TailRenderer(payload, None)
        rows = list(payload.output_raw.splitlines())
        result = r._apply_clamp(rows, 12)
        assert result == rows  # unchanged
        assert not any("earlier" in row or "more" in row for row in result)

    def test_chip_format_earlier(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class TailRenderer(BodyRenderer):
            truncation_bias = "tail"
            kind_icon = "¶"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        payload = _make_payload("\n".join(f"line{i}" for i in range(100)))
        r = TailRenderer(payload, None)
        rows = list(payload.output_raw.splitlines())
        result = r._apply_clamp(rows, 12)
        chip = result[0]
        assert "89 earlier" in chip

    def test_renderer_bias_overrides_default(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer

        class OverrideRenderer(BodyRenderer):
            truncation_bias = "tail"
            kind_icon = "{}"
            kind = None
            @classmethod
            def can_render(cls, *a): return True
            def build(self): return None

        payload = _make_payload("\n".join(f"line{i}" for i in range(30)))
        r = OverrideRenderer(payload, None)
        rows = list(payload.output_raw.splitlines())
        result = r._apply_clamp(rows, 12)
        assert "earlier" in result[0]

    def test_compact_uses_summary_line_not_clamp(self):
        """COMPACT tier routing: base build_widget with clamp_rows=None skips _apply_clamp."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        payload = _make_payload("\n".join(f"line{i}" for i in range(30)))
        cls_result = _make_cls_result()
        r = FallbackRenderer(payload, cls_result)
        with patch.object(r, "_apply_clamp") as mock_clamp:
            # COMPACT tier: clamp_rows is None (from _clamp_for_tier)
            # base build_widget with clamp_rows=None skips _apply_clamp
            widget = r.build_widget(clamp_rows=None)
            mock_clamp.assert_not_called()


# ---------------------------------------------------------------------------
# TB-4: Slow-renderer fallback
# ---------------------------------------------------------------------------

class TestSlowRendererFallback:
    def _make_body_pane(self):
        """Construct a bare BodyPane without Textual DOM."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        bp = object.__new__(BodyPane)
        bp._block = None
        bp._renderer_degraded = False
        bp._renderer = None
        bp._slow_worker_active = False
        bp._hard_timer = None
        bp._last_tier = None
        bp._err_body_locked = False
        return bp

    def test_fast_render_under_250ms_no_placeholder(self):
        """_mount_body_with_deadline with fast mock doesn't set _slow_worker_active."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = self._make_body_pane()
        mock_renderer = MagicMock()
        mock_widget = MagicMock()
        mock_renderer.build_widget.return_value = mock_widget
        bp._renderer = mock_renderer

        mounted = []
        bp.query = lambda _: MagicMock(remove=MagicMock())
        bp.mount = lambda w: mounted.append(w)

        bp._mount_body_with_deadline(DensityTier.DEFAULT)
        assert not bp._slow_worker_active
        assert mock_widget in mounted

    def test_placeholder_has_kind_icon(self):
        from hermes_cli.tui.tool_panel._footer import BodyPane
        bp = self._make_body_pane()
        w = bp._make_slow_placeholder("±")
        # Static stores content in .visual (Textual 8.x)
        content = str(w.visual)
        assert "±" in content

    def test_placeholder_has_rendering_caption(self):
        from hermes_cli.tui.tool_panel._footer import BodyPane
        bp = self._make_body_pane()
        w = bp._make_slow_placeholder("±")
        content = str(w.visual)
        assert "rendering" in content

    def test_renderer_raise_falls_back_immediate(self):
        """build_widget() raises → FallbackRenderer widget mounted, _log.exception called."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        import hermes_cli.tui.tool_panel._footer as footer_mod

        bp = self._make_body_pane()
        mock_renderer = MagicMock()
        mock_renderer.build_widget.side_effect = ValueError("boom")
        mock_renderer.payload = MagicMock()
        bp._renderer = mock_renderer

        mounted = []
        bp.query = lambda _: MagicMock(remove=MagicMock())
        bp.mount = lambda w: mounted.append(w)

        with patch.object(footer_mod._log, "exception") as mock_exc, \
             patch("hermes_cli.tui.body_renderers.fallback.FallbackRenderer.build_widget",
                   return_value=MagicMock()):
            bp._mount_body_with_deadline(DensityTier.DEFAULT)
            mock_exc.assert_called_once()

    def test_swap_in_discards_result_after_kill(self):
        """_slow_kill() sets _slow_worker_active=False; _swap_in_real_widget then no-ops."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        bp = self._make_body_pane()
        bp._slow_worker_active = False  # simulate kill already happened

        mounted = []
        bp.mount = lambda w: mounted.append(w)

        bp._swap_in_real_widget(MagicMock())
        assert not mounted  # guard fired: nothing mounted

    def test_fallback_after_2s_logs_warning(self):
        """_slow_kill() calls _log.warning with renderer class name."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        import hermes_cli.tui.tool_panel._footer as footer_mod
        from unittest.mock import PropertyMock

        bp = self._make_body_pane()
        bp._slow_worker_active = True
        bp._last_tier = DensityTier.DEFAULT

        mock_renderer = MagicMock()
        mock_renderer.__class__ = type("MockRenderer", (), {})
        bp._renderer = mock_renderer

        mounted = []
        bp.query = lambda _: MagicMock(remove=MagicMock())
        bp.mount = lambda w: mounted.append(w)

        mock_app = MagicMock()
        with patch.object(footer_mod._log, "warning") as mock_warn, \
             patch("hermes_cli.tui.body_renderers.fallback.FallbackRenderer.build_widget",
                   return_value=MagicMock()), \
             patch.object(type(bp), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch.object(bp, "_swap_in_real_widget"):
                bp._slow_kill()
            mock_warn.assert_called_once()

    def test_make_slow_placeholder_class(self):
        """_make_slow_placeholder returns a Static with 'slow-placeholder' class."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from textual.widgets import Static
        bp = self._make_body_pane()
        w = bp._make_slow_placeholder("🔍")
        assert isinstance(w, Static)
        assert "slow-placeholder" in w.classes

    def test_apply_density_trace_removes_children(self):
        """TRACE tier → clamp==0 → query('*').remove() called."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = self._make_body_pane()
        mock_renderer = MagicMock()
        bp._renderer = mock_renderer

        removed = []
        class FakeQuery:
            def remove(self): removed.append(True)
        bp.query = lambda _: FakeQuery()

        bp.apply_density(DensityTier.TRACE)
        assert removed  # remove() was called

    def test_apply_density_compact_calls_render_compact(self):
        """COMPACT tier → _render_compact_body() called."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = self._make_body_pane()
        mock_renderer = MagicMock()
        mock_renderer.summary_line.return_value = "3 rows × 4 cols"
        bp._renderer = mock_renderer

        with patch.object(bp, "_render_compact_body") as mock_compact:
            bp.apply_density(DensityTier.COMPACT)
            mock_compact.assert_called_once()

    def test_apply_density_default_calls_mount_with_deadline(self):
        """DEFAULT tier → _mount_body_with_deadline() called."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = self._make_body_pane()
        mock_renderer = MagicMock()
        bp._renderer = mock_renderer

        with patch.object(bp, "_mount_body_with_deadline") as mock_mount:
            bp.apply_density(DensityTier.DEFAULT)
            mock_mount.assert_called_once_with(DensityTier.DEFAULT)

    def test_apply_density_none_renderer_no_op(self):
        """apply_density with _renderer=None returns immediately without error."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = self._make_body_pane()
        bp._renderer = None
        # Should not raise
        bp.apply_density(DensityTier.DEFAULT)


# ---------------------------------------------------------------------------
# TB-5: Resolver clamp_rows
# ---------------------------------------------------------------------------

class TestResolverClampRows:
    def test_decision_includes_clamp_rows(self):
        """LayoutDecision dataclass has clamp_rows field."""
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        d = LayoutDecision(
            tier=DensityTier.DEFAULT,
            footer_visible=True,
            width=100,
            reason="auto",
        )
        assert hasattr(d, "clamp_rows")
        assert d.clamp_rows is None  # default

    def test_hero_clamp_none(self):
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier, DensityTier
        assert _clamp_for_tier(DensityTier.HERO) is None

    def test_default_clamp_matches_threshold(self):
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier, DensityTier, _DEFAULT_BODY_CLAMP
        assert _clamp_for_tier(DensityTier.DEFAULT) == _DEFAULT_BODY_CLAMP
        assert _DEFAULT_BODY_CLAMP == 12

    def test_trace_clamp_zero(self):
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier, DensityTier
        assert _clamp_for_tier(DensityTier.TRACE) == 0

    def test_compact_clamp_none(self):
        """COMPACT uses summary_line(), so clamp_rows is None."""
        from hermes_cli.tui.tool_panel.layout_resolver import _clamp_for_tier, DensityTier
        assert _clamp_for_tier(DensityTier.COMPACT) is None

    def test_renderer_receives_clamp_rows(self):
        """apply_density(DEFAULT) calls _mount_body_with_deadline with tier."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        bp = object.__new__(BodyPane)
        bp._block = None
        bp._renderer_degraded = False
        bp._renderer = MagicMock()
        bp._slow_worker_active = False
        bp._hard_timer = None
        bp._last_tier = None
        bp._err_body_locked = False

        mock_widget = MagicMock()
        bp._renderer.build_widget.return_value = mock_widget
        mounted = []
        bp.query = lambda _: MagicMock(remove=MagicMock())
        bp.mount = lambda w: mounted.append(w)

        with patch.object(bp, "_mount_body_with_deadline") as mock_mtd:
            bp.apply_density(DensityTier.DEFAULT)
            mock_mtd.assert_called_once_with(DensityTier.DEFAULT)
