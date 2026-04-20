"""Tests for OmissionBar — dual-position expand/scroll controls for the line cap.

Phase D redesign: both bars always in DOM from on_mount(); display toggled by
_refresh_omission_bars(). Interaction routes through block.rerender_window(start, end).

Run with:
    pytest -o "addopts=" tests/tui/test_omission_bar.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import (
    OmissionBar,
    StreamingToolBlock,
    _PAGE_SIZE,
    _VISIBLE_CAP,
)
from hermes_cli.tui.widgets import CopyableRichLog, OutputPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _new_block(pilot, label: str = "test cmd") -> StreamingToolBlock:
    app = pilot.app
    output = app.query_one(OutputPanel)
    panel = output.current_message
    if panel is None:
        panel = output.new_message()
    block = StreamingToolBlock(label=label)
    await panel.mount(block)
    await pilot.pause()
    return block


def _flush(block: StreamingToolBlock) -> None:
    block._flush_pending()


def _drain_log(log: CopyableRichLog) -> None:
    if not log._size_known:
        log._size_known = True
        while log._deferred_renders:
            log.write(*log._deferred_renders.popleft())


# ---------------------------------------------------------------------------
# T1: Both bars always mounted from on_mount; hidden below cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bars_always_mounted_hidden_below_cap():
    """Both omission bars are in DOM but display=False when below cap."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP - 1):
            block.append_line(f"line {i}")
        _flush(block)

        assert block._omission_bar_bottom_mounted is True
        assert block._omission_bar_top_mounted is True
        assert block._omission_bar_bottom is not None
        assert block._omission_bar_top is not None
        assert block._omission_bar_bottom.display is False
        assert block._omission_bar_top.display is False


# ---------------------------------------------------------------------------
# T2: Bottom bar becomes visible when cap exceeded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bottom_bar_visible_at_cap():
    """Bottom bar display=True when total lines > _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_bottom.display is True
        assert block._omission_bar_top.display is False


# ---------------------------------------------------------------------------
# T3: _omission_bar_bottom_mounted always True after on_mount
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_omission_bar_mounted_flag_always_true():
    """_omission_bar_bottom_mounted and _top_mounted are True from on_mount."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        # Flags True immediately — no lines needed
        assert block._omission_bar_bottom_mounted is True
        assert block._omission_bar_top_mounted is True

        for i in range(_VISIBLE_CAP + 5):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_bottom_mounted is True
        assert block._omission_bar_top_mounted is True


# ---------------------------------------------------------------------------
# T4: set_counts caches correct totals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_omission_bar_set_counts():
    """Bottom bar _total and _visible_end reflect flush state."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 50
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        assert bar._total == total
        assert bar._visible_end == _VISIBLE_CAP
        assert bar._visible_start == 0
        assert bar._total - bar._visible_end == 50


# ---------------------------------------------------------------------------
# T5: [↓] (--ob-down) expands window forward by _PAGE_SIZE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_down_button_expands_window():
    """rerender_window called with (vs, ve+_PAGE_SIZE) shifts bottom of window."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE + 10
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        initial_end = bar._visible_end  # == _VISIBLE_CAP
        block.rerender_window(bar._visible_start, min(bar._total, bar._visible_end + _PAGE_SIZE))

        bar2 = block._omission_bar_bottom
        assert bar2._visible_end == initial_end + _PAGE_SIZE


# ---------------------------------------------------------------------------
# T6: [↓all] (--ob-down-all) expands window to total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_down_all_button_expands_to_end():
    """rerender_window(vs, total) makes bottom bar hidden (all lines visible)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 75
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        block.rerender_window(bar._visible_start, bar._total)
        await pilot.pause()

        # set_counts only fires when bar is visible; when hidden, check via block state
        assert block._omission_bar_bottom.display is False
        assert block._visible_start + block._visible_count == total


# ---------------------------------------------------------------------------
# T7: [↑cap] (--ob-cap) resets window to 0.._VISIBLE_CAP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cap_button_resets_to_beginning():
    """[↑cap] collapses window back to 0.._VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        # First expand to show more
        block.rerender_window(0, total)
        await pilot.pause()

        # Now cap: reset to 0.._VISIBLE_CAP
        block.rerender_window(0, _VISIBLE_CAP)
        await pilot.pause()

        bar = block._omission_bar_bottom
        assert bar._visible_start == 0
        assert bar._visible_end == _VISIBLE_CAP
        assert bar.display is True


