"""UX Audit F — Overlays / Polish (F2–F8) regression tests.

All tests are pure-unit or text-parse; no full app run required.
"""
from __future__ import annotations

import re
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers — TCSS parsing
# ---------------------------------------------------------------------------

TCSS_PATH = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"


def _read_tcss() -> str:
    return TCSS_PATH.read_text()


def _extract_css_block(
    tcss: str,
    selector_fragment: str,
    exclude: str = "",
    require_terminal: bool = False,
) -> str:
    """Return the rule-block text that contains selector_fragment.

    Skips comment-only lines (stripped lines starting with '/*' or '*').
    Finds the first non-comment line containing selector_fragment (optionally
    excluding lines that also contain exclude), then collects until braces balance.
    Returns the full block including selector + declarations.

    If require_terminal=True, selector_fragment must appear at the END of the
    selector token — i.e. not followed by whitespace + another element.
    This avoids matching "ToolPanel:focus _Child { ... }" when looking for
    the standalone "ToolPanel:focus { ... }" block.
    """
    lines = tcss.splitlines()
    collecting = False
    block_lines: list[str] = []
    brace_depth = 0

    for line in lines:
        stripped = line.strip()
        is_comment = stripped.startswith("/*") or stripped.startswith("*")

        if not collecting:
            if is_comment:
                continue  # skip comment lines during selector search
            if selector_fragment in line:
                if exclude and exclude in line:
                    continue
                if require_terminal:
                    # Ensure selector_fragment is not followed by whitespace +
                    # another element (descendant combinator pattern).
                    idx = line.index(selector_fragment)
                    after = line[idx + len(selector_fragment):]
                    # OK suffixes: end-of-line, comma, { , whitespace-then-{
                    if re.match(r"^\s*[{,]", after) is None and after.strip() != "":
                        continue
                collecting = True
                block_lines.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0 and "{" not in line:
                    # selector-only line — keep accumulating
                    continue
                if brace_depth <= 0:
                    break  # degenerate single-line block
        else:
            block_lines.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                break

    return "\n".join(block_lines)


# ---------------------------------------------------------------------------
# F2 helpers — bypass Textual reactive + read-only property machinery
# ---------------------------------------------------------------------------

def _make_vcl_state() -> object:
    """Return a VirtualCompletionList-like instance with reactive and property
    machinery bypassed, sufficient to exercise render_line(0) in empty-state.

    We create an isolated subclass that:
    - Shadows all reactives with plain class attributes
    - Overrides the read-only `size` property with a stub
    - Skips super().__init__() entirely (no event loop needed)
    """
    from hermes_cli.tui.completion_list import VirtualCompletionList
    from rich.style import Style
    from rich.console import Console

    from rich.console import Console as _Console
    _stub_size = types.SimpleNamespace(width=40, height=5)
    _stub_scroll_offset = (0, 0)
    _stub_app = types.SimpleNamespace(console=_Console(no_color=True, width=40))

    class _Stub(VirtualCompletionList):
        # Shadow every reactive descriptor with a plain class attribute so the
        # descriptor __set__ is never invoked (no _id check, no event loop).
        items = tuple()            # type: ignore[assignment]
        highlighted = -1           # type: ignore[assignment]
        searching = False          # type: ignore[assignment]
        empty_reason = ""          # type: ignore[assignment]
        _shimmer_phase = 0         # type: ignore[assignment]
        virtual_size = None        # type: ignore[assignment]

        # Override read-only properties inherited from Textual Widget/ScrollView.
        size = _stub_size                      # type: ignore[assignment]
        scroll_offset = _stub_scroll_offset    # type: ignore[assignment]
        app = _stub_app                        # type: ignore[assignment]

        def __init__(self) -> None:  # type: ignore[override]
            # Intentionally skip super().__init__() — no Textual runtime needed.
            self._fuzzy_match_style = "bold"
            self._selected_style = Style()
            self._style_text_normal = Style(dim=True)
            self._style_text_selected = Style()
            self._style_path_suffix = Style(dim=True)
            self._style_empty = Style()
            self._shimmer_timer = None
            self._auto_close_timer = None
            self._auto_close_delay = 0.0
            self._auto_close_started_at = 0.0
            self.current_query = ""
            self._no_color = True

    return _Stub()


