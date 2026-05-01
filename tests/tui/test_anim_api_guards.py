"""ANIM-API: API correctness, defensive guards, and command path coverage.

TestAnimAPI1AmbientCommand  — 3 tests (M-1)
TestAnimAPI2TorusLUT        — 2 tests (L-4)
TestAnimAPI3CycleGuard      — 2 tests (L-5)
TestAnimAPI6CommandPaths    — 1 test  (coverage gap)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
from textual.css.query import NoMatches

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_service(app=None):
    """Build a CommandsService backed by a mock app."""
    from hermes_cli.tui.services.commands import CommandsService
    mock_app = app or MagicMock()
    svc = CommandsService.__new__(CommandsService)
    svc.app = mock_app
    return svc, mock_app


# ── ANIM-API-1: /anim ambient routes through orchestrator ─────────────────────

class TestAnimAPI1AmbientCommand:

    def test_anim_ambient_command_uses_orchestrator(self):
        svc, app = _make_service()
        ov = MagicMock()
        ov._visibility_state = "ambient"
        app.query_one.return_value = ov

        svc.persist_anim_config = MagicMock()
        app._flash_hint = MagicMock()

        svc.handle_anim_command("/anim ambient plasma")

        ov._orchestrator.set_ambient_engine.assert_called_once_with("plasma")

    def test_anim_ambient_command_overlay_not_mounted(self):
        svc, app = _make_service()
        app.query_one.side_effect = NoMatches()

        svc.persist_anim_config = MagicMock()
        app._flash_hint = MagicMock()

        svc.handle_anim_command("/anim ambient plasma")

        svc.persist_anim_config.assert_called_once()
        call_kwargs = svc.persist_anim_config.call_args[0][0]
        assert call_kwargs["ambient_engine"] == "plasma"
        assert call_kwargs["ambient_enabled"] is True

    def test_anim_ambient_command_does_not_mutate_instance_directly(self):
        svc, app = _make_service()
        ov = MagicMock()
        ov._visibility_state = "ambient"
        app.query_one.return_value = ov

        svc.persist_anim_config = MagicMock()
        app._flash_hint = MagicMock()

        svc.handle_anim_command("/anim ambient plasma")

        # orchestrator API used, not direct attribute assignment
        ov._orchestrator.set_ambient_engine.assert_called_once()
        # _current_engine_instance must NOT have been set directly
        assert "_current_engine_instance" not in ov.__dict__


# ── ANIM-API-2: Torus3DEngine LUT length guards ───────────────────────────────

class TestAnimAPI2TorusLUT:

    def test_torus3d_lut_lengths_match_class_attrs(self):
        from hermes_cli.tui.anim_engines import Torus3DEngine
        e = Torus3DEngine()
        assert len(e._THETA_LUT) == e.N_U
        assert len(e._PHI_LUT) == e.N_V

    def test_torus3d_lut_mismatch_raises_assertion(self):
        from hermes_cli.tui.anim_engines import Torus3DEngine

        class BadTorus(Torus3DEngine):
            N_U = 99  # mismatch: _THETA_LUT still has 20 entries

        with pytest.raises(AssertionError, match="N_U"):
            BadTorus()


# ── ANIM-API-3: _cycle guard against ValueError ───────────────────────────────

class TestAnimAPI3CycleGuard:

    def _make_panel_stub(self, value: str, choices: list[str]) -> object:
        from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel, _PanelField

        panel = AnimConfigPanel.__new__(AnimConfigPanel)
        panel._focus_idx = 0
        field = _PanelField(
            name="test",
            label="Test",
            kind="cycle",
            choices=choices,
            value=value,
        )
        panel._fields = [field]
        panel._push_to_overlay = MagicMock()
        panel._refresh_body = MagicMock()
        return panel

    def test_cycle_value_not_in_choices_defaults_to_first(self):
        panel = self._make_panel_stub("unknown", ["a", "b", "c"])
        panel._cycle(1)
        # unknown → index 0, +1 → index 1 → "b"
        assert panel._fields[0].value == "b"

    def test_cycle_value_in_choices_works_normally(self):
        panel = self._make_panel_stub("b", ["a", "b", "c"])
        panel._cycle(1)
        # "b" is at index 1, +1 → index 2 → "c"
        assert panel._fields[0].value == "c"


# ── ANIM-API-6: /anim sdf revert timer callback ───────────────────────────────

class TestAnimAPI6CommandPaths:

    def test_anim_sdf_revert_timer_callback(self):
        svc, app = _make_service()
        ov = MagicMock()
        ov.has_class.return_value = False

        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay, _overlay_config
        app.query_one.return_value = ov
        app.set_timer = MagicMock()
        app._svc_spinner = MagicMock()
        app.agent_running = False
        app._flash_hint = MagicMock()

        captured_cb = []

        def capture_timer(delay, cb):
            captured_cb.append(cb)

        app.set_timer.side_effect = capture_timer

        with patch(
            "hermes_cli.tui.services.commands.NoMatches", NoMatches
        ):
            svc.handle_anim_command("/anim sdf text")

        assert captured_cb, "set_timer was not called"

        expected_animation = _overlay_config().animation
        captured_cb[0]()
        assert ov.animation == expected_animation
