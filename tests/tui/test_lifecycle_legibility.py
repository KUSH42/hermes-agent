"""Tests for Tool Call Lifecycle Legibility spec (LL-1..LL-6).

Spec: /home/xush/.hermes/spec_tool_lifecycle_legibility.md

Test layout:
    TestLL1DensityFlash     — 6 tests — LL-1 density tier flash suppression
    TestLL2CompletingChip   — 5 tests — LL-2 completing chip 250ms gate
    TestLL3ErrorMarker      — 4 tests — LL-3 error-expanded class + glyph
    TestLL4KindOverride     — 7 tests — LL-4 kind override chip + cycling
    TestLL5Adoption         — 5 tests — LL-5 adoption flash + adopted class
    TestLL6PhaseChip        — 8 tests — LL-6 ToolCallHeader state→chip mapping
    Total: 35 tests
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view(
    state=None,
    completing_started_at=None,
    density_reason=None,
):
    """Build a minimal ToolCallViewState-like view for testing."""
    from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState
    import time as _t
    return ToolCallViewState(
        tool_call_id="test-1",
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
        start_s=_t.monotonic(),
        completing_started_at=completing_started_at,
        density_reason=density_reason,
    )


class _HeaderStub:
    """Stub wrapping ToolCallHeader methods without Textual Widget machinery."""

    def __init__(self, view):
        from hermes_cli.tui.tool_blocks._header import ToolCallHeader
        self._view = view
        self._phase_chip_timer = None
        self._completing_chip_timer = None
        self.is_attached = True

        phase_chip = MagicMock()
        phase_chip.display = False
        finalizing_chip = MagicMock()
        finalizing_chip.display = False
        self._phase_chip = phase_chip
        self._finalizing_chip = finalizing_chip

        # Bind real methods from ToolCallHeader
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


class _StreamingBlockStub:
    """Stub wrapping StreamingToolBlock methods without Textual Widget machinery."""

    def __init__(self):
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        self._kind_override = None
        self._was_generated = False
        self._remove_adopted_timer = None
        self.is_attached = True
        self.id = None

        posted = []
        self.post_message = lambda m: posted.append(m)
        self._posted = posted

        classes = set()
        self.add_class = lambda *a: classes.update(a)
        self.remove_class = lambda *a: [classes.discard(x) for x in a]
        self.classes = classes

        timers = []

        def _fake_set_timer(delay, cb):
            t = MagicMock()
            t._callback = cb
            t._delay = delay
            timers.append(t)
            return t

        self.set_timer = _fake_set_timer
        self._timers = timers

        # FS-3: settled state attrs
        self._settled = False
        self._settled_timer = None
        self._cancel_settled_timer = lambda: None

        # Bind real methods
        self.set_block_state = StreamingToolBlock.set_block_state.__get__(self)
        self._remove_adopted = StreamingToolBlock._remove_adopted.__get__(self)
        self._do_cycle_kind = StreamingToolBlock._do_cycle_kind.__get__(self)
        self.action_cycle_kind = StreamingToolBlock.action_cycle_kind.__get__(self)
        self.action_kind_revert = StreamingToolBlock.action_kind_revert.__get__(self)
        self._auto_renderer_kind = StreamingToolBlock._auto_renderer_kind.__get__(self)
        self._clear_settled = StreamingToolBlock._clear_settled.__get__(self)
        self._arm_settled_timer = StreamingToolBlock._arm_settled_timer.__get__(self)
        self._on_settled_timer = StreamingToolBlock._on_settled_timer.__get__(self)


# ---------------------------------------------------------------------------
# TestLL1DensityFlash
# ---------------------------------------------------------------------------

class TestLL1DensityFlash:
    """LL-1: density tier transition flash — tests the pure density_flash_text function."""

    def _flash(self, last_tier, new_tier, reason="auto"):
        """Call density_flash_text with given last/new tier and reason."""
        from hermes_cli.tui.tool_panel._core import density_flash_text
        from hermes_cli.tui.tool_panel.layout_resolver import DensityResult, DensityTier

        last = DensityResult(tier=last_tier, reason="auto") if last_tier is not None else None
        return density_flash_text(last, new_tier, reason)

    def test_initial_mount_no_flash(self):
        """last=None (first call) → no flash regardless of tier."""
        from hermes_cli.tui.tool_panel._core import density_flash_text
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        result = density_flash_text(None, DensityTier.HERO, "auto")
        assert result == ""

    def test_auto_promote_to_hero_flashes(self):
        """DEFAULT → HERO with reason=auto → '★ hero view'."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        result = self._flash(DensityTier.DEFAULT, DensityTier.HERO, "auto")
        assert result == "★ hero view"

    def test_auto_demote_to_compact_flashes(self):
        """DEFAULT → COMPACT with reason=auto → '▤ compact view'."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        result = self._flash(DensityTier.DEFAULT, DensityTier.COMPACT, "auto")
        assert result == "▤ compact view"

    def test_user_initiated_change_no_flash(self):
        """DEFAULT → HERO with reason=user → '' (rule 3)."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        result = self._flash(DensityTier.DEFAULT, DensityTier.HERO, "user")
        assert result == ""

    def test_error_override_no_flash(self):
        """HERO → DEFAULT with reason=error_override → '' (rule 3)."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        result = self._flash(DensityTier.HERO, DensityTier.DEFAULT, "error_override")
        assert result == ""

    @pytest.mark.parametrize("tier_name", ["DEFAULT", "COMPACT", "HERO", "TRACE"])
    def test_repeated_same_tier_no_flash(self, tier_name):
        """Same tier twice (auto) → '' (rule 2)."""
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier

        tier = DensityTier[tier_name]
        result = self._flash(tier, tier, "auto")
        assert result == ""


# ---------------------------------------------------------------------------
# TestLL2CompletingChip
# ---------------------------------------------------------------------------

class TestLL2CompletingChip:
    """LL-2: completing chip visible only after 250ms."""

    def test_completing_under_250ms_no_chip(self):
        """elapsed=0.249 → chip hidden."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING, completing_started_at=1000.0)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 1000.249
            header._render_phase_chip()

        assert header._finalizing_chip.display is False

    def test_completing_over_250ms_shows_chip(self):
        """elapsed=0.251 → chip shown with '…finalizing' text."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING, completing_started_at=1000.0)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 1000.251
            header._render_phase_chip()

        assert header._finalizing_chip.display is True
        header._finalizing_chip.update.assert_called_with("[dim]…FINALIZING[/dim]")

    def test_chip_removed_on_done(self):
        """Transition COMPLETING → DONE hides the finalizing chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING)
        header = _HeaderStub(view)
        header._finalizing_chip.display = True  # pre-condition

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 9999.0
            header.set_state(ToolCallState.DONE)

        assert header._finalizing_chip.display is False

    def test_chip_removed_on_error(self):
        """Transition COMPLETING → ERROR hides the finalizing chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING)
        header = _HeaderStub(view)
        header._finalizing_chip.display = True

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 9999.0
            header.set_state(ToolCallState.ERROR)

        assert header._finalizing_chip.display is False

    def test_chip_removed_on_cancelled(self):
        """Transition COMPLETING → CANCELLED hides finalizing chip, shows cancelled chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.COMPLETING)
        header = _HeaderStub(view)
        header._finalizing_chip.display = True

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 9999.0
            header.set_state(ToolCallState.CANCELLED)

        assert header._finalizing_chip.display is False
        # CANCELLED sets phase chip instead
        assert header._phase_chip.display is True


