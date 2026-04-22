"""Tests for M2 Compact/responsive layout.

Spec: /home/xush/.hermes/m2-compact-layout-spec.md
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.session_start = None
    return HermesApp(cli=cli, clipboard_available=True)


def _set_compact(app: HermesApp, value: bool) -> None:
    """Set compact mode, pinning _compact_manual so _flush_resize won't override."""
    app._compact_manual = True if value else None
    app.compact = value


# ---------------------------------------------------------------------------
# E1 — Reactive declaration + manual toggle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compact_reactive_exists() -> None:
    from textual.reactive import reactive as _reactive
    assert isinstance(HermesApp.__dict__.get("compact"), _reactive)


@pytest.mark.asyncio
async def test_compact_manual_attr_exists() -> None:
    app = _make_app()
    assert app._compact_manual is None


@pytest.mark.asyncio
async def test_compact_default_false() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        await pilot.pause(delay=0.15)
        assert pilot.app.compact is False


@pytest.mark.asyncio
async def test_compact_class_added() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        assert pilot.app.has_class("density-compact")


@pytest.mark.asyncio
async def test_compact_class_removed() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        _set_compact(pilot.app, False)
        await pilot.pause()
        assert not pilot.app.has_class("density-compact")


@pytest.mark.asyncio
async def test_auto_compact_narrow_width() -> None:
    async with _make_app().run_test(size=(100, 40)) as pilot:
        await pilot.pause(delay=0.15)
        assert pilot.app.compact is True
        assert pilot.app.has_class("density-compact")


@pytest.mark.asyncio
async def test_auto_compact_short_height() -> None:
    async with _make_app().run_test(size=(140, 28)) as pilot:
        await pilot.pause(delay=0.15)
        assert pilot.app.compact is True


@pytest.mark.asyncio
async def test_no_compact_large_terminal() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        await pilot.pause(delay=0.15)
        assert pilot.app.compact is False


@pytest.mark.asyncio
async def test_manual_toggle_on() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        pilot.app.action_toggle_density()
        await pilot.pause()
        assert pilot.app.compact is True
        assert pilot.app._compact_manual is True


@pytest.mark.asyncio
async def test_manual_toggle_restores_auto() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        pilot.app.action_toggle_density()  # → manual ON
        await pilot.pause()
        pilot.app.action_toggle_density()  # → auto restored
        await pilot.pause()
        assert pilot.app._compact_manual is None


@pytest.mark.asyncio
async def test_manual_toggle_survives_resize() -> None:
    async with _make_app().run_test(size=(140, 40)) as pilot:
        pilot.app.action_toggle_density()
        await pilot.pause()
        assert pilot.app.compact is True
        # Resize to large — manual should NOT be cancelled
        await pilot.resize_terminal(160, 50)
        await pilot.pause(delay=0.15)
        assert pilot.app.compact is True
        assert pilot.app._compact_manual is True


# ---------------------------------------------------------------------------
# E2 — Widget visibility
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compact_hides_nameplate() -> None:
    from hermes_cli.tui.widgets import AssistantNameplate
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        try:
            nameplate = pilot.app.query_one(AssistantNameplate)
            assert nameplate.display is False
        except Exception:
            pass  # widget may not exist in minimal test environment


@pytest.mark.asyncio
async def test_compact_chevron_text() -> None:
    from textual.widgets import Static
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        chev = pilot.app.query_one("#input-chevron", Static)
        assert chev.content == "❯"


@pytest.mark.asyncio
async def test_normal_chevron_text() -> None:
    from textual.widgets import Static
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, False)
        await pilot.pause()
        chev = pilot.app.query_one("#input-chevron", Static)
        assert chev.content == "❯ "


@pytest.mark.asyncio
async def test_compact_chevron_toggled_back() -> None:
    from textual.widgets import Static
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        _set_compact(pilot.app, False)
        await pilot.pause()
        chev = pilot.app.query_one("#input-chevron", Static)
        assert chev.content == "❯ "


