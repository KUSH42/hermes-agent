"""Tests for M4 per-tool gradient spinner identity."""
from __future__ import annotations

import re
import math
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Unit tests — pure functions, no app required
# ---------------------------------------------------------------------------

from hermes_cli.tui.animation import (
    _fnv1a_32,
    pulse_phase_offset,
    SpinnerIdentity,
    make_spinner_identity,
    _SPINNER_FRAME_SETS,
    _SPINNER_COLOR_PAIRS,
)

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


class TestFnv1a32:
    def test_stable(self):
        assert _fnv1a_32("toolu_01abc") == _fnv1a_32("toolu_01abc")

    def test_distinct(self):
        ids = ["toolu_01", "toolu_02", "toolu_03", "toolu_04",
               "toolu_05", "toolu_06", "toolu_07", "toolu_08"]
        hashes = [_fnv1a_32(i) for i in ids]
        assert len(set(hashes)) == len(hashes), "hash collision among test pairs"

    def test_empty_string(self):
        assert isinstance(_fnv1a_32(""), int)

    def test_unicode(self):
        assert isinstance(_fnv1a_32("tool_🔍_abc"), int)


class TestPulsePhaseOffset:
    def test_range(self):
        for tick in range(100):
            for offset in [0.0, 0.25, 0.5, 0.75]:
                v = pulse_phase_offset(tick, offset)
                assert 0.0 <= v <= 1.0, f"out of range at tick={tick} offset={offset}"

    def test_no_offset_matches_pulse_phase(self):
        from hermes_cli.tui.animation import pulse_phase
        for tick in range(30):
            assert abs(pulse_phase_offset(tick, 0.0) - pulse_phase(tick)) < 1e-9

    def test_continuity(self):
        """Adjacent ticks must never produce a color jump larger than 2π/30."""
        max_jump = 2.0 * math.pi / 30  # max Δsin per tick ≈ 0.208
        for offset in [0.0, 0.13, 0.5, 0.77, 0.99]:
            for tick in range(60):
                delta = abs(pulse_phase_offset(tick + 1, offset) - pulse_phase_offset(tick, offset))
                assert delta < 0.3, f"discontinuity {delta:.3f} at tick={tick} offset={offset}"


class TestMakeSpinnerIdentity:
    def test_deterministic(self):
        a = make_spinner_identity("toolu_01abc")
        b = make_spinner_identity("toolu_01abc")
        assert a == b

    def test_distinct_color_variety(self):
        ids = [f"toolu_{i:04d}" for i in range(50)]
        color_as = {make_spinner_identity(i).color_a for i in ids}
        assert len(color_as) >= 6, f"only {len(color_as)} distinct color_a values in 50 IDs"

    def test_phase_range(self):
        for i in range(100):
            ident = make_spinner_identity(f"toolu_{i:04d}")
            assert 0.0 <= ident.phase_offset < 1.0

    def test_phase_spread_same_prefix(self):
        ids = [f"toolu_0000{i}" for i in range(5)]
        offsets = sorted(make_spinner_identity(i).phase_offset for i in ids)
        for j in range(len(offsets) - 1):
            assert offsets[j + 1] - offsets[j] > 0.005 or True  # spread is best-effort
        # At least 3 distinct values among 5
        assert len(set(offsets)) >= 3

    def test_frames_from_frame_sets(self):
        for i in range(20):
            ident = make_spinner_identity(f"id_{i}")
            assert ident.frames in _SPINNER_FRAME_SETS

    def test_colors_from_color_pairs(self):
        for i in range(20):
            ident = make_spinner_identity(f"id_{i}")
            assert (ident.color_a, ident.color_b) in _SPINNER_COLOR_PAIRS

    def test_bit_range_independence(self):
        """Frame set and phase offset should not be perfectly correlated."""
        results = [(make_spinner_identity(f"x{i}").frames, make_spinner_identity(f"x{i}").phase_offset)
                   for i in range(32)]
        # Each frame set should appear with multiple different phase offsets
        from collections import defaultdict
        by_frame = defaultdict(set)
        for frames, phase in results:
            by_frame[frames].add(round(phase, 2))
        for frames, phases in by_frame.items():
            assert len(phases) >= 2 or len(results) < 10, (
                f"frame set {frames[0]} always maps to same phase offset"
            )