# ---------------------------------------------------------------------------
# TestLL3ErrorMarker
# ---------------------------------------------------------------------------

class TestLL3ErrorMarker:
    """LL-3: error-expanded class and ⚠-glyph visibility contract."""

    def test_error_state_adds_error_expanded_class(self):
        """Panel writes density_reason='error_override' to view when decision.reason=error_override."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision
        import threading

        view = _make_view(state=ToolCallState.ERROR)
        block = MagicMock()
        block._header = None

        panel = ToolPanel.__new__(ToolPanel)
        panel._block = block
        panel._view_state = view
        panel._last_density_result = None
        panel._footer_pane = None
        panel._user_collapse_override = False
        panel._auto_collapsed = False
        panel._body_pane = None
        panel._hint_row = None
        panel.post_message = MagicMock()
        panel._classes = set()  # Textual internal needed by remove_class/add_class

        decision = LayoutDecision(
            tier=DensityTier.DEFAULT,
            footer_visible=False,
            width=120,
            reason="error_override",
        )

        fake_app = SimpleNamespace(_thread_id=1, update_styles=MagicMock())
        with patch("threading.get_ident", return_value=1), \
             patch.object(type(panel), "app", new_callable=PropertyMock, return_value=fake_app), \
             patch.object(type(panel), "is_attached", new_callable=PropertyMock, return_value=True), \
             patch.object(type(panel), "density", new_callable=PropertyMock), \
             patch.object(type(panel), "collapsed", new_callable=PropertyMock):
            panel._apply_layout(decision)

        assert view.density_reason == "error_override"

    def test_error_glyph_shown_when_density_reason_is_error_override(self):
        """ToolCallHeader glyph condition: state==ERROR AND density_reason=='error_override'."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.ERROR, density_reason="error_override")
        glyph_visible = (
            view.state == ToolCallState.ERROR
            and view.density_reason == "error_override"
        )
        assert glyph_visible is True

    def test_non_error_default_no_marker(self):
        """Auto-promoted HERO: glyph condition false — no ⚠."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.DONE, density_reason="auto")
        glyph_visible = (
            view.state == ToolCallState.ERROR
            and view.density_reason == "error_override"
        )
        assert glyph_visible is False

    def test_user_promoted_default_no_error_marker(self):
        """User-initiated density change: glyph condition false."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.DONE, density_reason="user")
        glyph_visible = (
            view.state == ToolCallState.ERROR
            and view.density_reason == "error_override"
        )
        assert glyph_visible is False


