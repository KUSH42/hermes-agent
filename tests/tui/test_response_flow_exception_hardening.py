"""Exception hardening tests for ResponseFlowEngine / ReasoningFlowEngine.

Covers H-1..H-3, M-1..M-6, L-1..L-2 from spec_response_flow_exception_hardening.md.
All tests use MagicMock / SimpleNamespace stubs; no full Textual app run.

Run with:
    pytest -o "addopts=" tests/tui/test_response_flow_exception_hardening.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest
from rich.text import Text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_engine(*, prose_callback=None):
    """Minimal ResponseFlowEngine with fully mocked DOM."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    log = MagicMock()
    log.write_with_source = MagicMock()
    panel = MagicMock()
    panel._msg_id = 1
    panel._prose_blocks = []
    panel.response_log = log
    panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    engine = ResponseFlowEngine(panel=panel)
    engine._prose_log = log
    if prose_callback is not None:
        engine._prose_callback = prose_callback
    return engine, log, panel


# ---------------------------------------------------------------------------
# H-1 — prose_callback silent swallow with debug log
# ---------------------------------------------------------------------------

class TestH1ProseCallbackSwallow:
    def test_h1_prose_callback_exception_does_not_propagate(self):
        """Raising prose_callback must not crash process_line; debug log fired."""
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        engine, log, _ = _make_engine(prose_callback=bad_callback)

        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            engine.process_line("hello world")
            engine.flush()

        # prose was still written
        assert log.write_with_source.called
        # debug was fired with exc_info=True
        mock_log.debug.assert_called_once()
        call_kwargs = mock_log.debug.call_args
        assert call_kwargs.kwargs.get("exc_info") is True or (
            len(call_kwargs.args) >= 1 and call_kwargs[1].get("exc_info") is True
        )

    def test_h1_inline_emoji_callback_exception_does_not_propagate(self):
        """Raising prose_callback in _write_prose_inline_emojis must not crash."""
        from pathlib import Path

        bad_callback = MagicMock(side_effect=ValueError("emoji boom"))
        engine, log, panel = _make_engine(prose_callback=bad_callback)

        # Wire write_inline so the emoji path proceeds past early exits
        log.write_inline = MagicMock()

        # Emoji entry with required attributes
        entry = SimpleNamespace(pil_image=None, path="/tmp/smile.png", cell_width=2, cell_height=1)
        engine._emoji_registry = {"smile": entry}

        plain = "hello :smile: world"
        rich_text = Text(plain)

        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            with patch.object(engine, "_has_image_support", return_value=True):
                engine._write_prose_inline_emojis(rich_text, plain)

        mock_log.debug.assert_called_once()
        call_kwargs = mock_log.debug.call_args
        assert call_kwargs.kwargs.get("exc_info") is True or (
            len(call_kwargs.args) >= 1 and call_kwargs[1].get("exc_info") is True
        )


# ---------------------------------------------------------------------------
# H-2 — _mount_sources_bar logs warning on failure
# ---------------------------------------------------------------------------

class TestH2MountSourcesBarLogging:
    def _make_engine_with_citation(self):
        engine, log, panel = _make_engine()
        engine._cite_entries = {"[1]": ("Title", "https://example.com", None)}
        engine._cite_order = ["[1]"]
        engine._citations_enabled = True
        return engine, log, panel

    def _call_mount_sources_bar(self, engine, panel):
        """Capture the _do_mount closure from _mount_sources_bar."""
        captured_fn = None

        def _capture_refresh(fn):
            nonlocal captured_fn
            captured_fn = fn

        panel.call_after_refresh.side_effect = _capture_refresh
        with patch("hermes_cli.tui.widgets.SourcesBar", MagicMock(return_value=MagicMock())):
            engine._mount_sources_bar()
        return captured_fn

    def test_h2_sources_bar_mount_failure_logs_warning(self):
        engine, log, panel = self._make_engine_with_citation()
        captured_fn = self._call_mount_sources_bar(engine, panel)

        assert captured_fn is not None
        panel.mount.side_effect = RuntimeError("mount failed")
        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            with patch("hermes_cli.tui.widgets.SourcesBar", MagicMock()):
                captured_fn()
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs.get("exc_info") is True

    def test_h2_sources_bar_mount_success_no_warning(self):
        engine, log, panel = self._make_engine_with_citation()
        captured_fn = self._call_mount_sources_bar(engine, panel)

        assert captured_fn is not None
        panel.mount.side_effect = None
        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            with patch("hermes_cli.tui.widgets.SourcesBar", MagicMock()):
                captured_fn()
        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# H-3 — _mount_math_image logs warning on failure
