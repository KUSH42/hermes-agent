"""Tests for live-audit fixes H-1 and H-2.

H-1: ExecuteCodeBlock.complete() / WriteFileBlock.complete() used _stop_all_managed()
     instead of a manual three-call block that referenced the deleted _spinner_timer.
H-2: LiveLineWidget._commit_lines logs engine-missing race at DEBUG not WARNING.

Spec: /home/xush/.hermes/2026-04-28-h1-h2-fix-spec.md
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _no_matches():
    from textual.css.query import NoMatches
    return NoMatches("no widget")


def _make_live_widget(engine=None):
    """Return a LiveLineWidget wired with mocked app/panel/msg/rl (no run_test)."""
    from textual.css.query import NoMatches
    from hermes_cli.tui.widgets.renderers import LiveLineWidget, CopyableRichLog

    live = LiveLineWidget()
    live._tw_enabled = False
    live._tw_delay = 0.0
    live._tw_burst = 0
    live._tw_cursor = False
    live._blink_visible = True
    live._blink_timer = None
    live._blink_enabled = False
    live._animating = False
    live._pre_engine_lines = []
    live._pre_engine_warned = False

    msg = MagicMock()
    msg._response_engine = engine
    rl = MagicMock(spec=CopyableRichLog)
    rl._deferred_renders = []
    rl.write_with_source.side_effect = lambda rich, plain, *a, **kw: None
    rl.write.side_effect = lambda arg, *a, **kw: None
    msg.current_prose_log.return_value = rl

    panel = MagicMock()
    panel.current_message = msg

    app = MagicMock()
    from hermes_cli.tui.widgets import OutputPanel
    def _query_one(cls):
        if cls is OutputPanel:
            return panel
        raise NoMatches(f"no {cls}")
    app.query_one.side_effect = _query_one
    type(live).app = property(lambda self: app)  # type: ignore[assignment]
    return live, msg


# ---------------------------------------------------------------------------
# H-1 — ExecuteCodeBlock
# ---------------------------------------------------------------------------

class TestH1ExecuteCodeBlock:
    def test_complete_calls_stop_all_managed(self):
        """complete() must delegate timer cleanup to _stop_all_managed, not manual .stop() calls."""
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock, _STATE_FINALIZED

        block = ExecuteCodeBlock(initial_label="python")
        block._completed = False
        block._code_state = _STATE_FINALIZED  # skip finalize_code()
        block._managed_timers = []
        block._managed_pacers = []
        block._cached_cursor = None
        block._code_lines = []
        block._code_line_count = 0

        mock_header = MagicMock()
        block._header = mock_header
        block._tail = MagicMock()

        with (
            patch.object(block, "_stop_all_managed") as mock_stop,
            patch.object(block, "_flush_pending"),
            patch.object(block, "query_one", side_effect=_no_matches()),
        ):
            block.complete("0.5s")

        mock_stop.assert_called_once()

    def test_complete_no_spinner_timer_debug_log(self):
        """After fix, no debug log referencing _spinner_timer should be emitted."""
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock, _STATE_FINALIZED

        block = ExecuteCodeBlock(initial_label="python")
        block._completed = False
        block._code_state = _STATE_FINALIZED
        block._managed_timers = []
        block._managed_pacers = []
        block._cached_cursor = None
        block._code_lines = []
        block._code_line_count = 0
        block._header = MagicMock()
        block._tail = MagicMock()

        with (
            patch("hermes_cli.tui.execute_code_block._log") as mock_log,
            patch.object(block, "_flush_pending"),
            patch.object(block, "query_one", side_effect=_no_matches()),
        ):
            block.complete("0.5s")

        for c in mock_log.debug.call_args_list:
            assert "_spinner_timer" not in str(c), (
                f"_spinner_timer should not appear in debug logs: {c}"
            )

    def test_complete_clears_managed_timers(self):
        """After complete(), _managed_timers must be empty (timers stopped and cleared)."""
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock, _STATE_FINALIZED

        block = ExecuteCodeBlock(initial_label="python")
        block._completed = False
        block._code_state = _STATE_FINALIZED
        block._managed_pacers = []
        block._cached_cursor = None
        block._code_lines = []
        block._code_line_count = 0
        block._header = MagicMock()
        block._tail = MagicMock()

        # Register two mock timers
        t1, t2 = MagicMock(), MagicMock()
        block._managed_timers = [
            {"timer": t1, "stopped": False},
            {"timer": t2, "stopped": False},
        ]

        with (
            patch.object(block, "_flush_pending"),
            patch.object(block, "query_one", side_effect=_no_matches()),
        ):
            block.complete("0.5s")

        t1.stop.assert_called_once()
        t2.stop.assert_called_once()
        assert block._managed_timers == []


# ---------------------------------------------------------------------------
# H-1 — WriteFileBlock
# ---------------------------------------------------------------------------

class TestH1WriteFileBlock:
    def test_complete_calls_stop_all_managed(self):
        """WriteFileBlock.complete() must use _stop_all_managed, not manual .stop() calls."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock(path="src/foo.py")
        block._managed_timers = []
        block._managed_pacers = []
        block._pacer = None
        block._line_scratch = ""
        block._progress = None
        block._header = MagicMock()
        block._tail = MagicMock()
        block._content_line_count = 0
        block._body = MagicMock()

        with (
            patch.object(block, "_stop_all_managed") as mock_stop,
            patch.object(block, "_flush_pending"),
            patch.object(block, "_rehighlight_body"),
        ):
            block.complete("0.3s")

        mock_stop.assert_called_once()

    def test_complete_no_spinner_timer_debug_log(self):
        """No debug log referencing _spinner_timer after fix."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock(path="src/foo.py")
        block._managed_timers = []
        block._managed_pacers = []
        block._pacer = None
        block._line_scratch = ""
        block._progress = None
        block._header = MagicMock()
        block._tail = MagicMock()
        block._content_line_count = 0
        block._body = MagicMock()

        with (
            patch("hermes_cli.tui.write_file_block._log") as mock_log,
            patch.object(block, "_flush_pending"),
            patch.object(block, "_rehighlight_body"),
        ):
            block.complete("0.3s")

        for c in mock_log.debug.call_args_list:
            assert "_spinner_timer" not in str(c), (
                f"_spinner_timer should not appear in debug logs: {c}"
            )

    def test_complete_clears_managed_timers(self):
        """WriteFileBlock.complete() stops and clears all registered timers."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock(path="src/foo.py")
        block._managed_pacers = []
        block._pacer = None
        block._line_scratch = ""
        block._progress = None
        block._header = MagicMock()
        block._tail = MagicMock()
        block._content_line_count = 0
        block._body = MagicMock()

        t1, t2 = MagicMock(), MagicMock()
        block._managed_timers = [
            {"timer": t1, "stopped": False},
            {"timer": t2, "stopped": False},
        ]

        with (
            patch.object(block, "_flush_pending"),
            patch.object(block, "_rehighlight_body"),
        ):
            block.complete("0.3s")

        t1.stop.assert_called_once()
        t2.stop.assert_called_once()
        assert block._managed_timers == []


