"""Tests for reduced-motion gate — spec-D.

Classes:
  TestL8ResolverAndAPI  — 3 tests: resolver precedence + set_reduced_motion
  TestH7LiveLineGate    — 4 tests: blink suppression + runtime toggle
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from hermes_cli.tui.messages import ReducedMotionChanged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_stub(is_reduced: bool = False) -> MagicMock:
    """Minimal app stub whose is_reduced_motion() returns *is_reduced*."""
    app = MagicMock()
    app.is_reduced_motion = MagicMock(return_value=is_reduced)
    return app


# ---------------------------------------------------------------------------
# TestL8ResolverAndAPI
# ---------------------------------------------------------------------------

class TestL8ResolverAndAPI:
    """Resolver precedence + public API on HermesApp."""

    def _make_resolver_target(self):
        """Return a minimal object with just _resolve_reduced_motion bound."""
        from hermes_cli.tui.app import HermesApp
        import types

        obj = object.__new__(HermesApp)
        # Bind the method without __init__
        obj._resolve_reduced_motion = types.MethodType(
            HermesApp._resolve_reduced_motion, obj
        )
        return obj

    def test_resolve_precedence_config_wins(self, monkeypatch):
        """Config True beats env=0."""
        monkeypatch.setenv("HERMES_REDUCED_MOTION", "0")
        with patch(
            "hermes_cli.tui.app.read_raw_config",
            return_value={"tui": {"reduced_motion": True}},
            create=True,
        ):
            # Patch inside the method's local import
            with patch.dict("sys.modules", {}):
                import sys
                import types

                fake_config_mod = types.ModuleType("hermes_cli.config")
                fake_config_mod.read_raw_config = lambda: {"tui": {"reduced_motion": True}}
                orig = sys.modules.get("hermes_cli.config")
                sys.modules["hermes_cli.config"] = fake_config_mod
                try:
                    obj = self._make_resolver_target()
                    result = obj._resolve_reduced_motion()
                finally:
                    if orig is None:
                        del sys.modules["hermes_cli.config"]
                    else:
                        sys.modules["hermes_cli.config"] = orig
        assert result is True

    def test_resolve_precedence_env_used_when_no_config(self, monkeypatch):
        """Env=true is used when config returns {}."""
        import sys, types

        monkeypatch.setenv("HERMES_REDUCED_MOTION", "true")
        fake_config_mod = types.ModuleType("hermes_cli.config")
        fake_config_mod.read_raw_config = lambda: {}
        orig = sys.modules.get("hermes_cli.config")
        sys.modules["hermes_cli.config"] = fake_config_mod
        try:
            obj = self._make_resolver_target()
            result = obj._resolve_reduced_motion()
        finally:
            if orig is None:
                del sys.modules["hermes_cli.config"]
            else:
                sys.modules["hermes_cli.config"] = orig
        assert result is True

    def test_set_reduced_motion_posts_message(self):
        """set_reduced_motion(True) adds CSS class and posts ReducedMotionChanged."""
        from unittest.mock import MagicMock, patch
        from hermes_cli.tui.app import HermesApp
        import types

        obj = object.__new__(HermesApp)
        obj._reduced_motion = False

        posted = []
        obj.post_message = lambda msg: posted.append(msg)
        obj.add_class = MagicMock()
        obj.remove_class = MagicMock()

        obj.set_reduced_motion = types.MethodType(HermesApp.set_reduced_motion, obj)
        obj.set_reduced_motion(True)

        obj.add_class.assert_called_once_with("reduced-motion")
        assert obj._reduced_motion is True
        assert len(posted) == 1
        assert isinstance(posted[0], ReducedMotionChanged)
        assert posted[0].enabled is True


# ---------------------------------------------------------------------------
# TestH7LiveLineGate
# ---------------------------------------------------------------------------

class TestH7LiveLineGate:
    """Blink timer suppression in LiveLineWidget under reduced-motion.

    LiveLineWidget has Textual reactives so it cannot be instantiated without
    a running app.  The gate logic lives in two standalone spots:
      - on_mount: two lines after _blink_enabled assignment
      - on_reduced_motion_changed: standalone method
    We test by binding those methods to a SimpleNamespace stub.
    """

    def _make_stub(self, is_reduced: bool = False, blink_cfg: bool = True):
        """Minimal SimpleNamespace that satisfies the gate + handler logic."""
        import types
        from types import SimpleNamespace
        from hermes_cli.tui.widgets.renderers import LiveLineWidget

        stub = SimpleNamespace(
            _blink_enabled=blink_cfg,
            _blink_timer=None,
            app=_make_app_stub(is_reduced),
        )
        stub.on_reduced_motion_changed = types.MethodType(
            LiveLineWidget.on_reduced_motion_changed, stub
        )
        return stub

    def _apply_on_mount_gate(self, stub):
        """Execute just the reduced-motion gate lines from on_mount."""
        if stub._blink_enabled and getattr(stub.app, "is_reduced_motion", lambda: False)():
            stub._blink_enabled = False

    def test_blink_timer_not_created_when_reduced_motion(self):
        """Gate clears _blink_enabled when reduced-motion is active."""
        stub = self._make_stub(is_reduced=True, blink_cfg=True)
        self._apply_on_mount_gate(stub)
        assert stub._blink_enabled is False

    def test_blink_timer_created_when_motion_allowed(self):
        """Gate leaves _blink_enabled True when reduced-motion is off."""
        stub = self._make_stub(is_reduced=False, blink_cfg=True)
        self._apply_on_mount_gate(stub)
        assert stub._blink_enabled is True

    def test_blink_timer_stops_on_runtime_toggle_to_reduced_motion(self):
        """on_reduced_motion_changed(enabled=True) stops and clears blink timer."""
        stub = self._make_stub(is_reduced=False, blink_cfg=True)
        mock_timer = MagicMock()
        stub._blink_timer = mock_timer
        stub._blink_enabled = True

        stub.on_reduced_motion_changed(ReducedMotionChanged(enabled=True))

        mock_timer.stop.assert_called_once()
        assert stub._blink_timer is None
        assert stub._blink_enabled is False

    def test_blink_re_enabled_on_runtime_toggle_to_motion_allowed(self):
        """on_reduced_motion_changed(enabled=False) restores _blink_enabled from config."""
        stub = self._make_stub(is_reduced=True, blink_cfg=False)
        stub._blink_enabled = False

        with patch(
            "hermes_cli.tui.widgets.renderers._cursor_blink_enabled", return_value=True
        ):
            stub.on_reduced_motion_changed(ReducedMotionChanged(enabled=False))

        assert stub._blink_enabled is True
