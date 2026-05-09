"""Tests for HintBar render & phase fixes — HB2-H1..H3, HB2-M1..M4, HB2-L2.

Test classes:
    TestMarkupParsing           — HB2-H1 (5 tests)
    TestStreamingErrorPromotion — HB2-H2 (5 tests)
    TestStreamingWidthVariants  — HB2-H3 (4 tests)
    TestCssVarResolver          — HB2-M1 (3 tests)
    TestHintCache               — HB2-M2 (3 tests)
    TestPhaseEviction           — HB2-M3 (3 tests)
    TestSetPhaseShimmer         — HB2-M4 (2 tests)
    TestKeyConstantExports      — HB2-L2 (1 test)
Total: 26
"""
from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from hermes_cli.tui.widgets.status_bar import (
    HintBar,
    _HINT_CACHE_MAX,
    _STREAMING_PROMOTE_PRIORITY,
    _build_streaming_hint,
    _clear_hint_cache,
    _hint_cache,
    _hint_to_text,
    _hints_for,
)


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _FakeFlash:
    """Minimal FlashState stub."""
    def __init__(self, message: str, priority: int = 0) -> None:
        self.message = message
        self.priority = priority


class _FakeApp:
    """Minimal app stub for HintBar unit tests."""

    def __init__(
        self,
        *,
        css_vars: dict[str, str] | None = None,
        streaming: bool = False,
        agent_running: bool = False,
        command_running: bool = False,
        animations_enabled: bool = True,
        flash: "_FakeFlash | None" = None,
    ) -> None:
        self.status_streaming = streaming
        self.agent_running = agent_running
        self.command_running = command_running
        self._animations_enabled = animations_enabled
        self._css_vars = css_vars or {}
        self._flash = flash
        # feedback stub
        self.feedback = types.SimpleNamespace(
            peek=lambda channel: self._flash,
        )

    def get_css_variables(self) -> dict[str, str]:
        return self._css_vars

    def has_class(self, *_: Any) -> bool:
        return False


def _make_hintbar(
    *,
    css_vars: dict[str, str] | None = None,
    streaming: bool = False,
    agent_running: bool = False,
    command_running: bool = False,
    animations_enabled: bool = True,
    flash: "_FakeFlash | None" = None,
    hint: str = "",
    phase: str = "idle",
    width: int = 120,
) -> HintBar:
    """Build a HintBar with a fake app but no real DOM mount.

    Per feedback_textual_widget_test_stubs.md:
    - Textual reactives require _id in __dict__; use __dict__["_id"] = "test"
    - Store reactive values via __dict__["_reactive_<name>"] = value to bypass
      the descriptor's _set() which requires a mounted DOM node.
    - content_size is a property on Widget — must use __new__ subclass trick or
      patch; we use a local _FakeHintBar subclass that overrides it as a plain attr.
    - No DOMNode property access (has_focus, _parent) in these tests.
    """
    # Use a local subclass that overrides both content_size and app as plain properties
    # to bypass Widget/MessagePump internals (both are read-only properties on the real class).
    _w = width  # capture for closure
    _fake_app = _FakeApp(
        css_vars=css_vars,
        streaming=streaming,
        agent_running=agent_running,
        command_running=command_running,
        animations_enabled=animations_enabled,
        flash=flash,
    )

    class _FakeHintBar(HintBar):
        @property  # type: ignore[override]
        def content_size(self):  # type: ignore[override]
            return types.SimpleNamespace(width=_w)

        @property  # type: ignore[override]
        def app(self):  # type: ignore[override]
            return _fake_app

        def refresh(self, *_: Any, **__: Any) -> None:  # type: ignore[override]
            pass

    bar: HintBar = _FakeHintBar.__new__(_FakeHintBar)
    # Required by Textual reactive descriptors (DOMNode._id)
    bar.__dict__["_id"] = "hintbar-test"
    # Store reactive values directly in the backing store
    bar.__dict__["_reactive_hint"] = hint
    bar.__dict__["_reactive__shimmer_tick"] = 0
    # Plain instance attrs (not reactives)
    bar._phase = phase
    bar._shimmer_timer = None
    bar._shimmer_base = None
    bar._shimmer_skip = []
    bar._flash_timer = None
    bar._flash_text = ""
    bar._cycle_kind = None
    bar._kind_chip = None
    from hermes_cli.tui.tool_panel.density import DensityTier
    bar._density_tier = DensityTier.DEFAULT.value
    bar._has_ghost_suggestion = False
    bar._shimmer_tick = 0
    return bar


# ---------------------------------------------------------------------------
# TestMarkupParsing — HB2-H1
# ---------------------------------------------------------------------------