def _render_line0_text(vcl) -> str:
    strip = vcl.render_line(0)
    return "".join(seg.text for seg in strip)


def _static_text(widget) -> str:
    """Extract the text content of a Textual Static widget (name-mangled attr)."""
    # The attribute is name-mangled to _Static__content in Textual's Static class.
    return str(getattr(widget, "_Static__content", ""))


# ===========================================================================
# F2 — CompletionList auto-dismiss countdown hint
# ===========================================================================


class TestF2CompletionAutoDismissHint:
    def test_empty_shows_countdown_when_timer_active(self):
        """Timer active + 1s elapsed of 3s → shows 'closes in 2s'."""
        vcl = _make_vcl_state()
        vcl._auto_close_timer = object()  # sentinel — non-None
        vcl._auto_close_delay = 3.0
        vcl._auto_close_started_at = time.monotonic() - 1.0

        text = _render_line0_text(vcl)

        assert "closes in" in text
        assert "2s" in text

    def test_empty_no_countdown_without_timer(self):
        """No active timer → empty-state renders without countdown."""
        vcl = _make_vcl_state()
        vcl._auto_close_timer = None
        vcl._auto_close_delay = 0.0

        text = _render_line0_text(vcl)

        assert "closes in" not in text

    def test_empty_countdown_clamps_to_zero(self):
        """Timer started 4s ago with 3s delay → clamps to 0s, not negative."""
        vcl = _make_vcl_state()
        vcl._auto_close_timer = object()
        vcl._auto_close_delay = 3.0
        vcl._auto_close_started_at = time.monotonic() - 4.0

        text = _render_line0_text(vcl)

        assert "closes in 0s" in text
        assert "-" not in text  # no negative values in the output


# ===========================================================================
# F3 — SkillPicker disabled badge uses [dim](disabled)[/dim]
# ===========================================================================


class TestF3SkillPickerDisabledBadge:
    def test_disabled_skill_renders_dim_label_not_d_literal(self):
        """Disabled candidate should produce '(disabled)', not '[d]'."""
        source = (
            Path(__file__).parent.parent.parent
            / "hermes_cli" / "tui" / "overlays" / "skill_picker.py"
        )
        content = source.read_text()

        assert '"  [d]"' not in content, "Old [d] badge literal still present"
        assert "[dim](disabled)[/dim]" in content


# ===========================================================================
# F4 — SkillPicker empty state when all filtered candidates disabled
# ===========================================================================


class TestF4SkillPickerEmptyState:
    @staticmethod
    def _make_candidate(name: str, enabled: bool) -> object:
        c = MagicMock()
        c.name = name
        c.enabled = enabled
        c.source = "user"
        c.description = ""
        c.trigger_phrases = []
        c.do_not_trigger = []
        return c

    def test_filter_only_disabled_shows_disabled_message(self):
        """When filter matches only disabled skills, detail pane says so."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay

        overlay = SkillPickerOverlay.__new__(SkillPickerOverlay)
        overlay._filter = "foo"
        overlay._candidates = [self._make_candidate("foobar", enabled=False)]

        mounted: list[object] = []

        detail_mock = MagicMock()
        detail_mock.remove_children = MagicMock()
        detail_mock.mount.side_effect = lambda *w, **_kw: mounted.extend(w)

        def _query_one(selector, klass=None):
            if "picker-right" in selector:
                return detail_mock
            raise Exception(f"Unexpected query: {selector}")

        overlay.query_one = _query_one

        overlay._refresh_detail()

        assert mounted, "Expected at least one widget to be mounted"
        from textual.widgets import Static
        first = mounted[0]
        assert isinstance(first, Static), f"Expected Static, got {type(first)}"
        text = _static_text(first)
        assert "All matching skills are disabled" in text, (
            f"Expected disabled message, got: {text!r}"
        )

    def test_filter_with_enabled_shows_default_prompt(self):
        """When at least one enabled candidate exists, default prompt on no selection."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay

        overlay = SkillPickerOverlay.__new__(SkillPickerOverlay)
        overlay._filter = ""
        overlay._candidates = [self._make_candidate("alpha", enabled=True)]

        mounted: list[object] = []
        detail_mock = MagicMock()
        detail_mock.remove_children = MagicMock()
        detail_mock.mount.side_effect = lambda *w, **_kw: mounted.extend(w)

        def _query_one(selector, klass=None):
            if "picker-right" in selector:
                return detail_mock
            raise Exception(f"Unexpected: {selector}")

        overlay.query_one = _query_one
        overlay._selected_candidate = lambda: None

        overlay._refresh_detail()

        from textual.widgets import Static
        assert mounted, "Expected at least one widget to be mounted"
        first = mounted[0]
        assert isinstance(first, Static)
        assert "Select a skill to see details" in _static_text(first)


