"""Tests for the Tool Error Recovery Contract (ER-1..ER-5).

Classes:
  TestStderrInBody                  — ER-1: stderr_tail moved to ToolBodyContainer
  TestHeaderNoStderrwarnRemediation — ER-2: header drops stderrwarn + remediation chips
  TestFooterRecoveryActions         — ER-3: retry/copy_err sorted first with --recovery-action
  TestHintRowDefersToFooter         — ER-4: hint row deduplicates against visible footer chips
  TestNoLegacyChipNames             — ER-5: no stderrwarn/remediation in codebase segments
"""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from hermes_cli.tui.tool_blocks._header import ToolBodyContainer
from hermes_cli.tui.tool_panel._footer import FooterPane, _RECOVERY_KINDS, _RECOVERY_ORDER
from hermes_cli.tui.tool_panel.layout_resolver import (
    _DROP_ORDER_DEFAULT,
    _DROP_ORDER_HERO,
    _DROP_ORDER_COMPACT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(
    *,
    exit_code: "int | None" = None,
    is_error: bool = False,
    stderr_tail: str = "",
    chips: tuple = (),
    actions: tuple = (),
    artifacts: tuple = (),
    error_kind: "str | None" = None,
):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=chips,
        stderr_tail=stderr_tail,
        actions=actions,
        artifacts=artifacts,
        is_error=is_error,
        error_kind=error_kind,
    )


def _make_action(kind: str, hotkey: str, label: str, payload=None):
    from hermes_cli.tui.tool_result_parse import Action
    return Action(label=label, hotkey=hotkey, kind=kind, payload=payload)


# ---------------------------------------------------------------------------
# ER-1: Body owns stderr evidence
# ---------------------------------------------------------------------------

class TestStderrInBody:
    def _make_body_container(self) -> ToolBodyContainer:
        c = ToolBodyContainer()
        # Simulate widget tree without a real app
        c._omission_parent_block = None
        return c

    def test_set_stderr_tail_mounts_strip_with_text(self):
        """set_stderr_tail with text activates the --stderr-tail strip."""
        c = self._make_body_container()
        tail_w = MagicMock()
        tail_w.plain = ""
        with patch.object(c, "query_one", return_value=tail_w), \
             patch(
                 "hermes_cli.tui.body_renderers._grammar.SkinColors.from_app",
                 return_value=MagicMock(error="red"),
             ):
            c.set_stderr_tail("error: command not found")
        tail_w.add_class.assert_called_with("--active")
        tail_w.update.assert_called_once()

    def test_set_stderr_tail_none_hides_strip(self):
        """set_stderr_tail(None) removes --active and clears text."""
        c = self._make_body_container()
        tail_w = MagicMock()
        with patch.object(c, "query_one", return_value=tail_w):
            c.set_stderr_tail(None)
        tail_w.remove_class.assert_called_with("--active")
        tail_w.update.assert_called_with("")

    def test_set_stderr_tail_truncates_to_8_lines(self):
        """Only the last 8 lines of stderr are rendered."""
        c = self._make_body_container()
        lines = [f"line{i}" for i in range(20)]
        tail = "\n".join(lines)
        tail_w = MagicMock()
        captured_text = {}

        def capture_update(val):
            captured_text["text"] = val

        tail_w.update.side_effect = capture_update

        with patch.object(c, "query_one", return_value=tail_w), \
             patch(
                 "hermes_cli.tui.body_renderers._grammar.SkinColors.from_app",
                 return_value=MagicMock(error="red"),
             ):
            c.set_stderr_tail(tail)

        from rich.text import Text
        result = captured_text.get("text")
        assert isinstance(result, Text)
        assert result.plain.count("\n") == 7  # 8 lines → 7 newlines

    def test_footer_no_longer_renders_stderr(self):
        """FooterPane must not have a _render_stderr method (deleted in ER-1)."""
        assert not hasattr(FooterPane, "_render_stderr"), (
            "FooterPane._render_stderr still exists; ER-1 requires deleting it"
        )

    def test_footer_no_has_stderr_class_after_summary_update(self):
        """update_summary_v4 must not add has-stderr class to footer."""
        fp = FooterPane()
        fp._last_summary = None
        fp._last_promoted = frozenset()
        fp._last_resize_w = 0
        fp._diff_kind = ""
        fp._narrow_diff_glyph = "±"
        fp._show_all_artifacts = False
        from hermes_cli.tui.tool_panel.density import DensityTier
        fp._density = DensityTier.DEFAULT

        summary = _make_summary(is_error=True, stderr_tail="some error")
        # Patch compose-time children
        fp._content = MagicMock()
        fp._artifact_row = MagicMock()
        fp._action_row = MagicMock()
        fp._diff_affordance = MagicMock()

        with patch.object(fp, "add_class") as mock_add, \
             patch.object(fp, "_rebuild_action_buttons"), \
             patch.object(fp, "_rebuild_artifact_buttons"):
            fp._render_footer(summary, frozenset())

        added = [call.args[0] for call in mock_add.call_args_list]
        assert "has-stderr" not in added

    def test_footer_hidden_when_only_stderr_tail_present(self):
        """Footer with only stderr_tail (no chips/actions/artifacts) returns no content."""
        fp = FooterPane()
        fp._last_summary = _make_summary(stderr_tail="oops", is_error=False)
        from hermes_cli.tui.tool_panel.density import DensityTier
        fp._density = DensityTier.DEFAULT
        assert fp._has_footer_content() is False


