"""Tests that all 10 services are wired on HermesApp with correct types and order."""
import pytest
from unittest.mock import MagicMock


def _make_app():
    from hermes_cli.tui.app import HermesApp
    mock_cli = MagicMock()
    mock_cli.config = {}
    return HermesApp(cli=mock_cli)


def test_all_services_exist():
    from hermes_cli.tui.services import (
        ThemeService, SpinnerService, IOService, ToolRenderingService,
        BrowseService, SessionsService, ContextMenuService, CommandsService,
        WatchersService, KeyDispatchService,
    )
    app = _make_app()
    assert isinstance(app._svc_theme,    ThemeService)
    assert isinstance(app._svc_spinner,  SpinnerService)
    assert isinstance(app._svc_io,       IOService)
    assert isinstance(app._svc_tools,    ToolRenderingService)
    assert isinstance(app._svc_browse,   BrowseService)
    assert isinstance(app._svc_sessions, SessionsService)
    assert isinstance(app._svc_context,  ContextMenuService)
    assert isinstance(app._svc_commands, CommandsService)
    assert isinstance(app._svc_watchers, WatchersService)
    assert isinstance(app._svc_keys,     KeyDispatchService)


def test_services_hold_app_ref():
    app = _make_app()
    for attr in ("_svc_theme", "_svc_spinner", "_svc_io", "_svc_tools",
                 "_svc_browse", "_svc_sessions", "_svc_context", "_svc_commands",
                 "_svc_watchers", "_svc_keys"):
        svc = getattr(app, attr)
        assert svc.app is app, f"{attr}.app is not the app"


def test_service_imports_clean():
    """Services subpackage importable without errors."""
    from hermes_cli.tui import services  # noqa: F401
    assert hasattr(services, "AppService")
    assert hasattr(services, "ThemeService")


def test_theme_service_first_in_source_order():
    """ThemeService must be created before SpinnerService (documented order)."""
    import inspect
    from hermes_cli.tui.app import HermesApp
    src = inspect.getsource(HermesApp.__init__)
    theme_idx   = src.index("_svc_theme")
    spinner_idx = src.index("_svc_spinner")
    io_idx      = src.index("_svc_io")
    assert theme_idx < spinner_idx < io_idx, "Service init order violated"


def test_watchers_and_keys_last():
    """WatchersService and KeyDispatchService must be last two."""
    import inspect
    from hermes_cli.tui.app import HermesApp
    src = inspect.getsource(HermesApp.__init__)
    commands_idx = src.index("_svc_commands")
    watchers_idx = src.index("_svc_watchers")
    keys_idx     = src.index("_svc_keys")
    assert commands_idx < watchers_idx < keys_idx, "Watchers/keys must come last"


def test_no_service_holds_sibling_service_ref():
    """Services should not directly store refs to other services — lookup via app._svc_X."""
    from hermes_cli.tui.services import (
        ThemeService, SpinnerService, IOService, ToolRenderingService,
        BrowseService, SessionsService, ContextMenuService, CommandsService,
        WatchersService, KeyDispatchService,
    )
    import inspect
    for cls in (ThemeService, SpinnerService, IOService, ToolRenderingService,
                BrowseService, SessionsService, ContextMenuService, CommandsService,
                WatchersService, KeyDispatchService):
        src = inspect.getsource(cls.__init__)
        # Phase 1 shells should have no self._svc_* assignments
        assert "self._svc_" not in src, f"{cls.__name__}.__init__ stores a sibling svc ref"


def test_app_import_still_clean():
    """HermesApp importable without errors."""
    from hermes_cli.tui.app import HermesApp  # noqa: F401
    assert True


def test_services_base_class():
    from hermes_cli.tui.services.base import AppService
    from hermes_cli.tui.services.theme import ThemeService
    assert issubclass(ThemeService, AppService)


