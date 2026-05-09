"""Tests for SS-PH-M1 / SS-PH-M2 / SS-PH-L1 — streaming status phrasing."""
from __future__ import annotations

import types
from unittest.mock import PropertyMock


# ---------------------------------------------------------------------------
# SS-PH-M1: no-data placeholder character (TitledRule)
# ---------------------------------------------------------------------------

class TestNoDataDashPlaceholder:
    def _make_titled_rule(self):
        from hermes_cli.tui.widgets.renderers import TitledRule

        class _IsolatedRule(TitledRule):
            app = None  # type: ignore[assignment]

        obj = object.__new__(_IsolatedRule)
        obj._show_state = False
        obj._response_tok_s = None
        obj._response_elapsed_s = None
        obj._response_streaming = False
        return obj

    def test_reasoning_header_uses_dash_when_no_rate(self):
        rule = self._make_titled_rule()
        rule._response_streaming = True
        rule._response_tok_s = None
        result = rule._response_metrics_text()
        assert "— tok/s" in result
        assert "…" not in result

    def test_reasoning_header_replaces_dash_on_first_chunk(self):
        rule = self._make_titled_rule()
        rule._response_streaming = True
        rule._response_tok_s = None

        # simulate first chunk arriving
        rule._response_tok_s = 42.0
        rule._response_elapsed_s = 5.5
        result = rule._response_metrics_text()
        assert "42 tok/s" in result
        assert "— tok/s" not in result

    def test_glyph_no_data_constant_is_em_dash(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_NO_DATA
        assert GLYPH_NO_DATA == "—"  # U+2014 EM DASH


# ---------------------------------------------------------------------------
# SS-PH-M2: long-wait label disambiguation (ThinkingWidget + StatusBar)
# ---------------------------------------------------------------------------

class TestLongWaitLabel:
    def _make_thinking_widget(self):
        from hermes_cli.tui.widgets.thinking import ThinkingWidget

        class _IsolatedThinking(ThinkingWidget):
            app = None  # type: ignore[assignment]

        obj = object.__new__(_IsolatedThinking)
        obj._substate = None
        obj._cfg_show_elapsed = True
        obj._last_token_time = None
        obj._base_label = "Thinking…"
        return obj

    def test_thinking_label_long_wait_format(self):
        widget = self._make_thinking_widget()
        widget._substate = "LONG_WAIT"
        result = widget._get_label_text(128.0)
        assert result == "Working hard… · 2:08"

    def test_thinking_label_still_thinking_format(self):
        widget = self._make_thinking_widget()
        widget._substate = "LONG_WAIT"
        result = widget._get_label_text(75.0)
        assert result == "Still thinking… · 1:15"

    def _make_bar(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar

        class _IsolatedBar(StatusBar):
            app = None  # type: ignore[assignment]
            size = None  # type: ignore[assignment]
            content_size = None  # type: ignore[assignment]

        bar = object.__new__(_IsolatedBar)
        bar._model_changed_at = 0.0
        bar._cwd_changed_at = 0.0
        bar.__dict__["_tok_s_displayed"] = 0.0
        bar._pulse_active = False
        bar._pulse_t = 0.0
        bar._classes = frozenset()
        return bar

    def _make_app(self, **kwargs):
        defaults = dict(
            status_model="claude-sonnet-4-6",
            status_context_tokens=0,
            status_context_max=0,
            status_compaction_progress=0.0,
            status_compaction_enabled=False,
            status_streaming=True,
            agent_running=True,
            command_running=False,
            yolo_mode=False,
            compact=False,
            status_verbose=False,
            status_active_file="",
            status_active_file_offscreen=False,
            browse_mode=False,
            browse_index=0,
            _browse_total=0,
            status_output_dropped=False,
            context_pct=0.0,
            session_label="",
            session_count=1,
            status_error="",
            status_tok_s=0.0,
            status_phase="streaming",
            status_cwd="",
            feedback=None,
            _cfg={},
            status_streaming_elapsed_s=0.0,
            status_anchor_hints=None,
            status_worktree=None,
        )
        defaults.update(kwargs)
        app = types.SimpleNamespace(**defaults)
        app.get_css_variables = lambda: {}
        return app

    def _render(self, bar, app, *, width: int = 80) -> str:
        size_ns = types.SimpleNamespace(width=width, height=1)
        bar.__class__.app = property(lambda s: app)
        bar.__class__.size = property(lambda s: size_ns)
        bar.__class__.content_size = property(lambda s: size_ns)
        result = bar.render()
        if hasattr(result, "plain"):
            return result.plain
        return str(result)

    def test_status_bar_streaming_label_no_suffix_below_threshold(self):
        bar = self._make_bar()
        app = self._make_app(status_streaming_elapsed_s=5.0)
        text = self._render(bar, app)
        assert "streaming" in text
        # Below threshold → no elapsed suffix after "streaming"
        assert "streaming · " not in text

    def test_status_bar_streaming_label_with_elapsed(self):
        bar = self._make_bar()
        app = self._make_app(status_streaming_elapsed_s=128.0)
        text = self._render(bar, app)
        assert "streaming · 2:08" in text


# ---------------------------------------------------------------------------
# SS-PH-L1: format_elapsed_short helper
# ---------------------------------------------------------------------------

class TestFormatElapsedShort:
    def test_format_elapsed_short_seconds(self):
        from hermes_cli.tui.widgets.utils import format_elapsed_short
        assert format_elapsed_short(12.3) == "12.3s"

    def test_format_elapsed_short_minutes(self):
        from hermes_cli.tui.widgets.utils import format_elapsed_short
        assert format_elapsed_short(128.0) == "2:08"

    def test_format_elapsed_short_hours(self):
        from hermes_cli.tui.widgets.utils import format_elapsed_short
        assert format_elapsed_short(3728.0) == "1:02:08"