# ---------------------------------------------------------------------------
# T8: Top bar visible after window start shifts above zero
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_bar_visible_after_window_scrolled():
    """Top bar becomes visible when _visible_start > 0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 2
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_top.display is False

        # Scroll window forward — creates lines above
        block.rerender_window(_PAGE_SIZE, _PAGE_SIZE + _VISIBLE_CAP)
        await pilot.pause()

        assert block._omission_bar_top.display is True
        assert block._omission_bar_top._visible_start == _PAGE_SIZE


# ---------------------------------------------------------------------------
# T9: [↑all] (top bar) brings visible_start to 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_up_all_button_resets_top():
    """[↑all] scrolls window back to start (visible_start=0)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 2
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        # Shift window so top bar is visible
        block.rerender_window(_PAGE_SIZE, _PAGE_SIZE + _VISIBLE_CAP)
        await pilot.pause()
        assert block._omission_bar_top.display is True

        # [↑all]: rerender_window(0, ve) — brings start back to 0
        ve = block._omission_bar_top._visible_end
        block.rerender_window(0, ve)
        await pilot.pause()

        assert block._omission_bar_top.display is False
        assert block._omission_bar_bottom._visible_start == 0


# ---------------------------------------------------------------------------
# T10: copy_content returns all lines regardless of window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_content_unaffected_by_omission_bar():
    """copy_content() returns all lines regardless of OmissionBar window state."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 30
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        content = block.copy_content()
        assert len(content.splitlines()) == total


# ---------------------------------------------------------------------------
# T11: Multiple [↓] presses accumulate correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_down_presses_stack():
    """Two [↓] presses shift window end by 2 * _PAGE_SIZE."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 3
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        # First [↓]
        bar = block._omission_bar_bottom
        ve1 = bar._visible_end
        block.rerender_window(bar._visible_start, min(bar._total, ve1 + _PAGE_SIZE))
        bar2 = block._omission_bar_bottom
        ve2 = bar2._visible_end

        # Second [↓]
        block.rerender_window(bar2._visible_start, min(bar2._total, ve2 + _PAGE_SIZE))
        bar3 = block._omission_bar_bottom

        assert bar3._visible_end == _VISIBLE_CAP + _PAGE_SIZE * 2


# ---------------------------------------------------------------------------
# T12: [↓all] then [↑cap] round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_down_all_then_cap_roundtrip():
    """Expand to end then reset to cap returns to initial state."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 60
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        block.rerender_window(0, total)
        # bar hidden when all visible — check block._visible_count instead
        assert block._visible_start + block._visible_count == total

        block.rerender_window(0, _VISIBLE_CAP)
        bar = block._omission_bar_bottom
        assert bar._visible_start == 0
        assert bar._visible_end == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T13: Label updates after rerender_window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_label_updates_after_expand():
    """Bottom bar counts reflect new window after rerender_window."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE + 5
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        assert bar._total - bar._visible_end == _PAGE_SIZE + 5

        block.rerender_window(0, _VISIBLE_CAP + _PAGE_SIZE)
        bar2 = block._omission_bar_bottom
        assert bar2._total - bar2._visible_end == 5


# ---------------------------------------------------------------------------
# T14: Bottom bar buttons have correct CSS classes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bottom_bar_button_classes():
    """Bottom OmissionBar has buttons with --ob-cap, --ob-up, --ob-down, --ob-down-all."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        bar = block._omission_bar_bottom
        assert bar.query(".--ob-cap")
        assert bar.query(".--ob-up")
        assert bar.query(".--ob-down")
        assert bar.query(".--ob-down-all")


# ---------------------------------------------------------------------------
# T15: Top bar buttons have correct CSS classes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_bar_button_classes():
    """Top OmissionBar has buttons with --ob-up-all and --ob-up-page."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        bar = block._omission_bar_top
        assert bar.query(".--ob-up-all")
        assert bar.query(".--ob-up-page")


# ---------------------------------------------------------------------------
# T16: Bottom bar buttons disabled when window at default state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bottom_bar_cap_up_disabled_at_default():
    """[↑cap] and [↑] disabled when window is at start with default size."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        cap_btn = bar.query_one(".--ob-cap")
        up_btn = bar.query_one(".--ob-up")
        # At default: start=0, window=_VISIBLE_CAP — cap/up disabled
        assert cap_btn.disabled is True
        assert up_btn.disabled is True
        # Down still enabled
        assert bar.query_one(".--ob-down").disabled is False


# ---------------------------------------------------------------------------
# T17: Bottom bar buttons disabled when all lines shown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bottom_bar_hidden_when_all_shown():
    """Bottom bar hides (display=False) when visible window covers all lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_bottom.display is True

        # Show all lines: bar should hide
        block.rerender_window(0, total)
        await pilot.pause()

        assert block._omission_bar_bottom.display is False