# ---------------------------------------------------------------------------
# Phase 2: ContextMenuService + ThemeService method presence
# ---------------------------------------------------------------------------

def test_context_menu_service_has_key_methods():
    app = _make_app()
    svc = app._svc_context
    for method in (
        "show_context_menu_at",
        "show_context_menu_for_focused",
        "handle_click",
        "build_context_items",
        "build_tool_block_menu_items",
        "copy_code_block",
        "copy_tool_output",
        "copy_path_action",
        "open_external_url",
        "on_copyable_rich_log_link_clicked",
        "open_path_action",
        "copy_all_output",
        "copy_panel",
        "copy_text",
        "paste_into_input",
        "clear_input",
        "on_tool_panel_path_focused",
        "dismiss_all_info_overlays",
        "on_path_search_provider_batch",
    ):
        assert hasattr(svc, method), f"ContextMenuService missing method: {method}"
        assert callable(getattr(svc, method)), f"ContextMenuService.{method} not callable"


def test_theme_service_has_key_methods():
    app = _make_app()
    svc = app._svc_theme
    for method in (
        "flash_hint",
        "copy_text_with_hint",
        "apply_skin",
        "set_status_error",
        "get_selected_text",
        "populate_slash_commands",
        "refresh_slash_commands",
        "_apply_override_dict",
    ):
        assert hasattr(svc, method), f"ThemeService missing method: {method}"
        assert callable(getattr(svc, method)), f"ThemeService.{method} not callable"


def test_mixin_flash_hint_routes_to_service(monkeypatch):
    """app._flash_hint(...) must delegate to app.feedback.flash('hint-bar', ...)."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app.feedback, "flash", lambda channel, text, **kw: calls.append((channel, text)))
    app._flash_hint("test", 1.0)
    assert calls == [("hint-bar", "test")], f"Expected [('hint-bar', 'test')], got {calls}"


def test_theme_service_flash_hint_callable():
    app = _make_app()
    # Verify method exists and is callable; actual invocation requires a mounted app
    assert callable(app._svc_theme.flash_hint)


def test_theme_service_timer_state_initialized():
    """ThemeService.__init__ must create _flash_timer and _error_clear_timer."""
    app = _make_app()
    svc = app._svc_theme
    assert hasattr(svc, "_flash_timer"), "ThemeService missing _flash_timer"
    assert hasattr(svc, "_error_clear_timer"), "ThemeService missing _error_clear_timer"


def test_context_menu_service_is_context_menu_service():
    from hermes_cli.tui.services.context_menu import ContextMenuService
    from hermes_cli.tui.services.base import AppService
    assert issubclass(ContextMenuService, AppService)
    app = _make_app()
    assert isinstance(app._svc_context, ContextMenuService)


# ---------------------------------------------------------------------------
# Phase 2 batch 1 add-on: SpinnerService + BrowseService
# ---------------------------------------------------------------------------

def test_spinner_service_has_key_methods():
    app = _make_app()
    svc = app._svc_spinner
    for method in (
        "tick_spinner",
        "compute_hint_phase",
        "set_hint_phase",
        "set_chevron_phase",
        "build_hint_text",
        "tick_duration",
        "tick_fps",
        "drawille_show_hide",
        "on_fps_hud_visible",
    ):
        assert hasattr(svc, method), f"SpinnerService missing method: {method}"
        assert callable(getattr(svc, method)), f"SpinnerService.{method} not callable"


def test_browse_service_has_key_methods():
    app = _make_app()
    svc = app._svc_browse
    for method in (
        "rebuild_browse_anchors",
        "jump_anchor",
        "focus_anchor",
        "apply_browse_focus",
        "clear_browse_highlight",
        "clear_browse_pips",
        "apply_browse_pips",
        "update_browse_status",
        "on_browse_mode",
    ):
        assert hasattr(svc, method), f"BrowseService missing method: {method}"
        assert callable(getattr(svc, method)), f"BrowseService.{method} not callable"


def test_browse_service_anchors_initialized():
    app = _make_app()
    svc = app._svc_browse
    assert hasattr(svc, "_browse_anchors"), "BrowseService missing _browse_anchors"
    assert isinstance(svc._browse_anchors, list), "_browse_anchors must be a list"
    assert svc._browse_anchors == [], "_browse_anchors must be empty on init"


def test_mixin_set_hint_phase_routes_to_spinner(monkeypatch):
    """app._set_hint_phase(...) must delegate to app._svc_spinner.set_hint_phase(...)."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_spinner, "set_hint_phase", lambda phase: calls.append(phase))
    app._set_hint_phase("stream")
    assert calls == ["stream"], f"Expected ['stream'], got {calls}"