# ---------------------------------------------------------------------------
# ER-2: Header drops stderrwarn + remediation chips
# ---------------------------------------------------------------------------

class TestHeaderNoStderrwarnRemediation:
    def _header_source(self) -> str:
        import inspect
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        return inspect.getsource(ToolHeader._render_v4)

    def test_header_no_stderrwarn_segment(self):
        """No tail_segments.append(\"stderrwarn\", ...) in ToolHeader._render_v4 source."""
        src = self._header_source()
        assert '"stderrwarn"' not in src, (
            "stderrwarn segment construction still present in _render_v4"
        )

    def test_header_no_remediation_segment(self):
        """No tail_segments.append(\"remediation\", ...) in ToolHeader._render_v4 source."""
        src = self._header_source()
        # Use targeted check: 'tail_segments' + '"remediation"' in same expression
        import re
        hits = re.findall(r'tail_segments[^"]*"remediation"', src)
        assert not hits, f"remediation segment construction still present: {hits}"

    def test_header_keeps_exit_chip(self):
        """`exit` segment construction must still exist in _render_v4 source."""
        src = self._header_source()
        assert '"exit"' in src, "exit segment missing from _render_v4"

    def test_drop_order_no_stderrwarn_remediation(self):
        """All drop-order arrays must not list 'stderrwarn' or 'remediation'."""
        for name, arr in [
            ("_DROP_ORDER_DEFAULT", _DROP_ORDER_DEFAULT),
            ("_DROP_ORDER_HERO", _DROP_ORDER_HERO),
            ("_DROP_ORDER_COMPACT", _DROP_ORDER_COMPACT),
        ]:
            assert "stderrwarn" not in arr, f"{name} still contains 'stderrwarn'"
            assert "remediation" not in arr, f"{name} still contains 'remediation'"

    def test_footer_no_remediation_row_after_spec_lands(self):
        """FooterPane must have no _remediation_row attribute and no has-remediation CSS."""
        assert not hasattr(FooterPane, "_remediation_row"), (
            "FooterPane._remediation_row class attribute still exists"
        )
        assert "has-remediation" not in FooterPane.DEFAULT_CSS, (
            "'has-remediation' still present in FooterPane.DEFAULT_CSS"
        )


# ---------------------------------------------------------------------------
# ER-3: Footer recovery actions sorted first with --recovery-action class
# ---------------------------------------------------------------------------

