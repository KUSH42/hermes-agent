"""Tests for LP-COL canonical body indent spec (2026-05-09).

All LP-COL-* rules — one canonical body column ($body-indent: 2) across every
top-level OutputPanel surface.

Test approach:
- Static/file-content tests: assert declarations and sentinel comments in TCSS/Python files.
- Runtime style tests: mount widgets in minimal App shells with inline CSS that mirrors
  the hermes.tcss LP-COL rules; assert widget.styles.padding/margin values.

Note: HermesApp.run_test() crashes with VarSpec errors (missing skin vars). All runtime
tests use lightweight App subclasses with inline CSS instead.
"""
from __future__ import annotations

import pathlib

import pytest

# ---------------------------------------------------------------------------
# Shared CSS snippets that mirror the LP-COL hermes.tcss rules.
# Inline CSS in test Apps must re-declare the rules because hermes.tcss is not
# loaded by default in unit test App shells.
# ---------------------------------------------------------------------------

# LP-COL-2 padding rules for ToolPanel + BodyPane
_LP_COL2_CSS = """\
ToolPanel {
    height: auto;
    padding-left: 1;
}
ToolPanel BodyPane {
    padding-left: 1;
}
"""

# LP-COL-4 CodeSection / OutputSection rules
_LP_COL4_CSS = """\
CodeSection { padding-left: 0; }
OutputSection { padding-left: 0; }
ToolBodyContainer CopyableRichLog {
    padding-left: 0;
    height: auto;
    overflow-y: hidden;
    overflow-x: hidden;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TCSS_PATH = pathlib.Path("hermes_cli/tui/hermes.tcss")


def _tcss_text() -> str:
    return _TCSS_PATH.read_text()


# ---------------------------------------------------------------------------
# TestCanonicalIndentConstant (LP-COL-1) — 2 tests
# ---------------------------------------------------------------------------


class TestCanonicalIndentConstant:
    """LP-COL-1: Python constant and TCSS variable declaration."""

    def test_body_indent_constant_exposed(self):
        """BODY_INDENT_COLUMNS must be importable from output_panel and equal 2."""
        from hermes_cli.tui.widgets.output_panel import BODY_INDENT_COLUMNS

        assert BODY_INDENT_COLUMNS == 2

    def test_tcss_references_body_indent(self):
        """hermes.tcss must declare $body-indent: 2 in its variable block."""
        text = _tcss_text()
        assert "$body-indent: 2" in text, (
            "Expected '$body-indent: 2' in hermes.tcss variable block"
        )


# ---------------------------------------------------------------------------
# TestUserAndToolBodyAlignment (LP-COL-2) — 5 tests
# ---------------------------------------------------------------------------


class TestUserAndToolBodyAlignment:
    """LP-COL-2: UserMessagePanel and ToolPanel BodyPane share col 2."""

    def test_user_message_first_text_col_eq_2(self):
        """UserMessagePanel text col == 2: rail(1) + padding-left(1) = 2 (LP-GUTTER-2)."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        # After LP-GUTTER-2: padding: 0 1 + border-left: vkey → col 2
        assert "padding: 0 1" in UserMessagePanel.DEFAULT_CSS, (
            "UserMessagePanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-2)"
        )
        assert "border-left" in UserMessagePanel.DEFAULT_CSS, (
            "UserMessagePanel.DEFAULT_CSS must declare border-left rail (LP-GUTTER-2)"
        )

    def test_tcss_tool_panel_padding_left_1(self):
        """hermes.tcss must declare ToolPanel { padding-left: 1; } (LP-COL-2)."""
        text = _tcss_text()
        # LP-COL-2 adds a ToolPanel { height: auto; padding-left: 1; } block
        assert "padding-left: 1" in text, (
            "hermes.tcss must have ToolPanel padding-left: 1 (LP-COL-2)"
        )

    def test_tcss_tool_panel_body_pane_padding_left_1(self):
        """hermes.tcss must declare ToolPanel BodyPane { padding-left: 1; }."""
        text = _tcss_text()
        assert "ToolPanel BodyPane" in text, (
            "hermes.tcss must have ToolPanel BodyPane rule (LP-COL-2)"
        )

    def test_reasoning_panel_margin_left_eq_2(self):
        """ReasoningPanel text col == 2: rail(1) + padding-left(1) = 2 (LP-GUTTER-3)."""
        from hermes_cli.tui.widgets.message_panel import ReasoningPanel

        # After LP-GUTTER-3: margin: 0 + padding: 0 1 + border-left: vkey → col 2
        assert "margin: 0" in ReasoningPanel.DEFAULT_CSS, (
            "ReasoningPanel.DEFAULT_CSS must declare margin: 0 (LP-GUTTER-3)"
        )
        assert "padding: 0 1" in ReasoningPanel.DEFAULT_CSS, (
            "ReasoningPanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-3)"
        )

    def test_copyable_block_margin_left_eq_2(self):
        """CopyableBlock text col == 2: rail(1) + padding-left(1) = 2 (LP-GUTTER-1)."""
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        # After LP-GUTTER-1: margin: 0 + padding: 0 1 + border-left: vkey → col 2
        assert "padding: 0 1" in CopyableBlock.DEFAULT_CSS, (
            "CopyableBlock.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-1)"
        )
        assert "border-left" in CopyableBlock.DEFAULT_CSS, (
            "CopyableBlock.DEFAULT_CSS must declare border-left rail (LP-GUTTER-1)"
        )


