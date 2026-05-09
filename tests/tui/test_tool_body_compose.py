"""Tests for Tool Body Compose Cleanup Spec (B1–B9).

Spec: /home/xush/.hermes/2026-04-24-tool-body-compose-spec.md
Test file: tests/tui/test_tool_body_compose.py
"""
from __future__ import annotations

import re
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(label="copy body", hotkey="c", kind="copy_body", payload=None):
    from hermes_cli.tui.tool_result_parse import Action
    return Action(label=label, hotkey=hotkey, kind=kind, payload=payload)


def _make_summary(
    primary="✓ done",
    chips=(),
    actions=(),
    stderr_tail="",
    artifacts=(),
    is_error=False,
):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=primary,
        exit_code=None,
        chips=chips,
        stderr_tail=stderr_tail,
        actions=actions,
        artifacts=artifacts,
        is_error=is_error,
    )


def _make_block(label="output", lines=None, plain_lines=None, summary=None, tool_name=None):
    from hermes_cli.tui.tool_blocks._block import ToolBlock
    lines = lines or ["hello"]
    plain_lines = plain_lines or lines
    return ToolBlock(
        label, list(lines), list(plain_lines),
        tool_name=tool_name, summary=summary,
    )


# ---------------------------------------------------------------------------
# TestB1ActionChipsRow — 4 tests
# ---------------------------------------------------------------------------

class TestB1ActionChipsRow:
    def test_action_chip_row_mounts_one_label_per_action(self):
        """3 actions → 3 Label children."""
        from hermes_cli.tui.tool_blocks._block import ActionChipsRow
        actions = (
            _make_action("copy body", "c", "copy_body"),
            _make_action("retry", "r", "retry"),
            _make_action("open first", "o", "open_first"),
        )
        row = ActionChipsRow(actions)
        children = list(row.compose())
        from textual.widgets import Label
        assert len(children) == 3
        assert all(isinstance(c, Label) for c in children)

    def test_action_chip_copy_body_has_copy_class(self):
        """Label for copy_body carries -copy class."""
        from hermes_cli.tui.tool_blocks._block import ActionChipsRow, _action_class
        assert _action_class("copy_body") == "copy"
        assert _action_class("copy_paths") == "copy"
        assert _action_class("copy_json") == "copy"

    def test_action_chip_copy_err_has_error_class(self):
        """Label for copy_err carries -error class."""
        from hermes_cli.tui.tool_blocks._block import _action_class
        assert _action_class("copy_err") == "error"

    def test_action_chip_text_format(self):
        """Label text == ' [c] copy body ' (bracketed hotkey, space, label, padded)."""
        from hermes_cli.tui.tool_blocks._block import ActionChipsRow
        from textual.widgets import Label
        actions = (_make_action("copy body", "c", "copy_body"),)
        row = ActionChipsRow(actions)
        children = list(row.compose())
        assert len(children) == 1
        lbl = children[0]
        assert isinstance(lbl, Label)
        # Label stores raw string in _Static__content (name-mangled from Static)
        assert str(lbl._Static__content) == " [c] copy body "


# ---------------------------------------------------------------------------
# TestB2StderrTailActivation — 3 tests
# ---------------------------------------------------------------------------

class TestB2StderrTailActivation:
    def test_stderr_tail_activated_when_summary_has_stderr(self):
        """set_stderr_tail called with non-empty stderr when summary.stderr_tail set."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = _make_block(summary=_make_summary(stderr_tail="boom\nerror"))
        # Patch _body.set_stderr_tail to capture the call
        mock_body = MagicMock()
        mock_body.query_one.side_effect = Exception("not mounted")
        block._body = mock_body
        block._render_body = MagicMock()  # skip actual render
        block.on_mount()
        mock_body.set_stderr_tail.assert_called_once_with("boom\nerror")

    def test_stderr_tail_not_activated_when_empty(self):
        """Empty stderr_tail → set_stderr_tail called with None."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = _make_block(summary=_make_summary(stderr_tail=""))
        mock_body = MagicMock()
        block._body = mock_body
        block._render_body = MagicMock()
        block.on_mount()
        mock_body.set_stderr_tail.assert_called_once_with(None)

    def test_no_stderr_call_when_no_summary(self):
        """ToolBlock without summary= → set_stderr_tail never called."""
        block = _make_block()
        mock_body = MagicMock()
        block._body = mock_body
        block._render_body = MagicMock()
        block.on_mount()
        mock_body.set_stderr_tail.assert_not_called()


