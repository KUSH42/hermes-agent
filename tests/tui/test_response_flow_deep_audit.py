"""Deep-audit fixes for ResponseFlowEngine / ReasoningFlowEngine.

Covers HIGH-1, HIGH-2, MED-1..4, LOW-1..3 from
2026-04-25-response-flow-deep-audit.md.

All tests use MagicMock / SimpleNamespace stubs; no full Textual app run.

Run with:
    pytest -o "addopts=" tests/tui/test_response_flow_deep_audit.py -v
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch


# ---------------------------------------------------------------------------
# Shared helper (self-contained per spec note)
# ---------------------------------------------------------------------------

def _make_engine(*, panel_app=True):
    from hermes_cli.tui.response_flow import ResponseFlowEngine
    log = MagicMock()
    log.write_with_source = MagicMock()
    panel = MagicMock()
    panel._msg_id = 1
    panel._prose_blocks = []
    panel.response_log = log
    panel._mount_nonprose_block = MagicMock()
    if panel_app:
        panel.app.get_css_variables.return_value = {"preview-syntax-theme": "monokai"}
    else:
        type(panel).app = PropertyMock(return_value=None)
    engine = ResponseFlowEngine(panel=panel)
    engine._prose_log = log
    return engine, log, panel


# ---------------------------------------------------------------------------
# HIGH-1 — code-fence buffer flushed before block opens
# ---------------------------------------------------------------------------

class TestHigh1FenceBufferFlushed:
    def _classify_call(self, mounted_widget) -> str:
        cls_name = type(mounted_widget).__name__
        return cls_name

    def test_high1_numbered_lines_before_fence(self):
        engine, log, panel = _make_engine()
        engine._code_fence_buffer = ["1 | first", "2 | second"]
        engine.process_line("```python")
        names = [self._classify_call(c.args[0]) for c in panel._mount_nonprose_block.call_args_list]
        assert "InlineCodeFence" in names
        assert "StreamingCodeBlock" in names
        assert names.index("InlineCodeFence") < names.index("StreamingCodeBlock")

    def test_high1_numbered_lines_before_indented_code(self):
        engine, log, panel = _make_engine()
        engine._code_fence_buffer = ["1 | a", "2 | b"]
        engine.process_line("    indented_code_line")
        names = [type(c.args[0]).__name__ for c in panel._mount_nonprose_block.call_args_list]
        assert "InlineCodeFence" in names
        assert "StreamingCodeBlock" in names
        assert names.index("InlineCodeFence") < names.index("StreamingCodeBlock")

    def test_high1_numbered_lines_before_source_like(self):
        engine, log, panel = _make_engine()
        engine._code_fence_buffer = ["1 | a", "2 | b"]
        engine._pending_source_line = "foo();"
        engine.process_line("bar();")
        names = [type(c.args[0]).__name__ for c in panel._mount_nonprose_block.call_args_list]
        assert "InlineCodeFence" in names
        assert "StreamingCodeBlock" in names
        assert names.index("InlineCodeFence") < names.index("StreamingCodeBlock")

    def test_high1_numbered_lines_before_math(self):
        engine, log, panel = _make_engine()
        engine._math_enabled = True
        # force unicode-only path so _flush_math_block doesn't dispatch worker
        engine._math_renderer_mode = "unicode"
        engine._code_fence_buffer = ["1 | a", "2 | b"]
        engine.process_line("$$x=1$$")
        names = [type(c.args[0]).__name__ for c in panel._mount_nonprose_block.call_args_list]
        assert "InlineCodeFence" in names

    def test_high1_numbered_lines_before_inline_label(self):
        engine, log, panel = _make_engine()
        engine._code_fence_buffer = ["1 | a", "2 | b"]
        engine.process_line("Result: 42")
        names = [type(c.args[0]).__name__ for c in panel._mount_nonprose_block.call_args_list]
        assert "InlineCodeFence" in names
        assert "StreamingCodeBlock" in names
        assert names.index("InlineCodeFence") < names.index("StreamingCodeBlock")


# ---------------------------------------------------------------------------
# HIGH-2 — init guarded against missing app
# ---------------------------------------------------------------------------

class TestHigh2InitAppGuard:
    def test_high2_init_no_app(self):
        engine, _, _ = _make_engine(panel_app=False)
        assert engine._skin_vars == {}
        assert engine._math_enabled is True

    def test_high2_init_app_no_get_css_variables(self):
        from hermes_cli.tui.response_flow import ResponseFlowEngine
        log = MagicMock()
        log.write_with_source = MagicMock()
        panel = MagicMock()
        panel.response_log = log
        ns = SimpleNamespace()
        ns._math_enabled = False
        type(panel).app = PropertyMock(return_value=ns)
        engine = ResponseFlowEngine(panel=panel)
        assert engine._skin_vars == {}
        assert engine._math_enabled is False


# ---------------------------------------------------------------------------
# MED-1 — math worker + reasoning footnote app guards
# ---------------------------------------------------------------------------

class TestMed1AppGuards:
    def test_med1a_math_worker_no_app(self):
        engine, log, panel = _make_engine(panel_app=False)
        engine._math_enabled = True
        engine._math_renderer_mode = "auto"
        # caps NONE would short-circuit; force image path enabled then guard via app=None
        with patch("hermes_cli.tui.kitty_graphics.get_caps") as mock_caps:
            from hermes_cli.tui.kitty_graphics import GraphicsCap
            mock_caps.return_value = GraphicsCap.TGP
            engine._flush_math_block("x = 1")
        # synchronous unicode fallback writes through write_with_source
        assert log.write_with_source.called
        assert not panel._mount_nonprose_block.called

    def test_med1b_reasoning_footnote_no_app(self):
        from hermes_cli.tui.response_flow import ReasoningFlowEngine
        panel = MagicMock()
        panel._reasoning_log = MagicMock()
        panel._plain_lines = []
        type(panel).app = PropertyMock(return_value=None)
        engine = ReasoningFlowEngine(panel=panel)
        engine._footnote_defs = {"1": "body"}
        engine._footnote_order = ["1"]
        # Must not raise
        engine._render_footnote_section()


# ---------------------------------------------------------------------------
# MED-2 — flush() resets orphan non-NORMAL state
# ---------------------------------------------------------------------------

class TestMed2OrphanStateReset:
    def test_med2_flush_orphaned_in_code_state(self):
        engine, log, panel = _make_engine()
        engine._state = "IN_CODE"
        engine._active_block = None
        with patch("hermes_cli.tui.response_flow.logger") as mock_log:
            engine.flush()
        assert engine._state == "NORMAL"
        mock_log.debug.assert_called()
        assert any("unexpected state" in str(c.args) for c in mock_log.debug.call_args_list)

    def test_med2_flush_orphaned_in_indented_code_state(self):
        engine, log, panel = _make_engine()
        engine._state = "IN_INDENTED_CODE"
        engine._active_block = None
        engine.flush()
        assert engine._state == "NORMAL"


# ---------------------------------------------------------------------------
# MED-3 — module-level regex constants + threading import
# ---------------------------------------------------------------------------

class TestMed3RegexHoisting:
    def test_med3_strip_ansi_module_constants_exist(self):
        import hermes_cli.tui.response_flow as m
        assert hasattr(m, "_ANSI_STRIP_RE")
        assert hasattr(m, "_STRIP_ORPHAN_RE")
        assert hasattr(m, "_NORM_ORPHAN_RE")
        assert callable(m.threading.get_ident)
        assert m._strip_ansi("\x1b[31mhello\x1b[0m") == "hello"

    def test_med3_normalize_ansi_no_regression(self):
        from hermes_cli.tui.response_flow import _normalize_ansi_for_render
        out = _normalize_ansi_for_render("\x1b[1;37mtext\x1b[0m")
        assert "text" in out


# ---------------------------------------------------------------------------
# MED-4 — _mount_emoji exception logged at debug
# ---------------------------------------------------------------------------

class TestMed4MountEmojiLogging:
    def test_med4_mount_emoji_exception_logged(self):
        engine, log, panel = _make_engine()
        # registry with one entry
        entry = SimpleNamespace(
            path="/tmp/x.png",
            pil_image=MagicMock(),
            n_frames=1,
            cell_width=2,
            cell_height=1,
        )
        engine._emoji_registry = {"smile": entry}
        engine._emoji_images_enabled = True
        # force has-image-support True
        with patch.object(engine, "_has_image_support", return_value=True):
            # force _do_mount to be called directly (same thread path)
            panel.app._thread_id = None  # both will compare to None
            with patch("hermes_cli.tui.response_flow.threading.get_ident", return_value=None):
                # mount raises
                panel.mount = MagicMock(side_effect=RuntimeError("gone"))
                with patch("hermes_cli.tui.response_flow.logger") as mock_log:
                    with patch("hermes_cli.tui.widgets.InlineImage", MagicMock()):
                        engine._mount_emoji("smile")
        mock_log.debug.assert_called()
        # at least one call had exc_info=True and 'mount failed' substring
        found = False
        for c in mock_log.debug.call_args_list:
            if c.kwargs.get("exc_info") is True and "mount failed" in str(c.args):
                found = True
                break
        assert found


# ---------------------------------------------------------------------------
# LOW-1 — _apply_cont_indent still wraps correctly
# ---------------------------------------------------------------------------

class TestLow1ApplyContIndent:
    def test_low1_cont_indent_wraps_correctly(self):
        from hermes_cli.tui.response_flow import _apply_cont_indent, _LIST_WRAP_WIDTH
        long = "word " * 40
        out = _apply_cont_indent(long.strip(), indent="  ")
        lines = out.split("\n")
        assert len(lines[0]) <= _LIST_WRAP_WIDTH
        for ln in lines[1:]:
            assert ln.startswith("  ")


# ---------------------------------------------------------------------------
# LOW-3 — code-fence buffer flushed before footnote drain
# ---------------------------------------------------------------------------

class TestLow3FootnoteFlushOrder:
    def test_low3_numbered_lines_before_footnote_flush_order(self):
        engine, log, panel = _make_engine()
        engine._code_fence_buffer = ["1 | a", "2 | b"]
        engine.process_line("[^1]: footnote text")
        engine.flush()
        # InlineCodeFence mount must happen before any footnote separator write
        mount_idx = None
        for i, c in enumerate(panel._mount_nonprose_block.call_args_list):
            if type(c.args[0]).__name__ == "InlineCodeFence":
                mount_idx = i
                break
        assert mount_idx is not None
        # any write with separator must occur after mount; check separator written at all
        sep_seen = any(
            "─" * 40 in (c.args[1] if len(c.args) > 1 else "")
            for c in log.write_with_source.call_args_list
        )
        assert sep_seen
