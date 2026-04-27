"""Tests for Tool Calls — Canonical Liveness Per Phase spec (CL-1..CL-6).

Spec: /home/xush/.hermes/2026-04-26-tcs-canonical-liveness-spec.md

Test layout:
    TestNoTailSpinner           — 4 tests — CL-1: spinner segment deleted
    TestPhaseChipExclusivity    — 4 tests — CL-2: STREAMING clears …starting chip
    TestStreamingPhaseFlag      — 3 tests — CL-3: _streaming_phase canonical flag
    TestPulseStallCoordination  — 3 tests — CL-4: pulse freezes on stall
    TestMicrocopyTerminalCleanup — 1 test  — CL-5: microcopy cleared on complete
    TestSpinnerIdentitySkinDriven — 1 test — CL-6: make_spinner_identity uses tier_accents
    Total: 16 tests
"""
from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view(state=None, completing_started_at=None):
    from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState
    return ToolCallViewState(
        tool_call_id="test-cl",
        gen_index=0,
        tool_name="bash",
        label="bash",
        args={},
        state=state or ToolCallState.PENDING,
        block=None,
        panel=None,
        parent_tool_call_id=None,
        category="shell",
        depth=0,
        start_s=time.monotonic(),
        completing_started_at=completing_started_at,
        density_reason=None,
    )


class _HeaderStub:
    """Minimal stub binding ToolCallHeader methods for timer-driven tests."""

    def __init__(self, view):
        from hermes_cli.tui.tool_blocks._header import ToolCallHeader
        self._view = view
        self._phase_chip_timer = None
        self._completing_chip_timer = None
        self.is_attached = True

        self._phase_chip = MagicMock()
        self._phase_chip.display = False
        self._finalizing_chip = MagicMock()
        self._finalizing_chip.display = False

        self.set_state = ToolCallHeader.set_state.__get__(self)
        self._render_phase_chip = ToolCallHeader._render_phase_chip.__get__(self)
        self._clear_phase_chip = ToolCallHeader._clear_phase_chip.__get__(self)

        timers = []

        def _fake_set_timer(delay, cb):
            t = MagicMock()
            t._callback = cb
            t._delay = delay
            timers.append(t)
            return t

        self.set_timer = _fake_set_timer
        self._timers = timers


class _UpdateMicrocopyStub:
    """Minimal stub for testing StreamingToolBlock._update_microcopy stall logic."""

    def __init__(self, last_line_age_s: float = 0.0, completed: bool = False):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        now = time.monotonic()
        self._header = MagicMock()
        self._header._pulse_paused = False
        self._completed = completed
        self._last_line_time = now - last_line_age_s if last_line_age_s > 0 else now
        self._stream_started_at = now - max(last_line_age_s, 1.0)
        self._shimmer_phase = 0.0
        self._tool_name = "bash"
        self._total_received = 5
        self._bytes_received = 512
        self._last_http_status = None
        self._rate_samples: deque = deque(maxlen=60)
        self._body = MagicMock()
        self._microcopy_shown = False
        self.app = MagicMock()
        self.app._reduced_motion = False

        self._update_microcopy = StreamingToolBlock._update_microcopy.__get__(self)
        self._bytes_per_second = StreamingToolBlock._bytes_per_second.__get__(self)


# ---------------------------------------------------------------------------
# TestNoTailSpinner — CL-1
# ---------------------------------------------------------------------------

class TestNoTailSpinner:
    """CL-1: tail spinner segment deleted; icon pulse is the sole streaming animation."""

    def test_no_spinner_segment_during_streaming(self):
        """_render_v4() produces no 'spinner' segment when _streaming_phase=True."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader

        h = ToolHeader(label="bash -c ls", line_count=0, tool_name="bash")
        h._streaming_phase = True
        h._pulse_t = 0.5
        h._spinner_identity = None

        seen_segments: list[str] = []

        with patch.object(h, "_accessible_mode", return_value=False):
            # Capture segment names by monkey-patching list at render time
            original_render = ToolHeader._render_v4

            def _capturing_render(self_inner):
                # Shadow tail_segments list to capture names
                captured = []

                class _CapturingList(list):
                    def append(self_list, item):
                        if isinstance(item, tuple) and len(item) == 2:
                            seen_segments.append(item[0])
                        super().append(item)

                with patch("hermes_cli.tui.tool_blocks._header.Text", wraps=__import__("rich.text", fromlist=["Text"]).Text):
                    return original_render(self_inner)

            result = h._render_v4()

        # "spinner" segment was never wired into tail_segments — verify braille chars absent
        if result is not None:
            braille_spinner_frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
                                      "⠈", "⠘", "⠸", "⠾", "⠿", "⣾", "⣽", "⣻")
            plain = result.plain
            for ch in braille_spinner_frames:
                assert ch not in plain, f"Unexpected spinner char {ch!r} in rendered header"

    def test_no_spinner_timer_registered(self):
        """StreamingToolBlock no longer has a _tick_spinner method (timer deleted)."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        assert not hasattr(StreamingToolBlock, "_tick_spinner"), (
            "_tick_spinner should have been deleted by CL-1"
        )

    def test_pulse_starts_on_streaming(self):
        """on_mount calls self._header._pulse_start()."""
        import inspect
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        src = inspect.getsource(StreamingToolBlock.on_mount)
        assert "_pulse_start()" in src

    def test_pulse_stops_on_complete(self):
        """complete() calls self._header._pulse_stop()."""
        import inspect
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        src = inspect.getsource(StreamingToolBlock.complete)
        assert "_pulse_stop()" in src