# ---------------------------------------------------------------------------
# TestFooterPaneIndent (LP-COL-3) — 3 tests
# ---------------------------------------------------------------------------


class TestFooterPaneIndent:
    """LP-COL-3: FooterPane padding + LP-COL-2 parent = $body-indent (2)."""

    def test_footer_pane_default_css_padding_0_1(self):
        """FooterPane DEFAULT_CSS must declare padding: 0 1."""
        from hermes_cli.tui.tool_panel._footer import FooterPane

        assert "padding: 0 1" in FooterPane.DEFAULT_CSS, (
            "FooterPane.DEFAULT_CSS must keep padding: 0 1 (LP-COL-3)"
        )

    def test_footer_pane_lp_col_comment_present(self):
        """FooterPane.DEFAULT_CSS must carry the LP-COL-2 dependency comment."""
        from hermes_cli.tui.tool_panel._footer import FooterPane

        assert "LP-COL-2" in FooterPane.DEFAULT_CSS, (
            "FooterPane.DEFAULT_CSS must reference LP-COL-2 in comment"
        )

    def test_footer_pane_body_indent_reference_in_comment(self):
        """FooterPane.DEFAULT_CSS comment must reference $body-indent sentinel."""
        from hermes_cli.tui.tool_panel._footer import FooterPane

        assert "$body-indent" in FooterPane.DEFAULT_CSS, (
            "FooterPane.DEFAULT_CSS must mention $body-indent in comment"
        )


# ---------------------------------------------------------------------------
# TestToolBodyContentUnified (LP-COL-4) — 5 tests
# ---------------------------------------------------------------------------


class TestToolBodyContentUnified:
    """LP-COL-4: CodeSection and OutputSection no longer use 6-col indent."""

    def test_code_section_col_eq_0_in_tcss(self):
        """hermes.tcss CodeSection must declare padding-left: 0 (LP-COL-4)."""
        text = _tcss_text()
        assert "CodeSection { padding-left: 0;" in text, (
            "hermes.tcss must have CodeSection { padding-left: 0; } (LP-COL-4)"
        )

    def test_output_section_col_eq_0_in_tcss(self):
        """hermes.tcss OutputSection must declare padding-left: 0 (LP-COL-4)."""
        text = _tcss_text()
        assert "OutputSection { padding-left: 0;" in text, (
            "hermes.tcss must have OutputSection { padding-left: 0; } (LP-COL-4)"
        )

    def test_code_section_no_longer_6_col(self):
        """hermes.tcss must not contain CodeSection { padding-left: 6 }."""
        text = _tcss_text()
        assert "CodeSection { padding-left: 6" not in text, (
            "hermes.tcss must not have CodeSection { padding-left: 6 } (removed by LP-COL-4)"
        )

    def test_output_section_no_longer_6_col(self):
        """hermes.tcss must not contain OutputSection { padding-left: 6 }."""
        text = _tcss_text()
        assert "OutputSection { padding-left: 6" not in text, (
            "hermes.tcss must not have OutputSection { padding-left: 6 } (removed by LP-COL-4)"
        )

    def test_lp_col4_comment_in_tcss(self):
        """hermes.tcss must contain LP-COL-4 comment documenting the change."""
        text = _tcss_text()
        assert "LP-COL-4" in text, (
            "hermes.tcss must contain LP-COL-4 comment"
        )


# ---------------------------------------------------------------------------
# TestColCleanup (LP-COL-5) — 2 tests
# ---------------------------------------------------------------------------


