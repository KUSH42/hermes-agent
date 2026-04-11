"""Tests for hermes_cli.tui.tte_runner."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# resolve_effect
# ---------------------------------------------------------------------------

class TestResolveEffect:
    def test_known_name_returns_tuple(self):
        from hermes_cli.tui.tte_runner import resolve_effect
        result = resolve_effect("matrix")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_case_insensitive(self):
        from hermes_cli.tui.tte_runner import resolve_effect
        assert resolve_effect("MATRIX") == resolve_effect("matrix")
        assert resolve_effect("Matrix") == resolve_effect("matrix")

    def test_unknown_name_returns_none(self):
        from hermes_cli.tui.tte_runner import resolve_effect
        assert resolve_effect("not_a_real_effect") is None

    def test_all_15_effects_resolve(self):
        from hermes_cli.tui.tte_runner import resolve_effect, EFFECT_MAP
        assert len(EFFECT_MAP) == 15
        for name in EFFECT_MAP:
            assert resolve_effect(name) is not None, f"Effect '{name}' did not resolve"

    def test_whitespace_stripped(self):
        from hermes_cli.tui.tte_runner import resolve_effect
        assert resolve_effect("  matrix  ") is not None


# ---------------------------------------------------------------------------
# run_effect — import error (TTE not installed)
# ---------------------------------------------------------------------------

class TestRunEffectImportError:
    def test_import_error_prints_hint_and_does_not_crash(self, capsys):
        from hermes_cli.tui.tte_runner import run_effect

        # Simulate TTE not installed by making importlib.import_module raise
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            run_effect("matrix", "test")  # must not raise

        out = capsys.readouterr().out
        assert "not installed" in out.lower() or "terminaltexteffects" in out.lower()
        assert "pip install" in out.lower() or "install" in out.lower()


# ---------------------------------------------------------------------------
# run_effect — unknown effect name
# ---------------------------------------------------------------------------

class TestRunEffectUnknownName:
    def test_unknown_name_prints_available_and_does_not_crash(self, capsys):
        from hermes_cli.tui.tte_runner import run_effect

        run_effect("totally_fake_effect_xyz", "test")

        out = capsys.readouterr().out
        assert "Unknown effect" in out or "unknown" in out.lower()
        # Should list available effects
        assert "matrix" in out


# ---------------------------------------------------------------------------
# run_effect — skin gradient applied
# ---------------------------------------------------------------------------

class TestRunEffectSkinGradient:
    def _make_fake_tte(self):
        """Build a minimal fake TTE module tree that run_effect can call."""
        # Fake Color class
        class FakeColor:
            def __init__(self, hex_str):
                self.hex_str = hex_str

        # Fake effect config with final_gradient_stops
        fake_cfg = MagicMock()
        fake_cfg.final_gradient_stops = None

        # Fake terminal context manager
        fake_terminal = MagicMock()
        fake_terminal.__enter__ = MagicMock(return_value=fake_terminal)
        fake_terminal.__exit__ = MagicMock(return_value=False)
        fake_terminal.print = MagicMock()

        # Fake effect instance (iterable — yields nothing for speed)
        fake_effect = MagicMock()
        fake_effect.effect_config = fake_cfg
        fake_effect.terminal_config = MagicMock()
        fake_effect.terminal_output = MagicMock(return_value=fake_terminal)
        fake_effect.__iter__ = MagicMock(return_value=iter([]))

        # Fake effect class
        fake_cls = MagicMock(return_value=fake_effect)

        # Fake module
        fake_mod = MagicMock()
        fake_mod.Matrix = fake_cls

        # Fake graphics module with Color
        fake_graphics = MagicMock()
        fake_graphics.Color = FakeColor

        return fake_mod, fake_effect, fake_cfg, fake_graphics, FakeColor

    def test_skin_gradient_applied_to_final_gradient_stops(self):
        from hermes_cli.tui.tte_runner import run_effect

        fake_mod, fake_effect, fake_cfg, fake_graphics, FakeColor = self._make_fake_tte()

        fake_skin = MagicMock()
        fake_skin.get_color = MagicMock(side_effect=lambda key, default: default)

        def fake_import(name):
            if "effect_matrix" in name:
                return fake_mod
            if "graphics" in name:
                return fake_graphics
            raise ImportError(f"unexpected import: {name}")

        with patch("importlib.import_module", side_effect=fake_import):
            run_effect("matrix", "Hermes", skin=fake_skin)

        # final_gradient_stops should have been set to a tuple of Color objects
        assert fake_cfg.final_gradient_stops is not None
        stops = fake_cfg.final_gradient_stops
        assert isinstance(stops, tuple)
        assert all(isinstance(c, FakeColor) for c in stops)

    def test_skin_failure_does_not_crash(self):
        """If the skin raises, run_effect should still run with default TTE colors."""
        from hermes_cli.tui.tte_runner import run_effect

        fake_mod, fake_effect, fake_cfg, fake_graphics, FakeColor = self._make_fake_tte()

        bad_skin = MagicMock()
        bad_skin.get_color = MagicMock(side_effect=RuntimeError("skin broken"))

        def fake_import(name):
            if "effect_matrix" in name:
                return fake_mod
            if "graphics" in name:
                return fake_graphics
            raise ImportError(name)

        with patch("importlib.import_module", side_effect=fake_import):
            run_effect("matrix", "Hermes", skin=bad_skin)  # must not raise

        # Effect should still have been iterated (terminal_output called)
        fake_effect.terminal_output.assert_called_once()


# ---------------------------------------------------------------------------
# run_effect — happy path for multiple effects
# ---------------------------------------------------------------------------

class TestRunEffectHappyPath:
    """Verify run_effect can be called for each curated effect without crashing
    when TTE produces zero frames (empty iterator)."""

    EFFECTS_TO_TEST = [
        "matrix", "beams", "rain", "decrypt", "print", "slide", "wipe",
    ]

    def _make_minimal_fake_tte(self, class_name: str):
        fake_terminal = MagicMock()
        fake_terminal.__enter__ = MagicMock(return_value=fake_terminal)
        fake_terminal.__exit__ = MagicMock(return_value=False)
        fake_terminal.print = MagicMock()

        fake_effect = MagicMock()
        fake_effect.effect_config = None
        fake_effect.terminal_config = None
        fake_effect.terminal_output = MagicMock(return_value=fake_terminal)
        fake_effect.__iter__ = MagicMock(return_value=iter([]))

        fake_cls = MagicMock(return_value=fake_effect)
        fake_mod = MagicMock()
        setattr(fake_mod, class_name, fake_cls)
        return fake_mod

    def test_happy_path_runs_without_crash(self):
        from hermes_cli.tui.tte_runner import run_effect, EFFECT_MAP

        for effect_name in self.EFFECTS_TO_TEST:
            module_path, class_name = EFFECT_MAP[effect_name]

            fake_mod = self._make_minimal_fake_tte(class_name)

            def fake_import(name, _cls=class_name, _mod=fake_mod):
                if "graphics" in name:
                    gfx = MagicMock()
                    gfx.Color = MagicMock(side_effect=lambda x: x)
                    return gfx
                return _mod

            with patch("importlib.import_module", side_effect=fake_import):
                run_effect(effect_name, "Hermes")  # must not raise


# ---------------------------------------------------------------------------
# EFFECT_MAP / EFFECT_DESCRIPTIONS coverage
# ---------------------------------------------------------------------------

class TestEffectCatalogue:
    def test_every_map_entry_has_description(self):
        from hermes_cli.tui.tte_runner import EFFECT_MAP, EFFECT_DESCRIPTIONS
        for name in EFFECT_MAP:
            assert name in EFFECT_DESCRIPTIONS, f"Missing description for '{name}'"

    def test_no_extra_descriptions(self):
        from hermes_cli.tui.tte_runner import EFFECT_MAP, EFFECT_DESCRIPTIONS
        for name in EFFECT_DESCRIPTIONS:
            assert name in EFFECT_MAP, f"Description for '{name}' has no EFFECT_MAP entry"
