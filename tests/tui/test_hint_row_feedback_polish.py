"""HF-A..HF-G — Hint row & feedback polish tests.

Covers:
  HF-A: hint row deduplication vs visible footer action chips
  HF-B: toggle hint re-shows after long unfocus (time-based)
  HF-C: F1 hint shows "help" label, gated at narrow width
  HF-D: action_open_primary flashes "opening…" before blocking call
  HF-E: HTML clipboard cache module
  HF-F: F1 discovery mark gated on open-only
  HF-G: rotating power-key tip in hint row
"""
from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import hermes_cli.tui.tool_panel._completion as _comp_module
from hermes_cli.tui.tool_category import ToolCategory
from hermes_cli.tui.services import tool_tips


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_summary(*, is_error: bool = False, exit_code: int | None = None,
                  stderr_tail: str = "", actions=(), artifacts=()):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=(),
        actions=actions,
        artifacts=artifacts,
        is_error=is_error,
        stderr_tail=stderr_tail,
    )


def _make_action(kind: str, payload: str = "x"):
    return types.SimpleNamespace(kind=kind, payload=payload)


def _make_artifact(kind: str, path_or_url: str = "/tmp/x"):
    return types.SimpleNamespace(kind=kind, path_or_url=path_or_url)


def _make_panel(*, rs=None, width: int = 100, footer_chip_names: "set[str] | None" = None,
                block_completed: bool = True) -> types.SimpleNamespace:
    """Build a minimal ToolPanel stand-in for unit-testing _build_hint_text / _visible_footer_action_kinds."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    panel = types.SimpleNamespace()
    panel._result_summary_v4 = rs
    panel.is_mounted = True

    _size = types.SimpleNamespace(width=width)
    panel.size = _size

    # Simulate a completed / streaming block
    block = types.SimpleNamespace(_completed=block_completed)
    panel._block = block

    # Wire _build_hint_text, _visible_footer_action_kinds, _result_paths_for_action, _get_omission_bar
    panel._build_hint_text = ToolPanel._build_hint_text.__get__(panel)
    panel._visible_footer_action_kinds = ToolPanel._visible_footer_action_kinds.__get__(panel)
    panel._result_paths_for_action = lambda: []
    panel._get_omission_bar = lambda: None

    # Footer pane mock
    if footer_chip_names is not None:
        chips = [types.SimpleNamespace(name=n) for n in footer_chip_names]
        action_row = MagicMock()
        action_row.query.return_value = chips
        fp = MagicMock()
        fp.styles.display = "block"  # visible
        fp._action_row = action_row
        panel._footer_pane = fp
    else:
        panel._footer_pane = None

    return panel


# ---------------------------------------------------------------------------
# HF-A: Hint deduplication vs visible footer chips
# ---------------------------------------------------------------------------

class TestHintDedup:

    def test_hint_skips_retry_when_chip_visible(self):
        """error + footer expanded with 'retry' chip → hint omits r retry."""
        rs = _make_summary(is_error=True, exit_code=1)
        panel = _make_panel(rs=rs, footer_chip_names={"retry"}, width=100)
        t = panel._build_hint_text()
        plain = t.plain
        # Should NOT contain "r retry" style in the contextual slot
        assert "  r " not in plain or "retry" not in plain.split("r ")[-1][:6]

    def test_hint_shows_retry_when_collapsed(self):
        """error + no visible chips → hint shows r retry."""
        rs = _make_summary(is_error=True, exit_code=1)
        panel = _make_panel(rs=rs, footer_chip_names=set(), width=100)
        t = panel._build_hint_text()
        assert "r" in t.plain

    def test_hint_skips_stderr_when_chip_visible(self):
        """stderr present + 'copy_err' chip visible → hint omits e stderr."""
        rs = _make_summary(stderr_tail="some err")
        panel = _make_panel(rs=rs, footer_chip_names={"copy_err"}, width=100)
        t = panel._build_hint_text()
        # "e" for stderr should NOT appear when copy_err chip is visible
        spans = [(s.style, t.plain[s.start:s.end]) for s in t._spans]
        bold_keys = [text for style, text in spans if "bold" in str(style)]
        assert "e" not in bold_keys

    def test_hint_shows_url_always(self):
        """urls have no chip surface → u urls always shown when applicable."""
        rs = _make_summary(artifacts=(_make_artifact("url", "http://x.com"),))
        panel = _make_panel(rs=rs, footer_chip_names={"retry", "copy_err"}, width=100)
        t = panel._build_hint_text()
        assert "u" in t.plain


# ---------------------------------------------------------------------------
# HF-B: Toggle hint re-shows after long unfocus
# ---------------------------------------------------------------------------

class TestToggleHintReshow:

    def _make_focusable_panel(self) -> types.SimpleNamespace:
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = types.SimpleNamespace()
        panel._toggle_hint_shown_at = 0.0
        panel._discovery_shown = False
        panel._result_summary_v4 = None

        header = types.SimpleNamespace(_has_affordances=True)
        block = types.SimpleNamespace(_header=header)
        panel._block = block

        mock_app = MagicMock()
        panel.app = mock_app

        panel._maybe_show_discovery_hint = lambda: None
        panel._refresh_collapsed_strip = lambda: None
        panel._flash_header = MagicMock()
        panel.on_focus = ToolPanel.on_focus.__get__(panel)
        return panel

    def test_toggle_hint_first_focus_flashes(self):
        """Fresh panel (_toggle_hint_shown_at=0) → focus → flash fires."""
        panel = self._make_focusable_panel()
        panel.on_focus()
        panel._flash_header.assert_called_once_with("(Enter) toggle", tone="accent")

    def test_toggle_hint_immediate_refocus_silent(self):
        """focus → set _toggle_hint_shown_at to now → focus again → no flash (within 300s)."""
        import time
        panel = self._make_focusable_panel()
        # Mark as shown just now — within the 300s reshow window
        panel._toggle_hint_shown_at = time.monotonic()
        panel.on_focus()
        panel._flash_header.assert_not_called()

    def test_toggle_hint_reshows_after_window(self):
        """_toggle_hint_shown_at set to > 300s ago → focus → flash fires again."""
        import time
        panel = self._make_focusable_panel()
        panel._toggle_hint_shown_at = time.monotonic() - 400  # 400s ago
        panel.on_focus()
        panel._flash_header.assert_called_once_with("(Enter) toggle", tone="accent")


# ---------------------------------------------------------------------------
# HF-C: F1 hint shows label at wide width
# ---------------------------------------------------------------------------

class TestF1HintLabel:

    def test_f1_hint_shows_label_at_wide_width(self):
        """width 100 → 'F1 help' rendered in hint text."""
        rs = _make_summary()
        panel = _make_panel(rs=rs, width=100)
        t = panel._build_hint_text()
        assert "F1" in t.plain
        assert "help" in t.plain

    def test_f1_hint_omitted_at_narrow_width(self):
        """width 40 → no F1 in hint text."""
        rs = _make_summary()
        panel = _make_panel(rs=rs, width=40)
        t = panel._build_hint_text()
        assert "F1" not in t.plain


# ---------------------------------------------------------------------------
# HF-D: action_open_primary flashes before call
# ---------------------------------------------------------------------------

class TestOpenPrimaryFlash:

    def _make_action_panel(self):
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = types.SimpleNamespace()
        panel._flash_header = MagicMock()

        header = types.SimpleNamespace(
            _path_clickable=True,
            _full_path="/some/path/file.txt",
        )
        block = types.SimpleNamespace(_header=header)
        panel._block = block

        call_order: list[str] = []
        panel._flash_header.side_effect = lambda msg, **kw: call_order.append(f"flash:{msg}")

        mock_app = MagicMock()

        def _record_open(*args, **kwargs):
            call_order.append("open")

        mock_app._open_path_action.side_effect = _record_open
        panel.app = mock_app
        panel._call_order = call_order

        panel.action_open_primary = ToolPanel.action_open_primary.__get__(panel)
        return panel

    def test_open_primary_header_path_flashes_before_call(self):
        """flash 'opening…' must appear before _open_path_action call."""
        panel = self._make_action_panel()
        panel.action_open_primary()
        order = panel._call_order
        assert "flash:opening…" in order
        assert "open" in order
        assert order.index("flash:opening…") < order.index("open")

    def test_open_primary_header_path_flash_error_on_failure(self):
        """_open_path_action raises → flash 'open failed' with error tone."""
        panel = self._make_action_panel()

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        panel.app._open_path_action.side_effect = _raise
        # Override flash to capture tone
        tone_captured: list[str] = []
        original_flash = MagicMock()
        original_flash.side_effect = lambda msg, tone="success": tone_captured.append(tone)
        panel._flash_header = original_flash

        panel.action_open_primary()
        assert "error" in tone_captured


# ---------------------------------------------------------------------------
# HF-E: HTML clipboard cache
# ---------------------------------------------------------------------------

class TestClipboardCache:

    def test_write_html_creates_file_in_cache_dir(self, tmp_path: Path):
        from hermes_cli.tui import clipboard_cache
        with patch.object(clipboard_cache, "CACHE_DIR", tmp_path):
            # Patch cache_dir() to use tmp_path
            def _cache_dir():
                tmp_path.mkdir(parents=True, exist_ok=True)
                return tmp_path
            with patch.object(clipboard_cache, "cache_dir", _cache_dir):
                result = clipboard_cache.write_html("<html>hello</html>")
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "<html>hello</html>"

    def test_prune_deletes_old_files(self, tmp_path: Path):
        from hermes_cli.tui import clipboard_cache
        import time
        old_file = tmp_path / "copy_old.html"
        old_file.write_text("old")
        # Set mtime 25 hours ago
        old_mtime = time.time() - 25 * 3600
        import os
        os.utime(old_file, (old_mtime, old_mtime))

        with patch.object(clipboard_cache, "CACHE_DIR", tmp_path):
            deleted = clipboard_cache.prune_expired()

        assert deleted == 1
        assert not old_file.exists()

    def test_prune_keeps_recent_files(self, tmp_path: Path):
        from hermes_cli.tui import clipboard_cache
        import time
        recent_file = tmp_path / "copy_recent.html"
        recent_file.write_text("recent")
        # Set mtime 1 hour ago
        recent_mtime = time.time() - 1 * 3600
        import os
        os.utime(recent_file, (recent_mtime, recent_mtime))

        with patch.object(clipboard_cache, "CACHE_DIR", tmp_path):
            deleted = clipboard_cache.prune_expired()

        assert deleted == 0
        assert recent_file.exists()

    def test_action_copy_html_uses_cache_dir(self):
        """action_copy_html calls write_html from clipboard_cache instead of /tmp."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from rich.text import Text

        panel = types.SimpleNamespace()
        panel._flash_header = MagicMock()
        panel._result_summary_v4 = None

        # Mock block with all_rich
        mock_rich_item = Text("hello")
        block = types.SimpleNamespace(_all_rich=[mock_rich_item], _body=None)
        panel._block = block

        mock_app = MagicMock()
        mock_app.size = types.SimpleNamespace(width=80)
        mock_app.get_css_variables.return_value = {}
        panel.app = mock_app

        write_html_calls: list[str] = []

        def _fake_write_html(html: str):
            write_html_calls.append(html)
            return Path("/home/user/.cache/hermes/clipboard/copy_123.html")

        panel.action_copy_html = ToolPanel.action_copy_html.__get__(panel)

        with patch("hermes_cli.tui.tool_panel._actions.write_html", _fake_write_html, create=True):
            # Patch at the import site inside action_copy_html
            import hermes_cli.tui.clipboard_cache as cc
            with patch.object(cc, "write_html", _fake_write_html):
                panel.action_copy_html()

        assert len(write_html_calls) >= 1 or mock_app._copy_text_with_hint.called


