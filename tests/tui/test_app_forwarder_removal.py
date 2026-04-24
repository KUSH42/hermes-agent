"""Absence tests — all 43 DEPRECATED forwarder methods removed from HermesApp."""
import pytest
from hermes_cli.tui.app import HermesApp


class TestPhaseAAbsent:
    @pytest.mark.parametrize("method", [
        "_refresh_session_bar",
        "_refresh_session_records_from_index",
        "_on_session_notify_event",
        "_on_session_created",
        "_do_kill_session",
        "_show_merge_overlay",
        "_init_sessions",
        "_tick_duration",
        "_get_output_panel",
        "_current_message_panel",
    ])
    def test_deprecated_method_absent(self, method):
        assert not hasattr(HermesApp, method), f"HermesApp.{method} should have been deleted"


class TestPhaseBAbsent:
    @pytest.mark.parametrize("method", [
        # B-1 spinner
        "_tick_spinner",
        "_build_hint_text",
        "_compute_hint_phase",
        "_set_hint_phase",
        "_drawbraille_show_hide",
        # B-2 browse
        "_rebuild_browse_anchors",
        "_jump_anchor",
        "_focus_tool_panel",
        # B-3 commands
        "_handle_tui_command",
        "_handle_clear_tui",
        "_open_tools_overlay",
        "_persist_anim_config",
        "_update_anim_hint",
        "_initiate_retry",
        # B-4 watchers
        "_sync_compact_visibility",
        "_clear_attached_images",
        # B-5 session widget callers
        "_open_new_session_overlay",
        "_flash_sessions_max",
        "_switch_to_session",
        "_kill_session_prompt",
        "_open_merge_overlay",
        "_reopen_orphan_session",
        "_delete_orphan_session",
        "_create_new_session",
        "_run_merge",
        "_switch_to_session_by_index",
        # B-6 session test-only callers
        "_get_session_records",
        "_get_active_session_id",
        "_poll_session_index",
        "_handle_session_event",
        # B-7 tools test callers
        "_open_gen_block",
        "_open_execute_code_block",
        "_open_write_file_block",
    ])
    def test_deprecated_method_absent(self, method):
        assert not hasattr(HermesApp, method), f"HermesApp.{method} should have been deleted"
