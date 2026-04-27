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
- ExpireReason             — StrEnum: NATURAL, CANCELLED, PREEMPTED, UNMOUNTED

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
        except Exception:  # noqa: bare-except
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
        """Return the target widget for this adapter, or None if not applicable."""
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
    False means it was blocked by a higher-priority active flash.
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
        """
        self._channels[name] = _ChannelRecord(adapter=adapter, lifecycle_aware=lifecycle_aware)

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
                except Exception:  # noqa: bare-except
                    pass
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

        Returns FlashHandle with .displayed=True if applied, False if blocked.
        Raises KeyError if channel is not registered.
        """
        if channel not in self._channels:
            raise KeyError(f"FeedbackService: channel {channel!r} not registered")

        # FS-3: settled suppression — incidental flashes blocked on completed blocks;
        # focus and err-enter tones are always exempt (they encode state changes, not motion).
        _settled_tone_exempt = tone in ("focus", "err-enter")
        if not _settled_tone_exempt:
            _record = self._channels[channel]
            _widget = _record.adapter.widget
            if _widget is not None and getattr(_widget, "_settled", False):
                _log.debug("flash suppressed: channel=%r settled block", channel)
                return FlashHandle(displayed=False)

        record = self._channels[channel]
        adapter = record.adapter

        # --- Preemption logic ---
        if channel in self._active:
            existing = self._active[channel]
            # key= match always replaces, regardless of priority
            if key is not None and existing.key == key:
                self._cancel_flash_internal(channel, existing, ExpireReason.PREEMPTED)
            elif priority > existing.priority:
                # Higher priority preempts
                self._cancel_flash_internal(channel, existing, ExpireReason.PREEMPTED)
            elif priority == existing.priority:
                # Equal priority replaces (last-write-wins), no on_expire fired
                self._stop_flash_internal(channel, existing)
            else:
                # Lower priority — blocked
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
            if on_expire is not None:
                try:
                    on_expire(ExpireReason.UNMOUNTED)
                except Exception:  # noqa: bare-except
                    pass
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
            except Exception:  # noqa: bare-except
                pass

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
                    except Exception:  # noqa: bare-except
                        pass
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
                except Exception:  # noqa: bare-except
                    pass
        if state.on_expire is not None:
            try:
                state.on_expire(reason)
            except Exception:  # noqa: bare-except
                pass
        self._active.pop(channel, None)

    def _stop_flash_internal(self, channel: str, state: FlashState) -> None:
        """Stop a flash without firing on_expire (equal-priority replace)."""
        if state.token is not None:
            state.token.stop()
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
            except Exception:  # noqa: bare-except
                pass

        if state.on_expire is not None:
            try:
                state.on_expire(ExpireReason.NATURAL)
            except Exception:  # noqa: bare-except
                pass

        self._active.pop(channel, None)


# ---------------------------------------------------------------------------
# Concrete adapters (Phase A — created here; registered in Phase B)
# ---------------------------------------------------------------------------


class HintBarAdapter(ChannelAdapter):
    """Adapter for the HintBar widget (app-level, query by type)."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def _get_bar(self) -> Any:
        from hermes_cli.tui.widgets import HintBar
        try:
            bar = self._app.query_one(HintBar)
            if not bar.is_mounted:
                raise ChannelUnmountedError("HintBar not mounted")
            return bar
        except Exception as exc:
            if isinstance(exc, ChannelUnmountedError):
                raise
            raise ChannelUnmountedError("HintBar not found") from exc

    def apply(self, state: FlashState) -> None:
        bar = self._get_bar()
        bar.hint = state.message

    def restore(self) -> None:
        try:
            bar = self._get_bar()
            bar.hint = ""
        except ChannelUnmountedError:
            pass
        except Exception:  # noqa: bare-except
            pass


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
        except Exception:  # noqa: bare-except
            pass


class CodeFooterAdapter(ChannelAdapter):
    """Adapter for CodeBlockFooter copy-label flash (per-block)."""

    def __init__(self, footer: Any) -> None:
        self._footer = footer

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
        except Exception:  # noqa: bare-except
            pass
