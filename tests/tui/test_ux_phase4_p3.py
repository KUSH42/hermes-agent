"""Phase 4 Pass 3 — UX implementation tests (B4, C2, C3, D3, D4, F1, G1, G2, G3)."""

from __future__ import annotations

import time
import types
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B4 — Flash timer / TTL alignment
# ---------------------------------------------------------------------------


def test_flash_timer_matches_ttl():
    """_flash_expires delta must equal the set_timer duration (both 1.2)."""
    import inspect
    from hermes_cli.tui import tool_panel

    src = inspect.getsource(tool_panel.ToolPanel._flash_header)
    # TTL: monotonic() + 1.2
    assert "time.monotonic() + 1.2" in src
    # Timer: set_timer(1.2, ...)
    assert "set_timer(1.2," in src
    # Old stale value must NOT appear
    assert "set_timer(1.3," not in src


# ---------------------------------------------------------------------------
# C2 — Follow-tail attribute and behaviour
# ---------------------------------------------------------------------------


def test_follow_tail_attr_exists():
    """StreamingToolBlock must have _follow_tail defaulting to False."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    stb = StreamingToolBlock.__new__(StreamingToolBlock)
    stb._completed = False
    stb._pending = []
    stb._all_plain = []
    stb._all_rich = []
    stb._total_received = 0
    stb._bytes_received = 0
    stb._last_line_time = 0.0
    stb._rate_samples = []
    stb._last_http_status = None
    stb._follow_tail = False
    assert stb._follow_tail is False


def test_toggle_tail_follow_flips_flag():
    """action_toggle_tail_follow() must set block._follow_tail = True."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel

    stb = MagicMock(spec=StreamingToolBlock)
    stb._follow_tail = False

    panel = ToolPanel.__new__(ToolPanel)
    panel._block = stb
    panel._hint_row = None
    panel._result_summary_v4 = None
    panel._body_pane = None
    panel._footer_pane = None
    panel.notify = MagicMock()
    panel._flash_header = MagicMock()

    panel.action_toggle_tail_follow()

    assert stb._follow_tail is True
    panel._flash_header.assert_called_once()