# ===========================================================================
# F5 — SkillPicker left-pane border token
# ===========================================================================


class TestF5SkillPickerBorderToken:
    def test_skill_picker_left_pane_uses_pane_border(self):
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay

        css = SkillPickerOverlay.DEFAULT_CSS
        assert "$pane-border" in css, "Expected $pane-border token in DEFAULT_CSS"
        for line in css.splitlines():
            if "border-right" in line:
                assert "$primary" not in line, (
                    f"border-right still references $primary: {line!r}"
                )


# ===========================================================================
# F6 — OmissionBar reset-button opacity
# ===========================================================================


class TestF6OmissionBarResetOpacity:
    def test_omission_reset_button_70pct(self):
        tcss = _read_tcss()
        for line in tcss.splitlines():
            if "--at-default" in line and "color" in line:
                assert "70%" in line, (
                    f"Expected 70% opacity for --at-default, got: {line!r}"
                )
                assert "50%" not in line, (
                    f"Old 50% opacity still present: {line!r}"
                )
                return
        pytest.fail("Could not find OmissionBar Button.--at-default rule in hermes.tcss")


# ===========================================================================
# F7 — Unified focus ring
# ===========================================================================


class TestF7UnifiedFocusRing:
    def test_clarify_widget_focus_has_outline_60pct(self):
        tcss = _read_tcss()
        block = _extract_css_block(tcss, "ClarifyWidget:focus")
        assert "outline" in block, f"ClarifyWidget:focus block missing outline:\n{block}"
        assert "60%" in block, f"Expected 60% in ClarifyWidget:focus block:\n{block}"

    def test_clarify_widget_focus_has_background_tint(self):
        tcss = _read_tcss()
        block = _extract_css_block(tcss, "ClarifyWidget:focus")
        assert "background" in block, f"ClarifyWidget:focus block missing background:\n{block}"
        assert "8%" in block, f"Expected 8% in ClarifyWidget:focus block:\n{block}"

    def test_tool_panel_focus_has_outline(self):
        tcss = _read_tcss()
        # Must match standalone ToolPanel:focus { ... } block, not focus-within
        # or descendant combinator rules like "ToolPanel:focus _Child { ... }".
        block = _extract_css_block(
            tcss, "ToolPanel:focus", exclude="focus-within", require_terminal=True
        )
        assert "outline" in block, f"ToolPanel:focus block missing outline:\n{block}"
        assert "60%" in block, f"Expected 60% in ToolPanel:focus block:\n{block}"


# ===========================================================================
# F8 — ApprovalWidget diff max-height responsive
# ===========================================================================


class TestF8ApprovalDiffResponsive:
    def _get_block(self) -> str:
        return _extract_css_block(_read_tcss(), "approval-diff")

    def test_approval_diff_max_height_is_percent(self):
        block = self._get_block()
        match = re.search(r"max-height\s*:\s*(\S+)", block)
        assert match, f"Could not find max-height in block:\n{block}"
        value = match.group(1).rstrip(";")
        assert "%" in value, f"max-height should be a percentage, got: {value!r}"

    def test_approval_diff_has_min_height(self):
        block = self._get_block()
        assert "min-height" in block, f"approval-diff block missing min-height:\n{block}"
        assert "6" in block, f"Expected min-height: 6 in block:\n{block}"

    def test_approval_diff_no_literal_20(self):
        block = self._get_block()
        assert not re.search(r"max-height\s*:\s*20\b", block), (
            f"Literal max-height: 20 still present in approval-diff block:\n{block}"
        )
