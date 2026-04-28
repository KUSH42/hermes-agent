"""UX Audit E — Error / Edge States tests.

E1: empty-result header gets 'result-empty' class + '○ ' label prefix
E2: minified ToolPanel with error class keeps height:auto
E3: error-phase minimal hint includes both ^Z and ^C
E4: no caret/glyph key notation anywhere in hints
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from textual.geometry import Size
from textual.widget import Widget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bare_header(**kwargs):
    """ToolHeader via __new__ with minimal attribute stubs for _render_v4."""
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    defaults = dict(
        _label="run test",
        _tool_name="bash",
        _line_count=0,
        _panel=None,
        _spinner_char=None,
        _is_complete=True,
        _tool_icon_error=False,
        _primary_hero=None,
        _header_chips=[],
        _stats=None,
        _duration="",
        _has_affordances=False,
        _label_rich=None,
        _is_child_diff=False,
        _header_args={},
        _flash_msg=None,
        _flash_expires=0.0,
        _flash_tone="success",
        _error_kind=None,
        _tool_icon="",
        _full_path=None,
        _path_clickable=False,
        _is_child=False,
        _bold_label=False,
        _hidden=False,
        _shell_prompt=False,
        _stall_glyph_active=False,
        _streaming_kind_hint=None,
        _truncated_line_count=0,
        _no_underline=False,
        _hide_duration=False,
        _compact_tail=False,
        _elapsed_ms=None,
        _is_url=False,
        _classes=set(),
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(h, k, v)
    return h


def _render_header(h):
    """Call _render_v4 with spec_for stubbed at source and Widget.size patched."""
    fake_spec = MagicMock(
        render_header=True,
        primary_arg=None,
        category=MagicMock(value="shell"),
    )
    # spec_for is imported locally inside _render_v4; patch at source module.
    # update_node_styles needs a mounted app — suppress it for unit test.
    with patch("hermes_cli.tui.tool_category.spec_for", return_value=fake_spec):
        with patch.object(Widget, "size", new_callable=PropertyMock,
                          return_value=Size(80, 24)):
            with patch.object(Widget, "update_node_styles", return_value=None):
                with patch.object(h, "_accessible_mode", return_value=False):
                    with patch.object(h, "_colors", return_value=MagicMock(
                        success="#00ff00", error="#ff0000", accent="#5f87d7",
                        muted="#888888", separator_dim="#444444", icon_dim="#666666",
                    )):
                        return h._render_v4()


# ---------------------------------------------------------------------------
# E1 — Empty-result header visually distinct
# ---------------------------------------------------------------------------

class TestE1EmptyResultStyling:
    def test_empty_result_class_applied_when_empty(self):
        """_render_v4 on a DONE empty-result header adds 'result-empty' class."""
        h = _bare_header(_line_count=0, _is_complete=True, _tool_icon_error=False)
        _render_header(h)
        assert h.has_class("result-empty"), (
            f"expected 'result-empty' class after _render_v4; classes={h._classes!r}"
        )

    def test_empty_result_label_has_circle_prefix(self):
        """_render_v4 on a DONE empty-result header prefixes label with '○ '."""
        h = _bare_header(_line_count=0, _is_complete=True, _tool_icon_error=False)
        result = _render_header(h)
        assert result is not None, "_render_v4 returned None"
        assert "○ " in result.plain, (
            f"expected '○ ' prefix in label; plain={result.plain!r}"
        )

    def test_non_empty_result_no_circle_prefix(self):
        """_render_v4 on a DONE non-empty header does NOT add 'result-empty' or '○ '."""
        h = _bare_header(_line_count=5, _is_complete=True, _tool_icon_error=False)
        result = _render_header(h)
        assert not h.has_class("result-empty"), (
            f"'result-empty' class must not be added for non-empty result; classes={h._classes!r}"
        )
        if result is not None:
            assert not result.plain.startswith("○ "), (
                f"circle prefix must not appear for non-empty; plain={result.plain!r}"
            )


# ---------------------------------------------------------------------------
# E2 — Minified ToolPanel forces error blocks to expand
# ---------------------------------------------------------------------------

class TestE2MinifiedErrorExpand:
    def test_minified_no_error_has_class(self):
        """ToolPanel with only --minified class is minified (not error)."""
        from hermes_cli.tui.tool_panel._core import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._classes = set()
        panel.add_class = lambda *a: panel._classes.update(a)
        panel.has_class = lambda c: c in panel._classes
        panel.add_class("--minified")
        assert panel.has_class("--minified")
        assert not panel.has_class("tool-panel--error")

    def test_minified_error_has_both_classes(self):
        """ToolPanel with --minified and tool-panel--error has both classes."""
        from hermes_cli.tui.tool_panel._core import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._classes = set()
        panel.add_class = lambda *a: panel._classes.update(a)
        panel.has_class = lambda c: c in panel._classes
        panel.add_class("--minified")
        panel.add_class("tool-panel--error")
        assert panel.has_class("--minified")
        assert panel.has_class("tool-panel--error")

    def test_minified_error_css_rule_present(self):
        """TCSS has compound rule for minified+error height override."""
        import re
        tcss_path = (
            __file__.replace(
                "tests/tui/test_ux_audit_e_error_edge.py",
                "hermes_cli/tui/hermes.tcss",
            )
        )
        with open(tcss_path) as f:
            tcss = f.read()
        # Compound selector: ToolPanel.--minified.tool-panel--error
        assert re.search(
            r"ToolPanel\.--minified\.tool-panel--error\s*\{[^}]*height\s*:\s*auto",
            tcss,
        ), "Expected 'ToolPanel.--minified.tool-panel--error { height: auto; }' in hermes.tcss"


# ---------------------------------------------------------------------------
# E3 — Error-phase HintBar `minimal` includes `^C`
# ---------------------------------------------------------------------------

class TestE3ErrorMinimalHint:
    def setup_method(self, _):
        from hermes_cli.tui.widgets.status_bar import _hint_cache
        _hint_cache.clear()

    def test_error_minimal_contains_ctrl_z(self):
        """Error-phase minimal hint contains ⌃Z (undo)."""
        from hermes_cli.tui.widgets.status_bar import _build_hints
        result = _build_hints("error", "#ff0000")
        minimal = result["minimal"]
        assert "⌃Z" in minimal, f"⌃Z missing from error minimal: {minimal!r}"

    def test_error_minimal_contains_ctrl_c(self):
        """Error-phase minimal hint contains ⌃C (new prompt)."""
        from hermes_cli.tui.widgets.status_bar import _build_hints
        result = _build_hints("error", "#ff0000")
        minimal = result["minimal"]
        assert "⌃C" in minimal, f"⌃C missing from error minimal: {minimal!r}"

    def test_error_default_variant_unchanged(self):
        """Error-phase long variant also contains ⌃Z and ⌃C (regression guard)."""
        from hermes_cli.tui.widgets.status_bar import _build_hints
        result = _build_hints("error", "#ff0000")
        long_ = result["long"]
        assert "⌃Z" in long_, f"⌃Z missing from error long: {long_!r}"
        assert "⌃C" in long_, f"⌃C missing from error long: {long_!r}"


# ---------------------------------------------------------------------------
# E4 — StatusBar / HintBar key-symbol consistency
# ---------------------------------------------------------------------------

_ALL_PHASES = ["idle", "typing", "stream", "file", "browse", "overlay", "voice", "error", "unknown_phase"]


class TestE4KeySymbolConsistency:
    def setup_method(self, _):
        from hermes_cli.tui.widgets.status_bar import _hint_cache
        _hint_cache.clear()

    def test_no_caret_ctrl_notation_in_hints(self):
        """No ^C, ^Z, or ^F caret-form strings in any hint variant or streaming hint."""
        from hermes_cli.tui.widgets.status_bar import _build_hints, _build_streaming_hint
        all_text_parts: list[str] = []
        for phase in _ALL_PHASES:
            d = _build_hints(phase, "#ffffff")
            all_text_parts.extend(d.values())
        # streaming hint — returns (Text, list); extract plain text
        streaming_text, _ = _build_streaming_hint("#ffffff")
        all_text_parts.append(streaming_text.plain)
        combined = "\n".join(all_text_parts)
        for bad in ("^C", "^Z", "^F"):
            assert bad not in combined, (
                f"Found caret notation '{bad}' in hints.\n"
                f"Offending text:\n" + "\n".join(
                    p for p in all_text_parts if bad in p
                )
            )

    def test_no_glyph_enter_tab_space(self):
        """No ↵ (Enter), ⇥ (Tab), or ␣ (Space) glyph forms in any hint variant."""
        from hermes_cli.tui.widgets.status_bar import _build_hints
        all_text_parts: list[str] = []
        for phase in _ALL_PHASES:
            d = _build_hints(phase, "#ffffff")
            all_text_parts.extend(d.values())
        combined = "\n".join(all_text_parts)
        for bad in ("↵", "⇥", "␣"):
            assert bad not in combined, (
                f"Found glyph key form '{bad}' in hints; use Enter/Tab/Space instead.\n"
                f"Offending text:\n" + "\n".join(
                    p for p in all_text_parts if bad in p
                )
            )
