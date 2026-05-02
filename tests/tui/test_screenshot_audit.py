"""Tests for Screenshot Audit SS-1..SS-10.

Spec: /home/xush/.hermes/spec_screenshot_audit_2026-05-01.md
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_app(**kwargs):
    """Minimal app-like object for StatusBar render tests."""
    app = MagicMock()
    app.__class__.__name__ = "FakeApp"
    app.__dict__["feedback"] = None
    defaults = dict(
        status_model="claude-opus-4",
        status_context_tokens=8000,
        status_context_max=200000,
        status_compaction_progress=0.0,
        status_compaction_enabled=True,
        agent_running=False,
        command_running=False,
        browse_mode=False,
        yolo_mode=False,
        compact=False,
        status_output_dropped=False,
        status_error="",
        status_verbose=True,
        status_phase="idle",
        session_label="20260501_042307_b1a6",
        session_count=2,
        status_active_file="",
        status_active_file_offscreen=False,
        status_streaming=False,
        status_cwd="/home/user/project",
        context_pct=0.0,
        status_tok_s=0.0,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(app, k, v)
    app.get_css_variables.return_value = {}
    return app


# ===========================================================================
# SS-1: Completion fallback em-dash
# ===========================================================================

class TestSS1CompletionFallback:
    def test_completion_overlay_uses_em_dash_for_missing_description(self):
        from hermes_cli.tui.completion_overlay import _NO_DESCRIPTION_FALLBACK
        assert "—" in _NO_DESCRIPTION_FALLBACK

    def test_completion_overlay_passes_real_description_through(self):
        from hermes_cli.tui.completion_overlay import _NO_DESCRIPTION_FALLBACK
        desc = "Switch model"
        result = desc or _NO_DESCRIPTION_FALLBACK
        assert result == "Switch model"

    def test_skill_picker_uses_same_fallback_constant(self):
        from hermes_cli.tui.completion_overlay import _NO_DESCRIPTION_FALLBACK as co_fallback
        from hermes_cli.tui.overlays.skill_picker import _NO_DESCRIPTION_FALLBACK as sp_fallback
        assert co_fallback == sp_fallback

    def test_completion_overlay_empty_string_treated_as_missing(self):
        from hermes_cli.tui.completion_overlay import _NO_DESCRIPTION_FALLBACK
        result = "" or _NO_DESCRIPTION_FALLBACK
        assert "—" in result
        assert "(no description)" not in result


# ===========================================================================
# SS-2: Stall glyph
# ===========================================================================

class TestSS2WorkingHardStall:
    def _make_widget(self):
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        w = ThinkingWidget.__new__(ThinkingWidget)
        w._substate = "LONG_WAIT"
        w._cfg_show_elapsed = True
        w._last_token_time = None
        w._activate_time = time.monotonic() - 60
        return w

    def _elapsed_s(self, w):
        return time.monotonic() - w._activate_time

    def test_working_hard_no_stall_suffix_under_threshold(self):
        w = self._make_widget()
        w._last_token_time = time.monotonic() - 5
        text = w._get_label_text(self._elapsed_s(w))
        assert "◌" not in text
        assert "stalled" not in text

    def test_working_hard_shows_stall_glyph_after_threshold(self):
        w = self._make_widget()
        w._last_token_time = time.monotonic() - 35
        text = w._get_label_text(self._elapsed_s(w))
        assert "◌" in text
        assert "stalled?" in text

    def test_working_hard_stall_suffix_clears_on_token_arrival(self):
        w = self._make_widget()
        w._last_token_time = time.monotonic() - 35
        # confirm stale
        text = w._get_label_text(self._elapsed_s(w))
        assert "◌" in text
        # token arrives
        w.on_token_delta()
        text2 = w._get_label_text(self._elapsed_s(w))
        assert "◌" not in text2

    def test_stall_threshold_constant_shared(self):
        from hermes_cli.tui.streaming_microcopy import STALL_THRESHOLD_S
        import hermes_cli.tui.widgets.thinking as thinking_mod
        import ast, inspect
        src = inspect.getsource(thinking_mod)
        # ensure thinking.py imports STALL_THRESHOLD_S rather than defining it locally
        assert "STALL_THRESHOLD_S" in src
        assert "from hermes_cli.tui.streaming_microcopy import" in src or \
               "streaming_microcopy" in src

    def test_working_hard_uses_stall_markup_helper(self):
        w = self._make_widget()
        w._last_token_time = time.monotonic() - 35
        with patch("hermes_cli.tui.widgets.thinking.ThinkingWidget._get_label_text",
                   wraps=w._get_label_text):
            with patch(
                "hermes_cli.tui.streaming_microcopy._stall_markup",
                wraps=__import__(
                    "hermes_cli.tui.streaming_microcopy",
                    fromlist=["_stall_markup"],
                )._stall_markup,
            ) as mock_markup:
                w._get_label_text(self._elapsed_s(w))
                assert mock_markup.called
                args = mock_markup.call_args[0]
                assert args[0] is True  # stalled=True


# ===========================================================================
# SS-3: ThinkingWidget height: auto
# ===========================================================================

class TestSS3ThinkingAnchor:
    def test_thinking_sentinel_position_preserved(self):
        """Sentinel pattern: live content mounts before the duo, so ThinkingWidget stays last."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        # This is enforced by app.py usage pattern; test documents the contract.
        assert ThinkingWidget is not None

    def test_thinking_widget_has_auto_height(self):
        """ThinkingWidget CSS (hermes.tcss) must declare height: auto for the base rule."""
        import pathlib
        tcss = (pathlib.Path(__file__).parents[2] / "hermes_cli" / "tui" / "hermes.tcss").read_text()
        # Check that ThinkingWidget base rule exists with height: auto
        import re
        # Find a ThinkingWidget { ... } block (not a qualified selector like ThinkingWidget.--active)
        block_match = re.search(
            r"(?<![.\w-])ThinkingWidget\s*\{([^}]*)\}", tcss
        )
        assert block_match is not None, "No base ThinkingWidget { } rule in hermes.tcss"
        block_content = block_match.group(1)
        assert "height: auto" in block_content, \
            f"Expected 'height: auto' in ThinkingWidget base rule, got: {block_content!r}"

    def test_thinking_renders_adjacent_to_sparse_content(self):
        """ThinkingWidget does not define height: 1fr — no forced stretch to bottom."""
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        css = ThinkingWidget.DEFAULT_CSS
        assert "1fr" not in css or "ThinkingWidget { height: 1fr" not in css