def test_mixin_rebuild_browse_anchors_routes_to_browse(monkeypatch):
    """app._rebuild_browse_anchors() must delegate to app._svc_browse.rebuild_browse_anchors()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_browse, "rebuild_browse_anchors", lambda: calls.append(True))
    app._rebuild_browse_anchors()
    assert calls == [True], f"Expected [True], got {calls}"


# ---------------------------------------------------------------------------
# Phase 2 batch 3+: SessionsService + ToolRenderingService
# ---------------------------------------------------------------------------

def test_sessions_service_has_key_methods():
    app = _make_app()
    svc = app._svc_sessions
    for method in (
        "init_sessions",
        "refresh_session_bar",
        "poll_session_index",
        "refresh_session_records_from_index",
        "get_session_records",
        "get_active_session_id",
        "open_new_session_overlay",
        "flash_sessions_max",
        "new_worktree_session",
        "switch_to_session",
        "switch_to_session_by_index",
        "handle_session_event",
        "create_new_session",
        "on_session_created",
        "kill_session_prompt",
        "do_kill_session",
        "open_merge_overlay",
        "show_merge_overlay",
        "run_merge",
        "reopen_orphan_session",
        "delete_orphan_session",
        "resume_session",
        "open_sessions",
    ):
        assert hasattr(svc, method), f"SessionsService missing method: {method}"
        assert callable(getattr(svc, method)), f"SessionsService.{method} not callable"


def test_tool_rendering_service_has_key_methods():
    app = _make_app()
    svc = app._svc_tools
    for method in (
        "mount_tool_block",
        "open_streaming_tool_block",
        "close_streaming_tool_block",
        "append_streaming_line",
        "open_reasoning",
        "append_reasoning",
        "close_reasoning",
        "current_turn_tool_calls",
        "get_reasoning_panel",
        "current_message_panel",
        "set_plan_batch",
        "mark_plan_running",
        "mark_plan_done",
    ):
        assert hasattr(svc, method), f"ToolRenderingService missing method: {method}"
        assert callable(getattr(svc, method)), f"ToolRenderingService.{method} not callable"


def test_tool_rendering_service_streaming_map_initialized():
    app = _make_app()
    svc = app._svc_tools
    assert hasattr(svc, "_streaming_map"), "ToolRenderingService missing _streaming_map"
    assert isinstance(svc._streaming_map, dict), "_streaming_map must be a dict"
    assert svc._streaming_map == {}, "_streaming_map must be empty on init"


def test_tool_rendering_service_turn_tool_calls_initialized():
    app = _make_app()
    svc = app._svc_tools
    assert hasattr(svc, "_turn_tool_calls"), "ToolRenderingService missing _turn_tool_calls"
    assert isinstance(svc._turn_tool_calls, dict)
    assert svc._turn_tool_calls == {}


def test_app_turn_tool_calls_compat_property():
    """app._turn_tool_calls must return app._svc_tools._turn_tool_calls."""
    app = _make_app()
    # Inject a sentinel value into the service
    sentinel = {"tc-1": object()}
    app._svc_tools._turn_tool_calls = sentinel
    assert app._turn_tool_calls is sentinel, (
        "app._turn_tool_calls compat property must proxy to app._svc_tools._turn_tool_calls"
    )


# ---------------------------------------------------------------------------
# Phase 2 batch 4: IOService + CommandsService
# ---------------------------------------------------------------------------

def test_io_service_has_key_methods():
    app = _make_app()
    svc = app._svc_io
    for method in (
        "consume_output",
        "write_output",
        "flush_output",
        "play_effects_async",
        "play_effects_blocking",
        "play_tte_main",
        "play_tte",
        "play_tte_blocking",
        "stop_tte_main",
        "stop_tte",
        "get_working_directory",
    ):
        assert hasattr(svc, method), f"IOService missing method: {method}"
        assert callable(getattr(svc, method)), f"IOService.{method} not callable"


def test_commands_service_has_key_methods():
    app = _make_app()
    svc = app._svc_commands
    for method in (
        "handle_tui_command",
        "handle_clear_tui",
        "has_rollback_checkpoint",
        "open_tools_overlay",
        "handle_layout_command",
        "open_anim_config",
        "persist_anim_config",
        "update_anim_hint",
        "handle_anim_command",
        "try_auto_title",
        "toggle_drawille_overlay",
        "initiate_undo",
        "run_undo_sequence",
        "initiate_retry",
        "initiate_rollback",
        "run_rollback_sequence",
    ):
        assert hasattr(svc, method), f"CommandsService missing method: {method}"
        assert callable(getattr(svc, method)), f"CommandsService.{method} not callable"


def test_app_flush_output_is_permanent_forwarder():
    """app.flush_output() must delegate to _svc_io.flush_output() (permanent public API)."""
    app = _make_app()
    calls = []
    app._svc_io.flush_output = lambda: calls.append(True)
    app.flush_output()
    assert calls == [True], f"app.flush_output() did not delegate to svc: {calls}"


def test_app_write_output_is_permanent_forwarder():
    """app.write_output() must delegate to _svc_io.write_output() (permanent public API)."""
    app = _make_app()
    calls = []
    app._svc_io.write_output = lambda text: calls.append(text)
    app.write_output("hello")
    assert calls == ["hello"], f"app.write_output() did not delegate to svc: {calls}"


def test_app_handle_tui_command_routes_to_service(monkeypatch):
    """app._handle_tui_command() must delegate to _svc_commands.handle_tui_command()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_commands, "handle_tui_command", lambda text: calls.append(text) or False)
    result = app._handle_tui_command("/help")
    assert calls == ["/help"], f"Expected ['/help'], got {calls}"
    assert result is False


