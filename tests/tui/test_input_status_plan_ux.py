"""Tests for TUI Design 03 — Input, Status, and Plan UX fixes.

Covers INPUT-1, INPUT-2, STATUS-1, STATUS-2, PLAN-1.
"""
from __future__ import annotations

import inspect
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Size

from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar


# ---------------------------------------------------------------------------
# TestInputHeightOverride  (INPUT-1)
# ---------------------------------------------------------------------------

class TestInputHeightOverride(unittest.TestCase):
    """INPUT-1: _sync_height_to_content() must respect _input_height_override."""

    def _make_widget(self, override: int = 3):
        w = types.SimpleNamespace()
        w._input_height_override = override
        w.text = ""
        styles = types.SimpleNamespace()
        styles.max_height = override
        styles.height = 1
        w.styles = styles
        content_size = types.SimpleNamespace()
        content_size.width = 80
        w.content_size = content_size
        return w

    def test_input_height_override_survives_sync(self):
        """Raising override to 4 and syncing content keeps max_height at 4."""
        from hermes_cli.tui.input.widget import HermesInput
        w = self._make_widget(override=4)
        w.text = "hello"
        HermesInput._sync_height_to_content(w)
        self.assertEqual(w.styles.max_height, 4)

    def test_input_height_override_resets_after_submit(self):
        """action_submit() resets override to 3 and max_height back to 3."""
        from hermes_cli.tui.input.widget import HermesInput

        # Use a plain namespace to avoid Textual reactive machinery
        w = types.SimpleNamespace()
        w._input_height_override = 5
        w._rev_mode = False
        w.disabled = False
        w._history = []
        w._history_idx = -1
        w._suppress_autocomplete_once = False
        w._last_slash_hint_fragment = ""
        styles = types.SimpleNamespace()
        styles.max_height = 5
        styles.height = 3
        w.styles = styles
        content_size = types.SimpleNamespace()
        content_size.width = 80
        w.content_size = content_size
        w.text = "hello"

        w._save_to_history = MagicMock()
        w._hide_completion_overlay = MagicMock()
        w.post_message = MagicMock()
        w.load_text = MagicMock()
        w.Submitted = MagicMock(return_value=MagicMock())

        def sync_height():
            pass  # no-op; testing the override reset only
        w._sync_height_to_content = sync_height

        HermesInput.action_submit(w)
        self.assertEqual(w._input_height_override, 3)
        self.assertEqual(w.styles.max_height, 3)


# ---------------------------------------------------------------------------
# TestInputLegendCompact  (INPUT-2)
# ---------------------------------------------------------------------------

class TestInputLegendCompact:
    """INPUT-2: compact mode keeps locked legend visible; suppresses only ghost."""

    @pytest.fixture
    def app_class(self):
        class _App(App):
            CSS_PATH = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"

            def compose(self) -> ComposeResult:
                yield InputLegendBar()

        return _App

    @pytest.mark.asyncio
    async def test_compact_locked_input_still_shows_interrupt_legend(self, app_class):
        """locked legend stays visible in compact mode."""
        async with app_class().run_test(size=(80, 24)) as pilot:
            app = pilot.app
            app.add_class("density-compact")
            legend = app.query_one(InputLegendBar)
            legend.show_legend("locked")
            await pilot.pause()
            assert "--legend-locked" in legend.classes
            assert "--visible" in legend.classes
            rendered = str(legend.render())
            assert "Ctrl+C" in rendered
            # locked legend must NOT be hidden in compact mode
            assert legend.display

    @pytest.mark.asyncio
    async def test_compact_ghost_legend_can_hide(self, app_class):
        """ghost legend is suppressed in compact mode."""
        async with app_class().run_test(size=(80, 24)) as pilot:
            app = pilot.app
            app.add_class("density-compact")
            legend = app.query_one(InputLegendBar)
            legend.show_legend("ghost")
            await pilot.pause()
            assert "--legend-ghost" in legend.classes
            # ghost should be hidden under density-compact TCSS
            assert not legend.display

            # Now switch to locked — should become visible again
            legend.show_legend("locked")
            await pilot.pause()
            assert "--legend-locked" in legend.classes
            assert legend.display