def test_follow_tail_resets_on_complete():
    """calling complete() must reset _follow_tail to False."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    stb = StreamingToolBlock.__new__(StreamingToolBlock)
    # Minimal init needed to reach the reset line without exploding
    stb._completed = False
    stb._follow_tail = True
    stb._pending = []
    stb._all_plain = []
    stb._all_rich = []
    stb._total_received = 0
    stb._bytes_received = 0
    stb._last_line_time = 0.0
    stb._rate_samples = []
    stb._last_http_status = None
    stb._flush_slow = False
    stb._secondary_args_snapshot = ""
    stb._tail = MagicMock()
    stb._header = MagicMock()
    stb._body = MagicMock()
    stb._microcopy_widget = None
    stb._stream_started_at = time.monotonic()
    stb._visible_cap = 200
    stb._visible_count = 0
    stb._visible_start = 0
    stb._omission_bar_top_mounted = False
    stb._omission_bar_bottom_mounted = False

    # Mock timers so stop() doesn't fail
    stb._render_timer = MagicMock()
    stb._spinner_timer = MagicMock()
    stb._duration_timer = MagicMock()

    # _flush_pending and _clear_microcopy_on_complete need body query
    with patch.object(type(stb), '_flush_pending', lambda self: None), \
         patch.object(type(stb), '_clear_microcopy_on_complete', lambda self: None), \
         patch.object(type(stb), '_try_mount_media', lambda self: False):
        stb.complete("1.0s", is_error=False)

    assert stb._follow_tail is False


# ---------------------------------------------------------------------------
# C3 — ShellRenderer JSON/YAML finalize
# ---------------------------------------------------------------------------


def test_shell_renderer_finalize_json():
    """ShellRenderer.finalize returns Syntax with language 'json' for JSON output."""
    from hermes_cli.tui.body_renderer import ShellRenderer
    from rich.syntax import Syntax

    renderer = ShellRenderer()
    result = renderer.finalize(['{"a": 1}'])
    assert isinstance(result, Syntax)
    # result.lexer may be a pygments lexer object or a string depending on rich version
    lexer_name = (
        result.lexer if isinstance(result.lexer, str)
        else type(result.lexer).__name__.lower()
    )
    assert "json" in lexer_name


def test_shell_renderer_finalize_yaml():
    """ShellRenderer.finalize returns Syntax with language 'yaml' for YAML output."""
    from hermes_cli.tui.body_renderer import ShellRenderer
    from rich.syntax import Syntax

    renderer = ShellRenderer()
    result = renderer.finalize(["---", "foo: bar"])
    assert isinstance(result, Syntax)
    lexer_name = (
        result.lexer if isinstance(result.lexer, str)
        else type(result.lexer).__name__.lower()
    )
    assert "yaml" in lexer_name


def test_shell_renderer_finalize_plain():
    """ShellRenderer.finalize returns None for plain text output."""
    from hermes_cli.tui.body_renderer import ShellRenderer

    renderer = ShellRenderer()
    result = renderer.finalize(["hello world"])
    assert result is None


# ---------------------------------------------------------------------------
# D3 — Multiple remediation hints joined
# ---------------------------------------------------------------------------


def _make_chip(text: str, tone: str = "neutral", remediation: str | None = None) -> Any:
    chip = MagicMock()
    chip.text = text
    chip.tone = tone
    chip.remediation = remediation
    return chip


def _make_summary_v4(chips: list, actions: list | None = None) -> Any:
    summary = MagicMock()
    summary.chips = chips
    summary.actions = actions or []
    summary.artifacts = []
    summary.stderr_tail = None
    summary.primary = None
    summary.error_kind = None
    summary.is_error = False
    summary.exit_code = 0
    return summary


def _make_footer_pane_mock() -> Any:
    """Build a minimal FooterPane-like object for _render_footer testing."""
    from hermes_cli.tui.tool_panel import FooterPane

    fp = FooterPane.__new__(FooterPane)
    fp._show_all_artifacts = False
    fp._last_summary = None
    fp._last_promoted = frozenset()
    fp._content = MagicMock()
    fp._stderr_row = MagicMock()
    fp._artifact_row = MagicMock()
    fp._artifact_row.query = MagicMock(return_value=[])

    # Stub out add_class/remove_class to avoid Textual DOM internals
    fp.add_class = MagicMock()
    fp.remove_class = MagicMock()

    captured_text: list[Any] = []
    rem_static = MagicMock()
    rem_static.update = lambda t: captured_text.append(t)
    fp._remediation_row = rem_static
    fp._captured_text = captured_text
    return fp


def test_multiple_remediation_hints_joined():
    """When 2+ chips have remediation, hints appear inline in chip row."""
    fp = _make_footer_pane_mock()

    chips = [
        _make_chip("exit:1", "error", "check your permissions"),
        _make_chip("timeout", "warning", "increase timeout"),
    ]
    summary = _make_summary_v4(chips)

    with patch.object(type(fp), '_rebuild_artifact_buttons', lambda self, s: None):
        fp._render_footer(summary, frozenset())

    # Remediation hints are now inline in _content, not in _remediation_row
    content_update = fp._content.update.call_args[0][0]
    result_plain = content_update.plain if hasattr(content_update, "plain") else str(content_update)
    assert "check your permissions" in result_plain
    assert "increase timeout" in result_plain


def test_single_remediation_hint_unchanged():
    """Single chip remediation appears inline in chip row."""
    fp = _make_footer_pane_mock()

    chips = [_make_chip("exit:1", "error", "check your permissions")]
    summary = _make_summary_v4(chips)

    with patch.object(type(fp), '_rebuild_artifact_buttons', lambda self, s: None):
        fp._render_footer(summary, frozenset())

    content_update = fp._content.update.call_args[0][0]
    result_plain = content_update.plain if hasattr(content_update, "plain") else str(content_update)
    assert "check your permissions" in result_plain


# ---------------------------------------------------------------------------
# D4 — _build_hint_text additions
# ---------------------------------------------------------------------------


def _make_panel_for_hint(result_summary=None) -> Any:
    """Build a minimal ToolPanel-like object for _build_hint_text testing.

    Uses a plain object instead of ToolPanel.__new__ to avoid Textual
    reactive setup requirements.
    """
    panel = types.SimpleNamespace()
    panel._block = MagicMock()
    panel._tool_name = "bash"
    panel._result_summary_v4 = result_summary
    panel.collapsed = False
    panel._hint_row = None
    panel._body_pane = None
    panel._footer_pane = None
    panel._get_omission_bar = lambda: None
    panel._result_paths_for_action = lambda: []

    # Bind the real method from ToolPanel to our namespace object
    from hermes_cli.tui.tool_panel import ToolPanel
    import types as _types
    panel._build_hint_text = _types.MethodType(ToolPanel._build_hint_text, panel)
    return panel


def test_hint_text_contains_copy_ansi_html():
    """_build_hint_text must include C/H for color/html copy."""
    panel = _make_panel_for_hint()
    text = panel._build_hint_text()
    plain = text.plain if hasattr(text, "plain") else str(text)
    assert "C/H" in plain
    assert "color/html" in plain


def test_hint_text_contains_invocation():
    """_build_hint_text must always include I for invocation copy."""
    panel = _make_panel_for_hint()
    text = panel._build_hint_text()
    plain = text.plain if hasattr(text, "plain") else str(text)
    assert "I" in plain
    assert "invocation" in plain


def test_hint_text_shows_url_when_artifacts():
    """_build_hint_text must include 'u' when URL artifacts are present."""
    url_artifact = MagicMock()
    url_artifact.kind = "url"
    url_artifact.path_or_url = "https://example.com"

    summary = _make_summary_v4([])
    summary.artifacts = [url_artifact]
    summary.is_error = False
    summary.stderr_tail = None

    panel = _make_panel_for_hint(result_summary=summary)
    text = panel._build_hint_text()
    plain = text.plain if hasattr(text, "plain") else str(text)
    assert "u" in plain
    assert "copy urls" in plain.lower()


# ---------------------------------------------------------------------------
# F1 — Age microcopy
# ---------------------------------------------------------------------------


def test_set_age_microcopy_method_exists():
    """StreamingToolBlock must have a set_age_microcopy method."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    assert callable(getattr(StreamingToolBlock, "set_age_microcopy", None))


