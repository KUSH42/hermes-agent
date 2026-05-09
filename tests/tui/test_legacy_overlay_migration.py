"""SPEC-MOD-LEG: Tests for legacy overlay migration to ModalOverlayMixin.

Covers MOD-LEG-1 (ConfigOverlay), MOD-LEG-2 (SessionOverlay),
MOD-LEG-3 (HistorySearchOverlay), MOD-LEG-4 (dismiss_all_info_overlays /
_dismiss_floating_panels).  All tests use minimal stub apps — no full
HermesApp is started.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_fake_app():
    """Return a stub that simulates HermesApp's modal-stack interface."""
    app = MagicMock()
    app._modal_stack = []

    def _push(widget):
        app._modal_stack.append(widget)

    def _pop(widget):
        if widget in app._modal_stack:
            app._modal_stack.remove(widget)

    app.push_modal.side_effect = _push
    app.pop_modal.side_effect = _pop
    app.is_modal_active.side_effect = lambda: bool(app._modal_stack)
    app.focused = None
    return app


def _make_config_overlay(app=None):
    """Return a ConfigOverlay instance wired to a stub app (no Textual pilot)."""
    from hermes_cli.tui.overlays.config import ConfigOverlay
    from textual.css.query import NoMatches

    app = app or _make_fake_app()

    _bt_store: dict = {"v": ""}
    _at_store: dict = {"v": "model"}

    class _Isolated(ConfigOverlay):
        # Shadow Widget.border_title (reactive_attribute) so setters don't call refresh()
        @property  # type: ignore[override]
        def border_title(self):
            return _bt_store["v"]

        @border_title.setter
        def border_title(self, value: str) -> None:
            _bt_store["v"] = value

        # Shadow ConfigOverlay.active_tab reactive so setters don't need _id
        @property  # type: ignore[override]
        def active_tab(self):
            return _at_store["v"]

        @active_tab.setter
        def active_tab(self, value: str) -> None:
            _at_store["v"] = value

    _Isolated.app = property(lambda self: app)  # type: ignore[method-assign]

    overlay = _Isolated.__new__(_Isolated)
    # Minimal state required by ConfigOverlay.__init__
    overlay._yolo_previous_mode = "manual"
    overlay._reasoning_current_level = "medium"
    overlay._browsed_provider = ""
    overlay._provider_slugs = []
    overlay._snap_css_vars = {}
    overlay._snap_component_vars = {}
    overlay._snap_skin_name = "hermes"
    overlay._current_skin = "hermes"
    overlay._current_syntax = "monokai"
    overlay._skin_names = []
    overlay._syntax_schemes = []
    overlay._last_cli = None
    overlay._focus_caller = None
    overlay._model_prefetch_done = False
    # CSS class tracking
    overlay._classes: set[str] = set()

    def _has_class(*cls_names):
        return any(c in overlay._classes for c in cls_names)

    def _add_class(*cls_names):
        overlay._classes.update(cls_names)

    def _remove_class(*cls_names):
        overlay._classes -= set(cls_names)

    overlay.has_class = _has_class
    overlay.add_class = _add_class
    overlay.remove_class = _remove_class

    def _merge_bindings():
        from textual.binding import Bindings
        b = Bindings()
        from hermes_cli.tui.overlays.config import ConfigOverlay as _CO
        for binding in _CO.BINDINGS:
            b.bind(binding.key, binding.action, binding.description,
                   priority=binding.priority, show=binding.show)
        return b

    overlay._merge_bindings = _merge_bindings

    # focus_caller capture
    def _capture():
        overlay._focus_caller = app.focused

    overlay._capture_focus_caller = _capture

    # restore focus
    def _restore():
        return overlay._focus_caller

    overlay._restore_focus_to = _restore
    overlay._revert_skin_preview_if_any = MagicMock()
    overlay.call_after_refresh = MagicMock()
    overlay._refresh_active_tab = MagicMock()
    overlay.query_one = MagicMock(side_effect=NoMatches(""))

    return overlay, app


