"""ManagedTimerMixin — lifecycle-safe timer and pacer tracking for Textual widgets.

All registered timers and pacers are stopped atomically on _stop_all_managed() or
on_unmount. Already-stopped entries are skipped (idempotent). Callers that stop a
timer early (e.g. in complete()) should call _stop_all_managed() so the mixin
marks entries as stopped and skips them on unmount.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


class ManagedTimerMixin:
    """Tracks every timer/pacer the widget owns; on_unmount stops them all.

    Usage::

        class MyWidget(ManagedTimerMixin, Widget):
            def on_mount(self):
                self._t = self._register_timer(self.set_interval(0.1, self._tick))
                self._p = self._register_pacer(CharacterPacer(...))

            def on_unmount(self):
                # Extra cleanup first if needed, then chain:
                super().on_unmount()
    """

    def _register_timer(self, timer: object) -> object:
        """Register *timer* and return it so ``self.t = self._register_timer(...)`` works."""
        if not hasattr(self, "_managed_timers"):
            self._managed_timers: list[dict] = []
        self._managed_timers.append({"timer": timer, "stopped": False})
        return timer

    def _register_pacer(self, pacer: object) -> object:
        """Register *pacer* and return it so ``self.p = self._register_pacer(...)`` works."""
        if not hasattr(self, "_managed_pacers"):
            self._managed_pacers: list[dict] = []
        self._managed_pacers.append({"pacer": pacer, "stopped": False})
        return pacer

    def _stop_all_managed(self) -> None:
        """Stop all registered timers and pacers; mark each stopped=True (idempotent)."""
        for entry in getattr(self, "_managed_timers", []):
            if not entry["stopped"]:
                try:
                    entry["timer"].stop()
                    entry["stopped"] = True
                except Exception:
                    _log.debug("managed timer stop failed", exc_info=True)
        for entry in getattr(self, "_managed_pacers", []):
            if not entry["stopped"]:
                try:
                    entry["pacer"].stop()
                    entry["stopped"] = True
                except Exception:
                    _log.debug("managed pacer stop failed", exc_info=True)
        self._managed_timers = []
        self._managed_pacers = []

    def on_unmount(self) -> None:  # type: ignore[override]
        """Stop all managed resources, then chain to the next on_unmount in MRO."""
        self._stop_all_managed()
        parent_fn = getattr(super(), "on_unmount", None)
        if callable(parent_fn):
            parent_fn()