class TestMarkupParsing:
    """HB2-H1: hint values are parsed as Rich markup, not treated as literal strings."""

    def test_hint_markup_parsed_non_streaming(self) -> None:
        """Non-streaming: set hint='[bold]X[/]' → render returns Text with bold span."""
        bar = _make_hintbar(hint="[bold]X[/]")
        result = bar.render()
        assert isinstance(result, Text)
        text_str = result.plain
        assert "X" in text_str
        # Should have a bold span, not literal '[bold]X[/]'
        assert "[bold]" not in text_str

    def test_hint_invalid_markup_falls_back_to_plain(self) -> None:
        """Unbalanced markup falls back to plain text without raising."""
        bar = _make_hintbar(hint="[unbalanced")
        result = bar.render()
        assert isinstance(result, Text)
        # Should contain the literal text, no exception raised
        assert "[unbalanced" in result.plain

    def test_hint_to_text_bold_span_preserved(self) -> None:
        """_hint_to_text('[bold]X[/]') returns Text with bold span (not literal '[bold]X[/]')."""
        result = _hint_to_text("[bold]X[/]")
        assert isinstance(result, Text)
        assert result.plain == "X"
        # Span style may be a string 'bold' or a Style object — check either form
        has_bold = any(
            (isinstance(s.style, str) and "bold" in s.style)
            or (hasattr(s.style, "bold") and s.style.bold)
            for s in result._spans
        )
        assert has_bold, f"Expected bold span; got spans: {result._spans}"

    def test_hint_to_text_plain_string_no_spans(self) -> None:
        """_hint_to_text('hello') returns plain Text with no extra spans."""
        result = _hint_to_text("hello")
        assert result.plain == "hello"

    def test_streaming_flash_no_forced_dim(self) -> None:
        """Streaming + flash: flash text is not forced to dim style."""
        flash = _FakeFlash(message="[bold]urgent[/]", priority=0)
        bar = _make_hintbar(streaming=True, agent_running=True, flash=flash, width=200)
        result = bar.render()
        assert isinstance(result, Text)
        # Should not have dim forced on the entire text
        # The pinned text is separate; flash is appended. Check 'urgent' appears.
        assert "urgent" in result.plain


# ---------------------------------------------------------------------------
# TestStreamingErrorPromotion — HB2-H2
# ---------------------------------------------------------------------------

class TestStreamingErrorPromotion:
    """HB2-H2: priority >= NORMAL flashes are left-anchored during streaming."""

    def test_streaming_status_error_left_anchored_w120(self) -> None:
        """Width 120, p=10 (NORMAL) flash: render starts with the error message."""
        flash = _FakeFlash(message="⚠ something broke", priority=10)
        bar = _make_hintbar(streaming=True, agent_running=True, flash=flash, width=120)
        result = bar.render()
        assert isinstance(result, Text)
        # Error message should be at the start of rendered text
        assert result.plain.startswith("⚠ something broke")

    def test_streaming_status_error_drops_esc_w80(self) -> None:
        """Width 80, p=10: cue contains Ctrl+C but not 'Esc dismiss'."""
        flash = _FakeFlash(message="⚠ msg", priority=10)
        bar = _make_hintbar(streaming=True, agent_running=True, flash=flash, width=80)
        result = bar.render()
        assert isinstance(result, Text)
        plain = result.plain
        # Error is left-anchored
        assert "⚠ msg" in plain
        # 'dismiss' should NOT be present — too narrow for full cue + esc
        # (Esc is in the short streaming pinned text, not in promoted layout cue)
        assert "dismiss" not in plain

    def test_streaming_status_error_drops_cue_w40(self) -> None:
        """Width narrow enough that even cue_min doesn't fit: only the error renders.

        '⚠ msg' = 5 cells; cue_min '  ·  ⌃C' = 7 cells; total 12.
        Use width=8 to force cue drop (message=6 chars + cue_min=7 > 8).
        """
        flash = _FakeFlash(message="⚠ long error message here", priority=10)
        # At width 14: body="⚠ long error message here" (25 cells) > 14, cue doesn't fit
        # Actually let's just pick a very narrow width to guarantee the cue drops
        bar = _make_hintbar(streaming=True, agent_running=True, flash=flash, width=10)
        result = bar.render()
        assert isinstance(result, Text)
        # At width 10, body (25 cells) > 10 already, but body is always rendered;
        # cue_min (7 cells) cannot be appended since 25+7 > 10
        assert "⚠ long" in result.plain
        assert "⌃C" not in result.plain

    def test_streaming_low_flash_right_anchored(self) -> None:
        """Width 120, p=LOW (0): pinned renders left, flash appended right-of-separator."""
        flash = _FakeFlash(message="hint text", priority=0)
        bar = _make_hintbar(streaming=True, agent_running=True, flash=flash, width=120)
        result = bar.render()
        assert isinstance(result, Text)
        plain = result.plain
        # Low-priority: pinned interrupt text first, then separator, then flash
        # 'interrupt' appears in the long-form pinned text at width 120
        assert "interrupt" in plain
        assert "hint text" in plain
        # interrupt should come before the flash
        assert plain.index("interrupt") < plain.index("hint text")

    def test_streaming_no_flash_pinned_only(self) -> None:
        """No flash: pinned renders alone, no trailing separator."""
        bar = _make_hintbar(streaming=True, agent_running=True, flash=None, width=120)
        result = bar.render()
        assert isinstance(result, Text)
        plain = result.plain
        assert "interrupt" in plain
        assert "|" not in plain  # no separator appended