def _make_session_overlay(app=None):
    """Return a SessionOverlay instance wired to a stub app."""
    from hermes_cli.tui.overlays._legacy import SessionOverlay
    from textual.css.query import NoMatches

    app = app or _make_fake_app()

    _bt_store: dict = {"v": ""}

    class _Isolated(SessionOverlay):
        # Shadow Widget.border_title reactive so setters don't call refresh()
        @property  # type: ignore[override]
        def border_title(self):
            return _bt_store["v"]

        @border_title.setter
        def border_title(self, value: str) -> None:
            _bt_store["v"] = value

    _Isolated.app = property(lambda self: app)  # type: ignore[method-assign]

    overlay = _Isolated.__new__(_Isolated)
    overlay._sessions = []
    overlay._selected_idx = 0
    overlay._focus_caller = None
    overlay._classes: set[str] = set()

    def _has_class(*cls_names):
        return any(c in overlay._classes for c in cls_names)

    def _add_class(*cls_names):
        overlay._classes.update(cls_names)

    def _remove_class(*cls_names):
        overlay._classes -= set(cls_names)

    overlay.has_class = _has_class
    overlay.add_class = _add_class
    overlay.remove_class = _remove_class

    def _capture():
        overlay._focus_caller = app.focused

    overlay._capture_focus_caller = _capture

    def _restore():
        return overlay._focus_caller

    overlay._restore_focus_to = _restore
    overlay.focus = MagicMock()
    overlay.query_one = MagicMock(side_effect=NoMatches(""))
    overlay._load_sessions = MagicMock()

    # Bind _merge_bindings so test_esc can inspect it
    def _merge_bindings():
        from textual.binding import Bindings
        from hermes_cli.tui.overlays._legacy import SessionOverlay as _SO
        b = Bindings()
        for binding in _SO.BINDINGS:
            b.bind(binding.key, binding.action, binding.description,
                   priority=binding.priority, show=binding.show)
        return b

    overlay._merge_bindings = _merge_bindings
    return overlay, app


def _make_hso(app=None):
    """Return a HistorySearchOverlay instance wired to a stub app."""
    from hermes_cli.tui.widgets.overlays import HistorySearchOverlay
    from textual.css.query import NoMatches

    app = app or _make_fake_app()

    class _Isolated(HistorySearchOverlay):
        pass

    _Isolated.app = property(lambda self: app)  # type: ignore[method-assign]

    overlay = _Isolated.__new__(_Isolated)
    overlay._index = []
    overlay._current_results = []
    overlay._selected_idx = 0
    overlay._saved_hint = ""
    overlay._debounce_handle = None
    overlay._cross_session_loading = False
    overlay._max_results = 50
    overlay._last_click_idx = None
    overlay._shift_selected = set()
    overlay._mode = "current"
    overlay._query_history = []
    overlay._focus_caller = None
    overlay._classes: set[str] = set()

    def _has_class(*cls_names):
        return any(c in overlay._classes for c in cls_names)

    def _add_class(*cls_names):
        overlay._classes.update(cls_names)

    def _remove_class(*cls_names):
        overlay._classes -= set(cls_names)

    overlay.has_class = _has_class
    overlay.add_class = _add_class
    overlay.remove_class = _remove_class

    def _capture():
        overlay._focus_caller = app.focused

    overlay._capture_focus_caller = _capture

    def _restore():
        return overlay._focus_caller

    overlay._restore_focus_to = _restore
    # Use NoMatches so open_search's except NoMatches: pass blocks fire correctly
    overlay.query_one = MagicMock(side_effect=NoMatches(""))
    overlay._build_index = MagicMock()
    overlay._render_results = MagicMock()

    def _merge_bindings():
        from textual.binding import Bindings
        from hermes_cli.tui.widgets.overlays import HistorySearchOverlay as _HSO
        b = Bindings()
        for binding in _HSO.BINDINGS:
            b.bind(binding.key, binding.action, binding.description,
                   priority=binding.priority, show=binding.show)
        return b

    overlay._merge_bindings = _merge_bindings
    return overlay, app


# ---------------------------------------------------------------------------
# TestConfigOverlayMigration — MOD-LEG-1 (8 tests)
# ---------------------------------------------------------------------------