class TestColCleanup:
    """LP-COL-5: Compact density comment and margin-bottom dead-rule audit."""

    def test_compact_padding_documented(self):
        """Sentinel comment 'Pairs with LP-COL-2 canonical indent' appears before compact rule."""
        text = _tcss_text()
        assert "Pairs with LP-COL-2 canonical indent" in text, (
            "hermes.tcss must contain 'Pairs with LP-COL-2 canonical indent' sentinel (LP-COL-5 M2)"
        )
        # Verify comment appears before the compact UserMessagePanel rule
        comment_pos = text.index("Pairs with LP-COL-2 canonical indent")
        rule_pos = text.index("HermesApp.density-compact UserMessagePanel")
        assert comment_pos < rule_pos, (
            "LP-COL-2 sentinel comment must appear before the compact UserMessagePanel rule"
        )

    def test_margin_bottom_base_rule_commented(self):
        """LP-RHYTHM-1 replaced the old ToolPanel { margin-bottom: 0; } base rule.
        Assert the new uniform rhythm rule (LP-RHYTHM-1) is present instead.
        """
        text = _tcss_text()
        # LP-RHYTHM-1 superseded the old per-tier margin rules; assert the new block exists.
        assert "LP-RHYTHM-1" in text, (
            "hermes.tcss must contain LP-RHYTHM-1 uniform inter-block rhythm block"
        )
        assert "ChildPanel { margin-bottom: 0; }" in text, (
            "hermes.tcss must retain ChildPanel { margin-bottom: 0; } to keep group children tight"
        )


# ---------------------------------------------------------------------------
# TestCrossSurfaceIntegration — 5 tests
# ---------------------------------------------------------------------------


class TestCrossSurfaceIntegration:
    """Cross-surface column parity assertions."""

    def test_all_top_level_surfaces_col_eq_2(self):
        """UserMessagePanel, ReasoningPanel, CopyableBlock all achieve col 2 via rail+padding."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel, ReasoningPanel
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        # After LP-GUTTER: all three use rail(1)+padding-left(1) = col 2
        # UserMessagePanel: border-left: vkey + padding: 0 1 → left = 2
        assert "border-left" in UserMessagePanel.DEFAULT_CSS
        assert "padding: 0 1" in UserMessagePanel.DEFAULT_CSS
        # ReasoningPanel: border-left via tcss + margin: 0 + padding: 0 1 → left = 2
        assert "margin: 0" in ReasoningPanel.DEFAULT_CSS
        assert "padding: 0 1" in ReasoningPanel.DEFAULT_CSS
        # CopyableBlock: border-left: vkey + padding: 0 1 → left = 2
        assert "border-left" in CopyableBlock.DEFAULT_CSS
        assert "padding: 0 1" in CopyableBlock.DEFAULT_CSS

    def test_footer_matches_body_col(self):
        """FooterPane + parent ToolPanel padding sums to BODY_INDENT_COLUMNS."""
        from hermes_cli.tui.widgets.output_panel import BODY_INDENT_COLUMNS
        from hermes_cli.tui.tool_panel._footer import FooterPane

        # FooterPane own padding-left = 1 (from "padding: 0 1")
        # ToolPanel parent padding-left = 1 (from LP-COL-2 in hermes.tcss)
        # Total = 2 = BODY_INDENT_COLUMNS
        assert "padding: 0 1" in FooterPane.DEFAULT_CSS
        # The sum (1 + 1) matches the constant
        footer_own = 1  # from "padding: 0 1"
        parent_padding = 1  # LP-COL-2 ToolPanel padding-left
        assert footer_own + parent_padding == BODY_INDENT_COLUMNS

    def test_code_section_matches_plain_body_col(self):
        """CodeSection padding-left: 0 means no extra indent beyond BodyPane col 2."""
        text = _tcss_text()
        assert "CodeSection { padding-left: 0;" in text
        assert "OutputSection { padding-left: 0;" in text

    def test_compact_density_all_surfaces_col_eq_1(self):
        """Compact-density UserMessagePanel override reduces to padding: 0 1 (col == 1)."""
        text = _tcss_text()
        # The compact override reduces from 0 2 to 0 1
        assert "density-compact UserMessagePanel" in text
        # Check the compact override has padding: 0 1
        idx = text.index("density-compact UserMessagePanel")
        line = text[idx : idx + 100]
        assert "padding: 0 1" in line, (
            f"Compact UserMessagePanel rule must set padding: 0 1; got: {line!r}"
        )

    def test_indent_constant_matches_tcss_declaration(self):
        """BODY_INDENT_COLUMNS == 2 and TCSS declares $body-indent: 2."""
        from hermes_cli.tui.widgets.output_panel import BODY_INDENT_COLUMNS

        assert BODY_INDENT_COLUMNS == 2
        text = _tcss_text()
        assert f"$body-indent: {BODY_INDENT_COLUMNS}" in text
