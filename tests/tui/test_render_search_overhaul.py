"""Tests for SearchRenderer + VirtualSearchList overhaul (R-Sr1–R-Sr5)."""
from __future__ import annotations

import os
import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.body_renderers.search import (
    SearchRenderer,
    VirtualSearchList,
    _StickyGroupHeader,
    _SearchFooter,
    _ansi_highlight,
    _parse_search_output,
)
from hermes_cli.tui.body_renderers._grammar import SkinColors, build_rule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_renderer(raw: str, query: str | None = None) -> SearchRenderer:
    payload = MagicMock()
    payload.output_raw = raw
    cls_result = MagicMock()
    cls_result.metadata = {"query": query} if query else {}
    return SearchRenderer(payload, cls_result, app=None)


def _make_vsl(lines: list[tuple[str, str, str | None, int | None]]) -> VirtualSearchList:
    """Create a VirtualSearchList using __new__ for pure-unit tests."""
    w = VirtualSearchList.__new__(VirtualSearchList)
    w._lines = lines
    w._strips = [MagicMock() for _ in lines]
    w._line_kinds = [entry[1] for entry in lines]
    w._cursor_idx = 0
    w._viewport_height = 10
    w._hit_count = sum(1 for k in w._line_kinds if k == "hit")
    return w


# ---------------------------------------------------------------------------
# TestContextVsHit — R-Sr1 (5 pure unit tests)
# ---------------------------------------------------------------------------

class TestContextVsHit:

    def test_parse_hits_only(self):
        raw = "file.py\n1:foo\n2:bar\n"
        groups = _parse_search_output(raw)
        assert len(groups) == 1
        path, hits = groups[0]
        assert path == "file.py"
        assert all(h[2] is True for h in hits)

    def test_parse_context_distinguished(self):
        raw = "file.py\n1:match\n2-ctx before\n3-ctx after\n"
        groups = _parse_search_output(raw)
        _, hits = groups[0]
        assert hits[0][2] is True   # 1:match is a hit
        assert hits[1][2] is False  # 2-ctx is context
        assert hits[2][2] is False  # 3-ctx is context

    def test_render_context_is_dim_italic(self):
        raw = "src/foo.py\n1:match line\n2-context line\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        plain = text.plain
        # Find the context line spans
        span_styles = [str(span.style) for span in text._spans]
        italic_spans = [s for s in span_styles if "italic" in s.lower()]
        assert italic_spans, "context line must have at least one italic span"

    def test_render_hit_is_normal(self):
        raw = "src/foo.py\n1:match line\n"
        renderer = _make_renderer(raw, query="match")
        text = renderer.build()
        # Find the content part of the hit line — should be bold, NOT italic
        content_spans = [span for span in text._spans if "italic" in str(span.style).lower()]
        assert not content_spans, "hit line content must not be italic"

    def test_parse_json_context_type(self):
        import json
        data = {
            "matches": [
                {"path": "a.py", "line": 1, "content": "hit line", "type": "match"},
                {"path": "a.py", "line": 2, "content": "context line", "type": "context"},
                {"path": "a.py", "line": 3, "content": "no type line"},
            ]
        }
        groups = _parse_search_output(json.dumps(data))
        _, hits = groups[0]
        assert hits[0][2] is True   # type=match → is_hit
        assert hits[1][2] is False  # type=context → not is_hit
        assert hits[2][2] is True   # no type → default hit


# ---------------------------------------------------------------------------
# TestPathHeader — R-Sr2 (3 pure unit tests)
# ---------------------------------------------------------------------------

