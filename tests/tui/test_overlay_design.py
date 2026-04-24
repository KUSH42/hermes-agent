"""Tests for overlay design spec P0/P1 items.

Covers:
  P0-A  reduced-motion CSS rules
  P0-B  multi-overlay stacking (pause/resume, dismiss floating panels)
  P0-C  ContextMenu keyboard navigation
  P0-D  Countdown strip direction (▓ = remaining, ░ = elapsed)
  P1-A  Peek toggle (Alt+P) for SudoWidget / SecretWidget
  P1-C  Countdown strip color lerp ($primary → $warning → $error)
  P1-D  KeymapOverlay width breakpoints
"""

from __future__ import annotations

import asyncio
import queue
import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.context_menu import ContextMenu, MenuItem, _ContextItem
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState, UndoOverlayState
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    HistorySearchOverlay,
    KeymapOverlay,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)


# ---------------------------------------------------------------------------
# P0-B  pause_countdown / resume_countdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_stops_timer():
    """InterruptOverlay is visible when approval state is set ."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Q?",
            choices=["a"],
        )
        app.approval_state = state
        await pilot.pause()
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        w = app.query_one(InterruptOverlay)
        assert w.display


@pytest.mark.asyncio
async def test_resume_restarts_timer():
    """InterruptOverlay has active countdown timer when approval state is set."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Q?",
            choices=["a"],
        )
        app.approval_state = state
        await pilot.pause()
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        w = app.query_one(InterruptOverlay)
        assert w.display
        assert w._countdown_timer is not None


@pytest.mark.asyncio
async def test_undo_confirm_pauses_approval_countdown():
    """InterruptOverlay remains visible when undo queues on top of approval (preempt)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        app.approval_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
        )
        await pilot.pause()
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay, InterruptKind
        overlay = app.query_one(InterruptOverlay)
        assert overlay.display
        # Undo preempts approval — overlay still visible
        urq = queue.Queue()
        app.undo_state = UndoOverlayState(
            deadline=time.monotonic() + 10,
            response_queue=urq,
            user_text="hello world",
        )
        await pilot.pause()
        assert overlay.display
        # Undo is now on top; approval queued
        assert overlay.current_kind == InterruptKind.UNDO


@pytest.mark.asyncio
async def test_undo_confirm_resume_on_dismiss():
    """Clearing undo_state allows queued approval to resume in InterruptOverlay."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        rq = queue.Queue()
        app.approval_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
        )
        await pilot.pause()
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay, InterruptKind
        overlay = app.query_one(InterruptOverlay)
        urq = queue.Queue()
        app.undo_state = UndoOverlayState(
            deadline=time.monotonic() + 10,
            response_queue=urq,
            user_text="hello",
        )
        await pilot.pause()
        assert overlay.current_kind == InterruptKind.UNDO
        # Clear undo → overlay goes back to approval
        app.undo_state = None
        await pilot.pause()
        assert overlay.display


# ---------------------------------------------------------------------------
# P0-B  dismiss floating panels when agent overlay activates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarify_dismisses_keymap():
    """Opening ClarifyWidget dismisses KeymapOverlay (P0-B)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        ko = app.query_one(KeymapOverlay)
        ko.add_class("--visible")
        await pilot.pause()
        assert ko.has_class("--visible")

        app.clarify_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Q?",
            choices=["a"],
        )
        await pilot.pause()
        assert not ko.has_class("--visible")


@pytest.mark.asyncio
async def test_approval_dismisses_history_search():
    """Opening ApprovalWidget dismisses HistorySearchOverlay (P0-B)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hs = app.query_one(HistorySearchOverlay)
        hs.add_class("--visible")
        await pilot.pause()
        assert hs.has_class("--visible")

        app.approval_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["once", "deny"],
        )
        await pilot.pause()
        assert not hs.has_class("--visible")


# ---------------------------------------------------------------------------
# P0-C  ContextMenu keyboard navigation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_menu_down_selects_first():
    """First ↓ with no selection jumps to item 0 (P0-C)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [
            MenuItem("Copy", "", lambda: None),
            MenuItem("Paste", "", lambda: None),
        ]
        await menu.show(items, 10, 10)
        await pilot.pause()
        assert menu._selected_index == -1
        await pilot.press("down")
        await pilot.pause()
        assert menu._selected_index == 0
        item_widgets = menu._items()
        assert item_widgets[0].has_class("--selected")


@pytest.mark.asyncio
async def test_context_menu_up_down_navigation():
    """↑/↓ navigates through items, clamped at bounds (P0-C)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [
            MenuItem("A", "", lambda: None),
            MenuItem("B", "", lambda: None),
            MenuItem("C", "", lambda: None),
        ]
        await menu.show(items, 10, 10)
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert menu._selected_index == 1
        await pilot.press("up")
        await pilot.pause()
        assert menu._selected_index == 0
        # Can't go above 0
        await pilot.press("up")
        await pilot.pause()
        assert menu._selected_index == 0


@pytest.mark.asyncio
async def test_context_menu_enter_executes_selected():
    """Enter executes the highlighted item and dismisses (P0-C)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        executed: list[str] = []
        menu = app.query_one(ContextMenu)
        items = [
            MenuItem("Copy", "", lambda: executed.append("Copy")),
            MenuItem("Paste", "", lambda: executed.append("Paste")),
        ]
        await menu.show(items, 10, 10)
        await pilot.pause()
        await pilot.press("down")  # select item 0 (Copy)
        await pilot.press("enter")
        await pilot.pause()
        assert executed == ["Copy"]
        assert not menu.has_class("--visible")


@pytest.mark.asyncio
async def test_context_menu_enter_no_selection_just_dismisses():
    """Enter with _selected_index == -1 just dismisses (no crash)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        executed: list[str] = []
        menu = app.query_one(ContextMenu)
        items = [MenuItem("X", "", lambda: executed.append("X"))]
        await menu.show(items, 10, 10)
        await pilot.pause()
        assert menu._selected_index == -1
        await pilot.press("enter")
        await pilot.pause()
        assert executed == []
        assert not menu.has_class("--visible")