class TestFooterRecoveryActions:
    def _render_actions(self, actions: list) -> "list[dict]":
        """Call _rebuild_action_buttons and return captured button specs."""
        fp = FooterPane()
        from hermes_cli.tui.tool_panel.density import DensityTier
        fp._density = DensityTier.DEFAULT
        fp._last_summary = None
        fp._last_promoted = frozenset()
        fp._last_resize_w = 0
        fp._show_all_artifacts = False

        mounted: list[dict] = []

        class FakeButton:
            def __init__(self, label, classes="", name=""):
                self._label = label
                self._classes = classes
                self._name = name

        class FakeRow:
            def __init__(self):
                self._mounted: list[FakeButton] = []

            def query(self, sel):
                return []

            def mount(self, *btns):
                self._mounted.extend(btns)

        action_row = FakeRow()
        fp._action_row = action_row

        summary = _make_summary()
        with patch.object(fp, "remove_class"), patch.object(fp, "add_class"):
            fp._rebuild_action_buttons(summary, actions)

        return [
            {"kind": b._name, "classes": b._classes}
            for b in action_row._mounted
        ]

    def test_recovery_actions_sorted_first(self):
        """retry and copy_err appear before non-recovery actions."""
        copy_body = _make_action("copy_body", "y", "copy", "body")
        retry = _make_action("retry", "r", "retry")
        copy_err = _make_action("copy_err", "e", "copy err")
        result = self._render_actions([copy_body, copy_err, retry])
        kinds = [r["kind"] for r in result]
        assert kinds.index("retry") < kinds.index("copy_body")
        assert kinds.index("copy_err") < kinds.index("copy_body")

    def test_recovery_action_has_recovery_class(self):
        """retry and copy_err buttons have --recovery-action in classes."""
        retry = _make_action("retry", "r", "retry")
        copy_err = _make_action("copy_err", "e", "copy err")
        result = self._render_actions([retry, copy_err])
        for r in result:
            assert "--recovery-action" in r["classes"], (
                f"kind={r['kind']} missing --recovery-action in classes={r['classes']!r}"
            )

    def test_non_recovery_action_no_recovery_class(self):
        """Non-recovery actions (copy_body, open_first) must NOT have --recovery-action."""
        copy_body = _make_action("copy_body", "y", "copy", "text")
        open_first = _make_action("open_first", "o", "open", "/path")
        result = self._render_actions([copy_body, open_first])
        for r in result:
            assert "--recovery-action" not in r["classes"], (
                f"kind={r['kind']} unexpectedly has --recovery-action"
            )

    def test_retry_first_then_copy_err(self):
        """retry always appears before copy_err in the action row."""
        copy_err = _make_action("copy_err", "e", "copy err")
        retry = _make_action("retry", "r", "retry")
        result = self._render_actions([copy_err, retry])
        kinds = [r["kind"] for r in result]
        assert kinds.index("retry") < kinds.index("copy_err")


# ---------------------------------------------------------------------------
# ER-4: Hint row defers stderr/retry hints to footer
# ---------------------------------------------------------------------------

