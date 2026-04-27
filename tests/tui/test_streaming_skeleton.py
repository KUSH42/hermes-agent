"""SK-1 (pre-first-chunk skeleton) + SK-2 (streaming KIND hint defensive clear).

Spec: docs/2026-04-27-tcs-audit-05-streaming-skeleton-spec.md.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BLOCK_SUBCLASS_CACHE = {}
_HEADER_SUBCLASS_CACHE = {}


def _isolated_header_cls():
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    if "cls" not in _HEADER_SUBCLASS_CACHE:
        class _IsolatedHeader(ToolHeader):
            is_attached = False

            @property
            def size(self):
                return types.SimpleNamespace(width=80)
        _HEADER_SUBCLASS_CACHE["cls"] = _IsolatedHeader
    return _HEADER_SUBCLASS_CACHE["cls"]


def _isolated_block_cls():
    """Subclass StreamingToolBlock once with overridden read-only properties.

    Mutating `type(block).is_attached = PropertyMock(...)` directly leaks to
    other tests via the shared StreamingToolBlock class. A throwaway subclass
    isolates the override.
    """
    from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
    if "cls" not in _BLOCK_SUBCLASS_CACHE:
        class _IsolatedBlock(StreamingToolBlock):
            is_attached = True  # overrides Widget.is_attached property in MRO
            _fake_app = types.SimpleNamespace(_reduced_motion=False)

            @property
            def app(self):  # noqa: D401 — match Widget.app return contract
                return self._fake_app
        _BLOCK_SUBCLASS_CACHE["cls"] = _IsolatedBlock
    return _BLOCK_SUBCLASS_CACHE["cls"]


def _make_block():
    """Bare StreamingToolBlock subclass with skeleton attrs initialised + mocked widget surface.

    Uses a subclass to override read-only `is_attached`/`app` properties without
    mutating the shared StreamingToolBlock class (which would leak to other tests).
    """
    cls = _isolated_block_cls()
    block = cls.__new__(cls)
    # Skeleton attrs from __init__
    block._skeleton_widget = None
    block._skeleton_timer = None
    block._skeleton_pulse_timer = None
    block._skeleton_dim = True
    # Counters / state from __init__ that skeleton paths read
    block._total_received = 0
    block._completed = False
    block._is_unmounted = False
    block._broken = False
    block._tool_call_id = None
    block._tool_input = None
    block._tool_name = None
    block._pending = []
    block._all_plain = []
    block._all_rich = []
    block._bytes_received = 0
    block._last_line_time = 0.0
    block._truncated_line_count = 0
    block._should_strip_cwd = False
    block._detected_cwd = None
    block._line_byte_cap = 2000
    block._visible_cap = 200
    block._visible_count = 0
    block._visible_start = 0
    block._history_capped = False
    block._follow_tail = False
    block._follow_tail_dirty = False
    block._omission_bar_top_mounted = False
    block._omission_bar_bottom_mounted = False
    from collections import deque
    block._rate_samples = deque(maxlen=60)
    block._last_http_status = None
    block._flush_slow = False
    block._render_timer = None
    # Header stub (skeleton reads _tool_icon)
    block._header = MagicMock()
    block._header._tool_icon = "🔧"
    # Tail stub for mount before= anchor
    block._tail = MagicMock()
    # is_attached / app — mock as needed by individual tests
    block._view = None

    # Capture timer callbacks instead of scheduling
    captured = {"timers": [], "intervals": []}

    def _set_timer(delay, cb):
        tok = MagicMock()
        tok._delay = delay
        tok._cb = cb
        captured["timers"].append(tok)
        return tok

    def _set_interval(delay, cb):
        tok = MagicMock()
        tok._delay = delay
        tok._cb = cb
        captured["intervals"].append(tok)
        return tok

    block.set_timer = _set_timer
    block.set_interval = _set_interval
    block._register_timer = lambda t: t
    # mount captures the widget in _mounted_skeleton
    mounted = []

    def _mount(widget, *args, **kwargs):
        # is_mounted is a Textual Widget property — patch the class to True
        type(widget).is_mounted = PropertyMock(return_value=True)
        # remove() requires App context — replace with no-op for unit tests
        widget.remove = MagicMock()
        mounted.append(widget)

    block.mount = _mount
    # post_message no-op (used by append_line for ToolGroup notification)
    block.post_message = lambda *a, **k: None

    block._captured = captured
    block._mounted = mounted
    return block


# ---------------------------------------------------------------------------
# SK-2: streaming KIND hint defensive clear at COMPLETING/ERROR/CANCELLED
# ---------------------------------------------------------------------------

class TestStreamingHintClear:
    def _make_header(self, *, with_hint_value=None):
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        h = ToolHeader.__new__(ToolHeader)
        h._streaming_kind_hint = with_hint_value
        # `is_attached` is a read-only property on Widget — set on instance
        # via subclass to avoid leaking to other tests.
        cls = _isolated_header_cls()
        h.__class__ = cls
        return h

    def test_hint_cleared_on_completing(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        h = self._make_header(with_hint_value=ResultKind.DIFF)
        h._on_axis_change(None, "state", ToolCallState.STREAMING, ToolCallState.COMPLETING)
        assert h._streaming_kind_hint is None

    def test_hint_cleared_on_error(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        h = self._make_header(with_hint_value=ResultKind.JSON)
        h._on_axis_change(None, "state", ToolCallState.STREAMING, ToolCallState.ERROR)
        assert h._streaming_kind_hint is None

    def test_hint_cleared_on_cancel(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        h = self._make_header(with_hint_value=ResultKind.CODE)
        h._on_axis_change(None, "state", ToolCallState.STREAMING, ToolCallState.CANCELLED)
        assert h._streaming_kind_hint is None

    def test_hint_persists_during_streaming(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind
        h = self._make_header(with_hint_value=ResultKind.DIFF)
        # hint axis arrival, state stays STREAMING — only the hint branch runs
        h._on_axis_change(None, "streaming_kind_hint", None, ResultKind.DIFF)
        assert h._streaming_kind_hint is ResultKind.DIFF

    def test_late_hint_write_after_terminal_no_render(self):
        """state=DONE clears, late hint write sets field, but _render_v4 suppresses chip."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind

        # Use the helper from test_focus_and_settled.py — replicated inline for isolation.
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.body_renderers._grammar import SkinColors

        h = ToolHeader.__new__(ToolHeader)
        h._classes = set()
        h._is_child = False
        h._is_child_diff = False
        h._is_complete = True  # set by completion path
        h._tool_icon_error = False
        h._error_kind = None
        h._tool_name = "execute_code"
        h._header_args = {}
        h._label = "x"
        h._label_rich = None
        h._full_path = None
        h._path_clickable = False
        h._primary_hero = None
        h._line_count = 0
        h._stats = None
        h._duration = "0.2s"
        h._flash_msg = None
        h._flash_tone = None
        h._flash_expires = 0.0
        h._browse_badge = ""
        h._streaming_phase = False
        h._streaming_kind_hint = None
        h._tool_icon = "🔧"
        h._has_affordances = False
        h._panel = None
        colors = SkinColors.default()
        h._skin_colors_cache = colors
        h._focused_gutter_color = colors.tool_header_gutter
        h._colors = lambda: colors
        h._accessible_mode = lambda: False
        # size override on the isolated subclass (set after class swap below).
        # `is_attached` is a read-only property on Widget — set on instance
        # via subclass to avoid leaking to other tests.
        cls = _isolated_header_cls()
        h.__class__ = cls

        def _has_class(c):
            return c in h._classes
        h.has_class = _has_class

        # state=DONE → hint cleared (no-op since None already), then late hint write
        h._on_axis_change(None, "state", ToolCallState.STREAMING, ToolCallState.DONE)
        h._on_axis_change(None, "streaming_kind_hint", None, ResultKind.DIFF)
        assert h._streaming_kind_hint is ResultKind.DIFF  # field set

        # Render: visibility check `not self._is_complete` suppresses the chip
        rendered = h._render_v4()
        plain = rendered.plain if rendered is not None else ""
        assert "±" not in plain
        assert "diff" not in plain.lower()