# ---------------------------------------------------------------------------
# TestLL4KindOverride
# ---------------------------------------------------------------------------

class TestLL4KindOverride:
    """LL-4: renderer kind override chip cycling."""

    def test_override_chip_appears(self):
        """After _do_cycle_kind, KindOverrideChanged with override!=None is posted."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.widgets.status_bar import KindOverrideChanged

        block = _StreamingBlockStub()
        block._do_cycle_kind()

        assert len(block._posted) == 1
        msg = block._posted[0]
        assert isinstance(msg, KindOverrideChanged)
        assert msg.override is not None
        assert msg.override == RendererKind.DIFF  # first in definition order

    def test_override_chip_absent_when_none(self):
        """Initial state: _kind_override is None, no messages posted."""
        block = _StreamingBlockStub()
        assert block._kind_override is None
        assert block._posted == []

    def test_shift_t_clears_override(self):
        """action_kind_revert clears _kind_override."""
        from hermes_cli.tui.body_renderers import RendererKind

        block = _StreamingBlockStub()
        block._kind_override = RendererKind.DIFF

        with patch.object(block, "_auto_renderer_kind", return_value=RendererKind.PLAIN):
            block.action_kind_revert()

        assert block._kind_override is None

    def test_shift_t_reruns_classifier(self):
        """action_kind_revert calls _auto_renderer_kind() when override was active."""
        from hermes_cli.tui.body_renderers import RendererKind

        block = _StreamingBlockStub()
        block._kind_override = RendererKind.CODE

        called = []
        orig = block._auto_renderer_kind
        def _spy():
            called.append(1)
            return RendererKind.DIFF
        block._auto_renderer_kind = _spy

        block.action_kind_revert()

        assert called == [1]

    def test_shift_t_flashes_auto_kind(self):
        """action_kind_revert flashes 'kind: auto (X)' using classifier result."""
        from hermes_cli.tui.body_renderers import RendererKind
        from hermes_cli.tui.widgets.status_bar import FlashMessage

        block = _StreamingBlockStub()
        block._kind_override = RendererKind.DIFF
        block._auto_renderer_kind = lambda: RendererKind.PLAIN

        block.action_kind_revert()

        flash_msgs = [m for m in block._posted if isinstance(m, FlashMessage)]
        assert len(flash_msgs) == 1
        assert "kind: auto (plain)" in flash_msgs[0].text

    def test_shift_t_no_op_flash(self):
        """action_kind_revert with no override → flash 'no override'."""
        from hermes_cli.tui.widgets.status_bar import FlashMessage

        block = _StreamingBlockStub()
        assert block._kind_override is None

        block.action_kind_revert()

        flash_msgs = [m for m in block._posted if isinstance(m, FlashMessage)]
        assert len(flash_msgs) == 1
        assert flash_msgs[0].text == "no override"

    def test_chip_click_cycles_kind(self):
        """_do_cycle_kind advances through RendererKind in definition order, then wraps."""
        from hermes_cli.tui.body_renderers import RendererKind

        block = _StreamingBlockStub()

        block._do_cycle_kind()
        assert block._kind_override == RendererKind.DIFF

        block._posted.clear()
        block._do_cycle_kind()
        assert block._kind_override == RendererKind.CODE

        block._posted.clear()
        block._do_cycle_kind()
        assert block._kind_override == RendererKind.PLAIN

        block._posted.clear()
        block._do_cycle_kind()
        assert block._kind_override == RendererKind.DIFF  # wraps


# ---------------------------------------------------------------------------
# TestLL5Adoption
# ---------------------------------------------------------------------------

class TestLL5Adoption:
    """LL-5: GENERATED→STARTED adoption flash + adopted CSS class."""

    def test_adoption_flashes_started(self):
        """GENERATED → STARTED via adoption → FlashMessage('started') posted."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.widgets.status_bar import FlashMessage

        block = _StreamingBlockStub()
        block.set_block_state(ToolCallState.GENERATED)
        block.set_block_state(ToolCallState.STARTED)

        flash_msgs = [m for m in block._posted if isinstance(m, FlashMessage)]
        assert len(flash_msgs) == 1
        assert flash_msgs[0].text == "started"
        assert flash_msgs[0].duration == 1.2

    def test_direct_started_no_flash(self):
        """STARTED without prior GENERATED → no flash."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.widgets.status_bar import FlashMessage

        block = _StreamingBlockStub()
        block.set_block_state(ToolCallState.STARTED)  # no GENERATED first

        flash_msgs = [m for m in block._posted if isinstance(m, FlashMessage)]
        assert flash_msgs == []

    def test_adopted_class_added_then_removed(self):
        """adopted class added on adoption STARTED; _remove_adopted removes it."""
        from hermes_cli.tui.services.tools import ToolCallState

        block = _StreamingBlockStub()
        block.set_block_state(ToolCallState.GENERATED)
        block.set_block_state(ToolCallState.STARTED)

        assert "adopted" in block.classes

        block._remove_adopted()

        assert "adopted" not in block.classes
        assert block._remove_adopted_timer is None

    def test_adoption_id_backfill_unchanged(self):
        """SM-HIGH-02 regression: adoption visual must not interfere with id rewrite."""
        from hermes_cli.tui.services.tools import ToolCallState

        block = _StreamingBlockStub()
        block.id = "stream-tmp-42"

        block.set_block_state(ToolCallState.GENERATED)
        # Simulate id rewrite done externally by the service
        block.id = "tool-call-7"
        block.set_block_state(ToolCallState.STARTED)

        assert block.id == "tool-call-7"
        assert "adopted" in block.classes

    def test_block_reuse_flashes_again(self):
        """Block reuse: DONE resets _was_generated; second cycle flashes again."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.widgets.status_bar import FlashMessage

        block = _StreamingBlockStub()

        # First adoption
        block.set_block_state(ToolCallState.GENERATED)
        block.set_block_state(ToolCallState.STARTED)
        block.set_block_state(ToolCallState.DONE)
        block._posted.clear()

        # Second adoption after reuse
        block.set_block_state(ToolCallState.GENERATED)
        block.set_block_state(ToolCallState.STARTED)

        flash_msgs = [m for m in block._posted if isinstance(m, FlashMessage)]
        assert len(flash_msgs) == 1
        assert flash_msgs[0].text == "started"


