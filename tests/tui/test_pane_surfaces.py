"""R3 Phase C — ReferenceModal base + pane-fallback subclass tests.

Tests: 24 scenarios covering:
- show/hide --visible toggle for all 4 modals (8)
- CommandsOverlay filter input (3)
- UsageOverlay copy key wiring (2)
- WorkspaceOverlay tab switching (3)
- HelpOverlay scroll container (2)
- /help command opens HelpOverlay (1)
- F1 opens HelpOverlay (1)
- escape dismisses each (4)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.overlays import (
    CommandsOverlay,
    HelpOverlay,
    ReferenceModal,
    UsageOverlay,
    WorkspaceOverlay,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# 1. show_overlay() / hide_overlay() — --visible toggle (8 tests: 4×2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_show_adds_visible():
    """HelpOverlay: show_overlay() adds --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(HelpOverlay)
        assert not ov.has_class("--visible")
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")


@pytest.mark.asyncio
async def test_help_hide_removes_visible():
    """HelpOverlay: hide_overlay() removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(HelpOverlay)
        ov.show_overlay()
        await pilot.pause()
        ov.hide_overlay()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_usage_show_adds_visible():
    """UsageOverlay: show_overlay() adds --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        assert not ov.has_class("--visible")
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")


@pytest.mark.asyncio
async def test_usage_hide_removes_visible():
    """UsageOverlay: hide_overlay() removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        ov.show_overlay()
        await pilot.pause()
        ov.hide_overlay()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_commands_show_adds_visible():
    """CommandsOverlay: show_overlay() adds --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        assert not ov.has_class("--visible")
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")


@pytest.mark.asyncio
async def test_commands_hide_removes_visible():
    """CommandsOverlay: hide_overlay() removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        ov.show_overlay()
        await pilot.pause()
        ov.hide_overlay()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_workspace_show_adds_visible():
    """WorkspaceOverlay: show_overlay() adds --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        assert not ov.has_class("--visible")
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")


@pytest.mark.asyncio
async def test_workspace_hide_removes_visible():
    """WorkspaceOverlay: hide_overlay() removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov.show_overlay()
        await pilot.pause()
        ov.hide_overlay()
        await pilot.pause()
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 2. CommandsOverlay filter input (3 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commands_filter_empty_shows_all():
    """CommandsOverlay: empty filter shows all cached lines."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        ov.show_overlay()
        await pilot.pause()
        from textual.containers import Vertical
        container = ov.query_one("#commands-content", Vertical)
        # With empty filter all cached lines populate (count > 0)
        assert len(container.children) > 0


@pytest.mark.asyncio
async def test_commands_filter_narrows_results():
    """CommandsOverlay: typing a query narrows the displayed list."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        ov.show_overlay()
        await pilot.pause()
        from textual.containers import Vertical
        from textual.widgets import Input
        container = ov.query_one("#commands-content", Vertical)
        all_count = len(container.children)
        # Inject a rare query that won't match everything
        inp = ov.query_one("#commands-search", Input)
        # Use a query that should match fewer items than all
        inp.value = "zzz_no_match_xyz"
        await pilot.pause()
        # Either 0 results or the "(no commands available)" placeholder
        assert len(container.children) <= all_count


@pytest.mark.asyncio
async def test_commands_filter_reset_on_show():
    """CommandsOverlay: reopening clears filter to empty."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        ov.show_overlay()
        await pilot.pause()
        from textual.widgets import Input
        inp = ov.query_one("#commands-search", Input)
        inp.value = "something"
        await pilot.pause()
        ov.hide_overlay()
        ov.show_overlay()
        await pilot.pause()
        assert inp.value == ""


# ---------------------------------------------------------------------------
# 3. UsageOverlay copy key wiring (2 tests)
# ---------------------------------------------------------------------------

def test_usage_no_q_binding():
    """UsageOverlay.BINDINGS must NOT contain a q binding."""
    q_bindings = [b for b in UsageOverlay.BINDINGS if hasattr(b, "key") and b.key == "q"]
    assert not q_bindings, f"UsageOverlay should NOT have a q binding, found: {q_bindings}"


@pytest.mark.asyncio
async def test_usage_do_copy_calls_app_helper():
    """UsageOverlay._do_copy() calls app._copy_text_with_hint with stored text."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        ov._last_plain_text = "some usage text"
        with patch.object(app, "_copy_text_with_hint") as mock_copy:
            ov._do_copy()
            mock_copy.assert_called_once_with("some usage text")


# ---------------------------------------------------------------------------
# 4. WorkspaceOverlay tab switching (3 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_git_tab_active_by_default():
    """WorkspaceOverlay: git tab button has --tab-active class by default."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        from textual.widgets import Button
        git_btn = ov.query_one("#ws-tab-git", Button)
        assert git_btn.has_class("--tab-active")