# ---------------------------------------------------------------------------

class TestH3MountMathImageLogging:
    def test_h3_mount_math_image_failure_logs_warning(self):
        engine, log, panel = _make_engine()
        panel._mount_nonprose_block.side_effect = RuntimeError("widget boom")

        from pathlib import Path
        path = Path("/tmp/math.png")

        # MathBlockWidget is imported inline inside _mount_math_image — patch at source
        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            with patch("hermes_cli.tui.widgets.MathBlockWidget", MagicMock()):
                engine._mount_math_image(path, max_rows=10)

        mock_log.warning.assert_called_once()
        args, kwargs = mock_log.warning.call_args
        assert str(path) in str(args)
        assert kwargs.get("exc_info") is True

    def test_h3_mount_math_image_import_error_logs_warning(self):
        engine, log, panel = _make_engine()

        from pathlib import Path
        path = Path("/tmp/math2.png")

        # Make the inline import raise
        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            with patch.dict("sys.modules", {"hermes_cli.tui.widgets": None}):
                engine._mount_math_image(path, max_rows=5)

        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# M-1 — _handle_unknown_state uses module logger
# ---------------------------------------------------------------------------

class TestM1UnknownStateUsesLogger:
    def test_m1_unknown_state_logs_via_module_logger(self):
        engine, log, panel = _make_engine()
        engine._state = "BOGUS"

        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            engine._handle_unknown_state("some line")

        mock_log.warning.assert_called_once()
        msg = mock_log.warning.call_args.args[0]
        assert "BOGUS" in str(mock_log.warning.call_args) or \
               "BOGUS" in str(mock_log.warning.call_args.args[1:])
        assert engine._state == "NORMAL"

    def test_m1_unknown_state_does_not_use_panel_app_log(self):
        engine, log, panel = _make_engine()
        engine._state = "BOGUS"
        engine._active_block = None

        with patch("hermes_cli.tui.response_flow.logger"):
            engine._handle_unknown_state("x")

        # panel.app.log.warning must never be called
        panel.app.log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# M-2 — _handle_unknown_state flushes _active_block
# ---------------------------------------------------------------------------

class TestM2UnknownStateFlushesBlock:
    def test_m2_unknown_state_flushes_active_block(self):
        engine, log, panel = _make_engine()
        engine._state = "BOGUS"
        mock_block = MagicMock()
        engine._active_block = mock_block

        with patch("hermes_cli.tui.response_flow.logger"):
            engine._handle_unknown_state("x")

        mock_block.flush.assert_called_once()
        assert engine._active_block is None

    def test_m2_unknown_state_block_flush_failure_logs_debug(self):
        engine, log, panel = _make_engine()
        engine._state = "BOGUS"
        mock_block = MagicMock()
        mock_block.flush.side_effect = RuntimeError("already removed")
        engine._active_block = mock_block

        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            engine._handle_unknown_state("x")

        mock_log.debug.assert_called_once()
        assert mock_log.debug.call_args.kwargs.get("exc_info") is True
        assert engine._active_block is None


# ---------------------------------------------------------------------------
# M-3 — _resolve_log_width fallback behavior
# ---------------------------------------------------------------------------

class TestM3ResolveLogWidthFallback:
    def test_m3_resolve_log_width_region_fallback(self):
        """scrollable_content_region raises → falls through to size.width."""
        from hermes_cli.tui.response_flow import _resolve_log_width

        widget = MagicMock()
        type(widget).scrollable_content_region = PropertyMock(side_effect=RuntimeError)
        widget.size.width = 120

        result = _resolve_log_width(widget)
        assert result == 120

    def test_m3_resolve_log_width_all_fallback(self):
        """All three accessors raise → returns 80."""
        from hermes_cli.tui.response_flow import _resolve_log_width

        widget = MagicMock()
        type(widget).scrollable_content_region = PropertyMock(side_effect=RuntimeError)
        type(widget).size = PropertyMock(side_effect=RuntimeError)
        type(widget).app = PropertyMock(side_effect=RuntimeError)

        result = _resolve_log_width(widget)
        assert result == 80