# ---------------------------------------------------------------------------
# TestStatusBarStreaming  (STATUS-1)
# ---------------------------------------------------------------------------

class TestStatusBarStreaming(unittest.TestCase):
    """STATUS-1: StatusBar render dims spans during streaming; HintBar flash uses dim."""

    def _make_status_bar_app(self, model: str = "claude-3", ctx_tokens: int = 50000,
                              ctx_max: int = 128000, streaming: bool = False):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0
        sb._model_changed_at = 0.0

        import time as _time_mod
        sb._model_changed_at = _time_mod.monotonic()  # recent → bold style, not yet dim

        app = MagicMock()
        app.status_model = model
        app.status_context_tokens = ctx_tokens
        app.status_context_max = ctx_max
        app.status_streaming = streaming
        app.agent_running = True
        app.command_running = False
        app.status_phase = "reasoning"
        app.browse_mode = False
        app.status_error = ""
        app.status_output_dropped = False
        app.status_compaction_progress = 0.3
        app.status_compaction_enabled = True
        app.yolo_mode = False
        app.compact = False
        app.status_verbose = True
        app.status_active_file = ""
        app.status_active_file_offscreen = False
        app.session_label = ""
        app.session_count = 1
        app.context_pct = 30.0
        app.yolo_mode = False
        app._animations_enabled = False  # disable shimmer for span predictability
        app.get_css_variables = MagicMock(return_value={
            "status-running-color": "#FFBF00",
            "running-indicator-dim-color": "#6e6e6e",
        })
        app.feedback = None
        app._cfg = {}
        app.cli = None
        return sb, app

    def _render_sb(self, sb, app, width: int = 80) -> Text:
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
                return sb.render()

    def test_streaming_status_bar_renders_dimmed_segments_while_hint_bar_uses_supported_css(self):
        """STATUS-1: state/model/ctx spans gain `dim` during streaming; TCSS uses color: not opacity."""
        sb, app = self._make_status_bar_app(streaming=False)
        result_normal = self._render_sb(sb, app)

        app.status_streaming = True
        result_streaming = self._render_sb(sb, app)

        # Helper to find span by text
        def find_span(result: Text, target: str):
            for span in result._spans:
                seg = result.plain[span.start:span.end]
                if seg == target:
                    return str(span.style)
            return None

        model_label = "claude-3"
        ctx_label = "50.0k/128.0k"  # approximate; find any span containing model text

        # Collect all span texts and styles
        def span_map(result: Text) -> dict:
            m = {}
            for span in result._spans:
                seg = result.plain[span.start:span.end].strip()
                if seg:
                    m[seg] = str(span.style)
            return m

        spans_normal = span_map(result_normal)
        spans_streaming = span_map(result_streaming)

        # Model span: non-streaming should NOT have 'dim'; streaming SHOULD
        model_key = next((k for k in spans_normal if k == model_label or model_label in k), None)
        if model_key:
            assert "dim" not in spans_normal.get(model_key, ""), \
                f"Non-streaming model span should not contain dim: {spans_normal.get(model_key)}"
            assert "dim" in spans_streaming.get(model_key, ""), \
                f"Streaming model span should contain dim: {spans_streaming.get(model_key)}"

        # State label: thinking (no shimmer, _animations_enabled=False)
        thinking_key = next((k for k in spans_streaming if k == "thinking"), None)
        if thinking_key:
            assert "dim" in spans_streaming[thinking_key], \
                f"Streaming state label should contain dim: {spans_streaming[thinking_key]}"

        # TCSS assertions
        tcss_path = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
        content = tcss_path.read_text()
        # StatusBar.--streaming must NOT use opacity
        if "StatusBar.--streaming" in content:
            block = content.split("StatusBar.--streaming")[1].split("}")[0]
            assert "opacity" not in block, "StatusBar.--streaming must not use opacity"
        # HintBar.--streaming must use color: not opacity
        assert "HintBar.--streaming" in content
        hint_block = content.split("HintBar.--streaming")[1].split("}")[0]
        assert "color:" in hint_block
        assert "opacity" not in hint_block

    def test_streaming_hint_bar_render_keeps_action_labels_dimmed_when_mounted(self):
        """STATUS-1: HintBar flash hint gets dim style when streaming."""
        from hermes_cli.tui.widgets.status_bar import HintBar
        hb = HintBar.__new__(HintBar)
        hb._phase = "stream"
        hb._shimmer_base = None
        hb._shimmer_timer = None

        app = MagicMock()
        app.status_streaming = True
        app.get_css_variables = MagicMock(return_value={"accent-interactive": "#5f87d7"})

        content_size_mock = MagicMock()
        content_size_mock.width = 80

        # Mock reactive properties to avoid Textual node initialization requirement
        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(type(hb), "content_size", new_callable=PropertyMock,
                              return_value=content_size_mock):
                with patch.object(type(hb), "hint", new_callable=PropertyMock,
                                  return_value="copy ok"):
                    result = hb.render()

        assert isinstance(result, Text)
        plain = result.plain

        # Flash hint "copy ok" should appear and its span should have dim style
        assert "copy ok" in plain, f"Flash hint not in rendered text: {plain!r}"
        for span in result._spans:
            seg = plain[span.start:span.end]
            if "copy ok" in seg:
                assert "dim" in str(span.style), \
                    f"Flash hint span should have dim style, got: {span.style}"
                break
        else:
            pytest.fail("No span found covering 'copy ok' in HintBar render")

        # interrupt and dismiss should have dim style (regression guard)
        for keyword in ("interrupt", "dismiss"):
            if keyword in plain:
                for span in result._spans:
                    seg = plain[span.start:span.end]
                    if seg == keyword:
                        assert "dim" in str(span.style), \
                            f"'{keyword}' span should have dim style, got: {span.style}"
                        break