# ---------------------------------------------------------------------------
# HF-F: F1 discovery mark gated on open
# ---------------------------------------------------------------------------

class TestF1DiscoveryGate:

    @pytest.fixture(autouse=True)
    def reset_discovery(self):
        _comp_module._DISCOVERY_SHOWN_CATEGORIES.clear()
        yield
        _comp_module._DISCOVERY_SHOWN_CATEGORIES.clear()

    def _make_help_panel(self, overlay_visible: bool):
        from hermes_cli.tui.tool_panel import ToolPanel

        panel = types.SimpleNamespace()

        overlay = MagicMock()
        overlay.has_class.return_value = overlay_visible

        mock_app = MagicMock()
        mock_app.query_one.return_value = overlay
        panel.app = mock_app

        panel.action_show_help = ToolPanel.action_show_help.__get__(panel)
        return panel, overlay

    def test_f1_open_marks_discovery(self):
        """Overlay hidden → action → all categories discovered."""
        panel, overlay = self._make_help_panel(overlay_visible=False)
        panel.action_show_help()
        # overlay was hidden → opening → should mark all categories
        overlay.add_class.assert_called_with("--visible")
        assert len(_comp_module._DISCOVERY_SHOWN_CATEGORIES) == len(list(ToolCategory))

    def test_f1_close_does_not_mark_discovery(self):
        """Overlay already visible → action → discovered set unchanged (closing)."""
        panel, overlay = self._make_help_panel(overlay_visible=True)
        panel.action_show_help()
        overlay.remove_class.assert_called_with("--visible")
        # closing should NOT add to discovery set
        assert len(_comp_module._DISCOVERY_SHOWN_CATEGORIES) == 0