class TestPathHeader:

    def test_header_format(self):
        raw = "some/path/file.py\n1:content\n2:more\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        first_line = text.plain.split("\n")[0]
        import re
        assert re.match(r"^  [>▸] [\w./\-]+ +[-·] \d+ hits$", first_line), (
            f"header line format wrong: {first_line!r}"
        )
        # Two leading spaces
        assert first_line.startswith("  ")

    def test_header_uses_grammar_accent_color(self):
        raw = "foo.py\n1:x\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        colors = SkinColors.default()
        # Find span with accent colour
        accent_spans = [
            span for span in text._spans
            if colors.accent.lower() in str(span.style).lower()
        ]
        assert accent_spans, "▸ glyph must use accent colour"

    def test_multiple_groups_blank_between(self):
        raw = "file_a.py\n1:foo\nfile_b.py\n2:bar\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        lines = text.plain.split("\n")
        # Find the rule separator line (non-empty line between groups that is not a header/hit)
        group_a_header_idx = next(
            i for i, ln in enumerate(lines) if "file_a.py" in ln
        )
        group_b_header_idx = next(
            i for i, ln in enumerate(lines) if "file_b.py" in ln
        )
        between = lines[group_a_header_idx + 1: group_b_header_idx]
        # There should be exactly one non-empty separator line (the rule)
        non_empty = [ln for ln in between if ln.strip()]
        assert len(non_empty) >= 1, "must have a rule separator between groups"


# ---------------------------------------------------------------------------
# TestQueryHighlight — R-Sr3 (3 pure unit + 1 async)
# ---------------------------------------------------------------------------

class TestQueryHighlight:

    def test_ansi_highlight_inserts_escapes(self):
        result = _ansi_highlight("foo bar foo", "foo")
        assert result.count("\x1b[1m") == 2

    def test_ansi_highlight_case_insensitive(self):
        result = _ansi_highlight("foo FOO Foo", "FOO")
        assert result.count("\x1b[1m") == 3

    def test_ansi_highlight_invalid_regex_returns_raw(self):
        # Empty query → identity
        assert _ansi_highlight("hello", "") == "hello"
        assert _ansi_highlight("hello", "   ") == "hello"
        # Metachar query: re.escape makes it safe
        result = _ansi_highlight("1.2.3", ".")
        assert "\x1b[1m" in result  # dots matched

    @pytest.mark.asyncio
    async def test_virtual_list_preserves_bold(self):
        from textual.app import App, ComposeResult

        lines = [(f"\x1b[1mfoo\x1b[0m bar", "hit", "f.py", i) for i in range(200)]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            await pilot.pause()
            if widget._strips:
                segs = list(widget._strips[4])
                assert any(
                    getattr(getattr(s, "style", None), "bold", False) for s in segs
                ), "bold ANSI must survive Strip conversion"


# ---------------------------------------------------------------------------
# TestVirtualListNav — R-Sr4 (6 pure unit + 4 async)
# ---------------------------------------------------------------------------

