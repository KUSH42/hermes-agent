"""Tests for DiffAffordance widget (v3 Phase A, tui-tool-panel-v3-spec.md §5.9).

Covers:
- Default hidden state (display: none, no -has-diff class)
- set_diff() shows widget and updates stats
- clear_diff() hides widget and resets stats
- DiffAffordance present in FooterPane compose
- Child widget structure (connector/label/added/removed/chevron)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.diff_affordance import DiffAffordance


# ---------------------------------------------------------------------------
# Unit tests — no app needed
# ---------------------------------------------------------------------------


def test_initial_state_hidden():
    """DiffAffordance is not visible initially (no -has-diff class)."""
    d = DiffAffordance()
    assert not d.has_class("-has-diff")


def test_set_diff_adds_has_diff_class():
    """set_diff() adds -has-diff class to show the widget."""
    d = DiffAffordance()
    # Manually create child statics since compose() needs mounting
    from textual.widgets import Static
    d._nodes._append(Static("  ╰→ ", classes="connector"))
    d._nodes._append(Static("diff", classes="label"))
    d._nodes._append(Static("", classes="added"))
    d._nodes._append(Static("", classes="removed"))
    d._nodes._append(Static(" ▸", classes="chevron"))
    d.set_diff(5, 3)
    assert d.has_class("-has-diff")


def test_clear_diff_removes_has_diff_class():
    """clear_diff() removes -has-diff class."""
    d = DiffAffordance()
    from textual.widgets import Static
    d._nodes._append(Static("  ╰→ ", classes="connector"))
    d._nodes._append(Static("diff", classes="label"))
    d._nodes._append(Static("", classes="added"))
    d._nodes._append(Static("", classes="removed"))
    d._nodes._append(Static(" ▸", classes="chevron"))
    d.add_class("-has-diff")
    d.clear_diff()
    assert not d.has_class("-has-diff")


def test_default_css_display_none():
    """DiffAffordance DEFAULT_CSS has display: none."""
    assert "display: none" in DiffAffordance.DEFAULT_CSS


def test_has_diff_css_block():
    """DiffAffordance DEFAULT_CSS shows block when -has-diff class present."""
    assert "-has-diff" in DiffAffordance.DEFAULT_CSS
    assert "display: block" in DiffAffordance.DEFAULT_CSS


def test_height_is_one():
    """DiffAffordance DEFAULT_CSS has height: 1."""
    assert "height: 1" in DiffAffordance.DEFAULT_CSS


# ---------------------------------------------------------------------------
# Integration: DiffAffordance is in FooterPane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_affordance_in_footer_pane():
    """FooterPane compose includes DiffAffordance as child."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel, FooterPane

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._svc_tools.open_gen_block("patch")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        footer = panel.query_one(FooterPane)
        affordance = footer.query_one(DiffAffordance)
        assert affordance is not None
        assert not affordance.has_class("-has-diff"), "Should be hidden initially"


@pytest.mark.asyncio
async def test_diff_affordance_set_diff_shows():
    """set_diff() on affordance adds -has-diff and shows stats."""
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel, FooterPane

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(5):
            await pilot.pause()
        app.agent_running = True
        for _ in range(5):
            await pilot.pause()
        app._svc_tools.open_gen_block("patch")
        for _ in range(5):
            await pilot.pause()

        panel = app.query_one(OutputPanel).query_one(ToolPanel)
        footer = panel.query_one(FooterPane)
        affordance = footer.query_one(DiffAffordance)
        affordance.set_diff(added=6, removed=4)
        for _ in range(3):
            await pilot.pause()

        assert affordance.has_class("-has-diff")
        added_w = affordance.query_one(".added")
        assert "+6" in str(added_w.render())
        removed_w = affordance.query_one(".removed")
        assert "4" in str(removed_w.render())