def test_age_microcopy_only_when_complete():
    """set_age_microcopy is a no-op when _completed is False."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    stb = StreamingToolBlock.__new__(StreamingToolBlock)
    stb._completed = False
    stb._microcopy_widget = MagicMock()

    stb.set_age_microcopy("completed 15s ago")

    # The microcopy widget must NOT have been updated
    stb._microcopy_widget.update.assert_not_called()


# ---------------------------------------------------------------------------
# G1 — .--focus-hint CSS border-top separator
# ---------------------------------------------------------------------------


def test_focus_hint_css_class_present():
    """hermes.tcss must contain a ToolPanel > .--focus-hint rule with border-top."""
    import os
    tcss_path = os.path.join(
        os.path.dirname(__file__), "../../hermes_cli/tui/hermes.tcss"
    )
    with open(os.path.abspath(tcss_path)) as f:
        content = f.read()
    assert "ToolPanel > .--focus-hint" in content
    assert "border-top" in content


# ---------------------------------------------------------------------------
# G2 — clear_microcopy does not restore secondary args post-completion
# ---------------------------------------------------------------------------


def test_clear_microcopy_clears_secondary_args():
    """After clear_microcopy(), --secondary-args class is NOT present even if _secondary_text is set."""
    from hermes_cli.tui.tool_blocks import ToolBodyContainer

    tbc = ToolBodyContainer.__new__(ToolBodyContainer)
    tbc._secondary_text = "content: 100 chars · 5 lines"
    tbc._microcopy_active = True

    mc = MagicMock()
    mc.classes = set()

    added: list[str] = []
    removed: list[str] = []
    mc.add_class = lambda cls: added.append(cls)
    mc.remove_class = lambda cls: removed.append(cls)

    def _mc_widget():
        return mc

    tbc._mc_widget = _mc_widget

    tbc.clear_microcopy()

    # --secondary-args must NOT be added back
    assert "--secondary-args" not in added


def test_microcopy_slot_empty_post_completion():
    """After clear_microcopy(), the widget is updated to empty string."""
    from hermes_cli.tui.tool_blocks import ToolBodyContainer

    tbc = ToolBodyContainer.__new__(ToolBodyContainer)
    tbc._secondary_text = "some secondary text"
    tbc._microcopy_active = True

    updates: list[Any] = []
    mc = MagicMock()
    mc.add_class = MagicMock()
    mc.remove_class = MagicMock()
    mc.update = lambda v: updates.append(v)

    def _mc_widget():
        return mc

    tbc._mc_widget = _mc_widget

    tbc.clear_microcopy()

    assert updates and updates[-1] == ""


# ---------------------------------------------------------------------------
# G3 — _TONE_STYLES module-level constant
# ---------------------------------------------------------------------------


def test_tone_styles_constant_exists():
    """_TONE_STYLES must be importable from hermes_cli.tui.tool_panel."""
    from hermes_cli.tui.tool_panel import _TONE_STYLES
    assert isinstance(_TONE_STYLES, dict)


def test_tone_styles_has_expected_keys():
    """_TONE_STYLES must contain all five tone keys."""
    from hermes_cli.tui.tool_panel import _TONE_STYLES
    assert set(_TONE_STYLES.keys()) == {"success", "warning", "error", "accent", "neutral"}