def test_app_initiate_undo_routes_to_service(monkeypatch):
    """app._initiate_undo() must delegate to _svc_commands.initiate_undo()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_commands, "initiate_undo", lambda: calls.append(True))
    app._initiate_undo()
    assert calls == [True], f"Expected [True], got {calls}"


# ---------------------------------------------------------------------------
# Phase 2 batch 5: WatchersService + KeyDispatchService
# ---------------------------------------------------------------------------

def test_watchers_service_has_key_methods():
    app = _make_app()
    svc = app._svc_watchers
    for method in (
        "on_text_area_changed",
        "on_input_changed",
        "on_size",
        "on_compact",
        "sync_compact_visibility",
        "on_status_compaction_progress",
        "on_voice_mode",
        "on_voice_recording",
        "on_attached_images",
        "append_attached_images",
        "clear_attached_images",
        "insert_link_tokens",
        "drop_path_display",
        "handle_file_drop",
        "handle_file_drop_inner",
        "on_clarify_state",
        "on_approval_state",
        "on_highlighted_candidate",
        "on_sudo_state",
        "on_secret_state",
        "on_status_error",
        "auto_clear_status_error",
        "on_undo_state",
    ):
        assert hasattr(svc, method), f"WatchersService missing method: {method}"
        assert callable(getattr(svc, method)), f"WatchersService.{method} not callable"


def test_key_dispatch_service_has_key_methods():
    app = _make_app()
    svc = app._svc_keys
    for method in (
        "dispatch_key",
        "dispatch_input_submitted",
    ):
        assert hasattr(svc, method), f"KeyDispatchService missing method: {method}"
        assert callable(getattr(svc, method)), f"KeyDispatchService.{method} not callable"


def test_watchers_service_drop_path_display_is_static():
    """drop_path_display must work as a staticmethod (no app needed)."""
    from hermes_cli.tui.services.watchers import WatchersService
    from pathlib import Path
    result = WatchersService.drop_path_display(Path("/home/user/project/foo.py"), Path("/home/user/project"))
    assert result == "foo.py"


def test_watchers_service_drop_path_display_absolute_for_deep_relative():
    """drop_path_display returns absolute path when relative depth > 1."""
    from hermes_cli.tui.services.watchers import WatchersService
    from pathlib import Path
    result = WatchersService.drop_path_display(Path("/tmp/deep/path/file.py"), Path("/home/user/project"))
    assert result.startswith("/")


def test_app_handle_file_drop_routes_to_watchers(monkeypatch):
    """app.handle_file_drop() must delegate to _svc_watchers.handle_file_drop()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_watchers, "handle_file_drop", lambda paths: calls.append(paths))
    sentinel = [object()]
    app.handle_file_drop(sentinel)
    assert calls == [sentinel], f"Expected sentinel, got {calls}"