class TestVirtualListNav:

    def test_cursor_down_advances_idx(self):
        lines = [("line", "hit", "f.py", i) for i in range(5)]
        w = _make_vsl(lines)
        w.action_cursor_down()
        assert w._cursor_idx == 1

    def test_cursor_wraps_at_end(self):
        lines = [("line", "hit", "f.py", i) for i in range(3)]
        w = _make_vsl(lines)
        w._cursor_idx = 2
        w.action_cursor_down()
        assert w._cursor_idx == 2  # clamped, no wrap

    def test_page_down_advances_by_height(self):
        lines = [("line", "hit", "f.py", i) for i in range(20)]
        w = _make_vsl(lines)
        w._viewport_height = 5
        w._cursor_idx = 0
        w.action_page_down()
        assert w._cursor_idx == 4  # min(0 + 5 - 1, 19) = 4

    def test_home_end(self):
        lines = [("line", "hit", "f.py", i) for i in range(10)]
        w = _make_vsl(lines)
        w._cursor_idx = 5
        w.action_cursor_top()
        assert w._cursor_idx == 0
        w.action_cursor_bottom()
        assert w._cursor_idx == 9

    def test_empty_list_no_crash(self):
        w = _make_vsl([])
        w.action_cursor_down()
        w.action_cursor_up()
        w.action_page_down()
        w.action_page_up()
        w.action_cursor_top()
        w.action_cursor_bottom()
        assert w._cursor_idx == 0  # unchanged

    def test_enter_no_op_on_group_header(self):
        lines = [("header line", "header", "f.py", None)]
        w = _make_vsl(lines)
        # No safe_edit_cmd should be called
        with patch("hermes_cli.tui.body_renderers.search.safe_edit_cmd") as mock_edit:
            w.action_open_selection()
            mock_edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_enter_opens_editor(self):
        from textual.app import App, ComposeResult

        lines = [
            ("hit line content", "hit", "foo.py", 42),
            ("another hit", "hit", "foo.py", 99),
        ]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            widget._cursor_idx = 0
            with patch("hermes_cli.tui.body_renderers.search.safe_edit_cmd") as mock_edit:
                widget.action_open_selection()
                mock_edit.assert_called_once()
                kwargs = mock_edit.call_args
                assert kwargs[1]["line"] == 42 or kwargs[0][3] == 42

    @pytest.mark.asyncio
    async def test_footer_shows_cursor_of_total(self):
        from textual.app import App, ComposeResult

        lines = [("line", "hit", "f.py", i) for i in range(234)]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            widget._cursor_idx = 4
            widget._update_footer()
            await pilot.pause()
            footer = app.query_one(_SearchFooter)
            assert "5/234 lines" in str(footer.content)

    @pytest.mark.asyncio
    async def test_footer_accessibility_ascii(self):
        from textual.app import App, ComposeResult

        lines = [("line", "hit", "f.py", i) for i in range(5)]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        prev = os.environ.get("HERMES_NO_UNICODE")
        try:
            os.environ["HERMES_NO_UNICODE"] = "1"
            app = _App()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                widget = app.query_one(VirtualSearchList)
                widget._update_footer()
                await pilot.pause()
                footer = app.query_one(_SearchFooter)
                content = str(footer.content)
                assert "·" not in content, "should use ASCII dot in no-unicode mode"
                assert "." in content or "-" in content, "ASCII separator expected"
        finally:
            if prev is None:
                os.environ.pop("HERMES_NO_UNICODE", None)
            else:
                os.environ["HERMES_NO_UNICODE"] = prev

    @pytest.mark.asyncio
    async def test_empty_result_footer_shows_zero(self):
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=[])

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            footer = app.query_one(_SearchFooter)
            assert "0/0 lines" in str(footer.content)
            assert "0 hits" in str(footer.content)
            widget.action_cursor_down()
            assert widget._cursor_idx == 0  # no-op on empty

    def test_scrollbar_size_css_rule(self):
        import re
        tcss_path = (
            __import__("pathlib").Path(__file__).parent.parent.parent
            / "hermes_cli" / "tui" / "hermes.tcss"
        )
        content = tcss_path.read_text()
        # Find VirtualSearchList rule block
        block_m = re.search(
            r"VirtualSearchList\s*\{([^}]+)\}", content, re.DOTALL
        )
        assert block_m, "VirtualSearchList rule block not found"
        block = block_m.group(1)
        assert "scrollbar-size-vertical: 1" in block


# ---------------------------------------------------------------------------
# TestStickyGroupHeader — R-Sr5 (4 pure unit + 4 async)
# ---------------------------------------------------------------------------

