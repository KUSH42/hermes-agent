"""Tests for ToolPanel border-left accent contract (AC-HIGH-01, AC-MED-01, AC-LOW-01)."""
from __future__ import annotations

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from hermes_cli.tui.app import HermesApp
    return HermesApp(cli=MagicMock())


async def _pause(pilot, times: int = 3) -> None:
    for _ in range(times):
        await pilot.pause()


def _make_summary(*, is_error: bool, exit_code: int | None = None):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=is_error,
    )


# ---------------------------------------------------------------------------
# AC-HIGH-01 — No ToolAccent widget anywhere in the codebase
# ---------------------------------------------------------------------------


class TestNoToolAccentWidget:
    def test_tool_panel_core_source_has_no_tool_accent(self):
        """_core.py must not reference ToolAccent or tool_accent."""
        src = pathlib.Path("hermes_cli/tui/tool_panel/_core.py").read_text()
        assert "ToolAccent" not in src
        assert "tool_accent" not in src

    def test_tool_accent_module_removed(self):
        """hermes_cli.tui.tool_accent must not be importable."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("hermes_cli.tui.tool_accent")

    def test_no_tool_accent_tcss_selectors(self):
        """hermes.tcss must contain no ToolAccent selector."""
        src = pathlib.Path("hermes_cli/tui/hermes.tcss").read_text()
        assert "ToolAccent" not in src


# ---------------------------------------------------------------------------
# AC-MED-01 — Border-left class contract is the active accent system
# ---------------------------------------------------------------------------


class TestBorderAccentContract:
    @pytest.mark.asyncio
    async def test_streaming_panel_has_border_accent_classes(self):
        """Mounted shell ToolPanel has tool-panel--accent and category-shell."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app._svc_tools.open_gen_block("bash")
            await _pause(pilot)

            from hermes_cli.tui.tool_panel import ToolPanel
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel).query_one(ToolPanel)
            assert panel.has_class("tool-panel--accent"), "Missing tool-panel--accent"
            assert panel.has_class("category-shell"), "Missing category-shell"

    @pytest.mark.asyncio
    async def test_error_summary_sets_error_accent_class(self):
        """set_result_summary with is_error=True adds tool-panel--error."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app._svc_tools.open_gen_block("bash")
            await _pause(pilot)

            from hermes_cli.tui.tool_panel import ToolPanel
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel).query_one(ToolPanel)
            panel.set_result_summary(_make_summary(is_error=True, exit_code=1))
            await _pause(pilot)
            assert panel.has_class("tool-panel--error"), "Missing tool-panel--error after error summary"

    @pytest.mark.asyncio
    async def test_success_summary_clears_error_accent_class(self):
        """set_result_summary success removes tool-panel--error; accent still present."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app._svc_tools.open_gen_block("bash")
            await _pause(pilot)

            from hermes_cli.tui.tool_panel import ToolPanel
            from hermes_cli.tui.widgets import OutputPanel
            panel = app.query_one(OutputPanel).query_one(ToolPanel)

            panel.set_result_summary(_make_summary(is_error=True, exit_code=1))
            await _pause(pilot)
            assert panel.has_class("tool-panel--error")

            panel.set_result_summary(_make_summary(is_error=False, exit_code=0))
            await _pause(pilot)
            assert not panel.has_class("tool-panel--error"), "tool-panel--error must be removed on success"
            assert panel.has_class("tool-panel--accent"), "tool-panel--accent must persist after success"


# ---------------------------------------------------------------------------
# AC-LOW-01 — Reference cleanup
# ---------------------------------------------------------------------------


class TestReferenceCleanup:
    def test_no_tool_accent_production_references(self):
        """No .py or .tcss file under hermes_cli/ contains ToolAccent or tool_accent."""
        hermes_cli = pathlib.Path("hermes_cli")
        offenders = []
        for ext in ("*.py", "*.tcss"):
            for fpath in hermes_cli.rglob(ext):
                text = fpath.read_text(errors="replace")
                if "ToolAccent" in text or "tool_accent" in text:
                    offenders.append(str(fpath))
        assert not offenders, f"Stale references found: {offenders}"

    def test_old_test_file_deleted_new_file_exists(self):
        """test_tool_accent.py must not exist; test_tool_panel_accent_contract.py must exist."""
        tests_tui = pathlib.Path("tests/tui")
        assert not (tests_tui / "test_tool_accent.py").exists(), (
            "Old test file tests/tui/test_tool_accent.py must be deleted"
        )
        assert (tests_tui / "test_tool_panel_accent_contract.py").exists(), (
            "New test file tests/tui/test_tool_panel_accent_contract.py must exist"
        )