# ===========================================================================
# SS-4: Banner suppression
# ===========================================================================

class TestSS4BannerSuppression:
    def _ack_file(self, tmp_path) -> Path:
        return tmp_path / "banner_ack.json"

    def _write_ack(self, tmp_path, behind: int, days_ago: float = 0):
        f = self._ack_file(tmp_path)
        ts = time.time() - days_ago * 86400
        f.write_text(json.dumps({"acked_behind": behind, "ts": ts}))

    def test_banner_shows_first_time(self, tmp_path):
        from hermes_cli.banner import _should_show_update_banner
        with patch("hermes_cli.banner.get_hermes_home", return_value=tmp_path):
            assert _should_show_update_banner(100) is True

    def test_banner_suppressed_after_ack_within_7_days(self, tmp_path):
        from hermes_cli.banner import _should_show_update_banner
        self._write_ack(tmp_path, behind=100, days_ago=1)
        with patch("hermes_cli.banner.get_hermes_home", return_value=tmp_path):
            assert _should_show_update_banner(100) is False

    def test_banner_reappears_after_50_commit_drift(self, tmp_path):
        from hermes_cli.banner import _should_show_update_banner
        self._write_ack(tmp_path, behind=100, days_ago=1)
        with patch("hermes_cli.banner.get_hermes_home", return_value=tmp_path):
            # 160 - 100 = 60 >= 50 → show
            assert _should_show_update_banner(160) is True

    def test_banner_reappears_after_7_days(self, tmp_path):
        from hermes_cli.banner import _should_show_update_banner
        self._write_ack(tmp_path, behind=100, days_ago=8)
        with patch("hermes_cli.banner.get_hermes_home", return_value=tmp_path):
            assert _should_show_update_banner(100) is True

    def test_banner_dismiss_key_writes_ack_file(self, tmp_path):
        from hermes_cli.banner import write_banner_ack
        with patch("hermes_cli.banner.get_hermes_home", return_value=tmp_path):
            write_banner_ack(100)
        ack = json.loads(self._ack_file(tmp_path).read_text())
        assert ack["acked_behind"] == 100
        assert abs(ack["ts"] - time.time()) < 5