def test_mixin_watchers_text_area_changed_routes_to_service(monkeypatch):
    """app.on_text_area_changed() must delegate to _svc_watchers.on_text_area_changed()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_watchers, "on_text_area_changed", lambda ev: calls.append(ev))
    sentinel = object()
    app.on_text_area_changed(sentinel)
    assert calls == [sentinel]


def test_mixin_keys_dispatch_key_routes_to_service(monkeypatch):
    """app.on_key() must delegate to _svc_keys.dispatch_key()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_keys, "dispatch_key", lambda ev: calls.append(ev))
    sentinel = object()
    app.on_key(sentinel)
    assert calls == [sentinel]


def test_mixin_keys_input_submitted_routes_to_service(monkeypatch):
    """app.on_hermes_input_submitted() must delegate to _svc_keys.dispatch_input_submitted()."""
    app = _make_app()
    calls = []
    monkeypatch.setattr(app._svc_keys, "dispatch_input_submitted", lambda ev: calls.append(ev))
    sentinel = object()
    app.on_hermes_input_submitted(sentinel)
    assert calls == [sentinel]


def test_keys_service_uses_time_module():
    """KeyDispatchService must import time as _time at module level for test patching."""
    import hermes_cli.tui.services.keys as keys_mod
    assert hasattr(keys_mod, "_time"), "keys.py must have module-level 'import time as _time'"


def test_watchers_service_handle_file_drop_inner_blocked_by_overlay(monkeypatch):
    """handle_file_drop_inner flashes hint and returns early when approval_state is set."""
    from unittest.mock import MagicMock
    app = _make_app()

    flash_calls = []
    monkeypatch.setattr(app.feedback, "flash", lambda channel, text, **kw: flash_calls.append(text))

    # Patch getattr on the app so approval_state appears non-None without triggering reactive
    sentinel = MagicMock()
    monkeypatch.setattr(type(app), "approval_state", property(lambda self: sentinel), raising=False)
    monkeypatch.setattr(type(app), "clarify_state", property(lambda self: None), raising=False)
    monkeypatch.setattr(type(app), "sudo_state", property(lambda self: None), raising=False)
    monkeypatch.setattr(type(app), "secret_state", property(lambda self: None), raising=False)

    app._svc_watchers.handle_file_drop_inner([])
    assert any("unavailable" in c for c in flash_calls), f"Expected unavailable hint, got {flash_calls}"