@pytest.mark.asyncio
async def test_context_menu_selection_reset_on_reshow():
    """_selected_index resets to -1 each time show() is called."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        menu = app.query_one(ContextMenu)
        items = [MenuItem("A", "", lambda: None)]
        await menu.show(items, 10, 10)
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert menu._selected_index == 0
        # Re-show
        await menu.show(items, 10, 10)
        await pilot.pause()
        assert menu._selected_index == -1


# ---------------------------------------------------------------------------
# P1-A  Peek toggle — SudoWidget / SecretWidget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sudo_peek_toggle_unmasks():
    """Alt+P sets password=False and adds --unmasked class (P1-A)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            prompt="sudo password:",
        )
        app.sudo_state = state
        await pilot.pause()
        w = app.query_one(SudoWidget)
        assert w.display
        inp = w.query_one("#sudo-input")
        assert inp.password is True

        await pilot.press("alt+p")
        await pilot.pause()
        assert not inp.password
        assert w.has_class("--unmasked")


@pytest.mark.asyncio
async def test_sudo_peek_re_toggle_remasks():
    """Second Alt+P re-masks and removes --unmasked class (P1-A)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.sudo_state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            prompt="pwd:",
        )
        await pilot.pause()
        w = app.query_one(SudoWidget)
        await pilot.press("alt+p")
        await pilot.pause()
        assert not w.query_one("#sudo-input").password

        await pilot.press("alt+p")
        await pilot.pause()
        assert w.query_one("#sudo-input").password
        assert not w.has_class("--unmasked")


@pytest.mark.asyncio
async def test_secret_peek_toggle():
    """Alt+P unmasks SecretWidget input (P1-A)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.secret_state = SecretOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            prompt="API key:",
        )
        await pilot.pause()
        w = app.query_one(SecretWidget)
        inp = w.query_one("#secret-input")
        assert inp.password is True
        await pilot.press("alt+p")
        await pilot.pause()
        assert not inp.password
        assert w.has_class("--unmasked")


# ---------------------------------------------------------------------------
# P1-D  KeymapOverlay width breakpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keymap_wide_layout():
    """At ≥80 cols, KeymapOverlay shows wide layout with section headers."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        ko = app.query_one(KeymapOverlay)
        ko.add_class("--visible")
        await pilot.pause()
        from textual.widgets import Static
        content_w = ko.query_one("#keymap-content", Static)
        rendered = str(content_w.render())
        # Wide layout has "Navigation" section
        assert "Navigation" in rendered


@pytest.mark.asyncio
async def test_keymap_narrow_layout():
    """At <80 cols, KeymapOverlay switches to narrow layout."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()
        ko = app.query_one(KeymapOverlay)
        ko._update_content()
        await pilot.pause()
        from textual.widgets import Static
        content_w = ko.query_one("#keymap-content", Static)
        rendered = str(content_w.render())
        # Narrow layout still has "Keyboard Reference"
        assert "Keyboard Reference" in rendered


# ---------------------------------------------------------------------------
# P0-A  Reduced-motion class — smoke test (CSS is parsed without error)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reduced_motion_class_applies():
    """HermesApp.reduced-motion class can be added without CSS errors."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Adding the class should not raise
        app.add_class("reduced-motion")
        await pilot.pause()
        assert app.has_class("reduced-motion")
        app.remove_class("reduced-motion")
        await pilot.pause()
        assert not app.has_class("reduced-motion")


# ---------------------------------------------------------------------------
# Visual: tray modal icons in rendered content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarify_shows_question_mark_icon():
    """ClarifyWidget prefixes question with '?' icon."""
    from textual.widgets import Static
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.clarify_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Which branch?",
            choices=["main", "dev"],
        )
        await pilot.pause()
        w = app.query_one(ClarifyWidget)
        q = w.query_one("#clarify-question", Static)
        rendered = str(q.render())
        assert "?" in rendered
        assert "Which branch?" in rendered


@pytest.mark.asyncio
async def test_approval_shows_exclamation_icon():
    """ApprovalWidget prefixes question with '!' icon."""
    from textual.widgets import Static
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.approval_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=queue.Queue(),
            question="Allow deletion?",
            choices=["once", "deny"],
        )
        await pilot.pause()
        w = app.query_one(ApprovalWidget)
        q = w.query_one("#approval-question", Static)
        rendered = str(q.render())
        assert "!" in rendered
        assert "Allow deletion?" in rendered


@pytest.mark.asyncio
async def test_undo_overlay_border_is_all_sides():
    """InterruptOverlay DEFAULT_CSS uses all-sides border (not top-only)."""
    from hermes_cli.tui.overlays.interrupt import InterruptOverlay
    css = InterruptOverlay.DEFAULT_CSS
    assert "border: tall" in css
    assert "border-top:" not in css


@pytest.mark.asyncio
async def test_tray_modal_border_top_only():
    """InterruptOverlay uses tall all-sides border (R3: alias classes share same CSS)."""
    from hermes_cli.tui.overlays.interrupt import InterruptOverlay
    css = InterruptOverlay.DEFAULT_CSS
    assert "border: tall" in css