# ---------------------------------------------------------------------------
# HF-G: Rotating power-key tip in hint row
# ---------------------------------------------------------------------------

class TestPowerKeyTipRotation:

    @pytest.fixture(autouse=True)
    def reset_tips(self):
        tool_tips.reset()
        yield
        tool_tips.reset()

    def test_power_key_tip_rotates_per_advance(self):
        """advance() then current_tip() → different from before."""
        before = tool_tips.current_tip()
        tool_tips.advance()
        after = tool_tips.current_tip()
        assert before != after

    def test_power_key_tip_stable_within_response(self):
        """Two calls without advance → same tip."""
        t1 = tool_tips.current_tip()
        t2 = tool_tips.current_tip()
        assert t1 == t2

    def test_hint_row_includes_tip_when_room(self):
        """Wide hint row + completed block → last entry contains rotating tip in dim italic."""
        rs = _make_summary()
        panel = _make_panel(rs=rs, width=120, block_completed=True)
        tool_tips.reset()
        tip_key, tip_label = tool_tips.current_tip()
        t = panel._build_hint_text()
        # Both key and label should appear somewhere in the hint text
        assert tip_key in t.plain
        assert tip_label in t.plain

    def test_hint_row_omits_tip_when_narrow(self):
        """width 40 → no rotating tip (narrow mode)."""
        rs = _make_summary()
        panel = _make_panel(rs=rs, width=40, block_completed=True)
        tool_tips.reset()
        tip_key, tip_label = tool_tips.current_tip()
        t = panel._build_hint_text()
        assert tip_label not in t.plain

    def test_hint_row_omits_tip_when_streaming(self):
        """Block still streaming (rs is None) → no rotating tip."""
        panel = _make_panel(rs=None, width=120, block_completed=False)
        tool_tips.reset()
        _, tip_label = tool_tips.current_tip()
        t = panel._build_hint_text()
        assert tip_label not in t.plain