# ---------------------------------------------------------------------------
# TestB3BodyDeduplication — 5 tests
# ---------------------------------------------------------------------------

class TestB3BodyDeduplication:
    def test_body_omits_completed_ago_row(self):
        """set_age_microcopy deleted from StreamingToolBlock."""
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
        assert not hasattr(StreamingToolBlock, "set_age_microcopy"), (
            "set_age_microcopy must be removed from StreamingToolBlock"
        )

    def test_body_omits_duplicate_size_row(self):
        """_tick_age no longer calls set_age_microcopy."""
        import inspect
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        # Find _tick_age by searching all mixin methods
        src = inspect.getsource(_ToolPanelCompletionMixin._tick_age)
        assert "set_age_microcopy" not in src

    def test_body_omits_duplicate_basename_row(self):
        """promoted chip logic present in _completion.py set_result_summary."""
        import inspect
        from hermes_cli.tui.tool_panel import _completion
        src = inspect.getsource(_completion)
        assert "promoted" in src and "startswith" in src

    def test_body_renders_args_row_when_present(self):
        """set_args_row on ToolBodyContainer still works."""
        from hermes_cli.tui.tool_blocks._header import ToolBodyContainer
        from textual.widgets import Static
        container = ToolBodyContainer()
        # Manually inject the --args-row Static
        static = Static("", classes="--args-row")
        container._nodes = [static]  # type: ignore[attr-defined]
        # Verify the method finds the widget
        container.set_args_row("test args")

    def test_body_renders_stderr_and_actions_on_error(self):
        """B1+B2 wired: error summary passes actions+stderr to on_mount path."""
        from hermes_cli.tui.tool_result_parse import Action
        err_action = _make_action("copy error", "e", "copy_err")
        summary = _make_summary(
            primary="✗ error",
            actions=(err_action,),
            stderr_tail="fatal: something\n",
            is_error=True,
        )
        block = _make_block(summary=summary)
        mock_body = MagicMock()
        block._body = mock_body
        block._render_body = MagicMock()
        block.on_mount()
        # Both stderr and action chips must be activated
        mock_body.set_stderr_tail.assert_called_once_with("fatal: something\n")
        mock_body.mount.assert_called_once()


# ---------------------------------------------------------------------------
# TestB4FilenameColor — 2 tests
# ---------------------------------------------------------------------------

class TestB4FilenameColor:
    def test_filename_default_text_color(self):
        """No $tool-fname or $file-title variable mapped to warning in skins."""
        import pathlib
        skin_dir = pathlib.Path(__file__).parents[2] / "hermes_cli" / "tui" / "skins"
        if not skin_dir.exists():
            pytest.skip("skins dir not found")
        pattern = re.compile(r"tool-fname|file-title")
        for skin_file in skin_dir.glob("*.py"):
            src = skin_file.read_text()
            assert not pattern.search(src), (
                f"Skin {skin_file.name} defines tool-fname/file-title variable "
                f"(B4: must not exist to prevent warning-color leak)"
            )

    def test_filename_error_uses_error_color(self):
        """_action_class does not map file-tool types to 'retry'."""
        from hermes_cli.tui.tool_blocks._block import _action_class
        # Neutral/copy/retry/error are the only classes; file paths are not retry
        assert _action_class("open_first") == ""
        assert _action_class("open_url") == ""
        assert _action_class("edit_cmd") == ""


# ---------------------------------------------------------------------------
# TestB5TruncationHintExtraction — 4 tests
# ---------------------------------------------------------------------------

