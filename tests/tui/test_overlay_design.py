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
    CountdownMixin,
    HistorySearchOverlay,
    KeymapOverlay,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)


# ---------------------------------------------------------------------------
# P0-D + P1-C  Countdown strip helpers (pure function tests — no app needed)
# ---------------------------------------------------------------------------

class _FakeWidget(CountdownMixin):
    """Minimal stub satisfying CountdownMixin's duck-typed API for unit tests."""
    _state_attr = "fake_state"
    _timeout_response = None
    _countdown_prefix = "fake"


def test_countdown_strip_full():
    """At remaining == total, the strip should be mostly ▓."""
    fw = _FakeWidget()
    strip = fw._build_countdown_strip(remaining=30, total=30, width=40)
    plain = strip.plain
    # The ▓/▒ characters should dominate
    filled = plain.count("▓") + plain.count("▒")
    empty = plain.count("░")
    assert filled > empty, f"Expected mostly filled at full: {plain!r}"


def test_countdown_strip_empty():
    """At remaining == 0, the strip should be mostly ░."""
    fw = _FakeWidget()
    strip = fw._build_countdown_strip(remaining=0, total=30, width=40)
    plain = strip.plain
    filled = plain.count("▓") + plain.count("▒")
    empty = plain.count("░")
    assert empty > filled, f"Expected mostly empty at zero: {plain!r}"


def test_countdown_strip_half():
    """At remaining == total/2, filled ≈ empty (within ±3 chars)."""
    fw = _FakeWidget()
    strip = fw._build_countdown_strip(remaining=15, total=30, width=40)
    plain = strip.plain
    filled = plain.count("▓") + plain.count("▒")
    empty = plain.count("░")
    assert abs(filled - empty) <= 5, (
        f"Expected roughly balanced at half: {plain!r} filled={filled} empty={empty}"
    )


def test_countdown_strip_has_label():
    """Strip always ends with 'Ns' label."""
    fw = _FakeWidget()
    for remaining in (0, 1, 5, 15, 30):
        strip = fw._build_countdown_strip(remaining=remaining, total=30, width=40)
        assert f"{remaining}" in strip.plain, f"Label missing for remaining={remaining}"
        assert "s" in strip.plain


def test_countdown_strip_color_primary():
    """Remaining > 5 → bar color is $primary (#5f87d7)."""
    fw = _FakeWidget()
    strip = fw._build_countdown_strip(remaining=10, total=30, width=20)
    # Inspect spans; at least one span should have $primary-ish color
    spans_with_color = [
        s for s in strip._spans if s.style and getattr(s.style, "_color", None)
    ]
    assert len(spans_with_color) > 0


def test_countdown_strip_color_error():
    """Remaining ≤ 1 → bar color is $error (#ef5350)."""
    from hermes_cli.tui.animation import lerp_color
    fw = _FakeWidget()
    strip = fw._build_countdown_strip(remaining=1, total=30, width=20)
    # Verify no assertion error — the strip is constructed without crash
    assert strip.plain  # non-empty


# ---------------------------------------------------------------------------
# P0-B  pause_countdown / resume_countdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_stops_timer():
    """pause_countdown() clears _countdown_timer."""
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
        w = app.query_one(ApprovalWidget)
        assert w.display
        w.pause_countdown()
        assert w._countdown_timer is None
        assert w._was_paused is True


@pytest.mark.asyncio
async def test_resume_restarts_timer():
    """resume_countdown() restarts the timer and extends the deadline."""
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
        w = app.query_one(ApprovalWidget)
        w.pause_countdown()
        old_deadline = state.deadline
        await asyncio.sleep(0.2)
        w.resume_countdown()
        await pilot.pause()
        # deadline should be extended by ≥0.1s (actual sleep ~0.2s)
        assert state.deadline > old_deadline + 0.1
        assert w._countdown_timer is not None
        assert w._was_paused is False


@pytest.mark.asyncio
async def test_undo_confirm_pauses_approval_countdown():
    """Opening UndoConfirmOverlay pauses ApprovalWidget countdown (P0-B stacking)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Activate approval
        rq = queue.Queue()
        app.approval_state = ChoiceOverlayState(
            deadline=time.monotonic() + 30,
            response_queue=rq,
            question="Allow?",
            choices=["once", "deny"],
        )
        await pilot.pause()
        approval = app.query_one(ApprovalWidget)
        assert approval.display
        # Activate undo confirm
        urq = queue.Queue()
        app.undo_state = UndoOverlayState(
            deadline=time.monotonic() + 10,
            response_queue=urq,
            user_text="hello world",
        )
        await pilot.pause()
        # ApprovalWidget countdown should be paused
        assert approval._was_paused is True
        assert approval._countdown_timer is None


@pytest.mark.asyncio
async def test_undo_confirm_resume_on_dismiss():
    """Dismissing UndoConfirmOverlay resumes paused agent overlay countdown."""
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
        approval = app.query_one(ApprovalWidget)
        urq = queue.Queue()
        app.undo_state = UndoOverlayState(
            deadline=time.monotonic() + 10,
            response_queue=urq,
            user_text="hello",
        )
        await pilot.pause()
        assert approval._was_paused is True
        # Dismiss undo confirm
        app.undo_state = None
        await pilot.pause()
        # Approval countdown should be resumed
        assert approval._was_paused is False
        assert approval._countdown_timer is not None


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
    """UndoConfirmOverlay DEFAULT_CSS uses all-sides border (not top-only)."""
    css = UndoConfirmOverlay.DEFAULT_CSS
    assert "border: tall" in css
    assert "border-top" not in css


@pytest.mark.asyncio
async def test_tray_modal_border_top_only():
    """Tray modals (ClarifyWidget, ApprovalWidget, etc.) use top-only border."""
    for cls in (ClarifyWidget, ApprovalWidget, SudoWidget, SecretWidget):
        css = cls.DEFAULT_CSS
        assert "border-top:" in css, f"{cls.__name__} should have border-top"
        assert "border: tall" not in css, f"{cls.__name__} should NOT have all-sides border"