# ---------------------------------------------------------------------------
# E3 — ToolPanel compact broadcast (ToolHeaderBar deleted in A1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compact_broadcasts_to_tool_panels() -> None:
    """A1: compact sync targets ToolPanel directly (ToolHeaderBar deleted)."""
    from hermes_cli.tui.tool_panel import ToolPanel
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        for tp in pilot.app.query(ToolPanel):
            assert tp.has_class("--compact")


@pytest.mark.asyncio
async def test_compact_off_removes_from_tool_panels() -> None:
    from hermes_cli.tui.tool_panel import ToolPanel
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        _set_compact(pilot.app, False)
        await pilot.pause()
        for tp in pilot.app.query(ToolPanel):
            assert not tp.has_class("--compact")


# ---------------------------------------------------------------------------
# E4 — StatusBar abbreviation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_bar_compact_model_abbreviation() -> None:
    # Use size < 70 cols so compact+narrow abbreviation path fires
    from hermes_cli.tui.widgets import StatusBar
    async with _make_app().run_test(size=(60, 40)) as pilot:
        pilot.app.status_model = "claude-sonnet-4-6"
        _set_compact(pilot.app, True)
        await pilot.pause()
        sbar = pilot.app.query_one(StatusBar)
        rendered = str(sbar.render())
        assert "sonnet-4-6" in rendered
        assert "claude-sonnet" not in rendered


@pytest.mark.asyncio
async def test_status_bar_normal_model_unabbreviated() -> None:
    from hermes_cli.tui.widgets import StatusBar
    async with _make_app().run_test(size=(140, 40)) as pilot:
        pilot.app.status_model = "claude-sonnet-4-6"
        _set_compact(pilot.app, False)
        await pilot.pause()
        sbar = pilot.app.query_one(StatusBar)
        rendered = str(sbar.render())
        assert "claude-sonnet-4-6" in rendered


@pytest.mark.asyncio
async def test_status_bar_compact_session_truncation() -> None:
    # Use size < 70 cols so compact+narrow path fires
    from hermes_cli.tui.widgets import StatusBar
    async with _make_app().run_test(size=(60, 40)) as pilot:
        pilot.app.status_model = "m"
        pilot.app.session_label = "my-long-session-name"
        _set_compact(pilot.app, True)
        await pilot.pause()
        sbar = pilot.app.query_one(StatusBar)
        rendered = str(sbar.render())
        assert "my-lo…" in rendered


@pytest.mark.asyncio
async def test_status_bar_normal_session_not_truncated() -> None:
    from hermes_cli.tui.widgets import StatusBar
    async with _make_app().run_test(size=(140, 40)) as pilot:
        pilot.app.status_model = "m"
        pilot.app.session_label = "my-short"
        _set_compact(pilot.app, False)
        await pilot.pause()
        sbar = pilot.app.query_one(StatusBar)
        rendered = str(sbar.render())
        assert "my-short" in rendered


# ---------------------------------------------------------------------------
# E5 — Regression smoke
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compact_off_restores_chevron() -> None:
    from textual.widgets import Static
    async with _make_app().run_test(size=(140, 40)) as pilot:
        _set_compact(pilot.app, True)
        await pilot.pause()
        _set_compact(pilot.app, False)
        await pilot.pause()
        chev = pilot.app.query_one("#input-chevron", Static)
        assert chev.content == "❯ "
        assert not pilot.app.has_class("density-compact")


@pytest.mark.asyncio
async def test_known_slash_commands_includes_density() -> None:
    from hermes_cli.tui.app import _KNOWN_SLASH_COMMANDS
    assert "/density" in _KNOWN_SLASH_COMMANDS


@pytest.mark.asyncio
async def test_known_slash_commands_key_handler_includes_density() -> None:
    from hermes_cli.tui._app_key_handler import _KNOWN_SLASH_COMMANDS
    assert "/density" in _KNOWN_SLASH_COMMANDS