# ---------------------------------------------------------------------------
# M-4 — _make_rule cap failure does not raise
# ---------------------------------------------------------------------------

class TestM4MakeRuleCapFailure:
    def test_m4_make_rule_app_cap_failure_does_not_raise(self):
        """Both app.size accesses raise → returns Text of width 80."""
        from hermes_cli.tui.response_flow import _make_rule

        widget = MagicMock()
        type(widget).scrollable_content_region = PropertyMock(side_effect=RuntimeError)
        type(widget).size = PropertyMock(side_effect=RuntimeError)
        type(widget).app = PropertyMock(side_effect=RuntimeError)

        result = _make_rule(widget)
        assert isinstance(result, Text)
        assert len(result.plain) == 80


# ---------------------------------------------------------------------------
# M-5 — _detect_lang pygments failure returns "text"
# ---------------------------------------------------------------------------

class TestM5DetectLangPygmentsFailure:
    def test_m5_detect_lang_pygments_failure_returns_text(self):
        from hermes_cli.tui.response_flow import _detect_lang

        with patch("pygments.lexers.guess_lexer", side_effect=Exception("ClassNotFound")):
            result = _detect_lang("some ambiguous code")

        assert result == "text"


# ---------------------------------------------------------------------------
# M-6 — flush() detached guard
# ---------------------------------------------------------------------------

class TestM6FlushDetachedGuard:
    def test_m6_flush_returns_early_when_detached(self):
        engine, log, panel = _make_engine()
        engine._detached = True

        engine.flush()

        log.write_with_source.assert_not_called()

    def test_m6_flush_skips_block_close_when_detached(self):
        engine, log, panel = _make_engine()
        engine._detached = True
        mock_block = MagicMock()
        engine._active_block = mock_block
        engine._state = "IN_CODE"

        engine.flush()

        mock_block.flush.assert_not_called()

    def test_m6_flush_normal_when_not_detached(self):
        engine, log, panel = _make_engine()
        engine._detached = False
        engine._partial = "some partial"
        engine._clear_partial_preview = MagicMock()

        engine.flush()

        # prose log must have been written at some point via process_line("some partial")
        assert log.write_with_source.called


# ---------------------------------------------------------------------------
# L-1 — ReasoningFlowEngine init with None app uses defaults
# ---------------------------------------------------------------------------

class TestL1ReasoningInitPanelApp:
    def test_l1_reasoning_engine_init_with_none_app_uses_defaults(self):
        from hermes_cli.tui.response_flow import ReasoningFlowEngine

        # Use a plain object with app=None so getattr(panel, "app", None) → None
        panel = SimpleNamespace(
            app=None,
            _reasoning_log=MagicMock(),
            _plain_lines=[],
        )

        eng = ReasoningFlowEngine(panel=panel)

        assert eng._citations_enabled is True
        assert eng._emoji_images_enabled is True


# ---------------------------------------------------------------------------
# L-2 — _flush_code_fence_buffer mount failure logs debug + writes prose
# ---------------------------------------------------------------------------

class TestL2CodeFenceBufferFallback:
    def test_l2_code_fence_buffer_mount_failure_logs_debug_and_writes_prose(self):
        engine, log, panel = _make_engine()
        panel._mount_nonprose_block.side_effect = RuntimeError("no mount")
        engine._sync_prose_log = MagicMock()

        # Seed two numbered lines into the buffer
        engine._code_fence_buffer = ["  1  foo", "  2  bar"]

        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            engine._flush_code_fence_buffer()

        mock_log.debug.assert_called_once()
        assert mock_log.debug.call_args.kwargs.get("exc_info") is True
        # Both lines written as prose fallback
        assert log.write_with_source.call_count == 2