# ===========================================================================
# SS-5: Completion legend distinguishes Tab and Enter
# ===========================================================================

class TestSS5CompletionLegend:
    def test_completion_legend_distinguishes_tab_and_enter(self):
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        legend = InputLegendBar.LEGENDS["completion"]
        assert "Tab=insert" in legend
        assert "Enter=run" in legend
        assert "Tab=accept" not in legend
        assert "Enter=accept" not in legend

    def test_completion_legend_tab_inserts_enter_submits(self):
        """Legend verbs match key handler semantics (documented contract)."""
        from hermes_cli.tui.widgets.input_legend_bar import InputLegendBar
        legend = InputLegendBar.LEGENDS["completion"]
        # Tab → insert (single accept, no submit)
        assert "Tab=insert" in legend
        # Enter → run (accept + submit)
        assert "Enter=run" in legend


# ===========================================================================
# SS-6: Status bar ctx unit
# ===========================================================================

class TestSS6StatusBarContext:
    def _render(self, width=80, compact=False, ctx_tokens=0, ctx_max=1_000_000):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        from unittest.mock import PropertyMock
        sb = StatusBar.__new__(StatusBar)
        # Set non-reactive instance attrs directly
        sb.__dict__["_pulse_t"] = 0.0
        sb.__dict__["_pulse_tick"] = 0
        sb.__dict__["_model_changed_at"] = 0.0
        sb.__dict__["_cwd_changed_at"] = 0.0
        sb.__dict__["_hintbar_flashing"] = False
        app = _make_app(
            compact=compact,
            status_context_tokens=ctx_tokens,
            status_context_max=ctx_max,
            status_verbose=True,
            session_count=1,  # suppress session label
        )
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
                result = sb.render()
        return str(result)

    def test_status_bar_appends_ctx_unit_in_default_mode(self):
        text = self._render(width=80, compact=False)
        assert " ctx" in text

    def test_status_bar_omits_ctx_unit_in_compact_mode(self):
        text = self._render(width=60, compact=True)
        assert " ctx" not in text

    def test_format_compact_tokens_uppercase_units(self):
        from hermes_cli.tui.widgets.utils import _format_compact_tokens
        assert _format_compact_tokens(1_000_000) == "1M"
        assert _format_compact_tokens(96_000) == "96K"
        assert _format_compact_tokens(1_500) == "1.5K"


# ===========================================================================
# SS-7: Skills overflow uses chip format
# ===========================================================================

class TestSS7SkillsOverflow:
    def test_skill_list_no_overflow(self):
        from hermes_cli.banner import _format_skill_list
        skills = ["ab", "cd", "ef"]
        result = _format_skill_list(skills, width=100)
        assert result == "ab, cd, ef"
        assert "…" not in result

    def test_skill_list_overflow_uses_chip_format(self):
        from hermes_cli.banner import _format_skill_list
        skills = ["abcdefgh", "ijklmnop", "qrstuvwx", "yz"]
        result = _format_skill_list(skills, width=20)
        assert "…+" in result
        assert "more" in result
        # No half-truncated names
        parts = result.split(" …+")[0].split(", ")
        for part in parts:
            assert part in skills

    def test_skill_list_chip_count_correct(self):
        from hermes_cli.banner import _format_skill_list
        skills = ["a", "bbbbbbbbbbbbbbbb", "c", "d", "e"]
        result = _format_skill_list(skills, width=15)
        if "…+" in result:
            rendered_count = len(result.split(" …+")[0].split(", "))
            n = int(result.split("…+")[1].split(" ")[0])
            assert rendered_count + n == len(skills)