# ---------------------------------------------------------------------------
# TestPhaseChipExclusivity — CL-2
# ---------------------------------------------------------------------------

class TestPhaseChipExclusivity:
    """CL-2: STREAMING entry clears …starting chip immediately."""

    def test_starting_chip_clears_on_streaming_entry(self):
        """STARTED → STREAMING hides the phase chip immediately."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.STARTED)
        header = _HeaderStub(view)
        header._phase_chip.display = True  # chip was visible

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 9999.0
            header.set_state(ToolCallState.STREAMING)

        assert header._phase_chip.display is False

    def test_starting_chip_self_expires_after_0_8s(self):
        """STARTED backstop timer fires at 0.8s and hides the chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.PENDING)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            header.set_state(ToolCallState.STARTED)

        assert len(header._timers) == 1
        backstop = header._timers[0]
        assert abs(backstop._delay - 0.8) < 0.01

        # Simulate timer fire
        header._phase_chip.display = True
        backstop._callback()
        assert header._phase_chip.display is False

    def test_finalizing_chip_armed_on_completing(self):
        """STREAMING → COMPLETING arms the 251ms finalizing timer."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.STREAMING)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            header.set_state(ToolCallState.COMPLETING)

        completing_timers = [t for t in header._timers if abs(t._delay - 0.251) < 0.01]
        assert len(completing_timers) == 1

    def test_finalizing_chip_cleared_on_done(self):
        """COMPLETING → DONE hides the finalizing chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING)
        header = _HeaderStub(view)
        header._finalizing_chip.display = True

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 9999.0
            header.set_state(ToolCallState.DONE)

        assert header._finalizing_chip.display is False


# ---------------------------------------------------------------------------
# TestStreamingPhaseFlag — CL-3
# ---------------------------------------------------------------------------

class TestStreamingPhaseFlag:
    """CL-3: _streaming_phase is the canonical liveness flag on ToolHeader."""

    def test_streaming_phase_true_on_mount(self):
        """on_mount sets self._header._streaming_phase = True after _pulse_start()."""
        import inspect
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        src = inspect.getsource(StreamingToolBlock.on_mount)
        assert "_streaming_phase = True" in src

    def test_streaming_phase_false_after_complete(self):
        """complete() sets self._header._streaming_phase = False after _pulse_stop()."""
        import inspect
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        src = inspect.getsource(StreamingToolBlock.complete)
        assert "_streaming_phase = False" in src
        # Must come after _pulse_stop
        pulse_stop_pos = src.index("_pulse_stop()")
        streaming_false_pos = src.index("_streaming_phase = False")
        assert streaming_false_pos > pulse_stop_pos, (
            "_streaming_phase = False must appear after _pulse_stop()"
        )



# ---------------------------------------------------------------------------
# TestPulseStallCoordination — CL-4
# ---------------------------------------------------------------------------

class TestPulseStallCoordination:
    """CL-4: pulse freezes when output stalls; resumes on next line."""

    def test_pulse_paused_on_stall(self):
        """_update_microcopy sets header._pulse_paused=True when last line > 5s ago."""
        stub = _UpdateMicrocopyStub(last_line_age_s=6.0)
        stub._update_microcopy()
        assert stub._header._pulse_paused is True

    def test_pulse_resumed_on_new_line_after_stall(self):
        """_update_microcopy sets header._pulse_paused=False when output is flowing."""
        stub = _UpdateMicrocopyStub(last_line_age_s=0.1)  # recent line → not stalled
        stub._header._pulse_paused = True  # pre-condition: was paused
        stub._update_microcopy()
        assert stub._header._pulse_paused is False

    def test_pulse_tick_skipped_when_paused(self):
        """PulseMixin._pulse_step() is a no-op when _pulse_paused=True."""
        from hermes_cli.tui.animation import PulseMixin

        class _PulseWidget(PulseMixin):
            def __init__(self):
                self._pulse_t = 0.0
                self._pulse_tick = 0
                self._pulse_paused = True
                self._refreshed = False

            def refresh(self):
                self._refreshed = True

        widget = _PulseWidget()
        widget._pulse_step()

        assert widget._pulse_tick == 0, "_pulse_tick must not advance when paused"
        assert widget._pulse_t == 0.0, "_pulse_t must not change when paused"
        assert widget._refreshed is False, "refresh() must not be called when paused"


# ---------------------------------------------------------------------------
# TestMicrocopyTerminalCleanup — CL-5
# ---------------------------------------------------------------------------

class TestMicrocopyTerminalCleanup:
    """CL-5: microcopy is cleared when complete() is called."""

    def test_microcopy_cleared_on_complete(self):
        """complete() calls _clear_microcopy_on_complete(), leaving _microcopy_active=False."""
        import inspect
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        # Verify complete() calls _clear_microcopy_on_complete
        src = inspect.getsource(StreamingToolBlock.complete)
        assert "_clear_microcopy_on_complete()" in src

        # Also verify _clear_microcopy_on_complete sets _microcopy_active=False via body
        src2 = inspect.getsource(StreamingToolBlock._clear_microcopy_on_complete)
        assert "clear_microcopy" in src2


# ---------------------------------------------------------------------------
# TestSpinnerIdentitySkinDriven — CL-6 (deleted: make_spinner_identity removed in CU-1/CU-2)
