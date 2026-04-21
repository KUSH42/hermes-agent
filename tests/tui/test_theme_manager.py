"""Tests for hermes_cli/tui/theme_manager.py and the load_skin_full extension."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.skin_loader import SkinError, load_skin_full
from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS, ThemeManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "skin.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _yaml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "skin.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _mock_app() -> MagicMock:
    return MagicMock(spec=["refresh_css", "workers"])


# ---------------------------------------------------------------------------
# load_skin_full — new function in skin_loader
# ---------------------------------------------------------------------------

class TestLoadSkinFull:
    def test_returns_tuple(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"fg": "#fff"})
        result = load_skin_full(p)
        assert isinstance(result, tuple) and len(result) == 2

    def test_css_vars_matches_load_skin(self, tmp_path: Path) -> None:
        """CSS var output is identical to the original load_skin()."""
        from hermes_cli.tui.skin_loader import load_skin
        data = {"fg": "#aabbcc", "accent": "#ff0000"}
        p = _json(tmp_path, data)
        css_vars, _ = load_skin_full(p)
        assert css_vars == load_skin(p)

    def test_component_vars_extracted(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {
            "fg": "#fff",
            "component_vars": {"cursor-color": "#gold", "cursor-selection-bg": "#navy"},
        })
        css_vars, comp_vars = load_skin_full(p)
        assert "cursor-color" in comp_vars
        assert comp_vars["cursor-color"] == "#gold"
        assert comp_vars["cursor-selection-bg"] == "#navy"
        # component_vars must NOT appear in css_vars
        assert "cursor-color" not in css_vars
        assert "component_vars" not in css_vars

    def test_empty_component_vars(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"fg": "#fff"})
        _, comp_vars = load_skin_full(p)
        assert comp_vars == {}

    def test_invalid_component_vars_raises(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"component_vars": "not-a-dict"})
        with pytest.raises(SkinError):
            load_skin_full(p)

    def test_yaml_parity(self, tmp_path: Path) -> None:
        data = {
            "fg": "#aabbcc",
            "component_vars": {"cursor-color": "#FFD700"},
        }
        json_path = _json(tmp_path, data)
        yaml_text = (
            "fg: '#aabbcc'\n"
            "component_vars:\n"
            "  cursor-color: '#FFD700'\n"
        )
        yaml_path = _yaml(tmp_path, yaml_text)
        j_css, j_comp = load_skin_full(json_path)
        y_css, y_comp = load_skin_full(yaml_path)
        assert j_css == y_css
        assert j_comp == y_comp


# ---------------------------------------------------------------------------
# ThemeManager — load / apply
# ---------------------------------------------------------------------------

class TestThemeManagerLoad:
    def test_load_path_sets_css_vars(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"accent": "#7C3AED"})
        app = _mock_app()
        tm = ThemeManager(app)
        assert tm.load(p) is True
        # accent fans out to primary via semantic map
        assert tm.css_variables["primary"] == "#7C3AED"

    def test_load_dict_no_component_vars(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load_dict({"primary": "#ff0000"})
        assert tm.css_variables["primary"] == "#ff0000"
        # Component var defaults are still present
        assert "cursor-color" in tm.css_variables

    def test_load_dict_component_vars(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load_dict({
            "primary": "#ff0000",
            "component_vars": {"cursor-color": "#gold"},
        })
        assert tm.css_variables["cursor-color"] == "#gold"
        # Primary was not popped as component_var
        assert tm.css_variables["primary"] == "#ff0000"

    def test_load_dict_does_not_mutate_caller(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        original = {"primary": "#fff", "component_vars": {"cursor-color": "#abc"}}
        copy = dict(original)
        tm.load_dict(original)
        # Original dict must not be mutated
        assert original == copy

    def test_component_var_defaults_preserved_without_skin(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        for key, val in COMPONENT_VAR_DEFAULTS.items():
            assert tm.css_variables[key] == val

    def test_component_vars_override_defaults(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {
            "component_vars": {"cursor-color": "#FF0000"},
        })
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load(p)
        assert tm.css_variables["cursor-color"] == "#FF0000"
        # Other defaults still intact
        assert tm.css_variables["cursor-selection-bg"] == COMPONENT_VAR_DEFAULTS["cursor-selection-bg"]

    def test_fallback_chain_first_wins(self, tmp_path: Path) -> None:
        good = _json(tmp_path, {"accent": "#aaa"})
        bad = tmp_path / "missing.json"
        app = _mock_app()
        tm = ThemeManager(app)
        assert tm.load([good, bad]) is True
        assert "primary" in tm.css_variables

    def test_fallback_chain_second_wins(self, tmp_path: Path) -> None:
        bad = tmp_path / "missing.json"
        good = _json(tmp_path, {"accent": "#bbb"})
        app = _mock_app()
        tm = ThemeManager(app)
        assert tm.load([bad, good]) is True

    def test_fallback_chain_all_fail(self, tmp_path: Path) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        assert tm.load([tmp_path / "a.json", tmp_path / "b.json"]) is False

    def test_apply_calls_refresh_css(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        tm.apply()
        app.refresh_css.assert_called_once()

    def test_apply_swallows_refresh_error(self) -> None:
        app = _mock_app()
        app.refresh_css.side_effect = RuntimeError("boom")
        tm = ThemeManager(app)
        tm.apply()  # must not raise


# ---------------------------------------------------------------------------
# ThemeManager — hot reload
# ---------------------------------------------------------------------------

class TestThemeManagerHotReload:
    def test_no_reload_without_source(self) -> None:
        app = _mock_app()
        tm = ThemeManager(app)
        assert tm.check_for_changes() is False

    def test_no_reload_when_mtime_unchanged(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"accent": "#aaa"})
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load(p)
        app.refresh_css.reset_mock()
        assert tm.check_for_changes() is False
        app.refresh_css.assert_not_called()

    def test_reload_when_mtime_increases(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"accent": "#aaa"})
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load(p)
        app.refresh_css.reset_mock()

        # Bump mtime by rewriting the file
        time.sleep(0.01)
        p.write_text(json.dumps({"accent": "#bbb"}), encoding="utf-8")
        # Manually set mtime to "old" so check detects the change
        tm._source_mtime = 0.0

        assert tm.check_for_changes() is True
        app.refresh_css.assert_called_once()
        assert tm.css_variables["primary"] == "#bbb"

    def test_reload_missing_file_returns_false(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"accent": "#aaa"})
        app = _mock_app()
        tm = ThemeManager(app)
        tm.load(p)
        # Simulate file deletion
        tm._source_mtime = 0.0
        p.unlink()
        assert tm.check_for_changes() is False

    def test_background_watcher_reloads_off_thread(self, tmp_path: Path) -> None:
        p = _json(tmp_path, {"accent": "#aaa"})
        app = _mock_app()
        app.call_from_thread = lambda fn, *args: fn(*args)
        tm = ThemeManager(app)
        tm.load(p)
        app.refresh_css.reset_mock()
        tm.start_hot_reload(0.01)
        try:
            time.sleep(0.02)
            p.write_text(json.dumps({"accent": "#bbb"}), encoding="utf-8")
            deadline = time.time() + 1.0
            while time.time() < deadline:
                if app.refresh_css.called:
                    break
                time.sleep(0.02)
            assert app.refresh_css.called
            assert tm.css_variables["primary"] == "#bbb"
        finally:
            tm.stop_hot_reload()


# ---------------------------------------------------------------------------
# HermesApp integration — ThemeManager wired into get_css_variables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_get_css_variables_includes_component_defaults(tmp_path: Path) -> None:
    """ThemeManager defaults flow through to HermesApp.get_css_variables()."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        for key in COMPONENT_VAR_DEFAULTS:
            assert key in css_vars, f"Missing component var: {key}"


@pytest.mark.asyncio
async def test_app_apply_skin_path_uses_theme_manager(tmp_path: Path) -> None:
    """apply_skin(Path) routes through ThemeManager and respects component_vars."""
    from hermes_cli.tui.app import HermesApp

    p = _json(tmp_path, {
        "accent": "#7C3AED",
        "component_vars": {"cursor-color": "#FFD700"},
    })

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin(p)
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert css_vars["primary"] == "#7C3AED"
        assert css_vars["cursor-color"] == "#FFD700"


@pytest.mark.asyncio
async def test_app_apply_skin_dict_preserves_component_defaults(tmp_path: Path) -> None:
    """apply_skin(dict) keeps COMPONENT_VAR_DEFAULTS for un-overridden keys."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin({"primary": "#ff0000"})
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert css_vars["cursor-color"] == COMPONENT_VAR_DEFAULTS["cursor-color"]