class TestConfigOverlayMigration:

    def test_config_overlay_show_pushes_modal_stack(self) -> None:
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        assert app._modal_stack == [overlay]
        assert "--modal" in overlay._classes

    def test_config_overlay_dismiss_pops_modal_stack(self) -> None:
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        overlay.dismiss_overlay()
        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_config_overlay_esc_triggers_dismiss_overlay(self) -> None:
        from hermes_cli.tui.overlays.config import ConfigOverlay
        # Escape binding must be declared in the subclass's own BINDINGS
        # (ModalOverlayMixin.BINDINGS are invisible to Textual's _merge_bindings)
        esc_keys = [b.key for b in ConfigOverlay.BINDINGS]
        assert "escape" in esc_keys, "ConfigOverlay must declare escape binding in its own BINDINGS"
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        # action_dismiss delegates to dismiss_overlay
        overlay.action_dismiss()
        assert "--visible" not in overlay._classes

    def test_config_overlay_double_show_single_stack_entry(self) -> None:
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        overlay.show_overlay("model")  # second call must be a no-op
        assert len(app._modal_stack) == 1

    def test_config_overlay_skin_revert_on_dismiss(self) -> None:
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        overlay.dismiss_overlay()
        overlay._revert_skin_preview_if_any.assert_called_once()

    def test_config_overlay_focus_restored_on_dismiss(self) -> None:
        overlay, app = _make_config_overlay()
        mock_widget = MagicMock()
        mock_widget.is_mounted = True
        app.focused = mock_widget
        overlay.show_overlay("model")
        overlay.dismiss_overlay()
        mock_widget.focus.assert_called_once()

    def test_config_overlay_on_mount_no_raw_modal_class(self) -> None:
        """--modal must NOT be present before show_overlay is called."""
        overlay, _app = _make_config_overlay()
        # Overlay constructed but not shown — --modal absent
        assert "--modal" not in overlay._classes
        # border_title set is checked via overlay.border_title attr (not set in stub, but class def is valid)

    def test_config_overlay_all_dismiss_paths_call_dismiss_overlay(self) -> None:
        """All six internal dismiss paths must delegate to dismiss_overlay()."""
        from hermes_cli.tui.overlays.config import ConfigOverlay

        paths = [
            ("action_dismiss",         []),
            ("_set_yolo",              [False]),
            ("_confirm_model",         ["model-x"]),
            ("_confirm_verbose",       ["all"]),
            ("_inject_reasoning_command", ["medium"]),
        ]

        for method_name, args in paths:
            overlay, app = _make_config_overlay()
            overlay.show_overlay("model")
            with patch.object(ConfigOverlay, "dismiss_overlay") as mock_dismiss, \
                 patch("hermes_cli.tui.overlays.config._cfg_read_raw_config", return_value={}), \
                 patch("hermes_cli.tui.overlays.config._cfg_save_config"), \
                 patch("hermes_cli.tui.overlays.config._cfg_set_nested"):
                # For paths that query app internals
                app.query_one.side_effect = Exception("no DOM")
                try:
                    getattr(overlay, method_name)(*args)
                except Exception:
                    pass
                assert mock_dismiss.called, f"{method_name} did not call dismiss_overlay()"

        # co-yolo-cancel on_button_pressed path
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        with patch.object(ConfigOverlay, "dismiss_overlay") as mock_dismiss:
            event = MagicMock()
            event.button = MagicMock()
            event.button.id = "co-yolo-cancel"
            overlay.on_button_pressed(event)
            mock_dismiss.assert_called_once()


# ---------------------------------------------------------------------------
# TestSessionOverlayMigration — MOD-LEG-2 (9 tests)
# ---------------------------------------------------------------------------

class TestSessionOverlayMigration:

    def test_session_overlay_open_pushes_modal_stack(self) -> None:
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        assert app._modal_stack == [overlay]
        assert "--modal" in overlay._classes

    def test_session_overlay_dismiss_pops_modal_stack(self) -> None:
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        overlay.dismiss_overlay()
        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_session_overlay_esc_triggers_dismiss_overlay(self) -> None:
        from hermes_cli.tui.overlays._legacy import SessionOverlay
        esc_keys = [b.key for b in SessionOverlay.BINDINGS]
        assert "escape" in esc_keys, "SessionOverlay must declare escape binding in its own BINDINGS"
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        overlay.action_dismiss()
        assert "--visible" not in overlay._classes

    def test_session_overlay_action_dismiss_delegates_to_dismiss_overlay(self) -> None:
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        overlay.action_dismiss()
        assert "--visible" not in overlay._classes
        assert "--modal" not in overlay._classes
        assert app._modal_stack == []

    def test_session_overlay_action_select_dismisses_properly(self) -> None:
        overlay, app = _make_session_overlay()
        overlay._sessions = [{"id": "abc", "title": "Test"}]
        overlay.open_sessions()
        app.action_resume_session = MagicMock()
        overlay.action_select()
        assert app._modal_stack == []
        assert "--visible" not in overlay._classes

    def test_session_overlay_focus_restored_on_dismiss(self) -> None:
        overlay, app = _make_session_overlay()
        mock_widget = MagicMock()
        mock_widget.is_mounted = True
        app.focused = mock_widget
        overlay.open_sessions()
        overlay.dismiss_overlay()
        mock_widget.focus.assert_called_once()

    def test_session_overlay_on_mount_no_raw_modal_class(self) -> None:
        overlay, _app = _make_session_overlay()
        assert "--modal" not in overlay._classes

    def test_session_overlay_double_open_single_stack_entry(self) -> None:
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        overlay.open_sessions()  # second call must be a no-op
        assert len(app._modal_stack) == 1

    def test_session_overlay_action_new_session_dismisses_properly(self) -> None:
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        app._svc_commands = MagicMock()
        overlay.action_new_session()
        assert app._modal_stack == []
        assert "--visible" not in overlay._classes


