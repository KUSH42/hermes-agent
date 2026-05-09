"""Tests for LP-GUTTER-PHILOSOPHY spec (2026-05-09).

LP-GUTTER-1: CopyableBlock carries assistant rail ($accent vkey)
LP-GUTTER-2: UserMessagePanel carries user rail ($user-accent vkey) + palette key in all 11 skins
LP-GUTTER-3: ReasoningPanel margin → zero; rail column parity via padding: 0 1
LP-GUTTER-4: Density-compact rail visibility regression (static assertions)

Rail convention: border-left: vkey <colour> 60% on every top-level block;
padding-left: 1 inside the widget; total text column = rail(1) + padding(1) = 2 (= LP-COL $body-indent).

Test approach:
- All tests are static/file-content checks — assert DEFAULT_CSS declarations and
  DESIGN.md palette entries.  HermesApp runtime tests are omitted because HermesApp.run_test()
  crashes with VarSpec errors in the test environment (missing skin vars).
  The LP-GUTTER-4 "compact density" tests assert the same static invariants,
  confirming that rail is carried by border-left (not margin) and thus survives
  the density-compact margin: 0 overrides.
"""
from __future__ import annotations

import pathlib

import pytest

SKINS_DIR = pathlib.Path("hermes_cli/skins")
ALL_SKINS = [
    "ares", "catppuccin", "charizard", "hermes", "matrix",
    "mono", "poseidon", "sisyphus", "slate", "solarized-dark", "tokyo-night",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tcss_text() -> str:
    return pathlib.Path("hermes_cli/tui/hermes.tcss").read_text()


# ---------------------------------------------------------------------------
# TestCopyableBlockRail — LP-GUTTER-1  (2 tests)
# ---------------------------------------------------------------------------


class TestCopyableBlockRail:
    """LP-GUTTER-1: CopyableBlock carries a vkey assistant rail."""

    def test_copyable_block_has_vkey_border(self):
        """CopyableBlock.DEFAULT_CSS must declare border-left: vkey."""
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        css = CopyableBlock.DEFAULT_CSS
        assert "border-left" in css, (
            "CopyableBlock.DEFAULT_CSS must declare border-left (LP-GUTTER-1)"
        )
        assert "vkey" in css, (
            "CopyableBlock.DEFAULT_CSS border-left must use vkey style (LP-GUTTER-1)"
        )
        assert "$accent" in css, (
            "CopyableBlock.DEFAULT_CSS must reference $accent colour (LP-GUTTER-1)"
        )

    def test_copyable_block_first_text_col_eq_2(self):
        """CopyableBlock text column: rail(1) + padding-left(1) = 2 (LP-GUTTER-1)."""
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        css = CopyableBlock.DEFAULT_CSS
        # Rail accounts for col 1; padding-left: 1 brings text to col 2.
        assert "padding: 0 1" in css or "padding-left: 1" in css, (
            "CopyableBlock.DEFAULT_CSS must declare padding-left: 1 (LP-GUTTER-1)"
        )
        # Margin must be zero (or absent) — the rail sits at col 0 of content area.
        assert "margin: 0 2" not in css, (
            "CopyableBlock.DEFAULT_CSS must not declare margin: 0 2 after LP-GUTTER-1"
        )


# ---------------------------------------------------------------------------
# TestUserMessageRail — LP-GUTTER-2  (3 tests)
# ---------------------------------------------------------------------------


class TestUserMessageRail:
    """LP-GUTTER-2: UserMessagePanel carries a vkey user rail + $user-accent palette key."""

    def test_user_message_has_vkey_border(self):
        """UserMessagePanel.DEFAULT_CSS must declare border-left: vkey $user-accent."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        css = UserMessagePanel.DEFAULT_CSS
        assert "border-left" in css, (
            "UserMessagePanel.DEFAULT_CSS must declare border-left (LP-GUTTER-2)"
        )
        assert "vkey" in css, (
            "UserMessagePanel.DEFAULT_CSS border-left must use vkey style (LP-GUTTER-2)"
        )
        assert "$user-accent" in css, (
            "UserMessagePanel.DEFAULT_CSS must reference $user-accent colour (LP-GUTTER-2)"
        )

    def test_user_accent_var_defined_in_palette(self):
        """All 11 bundled skins must define user-accent in component-vars."""
        from hermes_cli.skin_engine import load_design_md_payload, _bundled_skins_dir

        skins_dir = _bundled_skins_dir()
        missing = []
        for skin_name in ALL_SKINS:
            dm_path = skins_dir / skin_name / "DESIGN.md"
            payload = load_design_md_payload(dm_path)
            # user-accent is in component-vars → SkinPayload.component_vars
            if "user-accent" not in payload.component_vars:
                missing.append(skin_name)
        assert not missing, (
            f"Skins missing 'user-accent' in component_vars: {missing} (LP-GUTTER-2)"
        )

    def test_user_message_wrapped_line_aligned_with_first_line(self):
        """UserMessagePanel padding: 0 1 → text column = 2 (rail+padding)."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        css = UserMessagePanel.DEFAULT_CSS
        # After LP-GUTTER-2 the padding is 0 1 (was 0 2).
        assert "padding: 0 1" in css, (
            "UserMessagePanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-2)"
        )
        # Old padding: 0 2 must be gone.
        assert "padding: 0 2" not in css, (
            "UserMessagePanel.DEFAULT_CSS must not declare padding: 0 2 (removed by LP-GUTTER-2)"
        )


# ---------------------------------------------------------------------------
# TestReasoningPanelColumn — LP-GUTTER-3  (2 tests)
# ---------------------------------------------------------------------------


class TestReasoningPanelColumn:
    """LP-GUTTER-3: ReasoningPanel margin removed; padding: 0 1 aligns text to col 2."""

    def test_reasoning_panel_first_text_col_eq_2(self):
        """ReasoningPanel DEFAULT_CSS: margin: 0 + padding: 0 1 → text at col 2."""
        from hermes_cli.tui.widgets.message_panel import ReasoningPanel

        css = ReasoningPanel.DEFAULT_CSS
        # Margin must be 0 (old margin: 0 2 removed).
        assert "margin: 0 2" not in css, (
            "ReasoningPanel.DEFAULT_CSS must not declare margin: 0 2 (LP-GUTTER-3)"
        )
        assert "margin: 0" in css, (
            "ReasoningPanel.DEFAULT_CSS must declare margin: 0 (LP-GUTTER-3)"
        )
        # Padding-left: 1 provides the body-indent compensation.
        assert "padding: 0 1" in css, (
            "ReasoningPanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-3)"
        )

    def test_reasoning_aligned_with_user_and_prose(self):
        """ReasoningPanel, UserMessagePanel, CopyableBlock all use rail+padding→col 2."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel, ReasoningPanel
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        # All three must declare padding: 0 1 (the col-2 mechanism post-LP-GUTTER).
        assert "padding: 0 1" in ReasoningPanel.DEFAULT_CSS, (
            "ReasoningPanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-3)"
        )
        assert "padding: 0 1" in UserMessagePanel.DEFAULT_CSS, (
            "UserMessagePanel.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-2)"
        )
        assert "padding: 0 1" in CopyableBlock.DEFAULT_CSS, (
            "CopyableBlock.DEFAULT_CSS must declare padding: 0 1 (LP-GUTTER-1)"
        )
        # hermes.tcss must carry the padding for ReasoningPanel (tcss wins on specificity).
        tcss = _tcss_text()
        assert "ReasoningPanel" in tcss
        # The margin: 0 2 old rule must be gone from tcss (may still appear in comments).
        # Find the ReasoningPanel block in tcss and check it has no live margin: 0 2 declaration.
        idx = tcss.index("ReasoningPanel {")
        block_end = tcss.index("}", idx)
        block = tcss[idx:block_end]
        # Strip comment lines before checking for the old margin declaration
        non_comment_lines = [
            ln for ln in block.splitlines()
            if not ln.strip().startswith("/*") and not ln.strip().startswith("*")
        ]
        non_comment_block = "\n".join(non_comment_lines)
        assert "margin: 0 2" not in non_comment_block, (
            "hermes.tcss ReasoningPanel block must not declare margin: 0 2 (LP-GUTTER-3)"
        )


# ---------------------------------------------------------------------------
# TestCompactDensityRails — LP-GUTTER-4  (3 tests)
# ---------------------------------------------------------------------------


class TestCompactDensityRails:
    """LP-GUTTER-4: density-compact zeroes margin but rails survive (border-left, not margin)."""

    def test_compact_user_panel_has_rail(self):
        """UserMessagePanel rail is border-left; compact margin: 0 does not remove it."""
        from hermes_cli.tui.widgets.message_panel import UserMessagePanel

        css = UserMessagePanel.DEFAULT_CSS
        # Rail is defined as border-left (not margin) — immune to margin: 0 overrides.
        assert "border-left" in css, (
            "UserMessagePanel.DEFAULT_CSS must declare border-left rail (LP-GUTTER-2/4)"
        )
        # Confirm compact override does not include border-left: none
        tcss = _tcss_text()
        idx = tcss.find("density-compact UserMessagePanel")
        if idx >= 0:
            line_end = tcss.index("}", idx)
            compact_rule = tcss[idx:line_end]
            assert "border-left: none" not in compact_rule, (
                "Compact UserMessagePanel rule must not set border-left: none (LP-GUTTER-4)"
            )

    def test_compact_reasoning_has_rail(self):
        """ReasoningPanel rail is border-left in tcss; compact margin: 0 is a no-op (was already 0)."""
        tcss = _tcss_text()
        # hermes.tcss must declare border-left: vkey $reasoning-accent on ReasoningPanel.
        assert "border-left: vkey $reasoning-accent" in tcss, (
            "hermes.tcss must keep border-left: vkey $reasoning-accent on ReasoningPanel (LP-GUTTER-4)"
        )
        # Compact override for ReasoningPanel must not include border-left: none.
        idx = tcss.find("density-compact ReasoningPanel")
        if idx >= 0:
            line_end = tcss.index("}", idx)
            compact_rule = tcss[idx:line_end]
            assert "border-left: none" not in compact_rule, (
                "Compact ReasoningPanel rule must not set border-left: none (LP-GUTTER-4)"
            )

    def test_compact_copyable_block_has_rail(self):
        """CopyableBlock rail is border-left in DEFAULT_CSS; compact margin: 0 does not remove it."""
        from hermes_cli.tui.widgets.renderers import CopyableBlock

        css = CopyableBlock.DEFAULT_CSS
        # Rail is border-left — not margin.
        assert "border-left" in css, (
            "CopyableBlock.DEFAULT_CSS must declare border-left rail (LP-GUTTER-1/4)"
        )
        # Confirm compact override does not remove the rail.
        tcss = _tcss_text()
        idx = tcss.find("density-compact CopyableBlock")
        if idx >= 0:
            line_end = tcss.index("}", idx)
            compact_rule = tcss[idx:line_end]
            assert "border-left: none" not in compact_rule, (
                "Compact CopyableBlock rule must not set border-left: none (LP-GUTTER-4)"
            )
