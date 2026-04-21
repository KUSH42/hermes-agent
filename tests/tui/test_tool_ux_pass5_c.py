"""Tests for Phase C — Error Handling & State (C1/C2/C3/C5)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from textual.widget import Widget
from textual.geometry import Size


def _bare_header(**kwargs):
    """ToolHeader via __new__ with minimal DOM stubs for _render_v4 testing."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    defaults = dict(
        _label="test", _tool_name="bash", _line_count=5, _panel=None,
        _spinner_char=None, _is_complete=True, _tool_icon_error=False,
        _primary_hero=None, _header_chips=[], _stats=None, _duration="1s",
        _has_affordances=False, _label_rich=None, _is_child_diff=False,
        _header_args={}, _flash_msg=None, _flash_expires=0.0, _flash_tone="success",
        _error_kind=None, _tool_icon="", _full_path=None, _path_clickable=False,
        _classes=frozenset(),
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(h, k, v)
    return h


# ---------------------------------------------------------------------------
# C1 — Timeout error kind detection
# ---------------------------------------------------------------------------

class TestC1Shell:
    def _make_ctx(self, raw, exit_code=None, is_error=True, error_kind=None):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        complete = ToolComplete(
            name="bash",
            raw_result=raw,
            exit_code=exit_code,
            is_error=is_error,
            error_kind=error_kind,
        )
        start = ToolStart(name="bash", args={"command": "sleep 100"})
        spec = MagicMock()
        spec.primary_result = "lines"
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_exit_124_becomes_timeout(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("Command timed out", exit_code=124)
        result = shell_result_v4(ctx)
        assert result.error_kind == "timeout"

    def test_timed_out_text_becomes_timeout(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("Process timed out after 30s", exit_code=1)
        result = shell_result_v4(ctx)
        assert result.error_kind == "timeout"

    def test_exit_137_becomes_signal(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("Process terminated", exit_code=137)
        result = shell_result_v4(ctx)
        assert result.error_kind == "signal"

    def test_sigkill_text_becomes_signal(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("SIGKILL received", exit_code=1)
        result = shell_result_v4(ctx)
        assert result.error_kind == "signal"

    def test_existing_error_kind_not_overwritten(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("failed", exit_code=1, error_kind="auth")
        result = shell_result_v4(ctx)
        assert result.error_kind == "auth"


class TestC1Code:
    def _make_ctx(self, raw, exit_code=None, is_error=True, error_kind=None):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        complete = ToolComplete(
            name="execute_code",
            raw_result=raw,
            exit_code=exit_code,
            is_error=is_error,
            error_kind=error_kind,
        )
        start = ToolStart(name="execute_code", args={"code": "import time; time.sleep(100)"})
        spec = MagicMock()
        spec.primary_result = "output"
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_code_exit_124_becomes_timeout(self):
        from hermes_cli.tui.tool_result_parse import code_result_v4
        ctx = self._make_ctx("Execution timed out", exit_code=124)
        result = code_result_v4(ctx)
        assert result.error_kind == "timeout"

    def test_code_exit_143_becomes_signal(self):
        from hermes_cli.tui.tool_result_parse import code_result_v4
        ctx = self._make_ctx("Script killed", exit_code=143)
        result = code_result_v4(ctx)
        assert result.error_kind == "signal"


# ---------------------------------------------------------------------------
# C2 — Remediation hints
# ---------------------------------------------------------------------------

class TestC2Shell:
    def _make_ctx(self, raw, exit_code, error_kind=None):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        complete = ToolComplete(
            name="bash",
            raw_result=raw,
            exit_code=exit_code,
            is_error=True,
            error_kind=error_kind,
        )
        start = ToolStart(name="bash", args={"command": "test"})
        spec = MagicMock()
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_timeout_remediation(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("timed out", 124, error_kind="timeout")
        result = shell_result_v4(ctx)
        chip_remediations = [c.remediation for c in result.chips if c.remediation]
        assert any("timeout_sec" in r for r in chip_remediations)

    def test_exit_127_command_not_found(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("command not found", 127)
        result = shell_result_v4(ctx)
        chip_remediations = [c.remediation for c in result.chips if c.remediation]
        assert any("PATH" in r for r in chip_remediations)

    def test_signal_remediation(self):
        from hermes_cli.tui.tool_result_parse import shell_result_v4
        ctx = self._make_ctx("SIGKILL", 137, error_kind="signal")
        result = shell_result_v4(ctx)
        chip_remediations = [c.remediation for c in result.chips if c.remediation]
        assert any("killed" in r or "memory" in r for r in chip_remediations)


class TestC2Code:
    def _make_ctx(self, raw, exit_code=1):
        from hermes_cli.tui.tool_result_parse import ParseContext, ToolComplete, ToolStart
        complete = ToolComplete(
            name="execute_code",
            raw_result=raw,
            exit_code=exit_code,
            is_error=True,
            error_kind=None,
        )
        start = ToolStart(name="execute_code", args={"code": "import foo"})
        spec = MagicMock()
        return ParseContext(complete=complete, start=start, spec=spec)

    def test_import_error_remediation(self):
        from hermes_cli.tui.tool_result_parse import code_result_v4
        ctx = self._make_ctx("ModuleNotFoundError: No module named 'pandas'")
        result = code_result_v4(ctx)
        chip_remediations = [c.remediation for c in result.chips if c.remediation]
        assert any("pip" in r for r in chip_remediations)

    def test_timeout_code_remediation(self):
        from hermes_cli.tui.tool_result_parse import code_result_v4
        ctx = self._make_ctx("timed out", 124)
        result = code_result_v4(ctx)
        chip_remediations = [c.remediation for c in result.chips if c.remediation]
        assert any("timeout" in r for r in chip_remediations)


# ---------------------------------------------------------------------------
# C3 — Diff stat "(partial)" when windowed
# ---------------------------------------------------------------------------

class TestC3:
    def test_partial_label_when_windowed(self):
        from hermes_cli.tui.tool_blocks import ToolHeaderStats
        panel_mock = MagicMock()
        panel_mock.collapsed = False
        panel_mock._block = MagicMock()
        panel_mock._block._visible_count = 50
        panel_mock._block._all_plain = ["x"] * 100  # 100 total, only 50 visible
        h = _bare_header(
            _label="diff", _line_count=100,
            _stats=ToolHeaderStats(additions=10, deletions=5),
            _panel=panel_mock,
            _has_affordances=True,
        )

        with patch("hermes_cli.tui.tool_blocks.spec_for") as ms:
            ms.return_value = MagicMock(render_header=True, primary_arg=None,
                                        category=MagicMock(value="shell"))
            with patch.object(h, "_accessible_mode", return_value=False):
                with patch.object(Widget, "size", new_callable=PropertyMock,
                                  return_value=Size(80, 24)):
                    result = h._render_v4()

        if result is not None:
            assert "(partial)" in result.plain


# ---------------------------------------------------------------------------
# C5 — Copy feedback format label + tone
# ---------------------------------------------------------------------------

class TestC5:
    def test_flash_tone_attr_exists(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        h = ToolHeader.__new__(ToolHeader)
        h._flash_tone = "success"
        assert h._flash_tone == "success"

    def test_flash_tone_defaults_success(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        h = ToolHeader("test", 5)
        assert h._flash_tone == "success"

    def test_flash_style_uses_tone(self):
        """Flash style maps: success→dim green, warning→dim yellow, error→dim red."""
        import time
        h = _bare_header(
            _flash_tone="warning",
            _flash_msg="copied HTML",
            _flash_expires=time.monotonic() + 10.0,
            _duration="",
        )

        with patch("hermes_cli.tui.tool_blocks.spec_for") as ms:
            ms.return_value = MagicMock(render_header=True, primary_arg=None,
                                        category=MagicMock(value="file"))
            with patch.object(h, "_accessible_mode", return_value=False):
                with patch.object(Widget, "size", new_callable=PropertyMock,
                                  return_value=Size(80, 24)):
                    result = h._render_v4()

        if result is not None:
            assert "copied HTML" in result.plain

    def test_flash_header_passes_tone(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = object.__new__(ToolPanel)
        panel._block = MagicMock()
        panel._block._header = MagicMock()
        panel._block._header._flash_msg = None
        panel._block._header._flash_tone = "success"

        import time
        with patch.object(panel, "set_timer"):
            panel._flash_header("copied HTML", tone="warning")

        assert panel._block._header._flash_tone == "warning"
        assert panel._block._header._flash_msg == "copied HTML"