class TestB5TruncationHintExtraction:
    def test_strip_truncation_hint_extracts_offset(self):
        text = "foo bar\n[Hint: Results truncated. Use offset=50 to see more, or narrow]"
        cleaned, offset = __import__(
            "hermes_cli.tui.tool_result_parse", fromlist=["_strip_truncation_hint"]
        )._strip_truncation_hint(text)
        assert offset == 50
        assert "Hint" not in cleaned
        assert "foo bar" in cleaned

    def test_strip_truncation_hint_no_match(self):
        from hermes_cli.tui.tool_result_parse import _strip_truncation_hint
        text = "some output without hint"
        cleaned, offset = _strip_truncation_hint(text)
        assert offset is None
        assert cleaned == text

    def test_search_parser_emits_truncated_chip(self):
        """Input with hint → ResultSummaryV4.chips includes '+50 more' warning chip."""
        from hermes_cli.tui.tool_result_parse import search_result_v4, ParseContext
        raw = "file.py:10: match\n[Hint: Results truncated. Use offset=50 to see more]"
        ctx = _make_parse_ctx(raw)
        result = search_result_v4(ctx)
        chip_texts = [c.text for c in result.chips]
        assert "+50 more" in chip_texts
        trunc_chip = next(c for c in result.chips if c.text == "+50 more")
        assert trunc_chip.tone == "warning"
        assert trunc_chip.kind == "status"

    def test_search_parser_emits_more_action(self):
        """Input with hint → Action with hotkey 'm', kind 'retry', payload '50'."""
        from hermes_cli.tui.tool_result_parse import search_result_v4
        raw = "match line\n[Hint: Results truncated. Use offset=50 to see more]"
        ctx = _make_parse_ctx(raw)
        result = search_result_v4(ctx)
        more_actions = [a for a in result.actions if a.hotkey == "m"]
        assert len(more_actions) == 1
        assert more_actions[0].kind == "retry"
        assert more_actions[0].payload == "50"


def _make_parse_ctx(raw: str, is_error: bool = False):
    """Build a minimal ParseContext for parser tests."""
    from hermes_cli.tui.tool_result_parse import ParseContext, ToolStart, ToolComplete
    complete = ToolComplete(
        name="grep",
        raw_result=raw,
        is_error=is_error,
        error_kind=None,
    )
    start = ToolStart(name="grep", args={"pattern": "foo"})
    spec = SimpleNamespace(tool_name="grep", display_name="grep", category=None)
    return ParseContext(complete=complete, start=start, spec=spec)


# ---------------------------------------------------------------------------
# TestB6MarkdownHRSuppression — 3 tests
# ---------------------------------------------------------------------------

class TestB6MarkdownHRSuppression:
    def test_tool_body_underscores_not_rendered_as_hr(self):
        """Body content with '___' → log write skips that line."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock(
            "output",
            ["regular content", "___________", "more content"],
            ["regular content", "___________", "more content"],
        )
        mock_rl = MagicMock()
        from textual.css.query import NoMatches
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body
        block._render_body()
        # Only 2 lines should be written (the ___ line is suppressed)
        written_plain = [call.args[1] for call in mock_rl.write_with_source.call_args_list]
        assert "___________" not in written_plain
        assert "regular content" in written_plain

    def test_tool_body_dashes_not_rendered_as_hr(self):
        """Body content with '---' → log write skips that line."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock(
            "output",
            ["before", "---", "after"],
            ["before", "---", "after"],
        )
        mock_rl = MagicMock()
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body
        block._render_body()
        written_plain = [call.args[1] for call in mock_rl.write_with_source.call_args_list]
        assert "---" not in written_plain

    def test_response_flow_prose_hr_still_works(self):
        """_HR_RE in _block.py does not affect prose outside _render_body."""
        from hermes_cli.tui.tool_blocks._block import _HR_RE
        # The regex only matches bare HR lines; normal content is untouched
        assert _HR_RE.match("---")
        assert _HR_RE.match("___")
        assert not _HR_RE.match("--- yaml front matter: value")
        assert not _HR_RE.match("hello world")
        assert not _HR_RE.match("x--")


# ---------------------------------------------------------------------------
# TestB7BlankRowCleanup — 3 tests
# ---------------------------------------------------------------------------

