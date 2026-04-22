"""tests/tui/test_response_flow_parser.py — 17 tests for parser hardening

Groups:
  P1 (3): _code_fence_buffer init — lives in __init__, not reset by _write_prose
  P2 (2): flush() missing imports — no NameError when _pending_source_line at turn end
  P3 (6): _commit_prose_line wired — InlineCodeFence accumulates and mounts correctly
  P4 (1): _mount_math_image stray flush removed
  P5 (5): _looks_like_source_line =‑heuristic tightened
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.response_flow import (
    ResponseFlowEngine,
    _looks_like_source_line,
    InlineCodeFence,
)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def _make_engine() -> ResponseFlowEngine:
    panel = MagicMock()
    panel.app.get_css_variables.return_value = {}
    panel.app._math_enabled = False
    panel.app._math_renderer = "unicode"
    panel.app._mermaid_enabled = False
    panel.app._math_dpi = 150
    panel.app._math_max_rows = 12
    panel.app._citations_enabled = False
    panel.app._emoji_registry = None
    panel.app._emoji_images_enabled = False
    panel.response_log = MagicMock()
    panel.response_log.write_with_source = MagicMock()
    panel.response_log._plain_lines = []
    panel.current_prose_log = MagicMock(return_value=panel.response_log)
    panel.is_attached = True
    return ResponseFlowEngine(panel=panel)


# ---------------------------------------------------------------------------
# P1 — _code_fence_buffer init
# ---------------------------------------------------------------------------

class TestCodeFenceBufferInit:
    def test_p1a_buffer_exists_after_init(self) -> None:
        engine = _make_engine()
        assert hasattr(engine, "_code_fence_buffer")
        assert engine._code_fence_buffer == []

    def test_p1b_write_prose_does_not_reset_buffer(self) -> None:
        """_write_prose must NOT overwrite _code_fence_buffer."""
        from rich.text import Text
        engine = _make_engine()
        engine._code_fence_buffer = ["  1 | def foo():"]
        engine._write_prose(Text("hello"), "hello")
        assert engine._code_fence_buffer == ["  1 | def foo():"], (
            "_write_prose reset _code_fence_buffer — bug P1 not fixed"
        )

    def test_p1c_buffer_survives_two_prose_writes(self) -> None:
        from rich.text import Text
        engine = _make_engine()
        engine._code_fence_buffer = ["line1", "line2"]
        engine._write_prose(Text("a"), "a")
        engine._write_prose(Text("b"), "b")
        assert engine._code_fence_buffer == ["line1", "line2"]


# ---------------------------------------------------------------------------
# P2 — flush() import guard
# ---------------------------------------------------------------------------

class TestFlushImport:
    def test_p2a_flush_no_error_with_pending_source_line(self) -> None:
        """flush() must not raise NameError when _pending_source_line is set."""
        engine = _make_engine()
        engine._pending_source_line = "x = foo(bar)"
        try:
            engine.flush()
        except NameError as e:
            pytest.fail(f"flush() raised NameError — missing import: {e}")

    def test_p2b_flush_writes_pending_source_line_to_log(self) -> None:
        engine = _make_engine()
        engine._pending_source_line = "result = compute()"
        written: list[str] = []
        engine._prose_log.write_with_source.side_effect = lambda t, p: written.append(p)
        engine.flush()
        assert any("result" in w or "compute" in w for w in written), (
            "flush() did not write pending source line to prose log"
        )


# ---------------------------------------------------------------------------
# P3 — _commit_prose_line wired into prose path
# ---------------------------------------------------------------------------

class TestCommitProseLineWired:
    def _engine_with_mount_spy(self):
        engine = _make_engine()
        mounted: list[object] = []

        def _mount_nonprose(widget):
            mounted.append(widget)

        engine._panel._mount_nonprose_block.side_effect = _mount_nonprose
        engine._panel.call_after_refresh = lambda fn, *a: fn(*a)
        return engine, mounted

    def test_p3a_single_numbered_line_goes_to_prose(self) -> None:
        engine, mounted = self._engine_with_mount_spy()
        written: list[str] = []
        engine._prose_log.write_with_source.side_effect = lambda t, p: written.append(p)
        engine.process_line("Some prose")
        engine.process_line("  1 | def foo():")
        engine.flush()
        assert not any(isinstance(w, InlineCodeFence) for w in mounted)
        # single line flushed as plain prose
        assert any("1" in w and "def foo" in w for w in written)

    def test_p3b_two_numbered_lines_mount_inline_code_fence(self) -> None:
        engine, mounted = self._engine_with_mount_spy()
        engine.process_line("  1 | def foo():")
        engine.process_line("  2 |     pass")
        engine.process_line("More prose after")
        engine.flush()  # SBB holds one line; flush drains it and the buffer
        assert any(isinstance(w, InlineCodeFence) for w in mounted)

    def test_p3c_three_numbered_lines_mount_one_fence(self) -> None:
        engine, mounted = self._engine_with_mount_spy()
        engine.process_line("  1 | x = 1")
        engine.process_line("  2 | y = 2")
        engine.process_line("  3 | z = 3")
        engine.process_line("Done.")
        engine.flush()
        fences = [w for w in mounted if isinstance(w, InlineCodeFence)]
        assert len(fences) == 1
        assert len(fences[0]._lines) == 3

    def test_p3d_numbered_lines_followed_by_prose_flushes_fence(self) -> None:
        """InlineCodeFence is flushed when a non-numbered prose line follows."""
        engine, mounted = self._engine_with_mount_spy()
        written: list[str] = []
        engine._prose_log.write_with_source.side_effect = lambda t, p: written.append(p)
        engine.process_line("  1 | a = 1")
        engine.process_line("  2 | b = 2")
        engine.process_line("This is prose.")
        engine.flush()
        fences = [w for w in mounted if isinstance(w, InlineCodeFence)]
        assert len(fences) == 1
        assert any("This is prose" in w for w in written)

    def test_p3e_flush_drains_open_buffer(self) -> None:
        """flush() must drain any remaining numbered-line buffer."""
        engine, mounted = self._engine_with_mount_spy()
        engine.process_line("  1 | foo = 1")
        engine.process_line("  2 | bar = 2")
        engine.flush()  # turn ends with no following prose
        assert any(isinstance(w, InlineCodeFence) for w in mounted)

    def test_p3f_prose_callback_fires_via_commit_prose_line(self) -> None:
        """_prose_callback must fire when lines go through _commit_prose_line."""
        engine = _make_engine()
        fired: list[str] = []
        engine._prose_callback = fired.append
        engine.process_line("Hello world")
        engine.flush()  # SBB holds one line; flush drains it
        assert any("Hello" in f for f in fired)


# ---------------------------------------------------------------------------
# P4 — _mount_math_image stray flush removed
# ---------------------------------------------------------------------------

class TestMountMathImageNoFlush:
    def test_p4_mount_math_image_does_not_call_flush_code_fence_buffer(self) -> None:
        engine = _make_engine()
        flush_calls: list[None] = []
        engine._flush_code_fence_buffer = lambda: flush_calls.append(None)  # type: ignore[method-assign]
        engine._panel._mount_nonprose_block = MagicMock()

        from pathlib import Path
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
            tmp = Path(f.name)
        try:
            with patch("hermes_cli.tui.widgets.MathBlockWidget", MagicMock()):
                engine._mount_math_image(tmp, 12)
        finally:
            tmp.unlink(missing_ok=True)

        assert flush_calls == [], (
            "_mount_math_image still calls _flush_code_fence_buffer — P4 not fixed"
        )


# ---------------------------------------------------------------------------
# P5 — _looks_like_source_line =‑heuristic
# ---------------------------------------------------------------------------

class TestLooksLikeSourceLineTightened:
    def test_p5a_bare_assignment_is_source(self) -> None:
        assert _looks_like_source_line("x=1")

    def test_p5b_key_equals_val_is_source(self) -> None:
        assert _looks_like_source_line("KEY=val")

    def test_p5c_function_call_assignment_is_source(self) -> None:
        assert _looks_like_source_line("foo = bar()")

    def test_p5d_prose_sentence_with_mid_equals_not_source(self) -> None:
        assert not _looks_like_source_line("the value is x = 5")

    def test_p5e_prose_sentence_starting_with_the_not_source(self) -> None:
        assert not _looks_like_source_line("the cost was set to low")
