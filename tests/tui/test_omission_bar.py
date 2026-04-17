"""Tests for OmissionBar — interactive expand/collapse controls for the line cap.

Run with:
    pytest -o "addopts=" tests/tui/test_omission_bar.py -v
"""

from __future__ import annotations

import asyncio
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
    """Synchronous flush — drains pending lines immediately."""
    block._flush_pending()


def _drain_log(log: CopyableRichLog) -> None:
    """In headless tests, drain deferred renders so log.lines is populated."""
    if not log._size_known:
        log._size_known = True
        while log._deferred_renders:
            log.write(*log._deferred_renders.popleft())


# ---------------------------------------------------------------------------
# T1: Bar not present before cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_not_present_before_cap():
    """OmissionBar is not mounted when line count is below _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP - 1):
            block.append_line(f"line {i}")
        _flush(block)

        assert block._omission_bar_mounted is False
        assert block._omission_bar is None
        assert len(block._body.query(OmissionBar)) == 0


# ---------------------------------------------------------------------------
# T2: Bar mounted at cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_mounted_at_cap():
    """OmissionBar is mounted when exactly _VISIBLE_CAP + 1 lines arrive."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_mounted is True
        assert block._omission_bar is not None


# ---------------------------------------------------------------------------
# T3: _omission_bar_mounted flag set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_omission_bar_mounted_flag():
    """_omission_bar_mounted transitions to True on cap hit."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        assert block._omission_bar_mounted is False

        for i in range(_VISIBLE_CAP + 5):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        assert block._omission_bar_mounted is True


# ---------------------------------------------------------------------------
# T4: Label text format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_omission_bar_label_text():
    """OmissionBar label shows correct omitted count after flush."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 50
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        assert bar._total == total
        assert bar._visible_end == _VISIBLE_CAP
        omitted = total - _VISIBLE_CAP
        assert bar._total - bar._visible_end == omitted


# ---------------------------------------------------------------------------
# T5: [+] increments _visible_end by _PAGE_SIZE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_one_page():
    """[+] reveals _PAGE_SIZE more lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE + 10
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        initial_end = bar._visible_end
        bar._do_expand_one()

        assert bar._visible_end == initial_end + _PAGE_SIZE


# ---------------------------------------------------------------------------
# T6: [++] sets _visible_end to _total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_all():
    """[++] reveals all remaining lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 75
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        bar._do_expand_all()

        assert bar._visible_end == total


# ---------------------------------------------------------------------------
# T7: [-] decrements, floors at _VISIBLE_CAP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collapse_one_page_floors_at_cap():
    """[-] collapses by _PAGE_SIZE, never below _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10  # only 10 lines beyond cap
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        # Expand to show all first
        bar._do_expand_all()
        assert bar._visible_end == total

        # One page collapse: 10 < _PAGE_SIZE, should floor at _VISIBLE_CAP
        bar._do_collapse_one()
        assert bar._visible_end == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T8: [--] resets to _VISIBLE_CAP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collapse_all_resets_to_cap():
    """[--] collapses visible window back to _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 100
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        bar._do_expand_all()
        assert bar._visible_end == total

        bar._do_collapse_all()
        assert bar._visible_end == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T9: Collapse buttons disabled at cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collapse_buttons_disabled_at_cap():
    """[--] and [-] buttons have -disabled class when at cap."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        # At cap initially — collapse buttons should be disabled
        bar._refresh_buttons()
        assert bar.query_one("#btn-collapse-all").has_class("-disabled")
        assert bar.query_one("#btn-collapse-one").has_class("-disabled")
        assert not bar.query_one("#btn-expand-one").has_class("-disabled")
        assert not bar.query_one("#btn-expand-all").has_class("-disabled")


# ---------------------------------------------------------------------------
# T10: Expand buttons disabled when all shown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_buttons_disabled_when_all_shown():
    """[+] and [++] buttons have -disabled class when all lines are visible."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        bar._do_expand_all()

        bar._refresh_buttons()
        assert bar.query_one("#btn-expand-one").has_class("-disabled")
        assert bar.query_one("#btn-expand-all").has_class("-disabled")
        assert not bar.query_one("#btn-collapse-all").has_class("-disabled")
        assert not bar.query_one("#btn-collapse-one").has_class("-disabled")