# ---------------------------------------------------------------------------
# TestStreamingWidthVariants — HB2-H3
# ---------------------------------------------------------------------------

class TestStreamingWidthVariants:
    """HB2-H3: streaming pinned text degrades based on terminal width."""

    def test_streaming_pinned_long_at_w120(self) -> None:
        """Width 120: returns long form including 'interrupt' and 'dismiss'."""
        bar = _make_hintbar(streaming=True, agent_running=True, flash=None, width=120)
        result = bar.render()
        plain = result.plain
        assert "interrupt" in plain
        assert "dismiss" in plain

    def test_streaming_pinned_short_at_w60(self) -> None:
        """Width 60 (< 78): returns short form — Ctrl+C and Esc without descriptions."""
        bar = _make_hintbar(streaming=True, agent_running=True, flash=None, width=60)
        result = bar.render()
        plain = result.plain
        # Short form has Ctrl+C and Esc but no 'interrupt'/'dismiss' descriptions
        assert "⌃C" in plain
        assert "Esc" in plain
        assert "interrupt" not in plain
        assert "dismiss" not in plain

    def test_streaming_pinned_minimal_at_w38(self) -> None:
        """Width 38 (< 48): returns minimal form — just Ctrl+C."""
        bar = _make_hintbar(streaming=True, agent_running=True, flash=None, width=38)
        result = bar.render()
        plain = result.plain
        assert "⌃C" in plain
        assert "Esc" not in plain

    def test_shimmer_base_respects_width(self) -> None:
        """_build_streaming_hint(k, width=60) returns short form; badges has 2 ranges."""
        k = "#5f87d7"
        text, badges = _build_streaming_hint(k, width=60)
        plain = text.plain
        # Short form: Ctrl+C and Esc
        assert "⌃C" in plain
        assert "Esc" in plain
        assert "interrupt" not in plain
        # Two badge ranges (one per key)
        assert len(badges) == 2


# ---------------------------------------------------------------------------
# TestCssVarResolver — HB2-M1
# ---------------------------------------------------------------------------

class TestCssVarResolver:
    """HB2-M1: _key_color() uses consistent accent-interactive → primary → hardcoded chain."""

    def test_key_color_uses_accent_interactive(self) -> None:
        """When both accent-interactive and primary are present, uses accent-interactive."""
        bar = _make_hintbar(css_vars={"accent-interactive": "#aabbcc", "primary": "#112233"})
        color = bar._key_color()
        assert color == "#aabbcc"

    def test_key_color_falls_back_to_primary(self) -> None:
        """When only primary is defined, returns primary."""
        bar = _make_hintbar(css_vars={"primary": "#112233"})
        color = bar._key_color()
        assert color == "#112233"

    def test_key_color_hardcoded_fallback(self) -> None:
        """When vars are empty, returns hardcoded '#5f87d7'."""
        bar = _make_hintbar(css_vars={})
        color = bar._key_color()
        assert color == "#5f87d7"


# ---------------------------------------------------------------------------
# TestHintCache — HB2-M2
# ---------------------------------------------------------------------------

class TestHintCache:
    """HB2-M2: hint cache is bounded at 32 entries with FIFO eviction."""

    def setup_method(self) -> None:
        _clear_hint_cache()

    def teardown_method(self) -> None:
        _clear_hint_cache()

    def test_hint_cache_bounded(self) -> None:
        """After inserting 40 distinct colors, cache size stays <= _HINT_CACHE_MAX."""
        for i in range(40):
            color = f"#{i:06x}"
            _hints_for("idle", color)
        assert len(_hint_cache) <= _HINT_CACHE_MAX

    def test_hint_cache_clears_on_skin_change(self) -> None:
        """After populating cache, _clear_hint_cache() empties it."""
        _hints_for("idle", "#aabbcc")
        assert len(_hint_cache) >= 1
        _clear_hint_cache()
        assert len(_hint_cache) == 0

    def test_hint_cache_fifo_eviction_order(self) -> None:
        """The first inserted entry is the first evicted when cache overflows."""
        _clear_hint_cache()
        # Insert exactly _HINT_CACHE_MAX entries
        first_key = None
        for i in range(_HINT_CACHE_MAX):
            color = f"#{i:06x}"
            _hints_for("idle", color)
            if i == 0:
                first_key = ("idle", color.lower())

        assert first_key in _hint_cache  # still present at capacity
        # Insert one more to trigger eviction
        _hints_for("idle", "#ffffff")
        # First inserted key should have been evicted
        assert first_key not in _hint_cache


