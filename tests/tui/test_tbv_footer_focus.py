"""TBV — Footer focus gate tests.

Spec: /home/xush/.hermes/spec_tbv_footer_focus_gate.md

13 tests across 6 classes — covers TBV-FF-H1 (dead CSS, can_focus guard, logging)
and TBV-FF-H2 (focus consolidation to :focus-within) and TBV-FF-M1 (IL-FOOTER-1).
"""
from __future__ import annotations

import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_TUI_ROOT = _REPO_ROOT / "hermes_cli" / "tui"
_TOOL_PANEL_DIR = _TUI_ROOT / "tool_panel"
_HERMES_TCSS = _TUI_ROOT / "hermes.tcss"


class TestDeadCssClasses:
    """H1 — --browsed and --expanded are never applied in Python source."""

    def test_dead_browsed_css_class_never_applied(self):
        pattern = re.compile(r'add_class\(.*--browsed')
        offenders = []
        for py_file in _TOOL_PANEL_DIR.rglob("*.py"):
            for n, line in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{py_file.relative_to(_REPO_ROOT)}:{n}: {line.strip()}")
        assert offenders == [], (
            "TBV-FF-H1: --browsed class is never set; these lines are unexpected:\n"
            + "\n".join(offenders)
        )

    def test_dead_expanded_css_class_never_applied(self):
        pattern = re.compile(r'add_class\(.*--expanded')
        offenders = []
        for py_file in _TOOL_PANEL_DIR.rglob("*.py"):
            for n, line in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{py_file.relative_to(_REPO_ROOT)}:{n}: {line.strip()}")
        assert offenders == [], (
            "TBV-FF-H1: --expanded class is never set on ToolPanel; these lines are unexpected:\n"
            + "\n".join(offenders)
        )


class TestCollapsedActionStripFocus:
    """H1 — _CollapsedActionStrip.can_focus must be False."""

    def test_collapsed_action_strip_can_focus_is_false(self):
        from hermes_cli.tui.tool_panel._footer import _CollapsedActionStrip
        assert _CollapsedActionStrip.can_focus is False, (
            "TBV-FF-H1: _CollapsedActionStrip.can_focus must be False to prevent "
            ":focus-within from firing on parent ToolPanel when the strip receives focus."
        )