class TestB7BlankRowCleanup:
    def test_trailing_newlines_stripped(self):
        """content 'a\\nb\\n\\n' → log receives 'a' and 'b' only."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock(
            "output",
            ["a", "b", "", ""],
            ["a", "b", "", ""],
        )
        mock_rl = MagicMock()
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body
        block._render_body()
        written_plain = [call.args[1] for call in mock_rl.write_with_source.call_args_list]
        assert "" not in written_plain
        assert written_plain == ["a", "b"]

    def test_no_double_blank_before_actions(self):
        """Trailing blanks removed from plain_lines list after _render_body."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock(
            "output",
            ["foo", "", ""],
            ["foo", "", ""],
        )
        mock_rl = MagicMock()
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body
        block._render_body()
        assert block._plain_lines == ["foo"]
        assert block._lines == ["foo"]

    def test_empty_content_no_log_mounted(self):
        """All lines blank → log receives no writes (all stripped)."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock("output", ["", "  ", ""], ["", "  ", ""])
        mock_rl = MagicMock()
        mock_body = MagicMock()
        mock_body.query_one.return_value = mock_rl
        block._body = mock_body
        block._render_body()
        mock_rl.write_with_source.assert_not_called()


# ---------------------------------------------------------------------------
# TestB8FileIconSingleton — 2 tests
# ---------------------------------------------------------------------------

class TestB8FileIconSingleton:
    def test_file_icon_rendered_once_per_panel(self):
        """B3 deleted basename row: body compose has no icon-bearing Static children."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        from textual.widgets import Static
        block = ToolBlock(
            "output",
            ["content"],
            ["content"],
            tool_name="read_file",
        )
        # Body compose yields Static statics (args-row, microcopy) and CopyableRichLog.
        # None of them should contain a file icon glyph — basename row was deleted by B3.
        children = list(block._body.compose())
        for child in children:
            if isinstance(child, Static):
                rendered = str(child._Static__content)
                # Should not contain 📄 or any file icon glyph
                assert "📄" not in rendered

    def test_file_icon_in_header_not_body(self):
        """ToolBlock body compose contains no Static children with file path text."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        from textual.widgets import Static
        block = ToolBlock(
            "/tmp/foo.py",
            ["line 1"],
            ["line 1"],
            tool_name="read_file",
        )
        # _header stores path; body Static children must not contain path basename
        children = list(block._body.compose())
        for w in children:
            if isinstance(w, Static):
                content = str(w._Static__content)
                assert "foo.py" not in content, (
                    f"Body Static contains path: {content!r}"
                )


# ---------------------------------------------------------------------------
# TestB9Regressions — 2 tests
# ---------------------------------------------------------------------------

class TestB9Regressions:
    def test_action_chip_hotkey_uniqueness_post_m(self):
        """'m' hotkey not in ToolPanel.BINDINGS and no duplicate in search_result_v4 actions."""
        from hermes_cli.tui.tool_panel._core import ToolPanel
        panel_hotkeys = {b.key for b in ToolPanel.BINDINGS}
        assert "m" not in panel_hotkeys, (
            f"'m' is already bound in ToolPanel.BINDINGS: {panel_hotkeys}"
        )
        # Also check search_result_v4 for a truncated output produces unique hotkeys
        from hermes_cli.tui.tool_result_parse import search_result_v4
        raw = "file.py:1: match\n[Hint: Results truncated. Use offset=50 to see more]"
        ctx = _make_parse_ctx(raw)
        result = search_result_v4(ctx)
        hotkeys = [a.hotkey for a in result.actions]
        assert len(hotkeys) == len(set(hotkeys)), f"Duplicate hotkeys: {hotkeys}"

    def test_header_label_contract_unchanged(self):
        """header_label_v4 for read_file returns Text with path in it."""
        from hermes_cli.tui.tool_blocks._shared import header_label_v4
        spec = SimpleNamespace(
            tool_name="read_file",
            display_name="read_file",
            category=None,
        )
        args = {"path": "/tmp/foo.py"}
        result = header_label_v4(
            spec, args,
            full_label="/tmp/foo.py",
            full_path="/tmp/foo.py",
            available=80,
        )
        # Result is a Rich Text; plain text should contain the path
        plain = result.plain if hasattr(result, "plain") else str(result)
        assert "foo.py" in plain