# ---------------------------------------------------------------------------
# SK-1: pre-first-chunk skeleton row
# ---------------------------------------------------------------------------

class TestSkeletonRow:
    def test_skeleton_not_mounted_when_first_chunk_arrives_before_100ms(self):
        block = _make_block()
        # Arm timer (simulates on_mount path)
        block._skeleton_timer = block._register_timer(
            block.set_timer(0.1, block._maybe_mount_skeleton)
        )
        # First chunk arrives before timer fires
        block.append_line("hello")
        assert block._skeleton_widget is None
        assert block._skeleton_timer is None

    def test_skeleton_mounted_after_100ms_no_chunk(self):
        block = _make_block()
        block._skeleton_timer = block._register_timer(
            block.set_timer(0.1, block._maybe_mount_skeleton)
        )
        # Fire the timer manually
        block._maybe_mount_skeleton()
        assert block._skeleton_widget is not None
        assert block._skeleton_widget.is_mounted is True
        assert block._mounted == [block._skeleton_widget]

    def test_skeleton_dismissed_on_first_chunk(self):
        block = _make_block()
        # Skeleton already mounted (timer fired)
        block._maybe_mount_skeleton()
        assert block._skeleton_widget is not None
        # First chunk dismisses it
        block.append_line("hello")
        assert block._skeleton_widget is None
        assert block._skeleton_pulse_timer is None

    def test_skeleton_uses_streaming_kind_hint_icon(self):
        from hermes_cli.tui.tool_payload import ResultKind
        block = _make_block()
        # view carries the hint
        block._view = types.SimpleNamespace(streaming_kind_hint=ResultKind.DIFF)
        block._maybe_mount_skeleton()
        assert block._skeleton_widget is not None
        # The Static was constructed with a Rich Text — fish out its renderable
        rendered = block._skeleton_widget._Static__content
        assert rendered.plain.startswith("± ")

    def test_skeleton_falls_back_to_generic_icon(self):
        block = _make_block()
        # No hint, no header icon — falls back to ▸
        block._header._tool_icon = ""
        block._maybe_mount_skeleton()
        assert block._skeleton_widget is not None
        assert block._skeleton_widget._Static__content.plain.startswith("▸ ")

    def test_skeleton_dismissed_on_complete(self):
        """complete() must call _dismiss_skeleton — verify via spy."""
        block = _make_block()
        block._maybe_mount_skeleton()
        assert block._skeleton_widget is not None

        # Stub out the rest of complete()'s surface so we can call it cleanly
        block._stop_all_managed = MagicMock()
        block._header._pulse_stop = MagicMock()
        block._header.set_error = MagicMock()
        block._header.flash_success = MagicMock()
        block._header.flash_error = MagicMock()
        block._header.refresh = MagicMock()
        block._header.add_class = MagicMock()
        block._flush_pending = MagicMock()
        block._tail.dismiss = MagicMock()
        block._clear_microcopy_on_complete = MagicMock()
        block._body = MagicMock()
        block._secondary_args_snapshot = ""
        block._stream_started_at = None  # forces else-branch in complete()
        block.add_class = MagicMock()
        block._try_mount_media = MagicMock()
        block._tool_input = None

        # Spy on _dismiss_skeleton to confirm complete() invokes it.
        with patch.object(block, "_dismiss_skeleton", wraps=block._dismiss_skeleton) as spy:
            block.complete("0.2s")
        spy.assert_called_once()
        assert block._skeleton_widget is None

    def test_skeleton_text_dim_styled(self):
        block = _make_block()
        block._maybe_mount_skeleton()
        rendered = block._skeleton_widget._Static__content
        # Spec accepts dim Style or --dim class — class always present at mount
        assert "tool-skeleton--dim" in (block._skeleton_widget.classes or "")
        # And every span carries dim style
        for span in rendered._spans:
            assert "dim" in str(span.style)

    def test_skeleton_glyph_is_three_middot(self):
        block = _make_block()
        block._maybe_mount_skeleton()
        assert "· · ·" in block._skeleton_widget._Static__content.plain
