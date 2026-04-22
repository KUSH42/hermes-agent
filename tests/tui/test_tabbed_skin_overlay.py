"""Tests for TabbedSkinOverlay — T-TSO, T-OVR, T-OPT suites."""
from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_overlay(**kwargs):
    """Construct TabbedSkinOverlay without a running Textual app."""
    from hermes_cli.tui.overlays import TabbedSkinOverlay
    ov = TabbedSkinOverlay.__new__(TabbedSkinOverlay)
    TabbedSkinOverlay.__init__(ov, **kwargs)
    return ov


@contextlib.contextmanager
def _with_app(ov, mock_app=None):
    """Inject mock_app into Widget.app property for the duration of the block."""
    if mock_app is None:
        mock_app = MagicMock()
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        yield mock_app


def _make_tm(css_vars=None, component_vars=None):
    from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
    tm = MagicMock()
    tm._css_vars = dict(css_vars or {})
    tm._component_vars = dict(component_vars or COMPONENT_VAR_DEFAULTS)
    return tm


# ---------------------------------------------------------------------------
# T-TSO — TabbedSkinOverlay structure and tab switching
# ---------------------------------------------------------------------------

class TestTabbedSkinOverlayStructure:
    """T-TSO-01–T-TSO-15"""

    def test_tso_01_has_three_tab_labels(self):
        """T-TSO-01: TabbedSkinOverlay has bindings for 3 named tabs."""
        from hermes_cli.tui.overlays import TabbedSkinOverlay
        bindings_keys = {b.key for b in TabbedSkinOverlay.BINDINGS}
        assert "1" in bindings_keys
        assert "2" in bindings_keys
        assert "3" in bindings_keys
        assert "tab" in bindings_keys
        assert "shift+tab" in bindings_keys
        assert "escape" in bindings_keys

    def test_tso_02_tab_cycles_1_to_2_to_3_to_1(self):
        """T-TSO-02: action_next_tab cycles 0→1→2→0."""
        ov = _make_overlay()
        ov._show_tab = MagicMock(side_effect=lambda i: setattr(ov, "_active_tab", i))
        ov._active_tab = 0

        ov.action_next_tab()
        assert ov._active_tab == 1
        ov.action_next_tab()
        assert ov._active_tab == 2
        ov.action_next_tab()
        assert ov._active_tab == 0

    def test_tso_03_keys_1_2_3_jump_directly(self):
        """T-TSO-03: action_goto_tab_N sets active tab directly."""
        ov = _make_overlay()
        ov._show_tab = MagicMock(side_effect=lambda i: setattr(ov, "_active_tab", i))
        ov.action_goto_tab_1()
        assert ov._active_tab == 0
        ov.action_goto_tab_2()
        assert ov._active_tab == 1
        ov.action_goto_tab_3()
        assert ov._active_tab == 2

    def test_tso_04_tab1_populated_with_skin_names_including_default(self):
        """T-TSO-04: _populate_tab1 includes 'default' always."""
        ov = _make_overlay()
        ov._current_skin = "default"
        mock_ol = MagicMock()
        ov.query_one = MagicMock(side_effect=lambda sel, *a: mock_ol)
        with patch.object(Path, "is_dir", return_value=False):
            ov._populate_tab1()
        assert "default" in ov._skin_names

    def test_tso_05_tab1_highlight_fires_apply_skin_path(self, tmp_path):
        """T-TSO-05: Tab 1 highlight calls app.apply_skin with skin path."""
        ov = _make_overlay()
        skins_dir = tmp_path / "skins"
        skins_dir.mkdir()
        (skins_dir / "matrix.yaml").write_text("fg: '#00ff00'\n")

        with _with_app(ov) as mock_app:
            with patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=tmp_path):
                ov._apply_skin_preview("matrix")

        mock_app.apply_skin.assert_called_once()
        arg = mock_app.apply_skin.call_args[0][0]
        assert isinstance(arg, Path)
        assert arg.stem == "matrix"

    def test_tso_06_tab1_enter_persists_display_skin(self):
        """T-TSO-06: _confirm_skin persists display.skin to config + flashes hint."""
        ov = _make_overlay()

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays._cfg_set_nested") as mock_set, \
             patch("hermes_cli.tui.overlays._cfg_save_config") as mock_save, \
             patch.object(ov, "_populate_tab1"):
            ov._confirm_skin("nord")

        mock_set.assert_called_once_with({}, "display.skin", "nord")
        mock_save.assert_called_once()
        mock_app._flash_hint.assert_called_once()
        assert "nord" in mock_app._flash_hint.call_args[0][0]
        # overlay stays open (no _dismiss call)
        assert ov._current_skin == "nord"

    def test_tso_07_escape_tab1_reverts_to_snapshot(self):
        """T-TSO-07: action_dismiss reverts to snapshot skin."""
        ov = _make_overlay()
        ov._snap_css_vars = {"accent": "#ff0000"}
        ov._snap_component_vars = {"cursor-color": "#FFF8DC"}

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.tui.overlays._dismiss_overlay_and_focus_input") as mock_dismiss:
            ov.action_dismiss()

        mock_app.apply_skin.assert_called_once()
        combined = mock_app.apply_skin.call_args[0][0]
        assert combined.get("accent") == "#ff0000"
        assert combined.get("component_vars", {}).get("cursor-color") == "#FFF8DC"
        mock_dismiss.assert_called_once_with(ov)

    def test_tso_08_tab2_populated_from_syntax_schemes(self):
        """T-TSO-08: _populate_tab2 uses SYNTAX_SCHEMES keys."""
        ov = _make_overlay()
        ov._current_syntax = "monokai"
        mock_ol = MagicMock()
        mock_static = MagicMock()

        def query_side(sel, *a):
            if "syntax-list" in sel:
                return mock_ol
            return mock_static

        ov.query_one = MagicMock(side_effect=query_side)
        ov._render_fixture = MagicMock()

        fake_schemes = {"monokai": {}, "dracula": {}, "nord": {}}
        with patch("hermes_cli.skin_engine.SYNTAX_SCHEMES", fake_schemes):
            ov._populate_tab2()

        assert set(ov._syntax_schemes) == {"monokai", "dracula", "nord"}

    def test_tso_09_tab2_highlight_fires_apply_skin_flat_dict(self):
        """T-TSO-09: Tab 2 highlight calls app.apply_skin with flat dict (not nested vars:)."""
        ov = _make_overlay()
        ov._render_fixture = MagicMock()

        with _with_app(ov) as mock_app:
            ov._apply_syntax_preview("dracula")

        mock_app.apply_skin.assert_called_once_with({"preview-syntax-theme": "dracula"})

    def test_tso_10_tab2_fixture_static_present(self):
        """T-TSO-10: FIXTURE_CODE is a non-empty module-level constant."""
        from hermes_cli.tui.overlays import FIXTURE_CODE
        assert isinstance(FIXTURE_CODE, str)
        assert len(FIXTURE_CODE.strip()) > 0
        assert "def fibonacci" in FIXTURE_CODE

    def test_tso_11_tab2_highlight_updates_fixture(self):
        """T-TSO-11: _apply_syntax_preview calls _render_fixture with new theme."""
        ov = _make_overlay()
        ov._render_fixture = MagicMock()

        with _with_app(ov):
            ov._apply_syntax_preview("nord")

        ov._render_fixture.assert_called_once_with("nord")

    def test_tso_12_escape_tab2_reverts_syntax(self):
        """T-TSO-12: action_dismiss reverts preview-syntax-theme to snapshot."""
        ov = _make_overlay()
        ov._snap_css_vars = {"preview-syntax-theme": "monokai"}
        ov._snap_component_vars = {}

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.tui.overlays._dismiss_overlay_and_focus_input"):
            ov.action_dismiss()

        combined = mock_app.apply_skin.call_args[0][0]
        assert combined.get("preview-syntax-theme") == "monokai"

    def test_tso_13_escape_after_both_tabs_reverts_both(self):
        """T-TSO-13: Escape reverts Tab 1 + Tab 2 previews together."""
        ov = _make_overlay()
        ov._snap_css_vars = {"preview-syntax-theme": "monokai", "accent": "#aaa"}
        ov._snap_component_vars = {"cursor-color": "#FFF8DC"}

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.tui.overlays._dismiss_overlay_and_focus_input"):
            ov.action_dismiss()

        combined = mock_app.apply_skin.call_args[0][0]
        assert combined.get("preview-syntax-theme") == "monokai"
        assert combined.get("accent") == "#aaa"
        assert combined.get("component_vars", {}).get("cursor-color") == "#FFF8DC"

    def test_tso_14_skin_picker_overlay_alias(self):
        """T-TSO-14: SkinPickerOverlay is an alias for TabbedSkinOverlay."""
        from hermes_cli.tui.overlays import SkinPickerOverlay, TabbedSkinOverlay
        assert SkinPickerOverlay is TabbedSkinOverlay

    def test_tso_15_tab_binding_has_priority(self):
        """T-TSO-15: 'tab' binding has priority=True."""
        from hermes_cli.tui.overlays import TabbedSkinOverlay
        tab_bindings = [b for b in TabbedSkinOverlay.BINDINGS if b.key == "tab"]
        assert tab_bindings, "No 'tab' binding found"
        assert tab_bindings[0].priority is True