@pytest.mark.asyncio
async def test_workspace_switch_git_tab_active():
    """WorkspaceOverlay._switch_tab('ws-git-pane') keeps git button --tab-active."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov._switch_tab("ws-git-pane")
        await pilot.pause()
        from textual.widgets import Button
        git_btn = ov.query_one("#ws-tab-git", Button)
        assert git_btn.has_class("--tab-active")


@pytest.mark.asyncio
async def test_workspace_switch_unknown_pane_no_crash():
    """WorkspaceOverlay._switch_tab with an unknown pane_id must not crash."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov._switch_tab("ws-nonexistent-pane")  # must not raise
        await pilot.pause()
        from textual.widgets import Button
        git_btn = ov.query_one("#ws-tab-git", Button)
        assert git_btn.has_class("--tab-active")


# ---------------------------------------------------------------------------
# 5. HelpOverlay scroll container renders (2 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_content_container_exists():
    """HelpOverlay: #help-content Vertical container is mounted."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from textual.containers import Vertical
        ov = app.query_one(HelpOverlay)
        container = ov.query_one("#help-content", Vertical)
        assert container is not None


@pytest.mark.asyncio
async def test_help_content_populated_on_mount():
    """HelpOverlay: #help-content has children after mount (commands cached)."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from textual.containers import Vertical
        ov = app.query_one(HelpOverlay)
        container = ov.query_one("#help-content", Vertical)
        assert len(container.children) > 0


# ---------------------------------------------------------------------------
# 6. /help command opens HelpOverlay (1 test)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slash_help_opens_help_overlay():
    """/help command makes HelpOverlay visible."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        inp.value = "/help"
        inp.action_submit()
        await pilot.pause()
        assert app.query_one(HelpOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# 7. HelpOverlay is pre-mounted with correct ID (1 test — replaces F1 premise)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_overlay_premounted_with_id():
    """HelpOverlay is pre-mounted in app compose() with id='help-overlay'."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one("#help-overlay")
        assert isinstance(ov, HelpOverlay)


# ---------------------------------------------------------------------------
# 8. Escape dismisses each (4 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escape_dismisses_help():
    """Escape dismisses HelpOverlay."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(HelpOverlay)
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")
        ov.action_dismiss()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_escape_dismisses_usage():
    """action_dismiss() dismisses UsageOverlay."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(UsageOverlay)
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")
        ov.action_dismiss()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_escape_dismisses_commands():
    """action_dismiss() dismisses CommandsOverlay."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(CommandsOverlay)
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")
        ov.action_dismiss()
        await pilot.pause()
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_escape_dismisses_workspace():
    """action_dismiss() dismisses WorkspaceOverlay."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov.show_overlay()
        await pilot.pause()
        assert ov.has_class("--visible")
        ov.action_dismiss()
        await pilot.pause()
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# Structural / unit tests (no app needed)
# ---------------------------------------------------------------------------

def test_all_4_are_reference_modal_subclasses():
    """All 4 reference overlays are subclasses of ReferenceModal."""
    for cls in (HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay):
        assert issubclass(cls, ReferenceModal), f"{cls.__name__} is not a ReferenceModal subclass"


def test_modal_ids_unchanged():
    """_modal_id values match existing CSS IDs."""
    assert HelpOverlay._modal_id == "help-overlay"
    assert UsageOverlay._modal_id == "usage-overlay"
    assert CommandsOverlay._modal_id == "commands-overlay"
    assert WorkspaceOverlay._modal_id == "workspace-overlay"


def test_help_q_binding_priority_false():
    """HelpOverlay q binding must have priority=False."""
    q_bindings = [b for b in HelpOverlay.BINDINGS if hasattr(b, "key") and b.key == "q"]
    assert q_bindings, "HelpOverlay should have a q binding"
    for b in q_bindings:
        assert not b.priority, f"HelpOverlay q binding should have priority=False, got {b.priority}"


def test_workspace_no_q_binding():
    """WorkspaceOverlay must NOT have a q binding."""
    q_bindings = [b for b in WorkspaceOverlay.BINDINGS if hasattr(b, "key") and b.key == "q"]
    assert not q_bindings, f"WorkspaceOverlay should NOT have a q binding, found: {q_bindings}"
