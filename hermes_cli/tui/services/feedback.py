"""RX1 — FeedbackService: unified flash/feedback coordinator for Hermes TUI.

Replaces 7+ ad-hoc per-widget timer implementations with a single service that
owns scheduling, cancellation, priority, and lifecycle integration.

Public surface
--------------
- FeedbackService          — the service class; one instance on HermesApp.feedback
- FlashHandle              — opaque result of flash(); .displayed tells if applied
- FlashState               — data class describing an active flash
- ChannelAdapter           — protocol / base class for channel-specific paint logic
- Scheduler / CancelToken  — protocols; production wraps set_timer, tests use fake
- Priority constants       — LOW, NORMAL, WARN, ERROR, CRITICAL
- ExpireReason             — StrEnum: NATURAL, CANCELLED, PREEMPTED, UNMOUNTED, SUPPRESSED
- SettledAware             — runtime-checkable Protocol; widgets opt-in to settled-suppression

Internal (not exported)
-----------------------
- ChannelUnmountedError    — raised by adapters when widget is not mounted
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

LOW: int = 0
NORMAL: int = 10
WARN: int = 20
ERROR: int = 30
CRITICAL: int = 40


# ---------------------------------------------------------------------------
# ExpireReason
# ---------------------------------------------------------------------------


class ExpireReason(StrEnum):
    NATURAL = "natural"
    CANCELLED = "cancelled"
    PREEMPTED = "preempted"
    UNMOUNTED = "unmounted"
    SUPPRESSED = "suppressed"  # never displayed: channel is in a state that intentionally blocks motion


# Tones that encode state changes (not incidental motion). These flash even on
# settled widgets because they signal that something the user cares about just
# changed. Add a tone here only when its semantics match.
_STATE_CHANGE_TONES: frozenset[str] = frozenset({"focus", "err-enter"})


@runtime_checkable
class SettledAware(Protocol):
    """Widgets that opt in to settled-suppression implement is_settled().

    A True return value means the widget has finalised — incidental flashes on
    its channel are suppressed (returns FlashHandle(displayed=False) and fires
    on_expire(SUPPRESSED)). State-change tones in _STATE_CHANGE_TONES bypass
    this check.
    """

    def is_settled(self) -> bool: ...


def _widget_is_settled(widget: Any) -> bool:
    """Return True iff the widget structurally implements SettledAware and is settled."""
    if isinstance(widget, SettledAware):
        return widget.is_settled()
    return False


# ---------------------------------------------------------------------------
# Internal exception — NOT exported; only used inside this module
# ---------------------------------------------------------------------------


class ChannelUnmountedError(Exception):
    """Raised by a ChannelAdapter.apply() when the target widget is unmounted."""


# ---------------------------------------------------------------------------
# Scheduler / CancelToken protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class CancelToken(Protocol):
    def stop(self) -> None:
        ...


@runtime_checkable
class Scheduler(Protocol):
    def after(self, delay: float, cb: Callable[[], None]) -> CancelToken:
        ...


# ---------------------------------------------------------------------------
# Production Scheduler — wraps app.set_timer
# ---------------------------------------------------------------------------


class _TimerCancelToken:
    """Thin wrapper around a Textual Timer object."""

    def __init__(self, timer: Any) -> None:
        self._timer = timer

    def stop(self) -> None:
        try:
            self._timer.stop()
        except Exception:  # timer may already be expired/stopped — teardown swallow is correct
            pass


class AppScheduler:
    """Production Scheduler that delegates to app.set_timer."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def after(self, delay: float, cb: Callable[[], None]) -> CancelToken:
        timer = self._app.set_timer(delay, cb)
        return _TimerCancelToken(timer)


# ---------------------------------------------------------------------------
# ChannelAdapter base class
# ---------------------------------------------------------------------------