# ---------------------------------------------------------------------------
# T11: copy_content returns all lines regardless of _visible_end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_content_unaffected_by_omission_bar():
    """copy_content() returns all lines regardless of OmissionBar state."""
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
# T12: Multiple [+] presses accumulate correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_expand_one_presses():
    """Multiple [+] presses stack _visible_end correctly."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 3
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        bar._do_expand_one()
        bar._do_expand_one()

        assert bar._visible_end == _VISIBLE_CAP + _PAGE_SIZE * 2


# ---------------------------------------------------------------------------
# T13: [++] then [--] round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_all_then_collapse_all_roundtrip():
    """[++] then [--] returns _visible_end to _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 60
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        bar._do_expand_all()
        assert bar._visible_end == total
        bar._do_collapse_all()
        assert bar._visible_end == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T14: Bar label updates after each button action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_label_updates_after_expand():
    """OmissionBar._total and _visible_end reflect state after button action."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE + 5
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        assert bar._total - bar._visible_end == _PAGE_SIZE + 5

        bar._do_expand_one()
        # 5 lines still omitted
        assert bar._total - bar._visible_end == 5


# ---------------------------------------------------------------------------
# T17: Bar survives complete()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_survives_complete():
    """OmissionBar remains mounted and visible after StreamingToolBlock.complete()."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None

        block.complete("1.5s")
        await pilot.pause()

        assert block._omission_bar_mounted is True
        assert block._omission_bar is bar


# ---------------------------------------------------------------------------
# T18: Bar label updates during streaming (via flush ticks)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_label_updates_during_streaming():
    """OmissionBar._total reflects new lines after each flush."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        # First batch: trigger cap
        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        first_total = bar._total

        # Second batch: more lines after cap
        for i in range(20):
            block.append_line(f"extra {i}")
        _flush(block)
        await pilot.pause()

        assert bar._total > first_total
        assert bar._total == _VISIBLE_CAP + 1 + 20


# ---------------------------------------------------------------------------
# T19: Disabled button click is no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_button_click_noop():
    """Clicking a -disabled button does not change _visible_end."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 20
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        # Collapse buttons disabled at cap
        assert bar.query_one("#btn-collapse-all").has_class("-disabled")
        initial_end = bar._visible_end

        # Simulate click on disabled button
        btn = bar.query_one("#btn-collapse-all")
        bar._do_collapse_all()  # should be no-op since _visible_end == _VISIBLE_CAP
        assert bar._visible_end == initial_end


# ---------------------------------------------------------------------------
# T20: _PAGE_SIZE constant used in [+]
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_size_constant_used():
    """[+] expand delta equals _PAGE_SIZE."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE * 2
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        before = bar._visible_end
        bar._do_expand_one()
        assert bar._visible_end - before == _PAGE_SIZE


# ---------------------------------------------------------------------------
# T21: Total = cap + 1 (one hidden line)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_total_equals_cap_plus_one():
    """OmissionBar shows 1 omitted line when total is _VISIBLE_CAP + 1."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        assert bar._total == _VISIBLE_CAP + 1
        assert bar._total - bar._visible_end == 1


# ---------------------------------------------------------------------------
# T22: Rapid [+] clamps to _total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rapid_expand_clamps_to_total():
    """Pressing [+] more times than there are pages clamps _visible_end at _total."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + 10  # only 10 hidden, less than one page
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None

        bar._do_expand_one()
        assert bar._visible_end == total  # clamped, not total + _PAGE_SIZE

        bar._do_expand_one()
        assert bar._visible_end == total  # second press: no-op (already at end)


# ---------------------------------------------------------------------------
# T23: _omission_bar is None before cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_omission_bar_none_before_cap():
    """_omission_bar is None when line count has not reached _VISIBLE_CAP."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        assert block._omission_bar is None

        for i in range(_VISIBLE_CAP // 2):
            block.append_line(f"line {i}")
        _flush(block)

        assert block._omission_bar is None


# ---------------------------------------------------------------------------
# T24: collapse_to clears and rewrites log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collapse_to_rewrites_log():
    """collapse_to(n) clears the log and rewrites exactly n lines."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        block = await _new_block(pilot)

        total = _VISIBLE_CAP + _PAGE_SIZE
        for i in range(total):
            block.append_line(f"line {i}")
        _flush(block)
        await pilot.pause()

        bar = block._omission_bar
        assert bar is not None
        # Expand one page
        bar._do_expand_one()
        assert bar._visible_end == _VISIBLE_CAP + _PAGE_SIZE

        # Collapse back to cap
        bar._do_collapse_all()
        assert bar._visible_end == _VISIBLE_CAP

        log = block._body.query_one(CopyableRichLog)
        _drain_log(log)
        assert len(log.lines) == _VISIBLE_CAP


# ---------------------------------------------------------------------------
# T25: reveal_lines appends without clearing existing lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reveal_lines_appends():
    """reveal_lines(start, end) adds lines without clearing the log."""
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

        # Directly call reveal_lines
        block.reveal_lines(_VISIBLE_CAP, total)

        _drain_log(log)
        assert len(log.lines) == before_count + 10