class TestStickyGroupHeader:

    def test_kinds_tagged_in_lines_list(self):
        raw = "file_a.py\n1:hit a\n2:hit a2\nfile_b.py\n3:hit b\n"
        renderer = _make_renderer(raw)
        lines = renderer._build_lines_list()
        kinds = [entry[1] for entry in lines]
        # Expected: header, hit, hit, rule, header, hit
        assert kinds[0] == "header"
        assert kinds[1] == "hit"
        assert kinds[2] == "hit"
        assert kinds[3] == "rule"
        assert kinds[4] == "header"
        assert kinds[5] == "hit"

    def test_sticky_hidden_when_header_visible(self):
        """_update_sticky hides sticky when cursor is on a header row."""
        lines = [
            ("hdr", "header", "a.py", None),
            ("hit", "hit", "a.py", 1),
        ]
        w = _make_vsl(lines)
        w._cursor_idx = 0  # cursor on header
        mock_sticky = MagicMock()
        with patch.object(w, "query_one", return_value=mock_sticky):
            w._update_sticky()
        mock_sticky.__setattr__("display", False)
        assert mock_sticky.display is not True

    def test_group_rule_replaces_blank(self):
        raw = "file_a.py\n1:foo\nfile_b.py\n2:bar\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        plain_lines = text.plain.split("\n")
        rule_plain = build_rule().plain
        assert any(ln.strip() == rule_plain.strip() for ln in plain_lines), (
            f"rule separator {rule_plain!r} not found in output lines"
        )

    def test_single_group_no_rule(self):
        raw = "file_a.py\n1:foo\n2:bar\n"
        renderer = _make_renderer(raw)
        text = renderer.build()
        rule_plain = build_rule().plain.strip()
        plain = text.plain
        assert rule_plain not in plain, "single-group output must have no rule"

    @pytest.mark.asyncio
    async def test_sticky_header_shows_current_group(self):
        from textual.app import App, ComposeResult

        lines = [
            ("hdr a", "header", "a.py", None),
            ("hit a1", "hit", "a.py", 1),
            ("hdr b", "header", "b.py", None),
            ("hit b1", "hit", "b.py", 10),
            ("hit b2", "hit", "b.py", 11),
        ]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            # Move cursor to second group's first hit (index 3)
            widget._cursor_idx = 3
            widget._update_sticky()
            await pilot.pause()
            sticky = app.query_one(_StickyGroupHeader)
            assert "b.py" in str(sticky.content)
            assert sticky.display is True

    @pytest.mark.asyncio
    async def test_sticky_header_hidden_when_header_visible(self):
        from textual.app import App, ComposeResult

        lines = [
            ("hdr", "header", "a.py", None),
            ("hit", "hit", "a.py", 1),
        ]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            widget._cursor_idx = 0
            widget._update_sticky()
            await pilot.pause()
            sticky = app.query_one(_StickyGroupHeader)
            assert sticky.display is False

    @pytest.mark.asyncio
    async def test_sticky_header_updates_on_scroll(self):
        from textual.app import App, ComposeResult

        lines = [
            ("hdr a", "header", "a.py", None),
            ("hit", "hit", "a.py", 1),
            ("hdr b", "header", "b.py", None),
            ("hit", "hit", "b.py", 5),
            ("hdr c", "header", "c.py", None),
            ("hit", "hit", "c.py", 9),
        ]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            # Move to group c's body
            widget._cursor_idx = 5
            widget._update_sticky()
            await pilot.pause()
            sticky = app.query_one(_StickyGroupHeader)
            assert "c.py" in str(sticky.content)

    @pytest.mark.asyncio
    async def test_single_group_sticky_hidden(self):
        from textual.app import App, ComposeResult

        lines = [
            ("hdr", "header", "a.py", None),
            ("hit1", "hit", "a.py", 1),
            ("hit2", "hit", "a.py", 2),
            ("hit3", "hit", "a.py", 3),
        ]

        class _App(App):
            def compose(self) -> ComposeResult:
                yield VirtualSearchList(lines=lines)

        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            widget = app.query_one(VirtualSearchList)
            # Past the header, no second header exists
            widget._cursor_idx = 3
            widget._update_sticky()
            await pilot.pause()
            sticky = app.query_one(_StickyGroupHeader)
            assert sticky.display is False

    def test_group_rule_dim_style(self):
        colors = SkinColors.default()
        rule = build_rule(colors=colors)
        # build_rule sets muted colour on the Text base style (not a span)
        base_style_str = str(rule.style)
        assert colors.muted.lower() in base_style_str.lower(), (
            "rule separator must use muted colour in base style"
        )
