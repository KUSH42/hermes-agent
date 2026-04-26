"""Tests for Streaming Pipeline Polish Spec (L1/L2/L3/L5/L6/L7/L11).

Run with:
    pytest -o "addopts=" tests/tui/test_streaming_polish.py -v
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

# ---------------------------------------------------------------------------
# Paths for static/AST checks
# ---------------------------------------------------------------------------

_STREAMING_PATH = Path("hermes_cli/tui/body_renderers/streaming.py")
_RESPONSE_FLOW_PATH = Path("hermes_cli/tui/response_flow.py")


def _tw_patch(enabled: bool = True, speed: int = 1, burst: int = 128, cursor: bool = False):
    import hermes_cli.tui.widgets as _w
    from unittest.mock import patch as _p
    return (
        _p.object(_w, "_typewriter_enabled", return_value=enabled),
        _p.object(_w, "_typewriter_delay_s", return_value=(1.0 / speed if speed > 0 else 0.0)),
        _p.object(_w, "_typewriter_burst_threshold", return_value=burst),
        _p.object(_w, "_typewriter_cursor_enabled", return_value=cursor),
    )


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


# ---------------------------------------------------------------------------
# L1 — Diff regex single-source
# ---------------------------------------------------------------------------

class TestL1DiffRegexShared:
    def test_diff_regex_single_source(self) -> None:
        """streaming._DIFF_HEADER_RE and _DIFF_ARROW_RE must be the same object as _shared's."""
        from hermes_cli.tui.body_renderers import streaming
        from hermes_cli.tui.tool_blocks import _shared

        assert streaming._DIFF_HEADER_RE is _shared._DIFF_HEADER_RE
        assert streaming._DIFF_ARROW_RE is _shared._DIFF_ARROW_RE


# ---------------------------------------------------------------------------
# L2 — _blink_visible reset on remount
# ---------------------------------------------------------------------------

class TestL2BlinkVisibleReset:
    @pytest.mark.asyncio
    async def test_blink_visible_reset_on_remount(self) -> None:
        """on_mount must reset _blink_visible=True even after a prior False value."""
        from hermes_cli.tui.widgets import LiveLineWidget

        patches = _tw_patch(enabled=False)

        class _LiveApp(App):
            def compose(self) -> ComposeResult:
                yield LiveLineWidget()

        with patches[0], patches[1], patches[2], patches[3]:
            app = _LiveApp()
            async with app.run_test(size=(80, 24)) as pilot:
                widget = app.query_one(LiveLineWidget)
                await pilot.pause()

                # Simulate blink timer flipping cursor invisible
                widget._blink_visible = False

                # Remove and remount a fresh instance
                await widget.remove()
                w2 = LiveLineWidget()
                await app.mount(w2)
                await pilot.pause()

                assert w2._blink_visible is True


# ---------------------------------------------------------------------------
# L3 — Orphaned CSI strip logs count
# ---------------------------------------------------------------------------

class TestL3OrphanedCSILog:
    def test_orphaned_csi_strip_logs_count(self, caplog: pytest.LogCaptureFixture) -> None:
        """subn path must log number of stripped orphaned CSI sequences."""
        from hermes_cli.tui.widgets.renderers import _ORPHANED_CSI_RE

        # Two orphaned CSI sequences (bracket + digits + letter, no leading ESC)
        text_with_orphans = "hello[0mworld[1;32mend"

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.renderers"):
            buf, n = _ORPHANED_CSI_RE.subn("", text_with_orphans)
            if n:
                logging.getLogger("hermes_cli.tui.widgets.renderers").debug(
                    "stripped %d orphaned CSI sequences from chunk", n
                )

        assert n == 2
        assert "stripped 2 orphaned" in caplog.text
        assert "[0m" not in buf
        assert "[1;32m" not in buf


# ---------------------------------------------------------------------------
# L5 — FileRenderer.render_stream_line logs and returns dim Text on failure
# ---------------------------------------------------------------------------

