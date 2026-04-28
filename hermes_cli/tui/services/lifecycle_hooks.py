"""Agent-state lifecycle hook registry (RX4).

Fires transition callbacks in priority order, error-isolated.

Transition names:
  on_turn_start        — agent_running False→True
  on_turn_end_any      — agent_running True→False (always)
  on_turn_end_success  — turn end with no error
  on_turn_end_error    — turn end with error set
  on_interrupt         — turn end caused by user interrupt (ESC/resubmit)
  on_compact_start     — /compact dispatched
  on_compact_complete  — compaction finishes
  on_streaming_start   — first token of assistant response
  on_streaming_end     — last token of assistant message
  on_error_set         — status_error "" → non-empty
  on_error_clear       — status_error non-empty → ""
  on_session_switch    — session_label changes
  on_session_resume    — session loads on startup/resume

Priority ranges (lower = earlier):
  10   — terminal state (OSC progress, desktop notify scheduling)
  50   — buffer flush (flush_live, evict_old_turns)
  100  — default / generic cleanups
  500  — visual chrome (chevron pulses, hint phase)
  900  — input refocus / placeholder restore (runs last)
"""
from __future__ import annotations

import logging
import weakref
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

_log = logging.getLogger(__name__)


@dataclass
class RegistrationHandle:
    """Opaque handle returned by register(); pass to unregister()."""
    _transition: str
    _id: int


@dataclass(order=True)
class _Registration:
    priority: int
    reg_order: int
    name: str
    _cb_ref: Any = field(compare=False)  # weakref.WeakMethod or direct callable
    _owner_id: int | None = field(compare=False)


class AgentLifecycleHooks:
    """Registry of transition→callback mappings for agent lifecycle events."""

    def __init__(self, app: "HermesApp | None" = None) -> None:
        self._app = app
        self._registrations: dict[str, list[_Registration]] = {}
        self._reg_counter: int = 0
        self._deferred: deque[tuple[str, dict[str, Any]]] = deque()
        self._firing: set[str] = set()  # reentrancy guard — snapshot on entry
        self._shutdown: bool = False

    def register(
        self,
        transition: str,
        callback: Callable[..., None],
        *,
        owner: object | None = None,
        priority: int = 100,
        name: str | None = None,
    ) -> RegistrationHandle:
        """Register *callback* to fire when *transition* occurs."""
        # Use WeakMethod for bound methods to avoid keeping owner alive
        if hasattr(callback, "__self__"):
            cb_ref = weakref.WeakMethod(callback)
        else:
            cb_ref = callback  # plain function — no weak ref needed

        owner_id = id(owner) if owner is not None else None
        n = name or getattr(callback, "__name__", repr(callback))
        self._reg_counter += 1
        reg = _Registration(
            priority=priority,
            reg_order=self._reg_counter,
            name=n,
            _cb_ref=cb_ref,
            _owner_id=owner_id,
        )
        self._registrations.setdefault(transition, []).append(reg)
        self._registrations[transition].sort()
        return RegistrationHandle(_transition=transition, _id=self._reg_counter)

    def unregister(self, handle: RegistrationHandle) -> None:
        """Remove the registration identified by *handle*."""
        bucket = self._registrations.get(handle._transition, [])
        self._registrations[handle._transition] = [
            r for r in bucket if r.reg_order != handle._id
        ]

    def unregister_owner(self, owner: object) -> None:
        """Remove all registrations whose owner is *owner*."""
        oid = id(owner)
        for transition in list(self._registrations):
            self._registrations[transition] = [
                r for r in self._registrations[transition] if r._owner_id != oid
            ]

    def fire(self, transition: str, **ctx: Any) -> None:
        """Fire all callbacks registered for *transition* in priority order."""
        if self._shutdown:
            return
        app = self._app
        if app is not None and not getattr(app, "is_running", True):
            self._deferred.append((transition, ctx))
            return

        # Snapshot current registrations to handle mutations during fire
        bucket = list(self._registrations.get(transition, []))
        for reg in bucket:
            cb_ref = reg._cb_ref
            # Resolve weak ref
            if isinstance(cb_ref, weakref.WeakMethod):
                cb = cb_ref()
                if cb is None:
                    # Owner GC'd — prune
                    self._registrations[transition] = [
                        r for r in self._registrations[transition] if r is not reg
                    ]
                    continue
            else:
                cb = cb_ref
            try:
                cb(**ctx)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as exc:
                msg = "AgentLifecycleHooks: %s/%s raised %r"
                args = (transition, reg.name, exc)
                if app is not None:
                    try:
                        app.log.error(msg, *args, exc_info=True)
                    except Exception:
                        _log.error(msg, *args, exc_info=True)
                else:
                    _log.error(msg, *args, exc_info=True)

    def drain_deferred(self) -> None:
        """Call from app.on_mount() to fire events queued before is_running."""
        while self._deferred:
            transition, ctx = self._deferred.popleft()
            self.fire(transition, **ctx)

    def shutdown(self) -> None:
        """Called from app.on_unmount(). Prevents further firing."""
        self._shutdown = True
        self._registrations.clear()
        self._deferred.clear()

    def snapshot(self) -> dict[str, list[str]]:
        """Debug introspection: transition → list of registration names."""
        return {t: [r.name for r in regs] for t, regs in self._registrations.items() if regs}