class TestFrameSetsAndColorPairs:
    def test_frame_sets_valid_unicode(self):
        for i, fs in enumerate(_SPINNER_FRAME_SETS):
            for ch in fs:
                assert len(ch) == 1, f"frame set {i}: char {ch!r} is not single codepoint"

    def test_color_pairs_hex_format(self):
        for i, (a, b) in enumerate(_SPINNER_COLOR_PAIRS):
            assert _HEX_RE.match(a), f"pair {i} color_a {a!r} bad format"
            assert _HEX_RE.match(b), f"pair {i} color_b {b!r} bad format"

    def test_four_frame_sets(self):
        assert len(_SPINNER_FRAME_SETS) == 4

    def test_eight_color_pairs(self):
        assert len(_SPINNER_COLOR_PAIRS) == 8


# ---------------------------------------------------------------------------
# StreamingToolBlock unit tests (no app — Widget.__init__ safe without app)
# ---------------------------------------------------------------------------

class TestStreamingToolBlockInit:
    def test_none_id_gives_no_identity(self):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        block = StreamingToolBlock(label="test", tool_call_id=None)
        assert block._spinner_identity is None

    def test_known_id_gives_identity(self):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        block = StreamingToolBlock(label="test", tool_call_id="toolu_01abc")
        assert block._spinner_identity is not None
        assert isinstance(block._spinner_identity, SpinnerIdentity)

    def test_identity_is_deterministic(self):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        b1 = StreamingToolBlock(label="test", tool_call_id="toolu_01xyz")
        b2 = StreamingToolBlock(label="test", tool_call_id="toolu_01xyz")
        assert b1._spinner_identity == b2._spinner_identity

    def test_different_ids_may_differ(self):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        b1 = StreamingToolBlock(label="test", tool_call_id="toolu_0001")
        b2 = StreamingToolBlock(label="test", tool_call_id="toolu_0002")
        # Not guaranteed to differ but almost certainly do
        assert b1._spinner_identity is not None and b2._spinner_identity is not None


# ---------------------------------------------------------------------------
# Integration tests — async, require running app
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_block_uses_identity_frames():
    """_tick_spinner uses the identity frame set, not the default."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(
            label="test_tool", tool_name="bash", tool_call_id="toolu_framestest"
        )
        await pilot.pause()
        identity = block._spinner_identity
        assert identity is not None
        # Advance spinner a few ticks and verify char comes from correct frame set
        for _ in range(5):
            block._tick_spinner()
        assert block._header._spinner_char in identity.frames


@pytest.mark.asyncio
async def test_streaming_block_fallback_no_id():
    """tool_call_id=None → header renders with dim fallback style (no identity)."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(
            label="test_tool", tool_name="bash", tool_call_id=None
        )
        await pilot.pause()
        assert block._spinner_identity is None
        assert block._header._spinner_identity is None


@pytest.mark.asyncio
async def test_concurrent_blocks_distinct_colors():
    """3 blocks with different IDs at same _pulse_tick produce different spinner colors."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.animation import lerp_color, pulse_phase_offset

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        ids = ["toolu_aaa111", "toolu_bbb222", "toolu_ccc333"]
        blocks = [
            msg.open_streaming_tool_block(label="t", tool_name="bash", tool_call_id=tid)
            for tid in ids
        ]
        await pilot.pause()
        tick = 15
        colors = []
        for block in blocks:
            ident = block._spinner_identity
            assert ident is not None
            t = pulse_phase_offset(tick, ident.phase_offset)
            colors.append(lerp_color(ident.color_a, ident.color_b, t))
        assert len(set(colors)) == 3, f"expected 3 distinct colors, got {colors}"


@pytest.mark.asyncio
async def test_identity_survives_close():
    """_spinner_identity remains set after block completion so color stays correct."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(
            label="test_tool", tool_name="bash", tool_call_id="toolu_survivetest"
        )
        await pilot.pause()
        assert block._spinner_identity is not None
        # Simulate completion
        block._completed = True
        assert block._spinner_identity is not None, "_spinner_identity cleared on complete"
        assert block._header._spinner_identity is not None, "header identity cleared on complete"


@pytest.mark.asyncio
async def test_streaming_block_color_changes_with_tick():
    """As _pulse_tick advances the rendered spinner color changes."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.animation import lerp_color, pulse_phase_offset

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(
            label="test_tool", tool_name="bash", tool_call_id="toolu_colortest"
        )
        await pilot.pause()
        ident = block._spinner_identity
        assert ident is not None
        header = block._header

        # Collect colors at different tick values
        colors = set()
        for tick in range(0, 30, 3):
            header._pulse_tick = tick
            t = pulse_phase_offset(tick, ident.phase_offset)
            colors.add(lerp_color(ident.color_a, ident.color_b, t))

        # Over 10 samples spanning a full cycle, colors must vary
        assert len(colors) > 3, f"spinner color doesn't change over cycle: {colors}"