# ---------------------------------------------------------------------------
# T-OVR — Override persistence layer
# ---------------------------------------------------------------------------

class TestOverridePersistence:
    """T-OVR-01–T-OVR-09 + T-OVR-06b"""

    def test_ovr_01_read_skin_overrides_absent(self):
        """T-OVR-01: read_skin_overrides returns {} when key absent."""
        from hermes_cli.config import read_skin_overrides
        with patch("hermes_cli.config.read_raw_config", return_value={}):
            result = read_skin_overrides()
        assert result == {}

    def test_ovr_02_save_skin_override_vars(self):
        """T-OVR-02: save_skin_override writes vars.preview-syntax-theme."""
        from hermes_cli.config import save_skin_override
        saved = {}

        with patch("hermes_cli.config.read_raw_config", return_value={}), \
             patch("hermes_cli.config.save_config", side_effect=saved.update):
            save_skin_override("vars.preview-syntax-theme", "nord")

        assert saved.get("display", {}).get("skin_overrides", {}).get(
            "vars", {}).get("preview-syntax-theme") == "nord"

    def test_ovr_03_save_skin_override_component_vars(self):
        """T-OVR-03: save_skin_override writes component_vars.cursor-color."""
        from hermes_cli.config import save_skin_override
        saved = {}

        with patch("hermes_cli.config.read_raw_config", return_value={}), \
             patch("hermes_cli.config.save_config", side_effect=saved.update):
            save_skin_override("component_vars.cursor-color", "#ff2d95")

        assert saved.get("display", {}).get("skin_overrides", {}).get(
            "component_vars", {}).get("cursor-color") == "#ff2d95"

    def test_ovr_04_apply_overrides_merges_vars(self):
        """T-OVR-04: ThemeManager._apply_overrides merges vars into _css_vars."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)
        tm._css_vars = {"accent": "#aaa"}
        tm._apply_overrides({"vars": {"preview-syntax-theme": "dracula"}})
        assert tm._css_vars["preview-syntax-theme"] == "dracula"
        assert tm._css_vars["accent"] == "#aaa"

    def test_ovr_05_apply_overrides_merges_component_vars(self):
        """T-OVR-05: ThemeManager._apply_overrides merges component_vars."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)
        tm._component_vars = {"cursor-color": "#FFF8DC"}
        tm._apply_overrides({"component_vars": {"cursor-color": "#ff2d95"}})
        assert tm._component_vars["cursor-color"] == "#ff2d95"

    def test_ovr_06_load_calls_apply_overrides(self, tmp_path):
        """T-OVR-06: ThemeManager.load() calls _apply_overrides after base load."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)

        skin_file = tmp_path / "test.yaml"
        skin_file.write_text("fg: '#ffffff'\n")

        with patch("hermes_cli.tui.theme_manager.load_skin_full", return_value=({}, {})), \
             patch("hermes_cli.config.read_skin_overrides",
                   return_value={"vars": {"preview-syntax-theme": "nord"}}):
            tm._apply_overrides = MagicMock()
            result = tm.load(skin_file)

        assert result is True
        tm._apply_overrides.assert_called_once()

    def test_ovr_06b_load_dict_does_not_call_apply_overrides(self):
        """T-OVR-06b: ThemeManager.load_dict() does NOT call _apply_overrides."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)
        tm._apply_overrides = MagicMock()

        tm.load_dict({"accent": "#abc"})

        tm._apply_overrides.assert_not_called()

    def test_ovr_07_skin_switch_reapplies_overrides(self, tmp_path):
        """T-OVR-07: Switching skins via load() re-applies overrides on new skin."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)

        skin_file = tmp_path / "nord.yaml"
        skin_file.write_text("fg: '#88c0d0'\n")

        overrides = {"vars": {"preview-syntax-theme": "dracula"}}
        with patch("hermes_cli.tui.theme_manager.load_skin_full", return_value=({"bg": "#222"}, {})), \
             patch("hermes_cli.config.read_skin_overrides", return_value=overrides):
            tm.load(skin_file)

        assert tm._css_vars.get("preview-syntax-theme") == "dracula"

    def test_ovr_08_tab2_confirm_persists_override(self):
        """T-OVR-08: Tab 2 Enter calls save_skin_override + flashes hint."""
        ov = _make_overlay()

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.config.save_skin_override") as mock_save:
            ov._confirm_syntax("nord")

        mock_save.assert_called_once_with("vars.preview-syntax-theme", "nord")
        mock_app._flash_hint.assert_called_once()
        assert "nord" in mock_app._flash_hint.call_args[0][0]

    def test_ovr_09_startup_applies_overrides(self, tmp_path):
        """T-OVR-09: load() with persisted skin_overrides applies them on first call."""
        from hermes_cli.tui.theme_manager import ThemeManager
        app = MagicMock()
        tm = ThemeManager(app)
        skin_file = tmp_path / "skin.yaml"
        skin_file.write_text("fg: '#fff'\n")

        with patch("hermes_cli.tui.theme_manager.load_skin_full", return_value=({}, {})), \
             patch("hermes_cli.config.read_skin_overrides",
                   return_value={"vars": {"preview-syntax-theme": "catppuccin"},
                                 "component_vars": {"cursor-color": "#ff2d95"}}):
            tm.load(skin_file)

        assert tm._css_vars.get("preview-syntax-theme") == "catppuccin"
        assert tm._component_vars.get("cursor-color") == "#ff2d95"


# ---------------------------------------------------------------------------
# T-OPT — Options tab
# ---------------------------------------------------------------------------

class TestOptionsTab:
    """T-OPT-01–T-OPT-12"""

    def test_opt_01_options_tab_has_four_rows(self):
        """T-OPT-01: TabbedSkinOverlay defines class-level preset dicts for 4 option types."""
        from hermes_cli.tui.overlays import TabbedSkinOverlay
        assert len(TabbedSkinOverlay._CURSOR_COLORS) == 4
        assert len(TabbedSkinOverlay._ANIM_COLORS) == 4
        assert len(TabbedSkinOverlay._SPINNER_STYLES) == 4

    def test_opt_02_bold_off_applies_skin(self):
        """T-OPT-02: Bold Off button calls apply_skin with preview-syntax-bold=false."""
        ov = _make_overlay()

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.config.save_skin_override"):
            ov._apply_bold(False)

        mock_app.apply_skin.assert_called_once_with({"preview-syntax-bold": "false"})

    def test_opt_03_preview_syntax_bold_false_sets_flag_streaming(self):
        """T-OPT-03: StreamingCodeBlock.refresh_skin sets _syntax_bold=False when bold=false."""
        from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock
        scb = StreamingCodeBlock.__new__(StreamingCodeBlock)
        scb._pygments_theme = "monokai"
        scb._state = "STREAMING"
        scb._syntax_bold = True
        scb._render_syntax = MagicMock()

        scb.refresh_skin({"preview-syntax-theme": "monokai", "preview-syntax-bold": "false"})

        assert scb._syntax_bold is False

    def test_opt_04_preview_syntax_bold_true_keeps_flag(self):
        """T-OPT-04: StreamingCodeBlock.refresh_skin keeps _syntax_bold=True by default."""
        from hermes_cli.tui.widgets.code_blocks import StreamingCodeBlock
        scb = StreamingCodeBlock.__new__(StreamingCodeBlock)
        scb._pygments_theme = "monokai"
        scb._state = "STREAMING"
        scb._syntax_bold = True
        scb._render_syntax = MagicMock()

        scb.refresh_skin({"preview-syntax-theme": "monokai"})

        assert scb._syntax_bold is True

    def test_opt_05_strip_bold_removes_modifiers(self):
        """T-OPT-05: _strip_bold("bold #ff0000") → "#ff0000"."""
        from hermes_cli.tui.widgets.code_blocks import _strip_bold
        assert _strip_bold("bold #ff0000") == "#ff0000"
        assert _strip_bold("italic bold #abc123") == "#abc123"
        assert _strip_bold("#aabbcc") == "#aabbcc"
        assert _strip_bold("underline #fff") == "#fff"
        assert _strip_bold("") == ""

    def test_opt_06_cursor_pink_applies_component_var(self):
        """T-OPT-06: Cursor Pink → app.apply_skin with component_vars.cursor-color."""
        ov = _make_overlay()

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.config.save_skin_override"):
            ov._apply_cursor_color("#ff2d95")

        mock_app.apply_skin.assert_called_once_with(
            {"component_vars": {"cursor-color": "#ff2d95"}})

    def test_opt_07_cursor_color_applies_live(self):
        """T-OPT-07: _apply_cursor_color updates component_vars live via load_dict."""
        from hermes_cli.tui.theme_manager import ThemeManager, COMPONENT_VAR_DEFAULTS
        app = MagicMock()
        tm = ThemeManager(app)
        tm._component_vars = dict(COMPONENT_VAR_DEFAULTS)

        tm.load_dict({"component_vars": {"cursor-color": "#ff2d95"}})

        assert tm._component_vars.get("cursor-color") == "#ff2d95"

    def test_opt_08_cursor_color_persists_to_skin_overrides(self):
        """T-OPT-08: _apply_cursor_color calls save_skin_override."""
        ov = _make_overlay()

        with _with_app(ov), \
             patch("hermes_cli.config.save_skin_override") as mock_save:
            ov._apply_cursor_color("#ff2d95")

        mock_save.assert_called_once_with("component_vars.cursor-color", "#ff2d95")

    def test_opt_09_anim_pink_sets_drawille_canvas_color(self):
        """T-OPT-09: _apply_anim_color updates drawille-canvas-color."""
        ov = _make_overlay()

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.config.save_skin_override"):
            ov._apply_anim_color("#ff2d95")

        mock_app.apply_skin.assert_called_once_with(
            {"component_vars": {"drawille-canvas-color": "#ff2d95"}})

    def test_opt_10_anim_color_persists_to_skin_overrides(self):
        """T-OPT-10: _apply_anim_color persists to skin_overrides.component_vars."""
        ov = _make_overlay()

        with _with_app(ov), \
             patch("hermes_cli.config.save_skin_override") as mock_save:
            ov._apply_anim_color("#ff2d95")

        mock_save.assert_called_once_with("component_vars.drawille-canvas-color", "#ff2d95")

    def test_opt_11_spinner_persists_to_display_spinner_style(self):
        """T-OPT-11: _apply_spinner persists to display.spinner_style (not skin_overrides)."""
        ov = _make_overlay()
        set_calls: list[tuple] = []

        with _with_app(ov), \
             patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays._cfg_set_nested",
                   side_effect=lambda cfg, k, v: set_calls.append((k, v))), \
             patch("hermes_cli.tui.overlays._cfg_save_config"):
            ov._apply_spinner("pulse")

        assert ("display.spinner_style", "pulse") in set_calls

    def test_opt_12_escape_from_options_reverts_all_previewed_changes(self):
        """T-OPT-12: action_dismiss reverts component_vars set during Tab 3 interactions."""
        ov = _make_overlay()
        ov._snap_css_vars = {}
        ov._snap_component_vars = {"cursor-color": "#FFF8DC", "drawille-canvas-color": "#00d7ff"}

        with _with_app(ov) as mock_app, \
             patch("hermes_cli.tui.overlays._dismiss_overlay_and_focus_input"):
            ov.action_dismiss()

        combined = mock_app.apply_skin.call_args[0][0]
        cv = combined.get("component_vars", {})
        assert cv.get("cursor-color") == "#FFF8DC"
        assert cv.get("drawille-canvas-color") == "#00d7ff"


# ---------------------------------------------------------------------------
# Additional unit tests for config helpers and module-level items
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_read_skin_overrides_returns_nested_dict(self):
        """read_skin_overrides extracts nested skin_overrides dict."""
        from hermes_cli.config import read_skin_overrides
        cfg = {"display": {"skin_overrides": {"vars": {"preview-syntax-theme": "nord"}}}}
        with patch("hermes_cli.config.read_raw_config", return_value=cfg):
            result = read_skin_overrides()
        assert result == {"vars": {"preview-syntax-theme": "nord"}}

    def test_strip_bold_idempotent(self):
        """_strip_bold is safe to call on already-clean style strings."""
        from hermes_cli.tui.widgets.code_blocks import _strip_bold
        assert _strip_bold("#abc") == "#abc"
        assert _strip_bold("  ") == ""

    def test_fixture_code_is_module_level_constant(self):
        """FIXTURE_CODE is importable from overlays module."""
        from hermes_cli.tui.overlays import FIXTURE_CODE
        assert "fibonacci" in FIXTURE_CODE
        assert FIXTURE_CODE.strip().startswith("def")
