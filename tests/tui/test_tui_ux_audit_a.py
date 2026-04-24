"""Phase A — Input Bar UX tests for the full TUI UX audit."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.input_widget import HermesInput
from hermes_cli.tui.widgets import HintBar


# ---------------------------------------------------------------------------
# A1 — height change flash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a1_height_expand_flashes_hint() -> None:
    """Ctrl+Shift+Up flashes 'Input height: N' to HintBar."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        # simulate height expand key
        inp._input_height_override = 3
        await pilot.press("ctrl+shift+up")
        await pilot.pause()
        hint_bar = app.query_one(HintBar)
        assert "Input height" in hint_bar.hint, f"hint_bar.hint={hint_bar.hint!r}"


@pytest.mark.asyncio
async def test_a1_height_shrink_flashes_hint() -> None:
    """Ctrl+Shift+Down flashes 'Input height: N' to HintBar."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._input_height_override = 6
        inp.styles.max_height = 6
        await pilot.press("ctrl+shift+down")
        await pilot.pause()
        hint_bar = app.query_one(HintBar)
        assert "Input height" in hint_bar.hint, f"hint_bar.hint={hint_bar.hint!r}"


# ---------------------------------------------------------------------------
# A2 — ghost text cleared on auto-dismiss
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a2_candidate_cleared_on_overlay_auto_dismiss() -> None:
    """app.highlighted_candidate is None after CompletionOverlay auto-dismiss."""
    from hermes_cli.tui.completion_overlay import CompletionOverlay
    from hermes_cli.tui.completion_list import VirtualCompletionList
    from hermes_cli.tui.path_search import SlashCandidate

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.highlighted_candidate = SlashCandidate(
            display="/help", command="/help", description="Get help", args_hint="", keybind_hint=""
        )
        overlay = app.query_one(CompletionOverlay)
        overlay.add_class("--visible")
        await pilot.pause()
        # fire auto-dismiss
        vcl = overlay.query_one(VirtualCompletionList)
        vcl.post_message(VirtualCompletionList.AutoDismiss())
        await pilot.pause()
        assert app.highlighted_candidate is None
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# A3 — rev-search mode indicator in placeholder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a3_rev_search_updates_placeholder() -> None:
    """Entering reverse-search mode sets placeholder to 'reverse-i-search:'."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["hello world", "foo bar"]
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert "reverse-i-search" in (inp.placeholder or ""), (
            f"placeholder={inp.placeholder!r}"
        )


@pytest.mark.asyncio
async def test_a3_rev_search_exit_restores_placeholder() -> None:
    """Exiting rev-search restores the idle placeholder."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp._history = ["hello world"]
        # enter rev-search
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert "reverse-i-search" in (inp.placeholder or "")
        # exit via escape
        await pilot.press("escape")
        await pilot.pause()
        assert inp.placeholder == inp._idle_placeholder, (
            f"placeholder={inp.placeholder!r}, expected={inp._idle_placeholder!r}"
        )


# ---------------------------------------------------------------------------
# A4 — error-aware placeholder after agent stops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a4_error_placeholder_shown_when_status_error_set() -> None:
    """When agent stops with status_error set, placeholder shows error hint."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # set up error before agent stop
        app.status_error = "API timeout: connection refused"
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert "Error:" in (inp.placeholder or ""), (
            f"placeholder={inp.placeholder!r}"
        )


@pytest.mark.asyncio
async def test_a4_normal_placeholder_when_no_error() -> None:
    """When agent stops with no error, placeholder is restored to idle."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_error = ""
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.placeholder == inp._idle_placeholder, (
            f"placeholder={inp.placeholder!r}"
        )


# ---------------------------------------------------------------------------
# A5 — ctrl+a removed from BINDINGS
# ---------------------------------------------------------------------------

def test_a5_ctrl_a_not_in_bindings() -> None:
    """ctrl+a must NOT be mapped to select_all (conflicts with readline)."""
    bindings = HermesInput.BINDINGS
    keys = [b.key for b in bindings]
    assert "ctrl+a" not in keys, (
        "ctrl+a should not override readline beginning-of-line"
    )


def test_a5_ctrl_shift_a_selects_all() -> None:
    """ctrl+shift+a should be mapped to select_all."""
    bindings = HermesInput.BINDINGS
    actions = {b.key: b.action for b in bindings}
    assert "ctrl+shift+a" in actions, "ctrl+shift+a must be in BINDINGS"
    assert "select_all" in actions["ctrl+shift+a"], (
        f"ctrl+shift+a should map to select_all, got {actions['ctrl+shift+a']!r}"
    )
