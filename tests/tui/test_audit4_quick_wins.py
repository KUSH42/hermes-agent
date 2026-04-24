"""Tests for Audit 4 Quick Wins spec.

Issues: TRIGGER-01/02/04, INTR-01/05/06, PANE-01/02,
        CONFIG-02/03/04, REF-02/03, BROWSE-02, SESS-01
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch, PropertyMock


# ── TestTriggerBindings ───────────────────────────────────────────────────────


class TestTriggerBindings:
    """TRIGGER-01/02/04: ctrl+b → browse, f3/f4 added, ctrl+shift+a show=True."""

    def _get_bindings(self):
        from hermes_cli.tui.app import HermesApp
        return {b.key: b for b in HermesApp.BINDINGS}

    def test_ctrl_b_not_anim_config(self):
        bindings = self._get_bindings()
        b = bindings.get("ctrl+b")
        assert b is not None
        assert b.action != "open_anim_config"

    def test_ctrl_b_toggles_browse_mode(self):
        from hermes_cli.tui.app import HermesApp
        app = types.SimpleNamespace(browse_mode=False)
        HermesApp.action_toggle_browse_mode(app)
        assert app.browse_mode is True
        HermesApp.action_toggle_browse_mode(app)
        assert app.browse_mode is False

    def test_ctrl_shift_a_still_opens_anim_config(self):
        bindings = self._get_bindings()
        b = bindings.get("ctrl+shift+a")
        assert b is not None
        assert b.action == "open_anim_config"

    def test_ctrl_shift_a_binding_show_true(self):
        bindings = self._get_bindings()
        b = bindings.get("ctrl+shift+a")
        assert b is not None
        assert b.show is True

    def test_f3_binding_resolves_to_show_commands(self):
        bindings = self._get_bindings()
        b = bindings.get("f3")
        assert b is not None
        assert b.action == "show_commands"

    def test_f4_binding_resolves_to_toggle_workspace(self):
        bindings = self._get_bindings()
        b = bindings.get("f4")
        assert b is not None
        assert b.action == "toggle_workspace"

    def test_action_show_commands_calls_show_overlay(self):
        from hermes_cli.tui.app import HermesApp
        from textual.css.query import NoMatches
        app = HermesApp.__new__(HermesApp)
        mock_overlay = MagicMock()
        mock_overlay.show_overlay = MagicMock()
        app.query_one = MagicMock(return_value=mock_overlay)
        HermesApp.action_show_commands(app)
        mock_overlay.show_overlay.assert_called_once()


# ── TestInterruptCountdown ────────────────────────────────────────────────────


class TestInterruptCountdown:
    """INTR-01/05: Countdown only starts for CLARIFY kind."""

    def _make_overlay(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        ov = InterruptOverlay.__new__(InterruptOverlay)
        ov._countdown_timer = None
        ov._dismiss_timer = None
        return ov

    def _make_payload(self, kind, countdown_s=5):
        from hermes_cli.tui.overlays.interrupt import InterruptPayload, InterruptKind
        return InterruptPayload(
            kind=kind,
            title="test",
            countdown_s=countdown_s,
        )

    def test_countdown_starts_for_clarify(self):
        from hermes_cli.tui.overlays.interrupt import InterruptKind, _COUNTDOWN_ALLOWED
        assert InterruptKind.CLARIFY in _COUNTDOWN_ALLOWED

    def test_countdown_not_started_for_approval(self):
        from hermes_cli.tui.overlays.interrupt import InterruptKind, _COUNTDOWN_ALLOWED
        assert InterruptKind.APPROVAL not in _COUNTDOWN_ALLOWED

    def test_countdown_not_started_for_sudo(self):
        from hermes_cli.tui.overlays.interrupt import InterruptKind, _COUNTDOWN_ALLOWED
        assert InterruptKind.SUDO not in _COUNTDOWN_ALLOWED

    def test_countdown_not_started_for_secret(self):
        from hermes_cli.tui.overlays.interrupt import InterruptKind, _COUNTDOWN_ALLOWED
        assert InterruptKind.SECRET not in _COUNTDOWN_ALLOWED

    def test_timeout_does_not_dismiss_approval(self):
        from hermes_cli.tui.overlays.interrupt import (
            InterruptOverlay, InterruptPayload, InterruptKind,
        )
        ov = InterruptOverlay.__new__(InterruptOverlay)
        ov._countdown_timer = None
        ov._dismiss_timer = None
        payload = InterruptPayload(
            kind=InterruptKind.APPROVAL,
            title="test",
            countdown_s=5,
        )
        payload.deadline = -1  # already expired
        ov._current_payload = payload
        ov.dismiss_current = MagicMock()
        ov._stop_countdown_timer = MagicMock()
        InterruptOverlay._tick_countdown(ov)
        ov.dismiss_current.assert_not_called()


# ── TestFlashReducedMotion ────────────────────────────────────────────────────


class TestFlashReducedMotion:
    """INTR-06: _flash_replace_border skipped under reduced-motion."""

    def _make_overlay(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        ov = InterruptOverlay.__new__(InterruptOverlay)
        ov._classes = set()
        ov.add_class = lambda *a: ov._classes.update(a)
        ov.remove_class = lambda *a: ov._classes.discard(a[0])
        return ov

    def test_flash_replace_border_skipped_with_reduced_motion(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        ov = self._make_overlay()
        mock_app = MagicMock()
        mock_app.has_class = MagicMock(return_value=True)
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            InterruptOverlay._flash_replace_border(ov)
        assert "--flash-replace" not in ov._classes

    def test_flash_replace_border_runs_without_reduced_motion(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        ov = self._make_overlay()
        mock_app = MagicMock()
        mock_app.has_class = MagicMock(return_value=False)
        ov.set_timer = MagicMock()
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            InterruptOverlay._flash_replace_border(ov)
        assert "--flash-replace" in ov._classes


# ── TestPaneManager ───────────────────────────────────────────────────────────


class TestPaneManager:
    """PANE-01/02: Right pane forced collapsed; no-op compose deleted."""

    def test_right_pane_collapsed_by_default_when_no_content(self):
        from hermes_cli.tui.pane_manager import PaneManager, _RIGHT_PANE_HAS_CONTENT
        assert _RIGHT_PANE_HAS_CONTENT is False
        pm = PaneManager(cfg={})
        assert pm._right_collapsed is True

    def test_right_pane_respects_config_when_has_content(self):
        import hermes_cli.tui.pane_manager as pm_mod
        original = pm_mod._RIGHT_PANE_HAS_CONTENT
        try:
            pm_mod._RIGHT_PANE_HAS_CONTENT = True
            from hermes_cli.tui.pane_manager import PaneManager
            pm = PaneManager(cfg={"layout_v2": {"start_collapsed_right": False}})
            assert pm._right_collapsed is False
        finally:
            pm_mod._RIGHT_PANE_HAS_CONTENT = original

    def test_pane_container_has_no_compose_method(self):
        from hermes_cli.tui.widgets.pane_container import PaneContainer
        assert "compose" not in PaneContainer.__dict__


# ── TestSkinPreview ───────────────────────────────────────────────────────────


class TestSkinPreview:
    """CONFIG-02: Skin preview on highlight without committing."""

    def _make_overlay(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = ConfigOverlay.__new__(ConfigOverlay)
        ov._snap_css_vars = {}
        ov._snap_component_vars = {}
        ov._current_skin = "default"
        return ov

    def test_highlight_applies_skin_without_saving(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = self._make_overlay()
        mock_tm = MagicMock()
        mock_tm.load_skin = MagicMock()
        mock_app = MagicMock()
        mock_app._theme_manager = mock_tm
        ov._confirm_skin = MagicMock()

        mock_opt = MagicMock()
        mock_opt.id = "co-skin-opt-catppuccin"
        mock_list = MagicMock()
        mock_list.id = "co-skin-list"
        event = MagicMock()
        event.option = mock_opt
        event.option_list = mock_list
        event.stop = MagicMock()

        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            ConfigOverlay.on_option_list_option_highlighted(ov, event)
        mock_tm.load_skin.assert_called_once_with("catppuccin")
        ov._confirm_skin.assert_not_called()

    def test_highlight_on_other_list_is_ignored(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = self._make_overlay()
        mock_tm = MagicMock()
        mock_app = MagicMock()
        mock_app._theme_manager = mock_tm

        mock_opt = MagicMock()
        mock_opt.id = "co-model-opt-claude-3"
        mock_list = MagicMock()
        mock_list.id = "co-model-list"
        event = MagicMock()
        event.option = mock_opt
        event.option_list = mock_list
        event.stop = MagicMock()

        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            ConfigOverlay.on_option_list_option_highlighted(ov, event)
        mock_tm.load_skin.assert_not_called()

    def test_select_still_persists_skin(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = self._make_overlay()
        ov._confirm_skin = MagicMock()

        event = MagicMock()
        event.option_id = "co-skin-opt-matrix"
        event.stop = MagicMock()

        ConfigOverlay.on_option_list_option_selected(ov, event)
        ov._confirm_skin.assert_called_once_with("matrix")

    def test_esc_reverts_preview(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = self._make_overlay()
        mock_tm = MagicMock()
        mock_tm.load_skin = MagicMock()
        mock_tm._css_vars = {"accent": "#blue"}
        mock_tm._component_vars = {}
        mock_tm.refresh_css = MagicMock()
        mock_app = MagicMock()
        mock_app._theme_manager = mock_tm
        ov._snap_css_vars = {"accent": "#original"}
        ov._snap_component_vars = {}

        # highlight triggers load_skin
        mock_opt = MagicMock()
        mock_opt.id = "co-skin-opt-matrix"
        mock_list = MagicMock()
        mock_list.id = "co-skin-list"
        event = MagicMock()
        event.option = mock_opt
        event.option_list = mock_list
        event.stop = MagicMock()
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            ConfigOverlay.on_option_list_option_highlighted(ov, event)
        mock_tm.load_skin.assert_called_once()

        # esc reverts — _cfg_save_config should NOT be called
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            with patch("hermes_cli.tui.overlays.config._cfg_save_config") as mock_save:
                ConfigOverlay._revert_skin_preview_if_any(ov)
                mock_save.assert_not_called()
        mock_tm.refresh_css.assert_called()


# ── TestSyntaxFixture ─────────────────────────────────────────────────────────


class TestSyntaxFixture:
    """CONFIG-03: Syntax fixture uses last-edited file language."""

    def _make_overlay(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = ConfigOverlay.__new__(ConfigOverlay)
        ov._current_syntax = "monokai"
        ov._syntax_schemes = []
        return ov

    def test_syntax_fixture_uses_last_file_extension(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        from hermes_cli.tui.overlays._legacy import FIXTURE_CODE
        ov = self._make_overlay()
        mock_app = MagicMock()
        mock_app.status_active_file = "main.rs"

        captured = {}

        def fake_query_one(sel, cls=None):
            w = MagicMock()
            def update(text):
                captured["text"] = text
            w.update = update
            return w

        ov.query_one = fake_query_one
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            ConfigOverlay._refresh_syntax_tab(ov)
        assert "text" in captured
        assert captured["text"] != FIXTURE_CODE

    def test_syntax_fixture_falls_back_to_python(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        from hermes_cli.tui.overlays._legacy import FIXTURE_CODE
        ov = self._make_overlay()
        mock_app = MagicMock()
        mock_app.status_active_file = ""

        captured = {}

        def fake_query_one(sel, cls=None):
            w = MagicMock()
            def update(text):
                captured["text"] = text
            w.update = update
            return w

        ov.query_one = fake_query_one
        with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
            ConfigOverlay._refresh_syntax_tab(ov)
        assert captured.get("text") == FIXTURE_CODE


# ── TestReasoningOptionList ───────────────────────────────────────────────────


class TestReasoningOptionList:
    """CONFIG-04: Reasoning tab uses OptionList not Buttons."""

    def test_reasoning_tab_has_option_list_not_buttons(self):
        import inspect
        from hermes_cli.tui.overlays.config import ConfigOverlay
        src = inspect.getsource(ConfigOverlay.compose)
        assert "co-rpo-list" in src
        assert "co-rpo-none" not in src
        assert "co-rpo-low" not in src

    def test_reasoning_option_selected_applies_level(self):
        from hermes_cli.tui.overlays.config import ConfigOverlay
        ov = ConfigOverlay.__new__(ConfigOverlay)
        ov._reasoning_current_level = "none"
        ov._apply_reasoning_level = MagicMock()

        event = MagicMock()
        event.option_id = "co-rpo-opt-medium"
        event.stop = MagicMock()

        ConfigOverlay.on_option_list_option_selected(ov, event)
        ov._apply_reasoning_level.assert_called_once_with("medium")


# ── TestWorkspaceNoSessions ───────────────────────────────────────────────────


class TestWorkspaceNoSessions:
    """REF-02: Sessions tab removed from WorkspaceOverlay."""

    def test_workspace_overlay_has_no_sessions_tab(self):
        import inspect
        from hermes_cli.tui.overlays.reference import WorkspaceOverlay
        src = inspect.getsource(WorkspaceOverlay.compose)
        assert "ws-tab-sessions" not in src

    def test_workspace_overlay_has_no_sessions_pane(self):
        import inspect
        from hermes_cli.tui.overlays.reference import WorkspaceOverlay
        src = inspect.getsource(WorkspaceOverlay)
        assert "_SessionsTab" not in src


# ── TestHelpOverlayQKey ───────────────────────────────────────────────────────


class TestHelpOverlayQKey:
    """REF-03: HelpOverlay q binding replaced by explicit on_key."""

    def test_q_dismisses_when_overlay_focused(self):
        from hermes_cli.tui.overlays.reference import HelpOverlay
        from textual.css.query import NoMatches
        ov = HelpOverlay.__new__(HelpOverlay)
        ov.action_dismiss = MagicMock()

        mock_screen = MagicMock()
        mock_screen.focused = MagicMock()  # some non-search widget

        # query_one raises NoMatches — simulates search not found / not focused
        ov.query_one = MagicMock(side_effect=NoMatches())

        event = MagicMock()
        event.key = "q"
        event.prevent_default = MagicMock()

        with patch.object(type(ov), "screen", new_callable=PropertyMock, return_value=mock_screen):
            HelpOverlay.on_key(ov, event)
        ov.action_dismiss.assert_called_once()

    def test_q_inserts_when_search_input_focused(self):
        from hermes_cli.tui.overlays.reference import HelpOverlay
        from textual.widgets import Input
        ov = HelpOverlay.__new__(HelpOverlay)
        ov.action_dismiss = MagicMock()

        mock_search = MagicMock(spec=Input)
        mock_screen = MagicMock()
        mock_screen.focused = mock_search
        ov.query_one = MagicMock(return_value=mock_search)

        event = MagicMock()
        event.key = "q"
        event.prevent_default = MagicMock()

        with patch.object(type(ov), "screen", new_callable=PropertyMock, return_value=mock_screen):
            HelpOverlay.on_key(ov, event)
        ov.action_dismiss.assert_not_called()


# ── TestBrowseMinimapAccent ───────────────────────────────────────────────────


class TestBrowseMinimapAccent:
    """BROWSE-02: BrowseMinimap uses $accent not hard-coded cyan."""

    def test_minimap_uses_accent_color(self):
        import inspect
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        src = inspect.getsource(BrowseMinimap.render_line)
        assert "get_css_variables" in src
        assert '"cyan"' in src  # fallback still present

    def test_minimap_falls_back_to_cyan_on_error(self):
        import inspect
        from hermes_cli.tui.browse_minimap import BrowseMinimap
        src = inspect.getsource(BrowseMinimap.render_line)
        # Ensure error handling path falls back to cyan
        assert "except Exception" in src
        assert "cyan" in src


# ── TestSessionRelTime ────────────────────────────────────────────────────────


class TestSessionRelTime:
    """SESS-01: Sessions older than 8 weeks show YYYY-MM-DD."""

    def _get_rel(self, diff_days: float) -> str:
        import time as _time
        from hermes_cli.tui.overlays._legacy import _SessionRow
        row = _SessionRow.__new__(_SessionRow)
        row._is_current = False
        now = _time.time()
        last_active = now - diff_days * 86400
        meta = {
            "id": "s1",
            "title": "test",
            "last_active": last_active,
            "message_count": 0,
        }
        row._meta = meta
        line = _SessionRow._build_label(row)
        return line

    def test_session_rel_time_over_8_weeks_shows_date(self):
        import re
        line = self._get_rel(60)
        assert re.search(r"\d{4}-\d{2}-\d{2}", line), f"Expected date in: {line!r}"

    def test_session_rel_time_under_8_weeks_shows_weeks(self):
        line = self._get_rel(14)
        assert "2w ago" in line, f"Expected '2w ago' in: {line!r}"