# ---------------------------------------------------------------------------
# TestStatusBarPhases  (STATUS-2)
# ---------------------------------------------------------------------------

class TestStatusBarPhases(unittest.TestCase):
    """STATUS-2: StatusBar renders distinct labels per agent phase."""

    def _make_app(self, agent_running=True, streaming=False, phase="reasoning",
                  command_running=False):
        app = MagicMock()
        app.agent_running = agent_running
        app.command_running = command_running
        app.status_streaming = streaming
        app.status_phase = phase
        app.browse_mode = False
        app.status_error = ""
        app.status_output_dropped = False
        app.status_model = "m"
        app.status_context_tokens = 0
        app.status_context_max = 128000
        app.status_compaction_progress = 0.0
        app.status_compaction_enabled = False
        app.yolo_mode = False
        app.compact = False
        app.status_verbose = True
        app.status_active_file = ""
        app.status_active_file_offscreen = False
        app.session_label = ""
        app.session_count = 1
        app.context_pct = 0.0
        app._animations_enabled = False
        app.get_css_variables = MagicMock(return_value={
            "status-running-color": "#FFBF00",
            "running-indicator-dim-color": "#6e6e6e",
        })
        app.feedback = None
        app._cfg = {}
        app.cli = None
        return app

    def _render(self, app, width=80):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0
        import time as _t
        sb._model_changed_at = _t.monotonic() - 10.0
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
                return str(sb.render())

    def test_status_bar_labels_distinct_agent_phases(self):
        """reasoning phase → thinking; tool_exec phase → tools."""
        from hermes_cli.tui.widgets.status_bar import StatusBar
        full_source = Path("hermes_cli/tui/widgets/status_bar.py").read_text()
        render_src = inspect.getsource(StatusBar.render)

        assert "status_phase" in full_source
        assert "_on_status_change" in full_source

        # No hard-coded "running" label in render
        assert 'append("running"' not in render_src
        assert "append('running'" not in render_src
        assert 'shimmer_text("running"' not in render_src
        assert "shimmer_text('running'" not in render_src

        # Behavioral: reasoning → thinking
        app = self._make_app(agent_running=True, phase="reasoning")
        text = self._render(app)
        assert "thinking" in text
        assert "running" not in text

        # Behavioral: tool_exec → tools
        app.status_phase = "tool_exec"
        text = self._render(app)
        assert "tools" in text
        assert "thinking" not in text

    def test_status_bar_streaming_label_wins_when_status_streaming_true(self):
        """streaming=True → label is 'streaming', not 'running' or 'thinking'."""
        app = self._make_app(agent_running=True, streaming=True, phase="reasoning")
        text = self._render(app)
        assert "streaming" in text
        assert "running" not in text
        assert "thinking" not in text

    def test_status_bar_command_label_wins_over_agent_running(self):
        """command_running=True → label is 'command' even when agent_running=True."""
        app = self._make_app(agent_running=True, command_running=True, phase="reasoning")
        text = self._render(app)
        assert "command" in text

    def test_status_phase_watch_registered_in_on_mount(self):
        """status_phase watch must be registered in on_mount, not __init__."""
        from hermes_cli.tui.widgets.status_bar import StatusBar
        mount_src = inspect.getsource(StatusBar.on_mount)
        assert "status_phase" in mount_src, \
            "StatusBar.on_mount must call self.watch(app, 'status_phase', ...)"