# ---------------------------------------------------------------------------
# H-2 — LiveLineWidget log level downgrade
# ---------------------------------------------------------------------------

class TestH2LiveLineWidgetLogLevel:
    def test_pre_engine_race_logs_at_debug_not_warning(self):
        """Engine-missing race must log at DEBUG; WARNING must NOT be emitted."""
        live, _msg = _make_live_widget(engine=None)

        with patch("hermes_cli.tui.widgets.renderers._log") as mock_log:
            live._buf = "hello\ntail"
            live._commit_lines()

        mock_log.warning.assert_not_called()
        assert mock_log.debug.call_count >= 1
        first_debug = mock_log.debug.call_args_list[0].args[0]
        assert "engine missing on first chunk" in first_debug

    def test_pre_engine_race_one_shot_per_instance(self):
        """_pre_engine_warned latch suppresses duplicate debug logs on subsequent calls."""
        live, _msg = _make_live_widget(engine=None)

        with patch("hermes_cli.tui.widgets.renderers._log") as mock_log:
            live._buf = "line-a\nline-b\ntail"
            live._commit_lines()

        engine_missing_calls = [
            c for c in mock_log.debug.call_args_list
            if "engine missing on first chunk" in c.args[0]
        ]
        assert len(engine_missing_calls) == 1
        assert live._pre_engine_warned is True