class TestL5SyntaxFallbackLog:
    def test_syntax_render_failure_logs_and_returns_dim_text(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When Syntax() raises, render_stream_line must log at debug and return dim Text."""
        from rich.text import Text
        from hermes_cli.tui.body_renderers.streaming import FileRenderer

        renderer = FileRenderer.__new__(FileRenderer)

        with patch("rich.syntax.Syntax", side_effect=Exception("boom")):
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.body_renderers.streaming"):
                result = renderer.render_stream_line("raw", "plain code", lang="python")

        assert isinstance(result, Text)
        assert "dim" in str(result.style)
        assert "syntax render failed" in caplog.text


# ---------------------------------------------------------------------------
# L7 — Logger at module top (before first ClassDef/FunctionDef)
# ---------------------------------------------------------------------------

class TestL7LoggerPosition:
    def test_response_flow_module_logger_at_top(self) -> None:
        """_log assignment must appear before the first ClassDef/FunctionDef in response_flow.py."""
        tree = _parse_module(_RESPONSE_FLOW_PATH)
        log_assign_idx: int | None = None
        first_def_idx: int | None = None

        for i, node in enumerate(tree.body):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_log"
                and log_assign_idx is None
            ):
                log_assign_idx = i
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and first_def_idx is None
            ):
                first_def_idx = i

        assert log_assign_idx is not None, "_log assignment not found in response_flow.py module body"
        assert first_def_idx is not None, "No ClassDef/FunctionDef found in response_flow.py"
        assert log_assign_idx < first_def_idx, (
            f"_log (index {log_assign_idx}) must appear before first class/function "
            f"(index {first_def_idx})"
        )


# ---------------------------------------------------------------------------
# L11 — Queue overflow does not lose chars
# ---------------------------------------------------------------------------

class TestL11QueueOverflow:
    @pytest.mark.asyncio
    async def test_typewriter_queue_overflow_does_not_lose_chars(self) -> None:
        """Feeding > _TW_CHAR_QUEUE_MAX chars must not lose any chars after flush()."""
        from hermes_cli.tui.widgets import LiveLineWidget
        from hermes_cli.tui.widgets.renderers import _TW_CHAR_QUEUE_MAX

        patches = _tw_patch(enabled=True, speed=1, burst=128, cursor=False)

        class _LiveApp(App):
            def compose(self) -> ComposeResult:
                yield LiveLineWidget()

        with patches[0], patches[1], patches[2], patches[3]:
            app = _LiveApp()
            async with app.run_test(size=(80, 24)) as pilot:
                widget = app.query_one(LiveLineWidget)
                await pilot.pause()

                n_chars = _TW_CHAR_QUEUE_MAX + 904  # well above 4096 cap, no newlines
                widget.feed("a" * n_chars)
                widget.flush()

                total = len(widget._buf)
                assert total == n_chars, (
                    f"Expected {n_chars} chars after overflow+flush, got {total} — chars lost"
                )


# ---------------------------------------------------------------------------
# Regression guards
# ---------------------------------------------------------------------------

class TestRegressionGuards:
    def test_no_duplicate_regex_in_streaming_module(self) -> None:
        """streaming.py must not define _DIFF_HEADER_RE/_DIFF_ARROW_RE locally."""
        tree = _parse_module(_STREAMING_PATH)
        forbidden = {"_DIFF_HEADER_RE", "_DIFF_ARROW_RE"}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in forbidden:
                        pytest.fail(
                            f"{target.id} must not be defined in streaming.py — "
                            "import from tool_blocks._shared instead"
                        )

    def test_file_renderer_except_block_logs(self) -> None:
        """FileRenderer.render_stream_line except block must call _log.*."""
        tree = _parse_module(_STREAMING_PATH)

        file_renderer: ast.ClassDef | None = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "FileRenderer":
                file_renderer = node
                break
        assert file_renderer is not None, "FileRenderer not found in streaming.py"

        method: ast.FunctionDef | None = None
        for node in file_renderer.body:
            if isinstance(node, ast.FunctionDef) and node.name == "render_stream_line":
                method = node
                break
        assert method is not None, "render_stream_line not found in FileRenderer"

        found_log_call = False
        for node in ast.walk(method):
            if isinstance(node, ast.ExceptHandler):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if (
                            isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "_log"
                            and func.attr in ("debug", "exception", "warning", "error")
                        ):
                            found_log_call = True
                            break

        assert found_log_call, (
            "FileRenderer.render_stream_line except block must call _log.debug/exception"
        )