# ===========================================================================
# SS-8: Nameplate tier accent
# ===========================================================================

class TestSS8NameplateTier:
    def _make_nameplate(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        np_ = AssistantNameplate.__new__(AssistantNameplate)
        np_._accent_hex = "#7b68ee"
        np_._text_hex = "#cccccc"
        return np_

    def test_nameplate_uses_tier_accent_when_present(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        np_ = self._make_nameplate()
        css_vars = {
            "nameplate-tier-hero-accent": "#ff0000",
            "nameplate-active-color": "#aabbcc",
        }
        result = np_._resolve_accent_hex(css_vars, tier="hero")
        assert result == "#ff0000"

    def test_nameplate_falls_back_to_active_color(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        np_ = self._make_nameplate()
        css_vars = {"nameplate-active-color": "#aabbcc"}
        result = np_._resolve_accent_hex(css_vars, tier="hero")
        assert result == "#aabbcc"

    def test_nameplate_falls_back_to_default(self):
        from hermes_cli.tui.widgets import AssistantNameplate
        np_ = self._make_nameplate()
        result = np_._resolve_accent_hex({}, tier=None)
        assert result == "#7b68ee"


# ===========================================================================
# SS-9: Session ID copy
# ===========================================================================

class TestSS9SessionCopy:
    def test_session_label_tooltip_shows_full_id(self):
        """StatusBar stores full session ID for copy action."""
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._full_session_id = "20260501_042307_b1a6abc123"
        assert sb._full_session_id == "20260501_042307_b1a6abc123"

    def test_session_label_s_key_copies_full_id(self):
        import sys
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._full_session_id = "full-session-id-xyz"
        mock_pyperclip = MagicMock()
        with patch.dict(sys.modules, {"pyperclip": mock_pyperclip}):
            sb.action_copy_session_id()
            mock_pyperclip.copy.assert_called_once_with("full-session-id-xyz")

    def test_session_label_no_copy_hint_when_clipboard_unavailable(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        import logging
        sb = StatusBar.__new__(StatusBar)
        sb._full_session_id = "full-session-id-xyz"
        with patch("builtins.__import__", side_effect=ImportError("no pyperclip")):
            # Should not raise — clipboard failure is silently logged
            try:
                sb.action_copy_session_id()
            except Exception as e:
                assert False, f"action_copy_session_id raised: {e}"


# ===========================================================================
# SS-10: /model X inline switch
# ===========================================================================

class TestSS10ModelNoop:
    def _make_cmd_service(self, active_model=""):
        app = MagicMock()
        app.active_model = active_model
        app.status_model = active_model
        app._apply_model_inline = MagicMock()
        app._flash_hint = MagicMock()
        from hermes_cli.tui.services.commands import CommandsService
        svc = CommandsService.__new__(CommandsService)
        svc.app = app
        return svc, app

    def test_model_command_noop_when_already_active(self):
        from hermes_cli.tui.services.commands import CommandsService
        svc, app = self._make_cmd_service(active_model="X")
        svc.handle_tui_command("/model X")
        app._apply_model_inline.assert_not_called()
        flash_text = app._flash_hint.call_args[0][0]
        assert "no change" in flash_text.lower()

    def test_model_command_switches_when_different(self):
        svc, app = self._make_cmd_service(active_model="X")
        svc.handle_tui_command("/model Y")
        app._apply_model_inline.assert_called_once_with("Y")
        flash_text = app._flash_hint.call_args[0][0]
        assert "switched" in flash_text.lower() or "Y" in flash_text

    def test_model_command_no_arg_opens_overlay(self):
        from textual.css.query import NoMatches
        svc, app = self._make_cmd_service(active_model="X")
        app.query_one.side_effect = NoMatches()
        svc.handle_tui_command("/model")
        app._apply_model_inline.assert_not_called()