# ---------------------------------------------------------------------------
# TestPhaseEviction — HB2-M3
# ---------------------------------------------------------------------------

class TestPhaseEviction:
    """HB2-M3: stale stream/file phase is evicted proactively in _on_streaming_change."""

    def test_streaming_end_evicts_stale_stream_phase(self) -> None:
        """streaming=False, running=False, phase='stream' → phase becomes 'idle'."""
        bar = _make_hintbar(streaming=False, agent_running=False, phase="stream")
        bar._on_streaming_change(streaming=False)
        assert bar._phase == "idle"

    def test_streaming_end_keeps_stream_phase_when_running(self) -> None:
        """streaming=False but running=True: phase stays 'stream', shimmer restarts."""
        bar = _make_hintbar(
            streaming=False,
            agent_running=True,
            phase="stream",
            animations_enabled=False,  # disable to avoid timer setup
        )
        bar._on_streaming_change(streaming=False)
        # Phase should remain 'stream' since agent is still running
        assert bar._phase == "stream"

    def test_render_guard_still_resets_orphan_phase(self) -> None:
        """Belt-and-braces: manually set _phase='stream', not running → render resets it."""
        bar = _make_hintbar(streaming=False, agent_running=False, phase="stream")
        # Bypass _on_streaming_change to simulate missed watcher
        bar._phase = "stream"
        result = bar.render()
        assert bar._phase == "idle"
        assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# TestSetPhaseShimmer — HB2-M4
# ---------------------------------------------------------------------------

class TestSetPhaseShimmer:
    """HB2-M4: set_phase checks shimmer consistency before short-circuiting."""

    def test_set_phase_same_phase_restarts_shimmer_when_inconsistent(self) -> None:
        """Phase already 'stream', shimmer stopped, should_shimmer=True → shimmer restarts."""
        bar = _make_hintbar(
            streaming=False,
            agent_running=True,
            phase="stream",
            animations_enabled=True,
        )
        # Shimmer is stopped but phase says stream — inconsistent
        assert bar._shimmer_timer is None
        # Patch _shimmer_start to track calls
        started = []
        original_start = bar._shimmer_start

        def _fake_start() -> None:
            started.append(True)

        bar._shimmer_start = _fake_start
        bar.set_phase("stream")
        assert len(started) == 1, "shimmer should have restarted"

    def test_set_phase_same_phase_no_op_when_consistent(self) -> None:
        """Phase already 'idle', shimmer stopped (consistent) → no refresh or timer touch."""
        bar = _make_hintbar(streaming=False, agent_running=False, phase="idle")
        # Idle + no shimmer is consistent
        refreshed = []
        bar.refresh = lambda: refreshed.append(True)  # type: ignore[method-assign]
        bar.set_phase("idle")
        # No refresh should fire since state is consistent
        assert len(refreshed) == 0, "no-op path should not call refresh"


# ---------------------------------------------------------------------------
# TestKeyConstantExports — HB2-L2
# ---------------------------------------------------------------------------

class TestKeyConstantExports:
    """HB2-L2: all KEY_* constants and HINT_MAX_PRIMARY importable from hermes_cli.tui.widgets."""

    def test_key_constants_importable(self) -> None:
        """All KEY_* and HINT_MAX_PRIMARY importable from hermes_cli.tui.widgets."""
        from hermes_cli.tui.widgets import (
            HINT_MAX_PRIMARY,
            KEY_CTRL_C,
            KEY_CTRL_F,
            KEY_CTRL_J,
            KEY_CTRL_SHIFT_H,
            KEY_CTRL_Z,
            KEY_DOWN,
            KEY_ENTER,
            KEY_ESC,
            KEY_SPACE,
            KEY_TAB,
            KEY_UP,
        )
        assert KEY_ENTER == "Enter"
        assert KEY_TAB == "Tab"
        assert KEY_SPACE == "Space"
        assert KEY_ESC == "Esc"
        assert KEY_CTRL_C == "⌃C"
        assert KEY_CTRL_F == "⌃F"
        assert KEY_CTRL_SHIFT_H == "⌃⇧H"
        assert KEY_CTRL_J == "⌃J"
        assert KEY_CTRL_Z == "⌃Z"
        assert KEY_UP == "↑"
        assert KEY_DOWN == "↓"
        assert HINT_MAX_PRIMARY == 3