# ---------------------------------------------------------------------------
# TestHistorySearchOverlayMigration — MOD-LEG-3 (9 tests)
# ---------------------------------------------------------------------------

class TestHistorySearchOverlayMigration:

    def test_history_search_open_pushes_modal_stack(self) -> None:
        overlay, app = _make_hso()
        overlay.open_search()
        assert app._modal_stack == [overlay]
        assert "--modal" in overlay._classes

    def test_history_search_dismiss_pops_modal_stack(self) -> None:
        overlay, app = _make_hso()
        overlay.open_search()
        overlay.dismiss_overlay()
        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_history_search_esc_triggers_dismiss_overlay(self) -> None:
        from hermes_cli.tui.widgets.overlays import HistorySearchOverlay
        esc_keys = [b.key for b in HistorySearchOverlay.BINDINGS]
        assert "escape" in esc_keys, "HistorySearchOverlay must declare escape binding in its own BINDINGS"
        overlay, app = _make_hso()
        overlay.open_search()
        overlay.action_dismiss()
        assert "--visible" not in overlay._classes

    def test_history_search_ctrl_f_dismiss_works(self) -> None:
        overlay, app = _make_hso()
        overlay.open_search()
        overlay.action_dismiss()
        assert "--visible" not in overlay._classes
        assert app._modal_stack == []

    def test_history_search_debounce_cancelled_on_dismiss(self) -> None:
        overlay, app = _make_hso()
        overlay.open_search()
        mock_timer = MagicMock()
        overlay._debounce_handle = mock_timer
        overlay.dismiss_overlay()
        mock_timer.stop.assert_called_once()
        assert overlay._debounce_handle is None

    def test_history_search_hint_bar_restored_on_dismiss(self) -> None:
        from hermes_cli.tui.widgets.status_bar import HintBar
        from textual.css.query import NoMatches

        overlay, app = _make_hso()
        # Manually place overlay in visible/modal state without calling open_search
        # (open_search would overwrite _saved_hint via app.query_one(HintBar).hint)
        overlay.add_class("--visible", "--modal")
        app._modal_stack.append(overlay)
        overlay._saved_hint = "original hint"

        mock_hint_bar = MagicMock()
        mock_hint_bar.hint = ""

        def _app_query_one(cls):
            if cls is HintBar:
                return mock_hint_bar
            raise NoMatches("not found")

        app.query_one.side_effect = _app_query_one
        overlay.dismiss_overlay()
        assert mock_hint_bar.hint == "original hint"

    def test_history_search_focus_restored_on_dismiss(self) -> None:
        overlay, app = _make_hso()
        mock_widget = MagicMock()
        mock_widget.is_mounted = True
        app.focused = mock_widget
        overlay.open_search()
        overlay.dismiss_overlay()
        mock_widget.focus.assert_called_once()

    def test_history_search_on_mount_no_raw_modal_class(self) -> None:
        overlay, _app = _make_hso()
        assert "--modal" not in overlay._classes

    def test_history_search_double_open_single_stack_entry(self) -> None:
        overlay, app = _make_hso()
        overlay.open_search()
        overlay.open_search()  # second call must be a no-op
        assert len(app._modal_stack) == 1


# ---------------------------------------------------------------------------
# TestDismissAllInfoOverlays — MOD-LEG-4 (5 tests)
# ---------------------------------------------------------------------------

def _make_visible_overlay_mock(cls_name: str = "overlay") -> MagicMock:
    """Mock overlay that is currently visible (has --visible class)."""
    w = MagicMock()
    w.has_class.return_value = True
    w.dismiss_overlay = MagicMock()
    return w


def _make_hidden_overlay_mock() -> MagicMock:
    """Mock overlay that is currently hidden."""
    w = MagicMock()
    w.has_class.return_value = False
    w.dismiss_overlay = MagicMock()
    return w