# ---------------------------------------------------------------------------
# T18: Bars survive complete()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bars_survive_complete():
    """Both bars remain mounted after StreamingToolBlock.complete()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        block.complete("1.5s")
        await pilot.pause()

        assert block._omission_bar_bottom_mounted is True
        assert block._omission_bar_top_mounted is True
        assert block._omission_bar_bottom.display is True


# ---------------------------------------------------------------------------
# T19: Bottom bar total updates during streaming
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_total_updates_during_streaming():
    """Bottom bar _total reflects new lines after each flush."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        first_total = block._omission_bar_bottom._total

        for i in range(20):
            block.append_line(f"extra {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_bottom._total == _VISIBLE_CAP + 1 + 20
        assert block._omission_bar_bottom._total > first_total


# ---------------------------------------------------------------------------
# T20: _PAGE_SIZE constant used in [↓]
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_size_constant_used():
    """[↓] expand delta equals _PAGE_SIZE."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 2
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        before = bar._visible_end
        block.rerender_window(bar._visible_start, min(bar._total, bar._visible_end + _PAGE_SIZE))

        assert block._omission_bar_bottom._visible_end - before == _PAGE_SIZE


# ---------------------------------------------------------------------------
# T21: Total = cap + 1 (one hidden line)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_total_equals_cap_plus_one():
    """Bar shows 1 omitted line when total is _VISIBLE_CAP + 1."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        assert bar._total == _VISIBLE_CAP + 1
        assert bar._total - bar._visible_end == 1


# ---------------------------------------------------------------------------
# T22: Rapid [↓] clamps at total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rapid_expand_clamps_to_total():
    """rerender_window with end > total is clamped at total."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10  # only 10 hidden, less than one page
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar_bottom
        # One [↓]: 10 < _PAGE_SIZE, clamps at total → bar hides (all shown)
        block.rerender_window(bar._visible_start, min(bar._total, bar._visible_end + _PAGE_SIZE))
        assert block._visible_start + block._visible_count == total
        assert block._omission_bar_bottom.display is False

        # Second [↓]: already at end, no change
        block.rerender_window(0, min(total, _VISIBLE_CAP + _PAGE_SIZE))
        assert block._visible_start + block._visible_count == total


# ---------------------------------------------------------------------------
# T23: rerender_window clears and rewrites log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rerender_window_rewrites_log():
    """rerender_window(start, end) clears log and writes exactly (end-start) lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        # Expand window to show all
        block.rerender_window(0, total)
        log = block._body.query_one(CopyableRichLog)
        _drain_log(log)
        assert len(log.lines) == total

        # Collapse back to cap
        block.rerender_window(0, _VISIBLE_CAP)
        _drain_log(log)
        assert len(log.lines) == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T24: reveal_lines appends without clearing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reveal_lines_appends():
    """reveal_lines(start, end) appends lines without clearing the log."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        log = block._body.query_one(CopyableRichLog)
        _drain_log(log)
        before_count = len(log.lines)

        block.reveal_lines(_VISIBLE_CAP, total)

        _drain_log(log)
        assert len(log.lines) == before_count + 10


# ---------------------------------------------------------------------------
# T25: visible_start tracked after rerender_window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_visible_start_tracked_after_rerender():
    """block._visible_start updates correctly via rerender_window."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 3
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._visible_start == 0

        block.rerender_window(_PAGE_SIZE, _PAGE_SIZE + _VISIBLE_CAP)
        assert block._visible_start == _PAGE_SIZE

        block.rerender_window(0, _VISIBLE_CAP)
        assert block._visible_start == 0


# ---------------------------------------------------------------------------
# §8 — [reset] button label (UX pass 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omission_bar_bottom_has_reset_button():
    """Bottom OmissionBar has '[reset]' button, not '[↑cap]'."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)
        await pilot.pause()

        bar = block._omission_bar_bottom
        assert bar is not None

        from textual.widgets import Button
        labels = [str(b.label) for b in bar.query(Button)]
        # Accept any icon-mode variant of the reset button label
        has_reset = any("reset" in lbl for lbl in labels)
        assert has_reset, f"Expected reset button, got {labels}"
        assert "[↑cap]" not in labels


# ---------------------------------------------------------------------------
# P1-3: omission bar counts updated while bar hidden
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_counts_updated_while_bar_hidden():
    """set_counts() is called even when the bar's display is False (hidden)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)
        await pilot.pause()

        bar = block._omission_bar_top
        assert bar is not None

        # Force bar hidden
        bar.display = False

        # Simulate counts update while hidden
        counts_received = []
        original_set_counts = bar.set_counts
        def _spy_set_counts(**kw):
            counts_received.append(kw)
            original_set_counts(**kw)
        bar.set_counts = _spy_set_counts

        # Trigger refresh
        block._visible_start = 5
        block._visible_count = 10
        block._all_plain = [f"line {i}" for i in range(20)]
        block._refresh_omission_bars()

        # set_counts must have been called even though bar was hidden
        assert len(counts_received) > 0, "set_counts should be called regardless of display state"