# ---------------------------------------------------------------------------
# TestPlanCollapsedBudget  (PLAN-1)
# ---------------------------------------------------------------------------

class TestPlanCollapsedBudget(unittest.TestCase):
    """PLAN-1: shared budget_non_zero predicate + header refresh on budget change."""

    def test_budget_predicate_parity(self):
        """Both _show_chip and _refresh_budget_visibility reference all 3 predicate legs."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel, _PlanPanelHeader
        chip_src = inspect.getsource(_PlanPanelHeader._show_chip)
        budget_src = inspect.getsource(PlanPanel._refresh_budget_visibility)
        for term in ("cost_usd", "tokens_in", "tokens_out"):
            assert term in chip_src, f"_show_chip missing '{term}' predicate leg"
            assert term in budget_src, f"_refresh_budget_visibility missing '{term}' predicate leg"

    def test_plan_collapsed_chip_shows_token_budget_when_cost_zero(self):
        """Collapsed header refreshes from budget watcher path when cost==0 but tokens non-zero."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel, _PlanPanelHeader, _BudgetSection

        panel = types.SimpleNamespace()
        panel._collapsed = True
        panel._active_hide_timer = None

        app = MagicMock()
        app.turn_cost_usd = 0.0
        app.turn_tokens_in = 1234
        app.turn_tokens_out = 56
        app.planned_calls = []
        panel.app = app

        # Track header rebuild calls
        panel._rebuild_header_calls = []
        panel._refresh_budget_visibility_calls = []

        def mock_rebuild_header():
            panel._rebuild_header_calls.append(1)

        def mock_refresh_budget(has_active, calls):
            panel._refresh_budget_visibility_calls.append((has_active, calls))

        panel._rebuild_header = mock_rebuild_header
        panel._refresh_budget_visibility = mock_refresh_budget

        mock_budget_section = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget_section)

        PlanPanel._on_budget_changed(panel)

        # _rebuild_header must have been called (closes the stale-header gap)
        assert len(panel._rebuild_header_calls) > 0, \
            "_on_budget_changed must call _rebuild_header()"
        assert len(panel._refresh_budget_visibility_calls) > 0, \
            "_on_budget_changed must call _refresh_budget_visibility()"

    def test_plan_budget_visibility_treats_output_only_usage_as_meaningful(self):
        """tokens_out > 0 alone triggers budget visibility in expanded mode."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel

        panel = types.SimpleNamespace()
        panel._collapsed = False
        panel._active_hide_timer = None

        app = MagicMock()
        app.turn_cost_usd = 0.0
        app.turn_tokens_in = 0
        app.turn_tokens_out = 56
        panel.app = app

        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)

        PlanPanel._refresh_budget_visibility(panel, has_active=False, calls=[])
        mock_budget.set_class.assert_called_with(True, "--visible")