class TestHintRowDefersToFooter:
    def _make_panel_with_summary(
        self,
        stderr_tail: str = "error msg",
        is_error: bool = True,
        footer_visible: bool = True,
        footer_action_kinds: "set[str]" = frozenset({"retry", "copy_err"}),
    ):
        # Plain MagicMock so attribute access doesn't raise on non-spec attrs
        panel = MagicMock()
        summary = _make_summary(
            is_error=is_error,
            stderr_tail=stderr_tail,
            exit_code=1 if is_error else 0,
        )
        panel._result_summary_v4 = summary
        panel._block = MagicMock()
        panel._block._completed = True
        panel._hint_visible = True
        panel._hint_row = MagicMock()
        panel._last_resize_w = 120
        panel.is_mounted = True
        panel.size = MagicMock(width=120)

        # Build fake footer pane
        fp = MagicMock()
        fp.styles.display = "block" if footer_visible else "none"
        btn_mocks = []
        for kind in footer_action_kinds:
            b = MagicMock()
            b.name = kind
            btn_mocks.append(b)
        fp._action_row.query.return_value = btn_mocks
        panel._footer_pane = fp

        panel._get_omission_bar = MagicMock(return_value=None)
        panel._result_paths_for_action = MagicMock(return_value=[])
        return panel, summary

    def test_recovery_hint_suppressed_when_footer_visible_with_chip(self):
        """When footer is visible and has retry+copy_err chips, hint row omits them."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        panel, _ = self._make_panel_with_summary(
            footer_visible=True,
            footer_action_kinds={"retry", "copy_err"},
        )
        # Simulate what _build_hint_text sees: footer visible with both chips
        visible_kinds = frozenset({"retry", "copy_err"})
        panel._visible_footer_action_kinds.return_value = visible_kinds

        from rich.text import Text
        result = _ToolPanelActionsMixin._build_hint_text(panel)
        hint_str = result.plain if isinstance(result, Text) else str(result)
        # With both chips visible in footer, hint row must not duplicate them
        assert "retry" not in hint_str, (
            f"retry hint appeared even though footer chip is visible: {hint_str!r}"
        )
        assert "stderr" not in hint_str, (
            f"stderr hint appeared even though footer chip is visible: {hint_str!r}"
        )

    def test_recovery_hint_present_when_footer_hidden_in_hero(self):
        """When footer is hidden (HERO), hint row provides the recovery keyboard hint."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        panel, _ = self._make_panel_with_summary(
            footer_visible=False,
            footer_action_kinds=set(),
        )
        # Simulate: footer hidden → _visible_footer_action_kinds returns empty
        panel._visible_footer_action_kinds.return_value = frozenset()

        from rich.text import Text
        result = _ToolPanelActionsMixin._build_hint_text(panel)
        hint_str = result.plain if isinstance(result, Text) else str(result)
        # With footer hidden, retry and/or stderr hints must be present
        assert "retry" in hint_str or "stderr" in hint_str, (
            f"No recovery hint in hint row when footer is hidden: {hint_str!r}"
        )

    def test_recovery_hint_present_when_user_collapsed_footer_zero_budget(self):
        """Collapsed blocks (footer hidden) still show retry hint in hint row."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        panel, _ = self._make_panel_with_summary(
            footer_visible=False,
            footer_action_kinds=set(),
            is_error=True,
            stderr_tail="",
        )
        # Footer hidden → no visible chips
        panel._visible_footer_action_kinds.return_value = frozenset()

        from rich.text import Text
        result = _ToolPanelActionsMixin._build_hint_text(panel)
        hint_str = result.plain if isinstance(result, Text) else str(result)
        assert "retry" in hint_str, (
            f"retry hint missing when footer hidden: {hint_str!r}"
        )


# ---------------------------------------------------------------------------
# ER-5: No legacy chip names in codebase segment construction
# ---------------------------------------------------------------------------

class TestNoLegacyChipNames:
    def test_no_stderrwarn_in_codebase(self):
        """No production code in hermes_cli/ should use the string 'stderrwarn'."""
        result = subprocess.run(
            ["grep", "-rn", "stderrwarn", "hermes_cli/"],
            capture_output=True, text=True,
        )
        hits = [line for line in result.stdout.splitlines() if line.strip()]
        assert hits == [], (
            f"'stderrwarn' still referenced in production code:\n" + "\n".join(hits)
        )

    def test_no_remediation_chip_segment_in_codebase(self):
        """No tail_segments.append(...'remediation'...) in tool_blocks/."""
        result = subprocess.run(
            ["grep", "-rn", r'tail_segments.*"remediation"', "hermes_cli/tool_blocks/"],
            capture_output=True, text=True,
        )
        hits = [line for line in result.stdout.splitlines() if line.strip()]
        assert hits == [], (
            f"remediation segment construction still present:\n" + "\n".join(hits)
        )