class TestFocusLogging:
    """H1 — ToolPanel.on_focus and on_blur emit DEBUG logs with TBV-FF-H1 tag."""

    def test_on_focus_blur_logs_debug(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel

        panel = object.__new__(ToolPanel)

        with patch("hermes_cli.tui.tool_panel._core._log") as mock_log:
            panel.on_focus()
            panel.on_blur()

        assert mock_log.debug.call_count == 2, (
            f"Expected 2 debug calls, got {mock_log.debug.call_count}"
        )
        calls_args = [str(call) for call in mock_log.debug.call_args_list]
        assert all("TBV-FF-H1" in s for s in calls_args), (
            f"Not all debug calls contain 'TBV-FF-H1': {calls_args}"
        )


class TestActionRowVisibilityIntegration:
    """H1 — action-row visibility gates: panel-focused shows, composer-focused hides."""

    def test_action_row_hidden_default_in_css(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        css = ToolPanel.DEFAULT_CSS
        assert "FooterPane.has-actions > .action-row { display: none; }" in css, (
            "DEFAULT_CSS must set .action-row to display:none as the default hide rule."
        )

    def test_focus_within_rule_is_sole_action_row_show_gate(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        css = ToolPanel.DEFAULT_CSS
        focus_pattern = re.compile(
            r'ToolPanel:focus\s+FooterPane\.has-actions\s*>\s*\.action-row\s*\{\s*display:\s*block'
        )
        assert not focus_pattern.search(css), (
            "TBV-FF-H2: ToolPanel:focus .action-row display:block rule must be removed from "
            "DEFAULT_CSS; the sole gate is ToolPanel:focus-within in hermes.tcss."
        )
        tcss_text = _HERMES_TCSS.read_text(errors="replace")
        assert "ToolPanel:focus-within FooterPane.has-actions > .action-row { display: block; }" in tcss_text, (
            "TBV-FF-H2: ToolPanel:focus-within gate must exist in hermes.tcss."
        )


class TestFocusWithinConsolidation:
    """H2 — :focus-within is the sole gate; :focus action-row rule is removed."""

    def test_focus_within_subsumes_focus_for_action_row(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        css = ToolPanel.DEFAULT_CSS
        pattern = re.compile(
            r'ToolPanel:focus\s+FooterPane\.has-actions\s*>\s*\.action-row\s*\{\s*display:\s*block'
        )
        assert not pattern.search(css), (
            "TBV-FF-H2: redundant :focus action-row display:block rule found in DEFAULT_CSS. "
            "It should have been removed — :focus-within in hermes.tcss subsumes it."
        )

    def test_focus_within_rule_exists_in_hermes_tcss(self):
        tcss_text = _HERMES_TCSS.read_text(errors="replace")
        target = "ToolPanel:focus-within FooterPane.has-actions > .action-row { display: block; }"
        count = tcss_text.count(target)
        assert count == 1, (
            f"TBV-FF-H2: expected exactly 1 match of the :focus-within .action-row rule in "
            f"hermes.tcss, found {count}."
        )

    def test_dead_browsed_rule_removed_from_default_css(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        assert "--browsed" not in ToolPanel.DEFAULT_CSS, (
            "TBV-FF-H1: --browsed CSS rule must be removed from DEFAULT_CSS."
        )

    def test_dead_expanded_rule_removed_from_default_css(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        assert "--expanded" not in ToolPanel.DEFAULT_CSS, (
            "TBV-FF-H1: --expanded CSS rule must be removed from DEFAULT_CSS."
        )


class TestInvariantILFooter1:
    """M1 — IL-FOOTER-1 a/b/c invariant assertions."""

    def test_invariant_il_footer_1a_no_action_row_rule_in_tool_panel_python(self):
        pattern = re.compile(
            r'FooterPane\.has-actions\s*>\s*\.action-row\s*\{\s*display:\s*block'
        )
        offenders = []
        for py_file in _TOOL_PANEL_DIR.rglob("*.py"):
            for n, line in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{py_file.relative_to(_REPO_ROOT)}:{n}: {line.strip()}")
        assert offenders == [], (
            "IL-FOOTER-1a: all .action-row display:block rules must live exclusively in "
            "hermes.tcss, not in Python source:\n" + "\n".join(offenders)
        )

    def test_invariant_il_footer_1b_single_action_row_rule_in_hermes_tcss(self):
        tcss_text = _HERMES_TCSS.read_text(errors="replace")
        pattern = re.compile(
            r'FooterPane\.has-actions\s*>\s*\.action-row\s*\{\s*display:\s*block'
        )
        matching_lines = [
            line.strip()
            for line in tcss_text.splitlines()
            if pattern.search(line)
        ]
        assert len(matching_lines) == 1, (
            f"IL-FOOTER-1b: expected exactly 1 .action-row display:block rule in hermes.tcss, "
            f"found {len(matching_lines)}: {matching_lines}"
        )
        assert ":focus-within" in matching_lines[0], (
            f"IL-FOOTER-1b: the sole .action-row rule must use :focus-within; "
            f"found: {matching_lines[0]}"
        )

    def test_invariant_il_footer_1c_no_dead_class_mutations(self):
        pattern = re.compile(r'add_class\(.*--(browsed|expanded)')
        offenders = []
        for py_file in _TUI_ROOT.rglob("*.py"):
            for n, line in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{py_file.relative_to(_REPO_ROOT)}:{n}: {line.strip()}")
        assert offenders == [], (
            "IL-FOOTER-1c: dead CSS class mutations found in tui/ Python source:\n"
            + "\n".join(offenders)
        )