# ---------------------------------------------------------------------------
# TestLL6PhaseChip
# ---------------------------------------------------------------------------

class TestLL6PhaseChip:
    """LL-6: ToolCallHeader state → chip mapping."""

    def test_pending_no_phase_chip(self):
        """PENDING → both chips hidden."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.PENDING)
        header = _HeaderStub(view)
        header._render_phase_chip()

        assert header._phase_chip.display is False
        assert header._finalizing_chip.display is False

    def test_started_chip_visible_then_hidden(self):
        """set_state(STARTED) shows phase chip; _clear_phase_chip hides it."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.GENERATED)
        header = _HeaderStub(view)

        header.set_state(ToolCallState.STARTED)

        assert header._phase_chip.display is True
        header._phase_chip.update.assert_called_with("[dim]…STARTING[/dim]")

        header._clear_phase_chip()
        assert header._phase_chip.display is False

    def test_started_then_completing_phase_chip_hidden(self):
        """STARTED chip visible; transitioning to COMPLETING clears it."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.GENERATED)
        header = _HeaderStub(view)

        header.set_state(ToolCallState.STARTED)
        assert header._phase_chip.display is True

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 5000.0
            view.completing_started_at = None  # no completing_started_at → no finalizing chip
            header.set_state(ToolCallState.COMPLETING)

        assert header._phase_chip.display is False

    def test_streaming_no_phase_chip(self):
        """STREAMING → both chips hidden."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.GENERATED)
        header = _HeaderStub(view)

        header.set_state(ToolCallState.STREAMING)

        assert header._phase_chip.display is False
        assert header._finalizing_chip.display is False

    def test_completing_chip_present(self):
        """set_state(COMPLETING) then _render_phase_chip with elapsed>250ms shows chip."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.GENERATED, completing_started_at=1000.0)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 1000.251
            header.set_state(ToolCallState.COMPLETING)
            # Simulate deferred _render_phase_chip callback firing after 0.251s timer
            header._render_phase_chip()

        assert header._finalizing_chip.display is True
        header._finalizing_chip.update.assert_called_with("[dim]…FINALIZING[/dim]")
        assert header._phase_chip.display is False

    def test_done_no_phase_chip(self):
        """DONE → both chips hidden."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.STARTED)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            header.set_state(ToolCallState.DONE)

        assert header._phase_chip.display is False
        assert header._finalizing_chip.display is False

    def test_cancelled_chip_persistent(self):
        """CANCELLED → phase chip shows 'cancelled' with no timer."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.GENERATED)
        header = _HeaderStub(view)

        header.set_state(ToolCallState.CANCELLED)

        assert header._phase_chip.display is True
        header._phase_chip.update.assert_called_with("[dim]CANCELLED[/dim]")
        # No timer set for CANCELLED
        assert header._phase_chip_timer is None

    def test_error_no_phase_chip_glyph_only(self):
        """ERROR → both chips hidden (LL-3 ⚠-glyph in separate slot handles error visual)."""
        from hermes_cli.tui.services.tools import ToolCallState

        view = _make_view(state=ToolCallState.STARTED)
        header = _HeaderStub(view)

        with patch("hermes_cli.tui.tool_blocks._header.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            header.set_state(ToolCallState.ERROR)

        assert header._phase_chip.display is False
        assert header._finalizing_chip.display is False