class ChannelAdapter:
    """Base class for channel-specific widget adapters.

    Subclasses implement apply() and restore(). Neither method owns a timer.
    apply() raises ChannelUnmountedError if the target widget is not mounted.
    restore() is a silent no-op on unmounted widgets.
    """

    @property
    def widget(self) -> "Any | None":
        """Return the target widget, or None to opt out of settled-suppression.

        A return value of None means the channel is global / app-level and is
        never blocked by settled state. Per-block adapters should return the
        block widget (or its closest SettledAware ancestor) so suppression can
        take effect once the block is finalised.
        """
        return None

    def apply(self, state: "FlashState") -> None:
        raise NotImplementedError

    def restore(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# FlashState
# ---------------------------------------------------------------------------


@dataclass
class FlashState:
    """Active flash record.  token is None between construction and scheduler call."""

    id: str
    channel: str
    message: str
    duration: float
    priority: int
    tone: str
    expires_at: float
    key: str | None
    on_expire: Callable[[ExpireReason], None] | None
    token: CancelToken | None = field(default=None)


# ---------------------------------------------------------------------------
# FlashHandle
# ---------------------------------------------------------------------------


class FlashHandle:
    """Opaque result of FeedbackService.flash().

    .displayed is True when the flash was applied to the channel.
    False means it was blocked by a strictly-higher-priority active flash, or
    suppressed by a settled-aware widget (see ExpireReason.SUPPRESSED).
    Holding this object does NOT extend the flash lifetime.
    """

    __slots__ = ("displayed",)

    def __init__(self, displayed: bool) -> None:
        self.displayed = displayed


# ---------------------------------------------------------------------------
# _ChannelRecord — internal registry entry
# ---------------------------------------------------------------------------


@dataclass
class _ChannelRecord:
    adapter: ChannelAdapter
    lifecycle_aware: bool = False


# ---------------------------------------------------------------------------
# FeedbackService
# ---------------------------------------------------------------------------


class FeedbackService:
    """Centralised flash / feedback coordinator.

    Construction
    ------------
    Instantiate on HermesApp with an AppScheduler (or FakeScheduler in tests).
    Register channel adapters before any flash calls on those channels.

    Thread safety
    -------------
    All public methods must be called from the Textual event loop.
    Thread-boundary code continues using call_from_thread to reach the
    event-loop-side wrappers (_flash_hint, etc.) which then call flash().
    """

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler
        self._channels: dict[str, _ChannelRecord] = {}
        self._active: dict[str, FlashState] = {}  # channel -> active FlashState
        self._counter: int = 0
        # FB-L1 re-entry guard: channel names mid-overwrite in register_channel.
        # flash() short-circuits when its target is in this set.
        self._registering: set[str] = set()

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register_channel(
        self,
        name: str,
        adapter: ChannelAdapter,
        *,
        lifecycle_aware: bool = False,
    ) -> None:
        """Register a channel adapter.

        lifecycle_aware=True marks this channel as participant in
        on_agent_idle / on_agent_active lifecycle events (e.g. hint-bar).

        FB-L1: re-registration warns at WARNING level and cancels any active
        flash on the OLD adapter (UNMOUNTED, no restore). Re-entrant flash()
        calls from the cancelled flash's on_expire callback are blocked via
        the _registering guard so the new adapter never receives a stray
        timer-driven restore() from a flash registered against the old adapter.
        """
        if name in self._channels:
            _previous = type(self._channels[name].adapter).__name__
            _incoming = type(adapter).__name__
            _log.warning(
                "FeedbackService: channel %r re-registered; previous=%s dropped, new=%s",
                name, _previous, _incoming,
            )
            self._registering.add(name)
            try:
                if name in self._active:
                    self._cancel_flash_internal(
                        name, self._active[name], ExpireReason.UNMOUNTED,
                    )
                self._channels[name] = _ChannelRecord(
                    adapter=adapter, lifecycle_aware=lifecycle_aware,
                )
            finally:
                self._registering.discard(name)
        else:
            self._channels[name] = _ChannelRecord(
                adapter=adapter, lifecycle_aware=lifecycle_aware,
            )

    def deregister_channel(self, name: str) -> None:
        """Deregister a channel, cancelling any active flash with reason UNMOUNTED.

        Safe to call from on_unmount hooks; adapter is removed from registry
        so stale widget references don't accumulate.
        """
        if name in self._active:
            state = self._active[name]
            if state.token is not None:
                state.token.stop()
            # fire callback but do NOT call adapter.restore() — widget is gone
            if state.on_expire is not None:
                try:
                    state.on_expire(ExpireReason.UNMOUNTED)
                except Exception:  # user-supplied callback must not crash the service
                    _log.debug("on_expire callback raised during deregister", exc_info=True)
            del self._active[name]
        self._channels.pop(name, None)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def flash(
        self,
        channel: str,
        message: str,
        *,
        duration: float = 2.0,
        priority: int = NORMAL,
        tone: str = "info",
        on_expire: Callable[[ExpireReason], None] | None = None,
        key: str | None = None,
    ) -> FlashHandle:
        """Display a flash message on the named channel.

        Returns FlashHandle with .displayed=True if applied, False if blocked
        or suppressed.
        Raises KeyError if channel is not registered.

        Convention: called from the event loop only — workers should marshal via
        App.call_from_thread. The settled-suppression check and preemption-lock
        sequence rely on this single-threaded convention; multi-threaded use is
        undefined behavior and would need an explicit contract bump.
        """
        if channel not in self._channels:
            raise KeyError(f"FeedbackService: channel {channel!r} not registered")

        # FB-L1: re-entry guard. A flash() call from inside an on_expire callback
        # that fired during register_channel's mid-swap window would otherwise
        # land in _active against the OLD adapter; the new adapter would later
        # receive its timer-driven restore(). Block and warn instead.
        if channel in self._registering:
            _log.warning(
                "flash() ignored during register_channel re-entry on %r", channel,
            )
            return FlashHandle(displayed=False)

        # FS-3: settled suppression — incidental flashes blocked on settled-aware
        # widgets; tones in _STATE_CHANGE_TONES are always exempt (they encode
        # state changes, not motion).
        _settled_tone_exempt = tone in _STATE_CHANGE_TONES
        if not _settled_tone_exempt:
            _record = self._channels[channel]
            _widget = _record.adapter.widget
            if _widget is not None and _widget_is_settled(_widget):
                _log.debug("flash suppressed: channel=%r settled block", channel)
                if on_expire is not None:
                    try:
                        on_expire(ExpireReason.SUPPRESSED)
                    except Exception:  # user-supplied callback must not crash flash()
                        _log.debug("on_expire raised on SUPPRESSED", exc_info=True)
                return FlashHandle(displayed=False)

        record = self._channels[channel]
        adapter = record.adapter

        # --- Preemption logic ---
        # Branch precedence: key match short-circuits before priority compare.
        # Equal-or-higher priority preempts; strictly-lower is blocked.
        if channel in self._active:
            existing = self._active[channel]
            if key is not None and existing.key == key:
                self._cancel_flash_internal(channel, existing, ExpireReason.PREEMPTED)
            elif priority >= existing.priority:
                self._cancel_flash_internal(channel, existing, ExpireReason.PREEMPTED)
            else:
                _log.debug(
                    "flash preempted: incoming=%r (p=%s) blocked by current=%r (p=%s)",
                    message, priority,
                    existing.message, existing.priority,
                )
                return FlashHandle(displayed=False)

        # --- Create new state ---
        self._counter += 1
        state = FlashState(
            id=str(self._counter),
            channel=channel,
            message=message,
            duration=duration,
            priority=priority,
            tone=tone,
            expires_at=time.monotonic() + duration,
            key=key,
            on_expire=on_expire,
            token=None,
        )

        # --- Apply to widget ---
        try:
            adapter.apply(state)
        except ChannelUnmountedError:
            try:
                adapter.restore()
            except Exception:  # widget already gone (ChannelUnmountedError just fired);
                # restore() failure here is teardown-tier per global rule — debug is correct.
                _log.debug("post-preempt restore failed for %r", channel, exc_info=True)
            if on_expire is not None:
                try:
                    on_expire(ExpireReason.UNMOUNTED)
                except Exception:  # user-supplied callback must not crash flash()
                    _log.debug("on_expire callback raised on ChannelUnmountedError", exc_info=True)
            return FlashHandle(displayed=False)
        except Exception:
            # Generic-Exception branch (FB-M1): log full traceback (user-visible
            # "see log for details" is now backed by an actual ERROR-level entry).
            _log.exception("adapter.apply() failed for channel %r", channel)
            try:
                adapter.restore()
            except Exception:  # restore is best-effort after a broken apply()
                _log.debug("restore after apply failure raised for %r", channel, exc_info=True)
            if on_expire is not None:
                try:
                    on_expire(ExpireReason.UNMOUNTED)
                except Exception:  # user-supplied callback must not crash flash()
                    _log.debug("on_expire callback raised after apply failure", exc_info=True)
            return FlashHandle(displayed=False)

        # --- Schedule expiry ---
        flash_id = state.id

        def _expire_cb() -> None:
            self._on_expire(flash_id)

        token = self._scheduler.after(duration, _expire_cb)
        state.token = token
        self._active[channel] = state

        return FlashHandle(displayed=True)

    def cancel(self, channel: str, key: str | None = None) -> bool:
        """Cancel the active flash on a channel.

        If key is given, only cancels if the active flash matches that key.
        Returns True if a flash was cancelled, False otherwise.
        """
        if channel not in self._active:
            return False
        state = self._active[channel]
        if key is not None and state.key != key:
            return False
        self._cancel_flash_internal(channel, state, ExpireReason.CANCELLED)
        return True

    def cancel_all(self, channel: str | None = None) -> int:
        """Cancel all active flashes, optionally filtered to one channel.

        Returns count of cancelled flashes.
        """
        if channel is not None:
            if self.cancel(channel):
                return 1
            return 0

        channels = list(self._active.keys())
        count = 0
        for ch in channels:
            if ch in self._active:
                state = self._active[ch]
                self._cancel_flash_internal(ch, state, ExpireReason.CANCELLED)
                count += 1
        return count

    def peek(self, channel: str) -> FlashState | None:
        """Return the active FlashState for a channel, or None."""
        return self._active.get(channel)

    def would_flash(self, channel: str, priority: int) -> bool:
        """Return True if flash(channel, priority=priority) would be applied (not blocked).

        Equal-priority returns True (incoming would preempt).
        Raises KeyError if the channel is not registered (same contract as flash()).
        """
        if channel not in self._channels:
            raise KeyError(f"FeedbackService: channel {channel!r} not registered")
        if channel not in self._active:
            return True
        existing = self._active[channel]
        return priority >= existing.priority

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_agent_idle(self) -> None:
        """Called when agent transitions to idle.

        For lifecycle-aware channels: if no flash is active, calls adapter.restore()
        to set the resting state. If a flash is active, leaves it untouched (fixes E3).
        """
        for name, record in self._channels.items():
            if not record.lifecycle_aware:
                continue
            if name in self._active:
                continue  # active flash — leave it alone
            try:
                record.adapter.restore()
            except Exception:  # adapter.restore() is best-effort; widget may be unmounted
                _log.debug("on_agent_idle: adapter.restore() failed for %r", name, exc_info=True)

    def on_agent_active(self) -> None:
        """Called when agent transitions to active. No-op for flash state."""
        pass

    def on_turn_start(self) -> None:
        """Called at the start of each turn. No-op for flash state."""
        pass

    def on_session_switch(self) -> None:
        """Called on session switch. No-op for flash state."""
        pass

    def shutdown(self) -> None:
        """Stop all timers. Does NOT call adapter.restore() (widgets may be gone)."""
        channels = list(self._active.keys())
        for channel in channels:
            if channel in self._active:
                state = self._active[channel]
                if state.token is not None:
                    state.token.stop()
                if state.on_expire is not None:
                    try:
                        state.on_expire(ExpireReason.UNMOUNTED)
                    except Exception:  # user-supplied callback must not crash shutdown
                        _log.debug("on_expire callback raised during shutdown", exc_info=True)
        self._active.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel_flash_internal(
        self,
        channel: str,
        state: FlashState,
        reason: ExpireReason,
    ) -> None:
        """Cancel a flash: stop timer, fire on_expire, drop from active.

        Does NOT call adapter.restore() for PREEMPTED/UNMOUNTED.
        For CANCELLED, restore IS called (explicit user cancel = hide flash).
        """
        if state.token is not None:
            state.token.stop()
        if reason == ExpireReason.CANCELLED:
            # Explicit cancel: restore widget to resting state
            record = self._channels.get(channel)
            if record is not None:
                try:
                    record.adapter.restore()
                except Exception:  # widget may be unmounted during cancel — best-effort
                    _log.debug("_cancel_flash_internal: restore() failed for %r", channel, exc_info=True)
        if state.on_expire is not None:
            try:
                state.on_expire(reason)
            except Exception:  # user-supplied callback must not crash the service
                _log.debug("on_expire callback raised for channel %r", channel, exc_info=True)
        self._active.pop(channel, None)

    def _on_expire(self, flash_id: str) -> None:
        """Timer callback — called when a flash expires naturally."""
        # Find state by id
        channel = None
        state = None
        for ch, st in self._active.items():
            if st.id == flash_id:
                channel = ch
                state = st
                break
        if channel is None or state is None:
            return  # already cancelled (I2)

        record = self._channels.get(channel)
        if record is not None:
            try:
                record.adapter.restore()
            except Exception:  # widget may be unmounted on natural expiry — best-effort
                _log.debug("_on_expire: restore() failed for %r", channel, exc_info=True)

        if state.on_expire is not None:
            try:
                state.on_expire(ExpireReason.NATURAL)
            except Exception:  # user-supplied callback must not crash the service
                _log.debug("on_expire callback raised on natural expiry for %r", channel, exc_info=True)

        self._active.pop(channel, None)


# ---------------------------------------------------------------------------
# Concrete adapters (Phase A — created here; registered in Phase B)
# ---------------------------------------------------------------------------


class HintBarAdapter(ChannelAdapter):
    """Adapter for the HintBar widget (app-level, query by type)."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def _get_bar(self) -> Any:
        # FB-M1 companion: narrow to NoMatches only. Render errors / AttributeError
        # propagate so the generic-Exception branch in flash() can ERROR-log them
        # with full traceback instead of masking as cheap UNMOUNTED.
        from textual.css.query import NoMatches
        from hermes_cli.tui.widgets import HintBar
        try:
            bar = self._app.query_one(HintBar)
        except NoMatches as exc:
            raise ChannelUnmountedError("HintBar not found") from exc
        if not bar.is_mounted:
            raise ChannelUnmountedError("HintBar not mounted")
        return bar

    def apply(self, state: FlashState) -> None:
        bar = self._get_bar()
        bar.hint = state.message

    def restore(self) -> None:
        try:
            bar = self._get_bar()
            bar.hint = ""
        except ChannelUnmountedError:
            pass  # HintBar not mounted — teardown swallow is correct
        except Exception:  # unexpected error restoring hint bar — log but don't crash
            _log.debug("HintBarAdapter.restore() failed", exc_info=True)


class ToolHeaderAdapter(ChannelAdapter):
    """Adapter for ToolHeader._flash_msg / _flash_tone (per-block)."""

    def __init__(self, header: Any) -> None:
        self._header = header

    @property
    def widget(self) -> "Any":
        return self._header

    def apply(self, state: FlashState) -> None:
        hdr = self._header
        if not getattr(hdr, "is_mounted", False):
            raise ChannelUnmountedError("ToolHeader not mounted")
        hdr._flash_msg = state.message
        hdr._flash_tone = state.tone
        hdr._flash_expires = state.expires_at
        hdr.refresh()

    def restore(self) -> None:
        hdr = self._header
        if not getattr(hdr, "is_mounted", False):
            return
        try:
            hdr._flash_msg = None
            hdr.refresh()
        except Exception:  # ToolHeader may be unmounted between is_mounted check and refresh
            _log.debug("ToolHeaderAdapter.restore() failed", exc_info=True)


class CodeFooterAdapter(ChannelAdapter):
    """Adapter for CodeBlockFooter copy-label flash (per-block).

    widget resolves to the footer's closest SettledAware ancestor (today only
    StreamingToolBlock, but defined by the protocol — not pinned to that class)
    so footers participate in settled-suppression once their parent block is
    finalised. CodeBlockFooter itself does not implement SettledAware, so
    returning the footer directly would be a no-op against that goal.
    """

    def __init__(self, footer: Any) -> None:
        self._footer = footer
        self._settled_ancestor: Any | None = None

    @property
    def widget(self) -> "Any | None":
        # Cache invariant: an adapter is constructed per-footer; the footer is
        # owned by exactly one StreamingToolBlock for its lifetime. The retry
        # path in _streaming.py:805,808 calls _clear_settled() on the same
        # block — it never replaces the block — so the cached ancestor stays
        # valid. None results are NOT cached: pre-mount ancestors_with_self
        # returns []; the next call (post-mount) must walk again.
        if self._settled_ancestor is not None:
            return self._settled_ancestor
        for node in self._footer.ancestors_with_self:
            if isinstance(node, SettledAware):
                self._settled_ancestor = node
                return node
        return None

    def clear_cache(self) -> None:
        """Defensive cache reset — call from CodeBlockFooter.on_unmount.

        Reparenting is not a documented use case in the current code, but
        nothing in the type system prevents it; if it ever happens, the cache
        would otherwise hold a stale reference.
        """
        self._settled_ancestor = None

    def apply(self, state: FlashState) -> None:
        footer = self._footer
        if not getattr(footer, "is_mounted", False):
            raise ChannelUnmountedError("CodeBlockFooter not mounted")
        footer._copy.update(state.message)
        footer.add_class("--flash-copy")

    def restore(self) -> None:
        footer = self._footer
        if not getattr(footer, "is_mounted", False):
            return
        try:
            footer.remove_class("--flash-copy")
            footer._copy.update(footer._copy_original)
        except Exception:  # footer may be unmounted between is_mounted check and update
            _log.debug("CodeFooterAdapter.restore() failed", exc_info=True)