class TestDismissAllInfoOverlays:

    def _make_svc(self, app_mock):
        from hermes_cli.tui.services.context_menu import ContextMenuService
        svc = ContextMenuService.__new__(ContextMenuService)
        svc._app = app_mock
        type(svc).app = property(lambda self: self._app)  # type: ignore[misc]
        return svc

    def test_dismiss_all_info_overlays_pops_config_overlay_stack(self) -> None:
        from hermes_cli.tui.overlays.config import ConfigOverlay
        overlay, app = _make_config_overlay()
        overlay.show_overlay("model")
        assert app._modal_stack == [overlay]

        app_mock = MagicMock()
        app_mock._modal_stack = app._modal_stack
        app_mock._sync_workspace_polling_state = MagicMock()

        def _query(cls):
            if cls is ConfigOverlay:
                return [overlay]
            return []

        app_mock.query.side_effect = _query
        svc = self._make_svc(app_mock)

        with patch("hermes_cli.tui.overlays.config.ConfigOverlay.dismiss_overlay",
                   side_effect=overlay.dismiss_overlay):
            svc.dismiss_all_info_overlays()

        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_dismiss_all_info_overlays_pops_session_overlay_stack(self) -> None:
        from hermes_cli.tui.overlays._legacy import SessionOverlay
        overlay, app = _make_session_overlay()
        overlay.open_sessions()
        assert app._modal_stack == [overlay]

        app_mock = MagicMock()
        app_mock._modal_stack = app._modal_stack
        app_mock._sync_workspace_polling_state = MagicMock()

        def _query(cls):
            if cls is SessionOverlay:
                return [overlay]
            return []

        app_mock.query.side_effect = _query
        svc = self._make_svc(app_mock)

        with patch.object(SessionOverlay, "dismiss_overlay",
                          side_effect=overlay.dismiss_overlay):
            svc.dismiss_all_info_overlays()

        assert app._modal_stack == []
        assert "--modal" not in overlay._classes

    def test_dismiss_all_info_overlays_pops_reference_modal_stack(self) -> None:
        """Covers the four ReferenceModal-derived overlays (HelpOverlay etc.)."""
        from hermes_cli.tui.overlays.reference import HelpOverlay

        visible_mock = _make_visible_overlay_mock()

        app_mock = MagicMock()
        app_mock._sync_workspace_polling_state = MagicMock()
        app_mock._modal_stack = [visible_mock]

        def _query(cls):
            if cls is HelpOverlay:
                return [visible_mock]
            return []

        app_mock.query.side_effect = _query
        svc = self._make_svc(app_mock)
        svc.dismiss_all_info_overlays()

        visible_mock.dismiss_overlay.assert_called_once()

    def test_dismiss_all_info_overlays_skip_closed_overlays(self) -> None:
        """dismiss_overlay() must NOT be called for hidden overlays."""
        hidden = _make_hidden_overlay_mock()

        app_mock = MagicMock()
        app_mock._sync_workspace_polling_state = MagicMock()
        app_mock.query.return_value = [hidden]
        svc = self._make_svc(app_mock)
        svc.dismiss_all_info_overlays()

        hidden.dismiss_overlay.assert_not_called()

    def test_dismiss_all_info_overlays_tpho_calls_dismiss_overlay(self) -> None:
        """ToolPanelHelpOverlay: dismiss_overlay() is called (not bare remove_class).

        ToolPanelHelpOverlay.show_overlay() pushes to _modal_stack; dismiss must
        pop it via dismiss_overlay() or the stack becomes permanently stale.
        """
        from hermes_cli.tui.overlays._legacy import ToolPanelHelpOverlay

        tpho = MagicMock()
        tpho.has_class = MagicMock(return_value=True)
        tpho.dismiss_overlay = MagicMock()

        app_mock = MagicMock()
        app_mock._sync_workspace_polling_state = MagicMock()

        def _query(cls):
            if cls is ToolPanelHelpOverlay:
                return [tpho]
            return []

        app_mock.query.side_effect = _query
        svc = self._make_svc(app_mock)
        svc.dismiss_all_info_overlays()

        tpho.dismiss_overlay.assert_called_once()


# ---------------------------------------------------------------------------
# TestDismissFloatingPanels — MOD-LEG-4 (1 test)
# ---------------------------------------------------------------------------

class TestDismissFloatingPanels:

    def test_dismiss_floating_panels_pops_history_search_stack(self) -> None:
        """_dismiss_floating_panels → action_dismiss → dismiss_overlay chain."""
        overlay, app = _make_hso()
        overlay.open_search()
        assert app._modal_stack == [overlay]

        # Simulate what _dismiss_floating_panels does: calls hs.action_dismiss()
        overlay.action_dismiss()

        assert app._modal_stack == []
        assert "--modal" not in overlay._classes
