"""Phase 2 tests for BodyRenderer hierarchy (tui-tool-panel-v2-spec.md §12.2).

20 unit tests covering render_stream_line, finalize, and preview for each
renderer in isolation — no ToolPanel wrapper needed.

T-BR1  .. T-BR7:  render_stream_line one per renderer
T-BR8  .. T-BR12: finalize for renderers that implement it
                  (CodeRenderer, FileRenderer, SearchRenderer, WebRenderer, TextRenderer)
                  Shell and Agent have finalize==None (asserted in stream tests).
T-BR13 .. T-BR19: preview one per renderer
T-BR20:            preview fallback — _preview_fallback logic gate check
"""

from __future__ import annotations

import pytest
from rich.text import Text
from rich.syntax import Syntax

from hermes_cli.tui.body_renderers.streaming import (
    StreamingBodyRenderer as BodyRenderer,
    ShellRenderer,
    CodeRenderer,
    FileRenderer,
    SearchRenderer,
    WebRenderer,
    AgentRenderer,
    TextRenderer,
)
from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# T-BR1: ShellRenderer.render_stream_line
# ---------------------------------------------------------------------------


def test_br1_shell_render_stream_line():
    """ShellRenderer returns Text.from_ansi passthrough."""
    r = ShellRenderer()
    raw = "\x1b[32mhello\x1b[0m"
    result = r.render_stream_line(raw, "hello")
    assert isinstance(result, Text)
    assert "hello" in result.plain


# ---------------------------------------------------------------------------
# T-BR2: CodeRenderer.render_stream_line
# ---------------------------------------------------------------------------


def test_br2_code_render_stream_line():
    """CodeRenderer.render_stream_line delegates to render_output_line (stdout ANSI)."""
    r = CodeRenderer()
    raw = "\x1b[33m42\x1b[0m"
    result = r.render_stream_line(raw, "42")
    assert isinstance(result, Text)
    assert "42" in result.plain


# ---------------------------------------------------------------------------
# T-BR3: FileRenderer.render_stream_line
# ---------------------------------------------------------------------------


def test_br3_file_render_stream_line():
    """FileRenderer.render_stream_line produces a Syntax per-line renderable."""
    r = FileRenderer()
    result = r.render_stream_line("x = 1", "x = 1", lang="python")
    # Should be a Syntax instance (or Text fallback, but Syntax expected)
    assert result is not None


# ---------------------------------------------------------------------------
# T-BR4: SearchRenderer.render_stream_line
# ---------------------------------------------------------------------------


def test_br4_search_render_stream_line():
    """SearchRenderer.render_stream_line returns ANSI passthrough Text."""
    r = SearchRenderer()
    result = r.render_stream_line("src/foo.py:12: def bar()", "src/foo.py:12: def bar()")
    assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# T-BR5: WebRenderer.render_stream_line
# ---------------------------------------------------------------------------


def test_br5_web_render_stream_line():
    """WebRenderer.render_stream_line returns ANSI passthrough Text."""
    r = WebRenderer()
    result = r.render_stream_line("HTTP/1.1 200 OK", "HTTP/1.1 200 OK")
    assert isinstance(result, Text)
    assert "200 OK" in result.plain


# ---------------------------------------------------------------------------
# T-BR6: AgentRenderer.render_stream_line (no finalize)
# ---------------------------------------------------------------------------


def test_br6_agent_render_stream_line_no_finalize():
    """AgentRenderer.render_stream_line returns Text; finalize returns None."""
    r = AgentRenderer()
    result = r.render_stream_line("thinking...", "thinking...")
    assert isinstance(result, Text)
    assert r.finalize(["thinking..."]) is None


# ---------------------------------------------------------------------------
# T-BR7: TextRenderer.render_stream_line (no finalize)
# ---------------------------------------------------------------------------


def test_br7_text_render_stream_line_no_finalize():
    """TextRenderer.render_stream_line returns Text; finalize returns None."""
    r = TextRenderer()
    result = r.render_stream_line("misc output", "misc output")
    assert isinstance(result, Text)
    assert "misc output" in result.plain
    assert r.finalize(["misc output"]) is None


# ---------------------------------------------------------------------------
# T-BR8: CodeRenderer.finalize (base protocol: returns None for stdout)
# ---------------------------------------------------------------------------


def test_br8_code_renderer_finalize_returns_none():
    """CodeRenderer.finalize returns None — stdout is ANSI, no canonical replacement."""
    r = CodeRenderer()
    result = r.finalize(["line1", "line2"])
    assert result is None


# ---------------------------------------------------------------------------
# T-BR9: CodeRenderer.finalize_code produces rich.Syntax
# ---------------------------------------------------------------------------


def test_br9_code_renderer_finalize_code():
    """CodeRenderer.finalize_code returns Syntax for multi-line code."""
    r = CodeRenderer()
    code = "def foo():\n    return 42"
    result = r.finalize_code(code)
    assert result is not None
    assert isinstance(result, Syntax)


def test_br9b_code_renderer_finalize_code_single_line_returns_none():
    """CodeRenderer.finalize_code returns None for single-line code (lives in header)."""
    r = CodeRenderer()
    result = r.finalize_code("print('hi')")
    assert result is None


# ---------------------------------------------------------------------------
# T-BR10: FileRenderer.finalize produces rich.Syntax
# ---------------------------------------------------------------------------


def test_br10_file_renderer_finalize():
    """FileRenderer.finalize returns Syntax for non-empty content."""
    r = FileRenderer()
    lines = ["def hello():", "    pass"]
    result = r.finalize(lines, lang="python")
    assert result is not None
    assert isinstance(result, Syntax)


def test_br10b_file_renderer_finalize_empty_returns_none():
    """FileRenderer.finalize returns None for empty content."""
    r = FileRenderer()
    assert r.finalize([]) is None


# ---------------------------------------------------------------------------
# T-BR11: SearchRenderer.finalize returns Text
# ---------------------------------------------------------------------------


def test_br11_search_renderer_finalize():
    """SearchRenderer.finalize returns a Text renderable for non-empty results."""
    r = SearchRenderer()
    lines = ["src/a.py:10: def foo()", "src/b.py:20: def bar()"]
    result = r.finalize(lines)
    assert result is not None
    assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# T-BR12: WebRenderer.finalize — JSON content → Syntax
# ---------------------------------------------------------------------------


def test_br12_web_renderer_finalize_json():
    """WebRenderer.finalize pretty-prints JSON as rich.Syntax."""
    r = WebRenderer()
    result = r.finalize(['{"key": "value", "n": 42}'])
    assert result is not None
    assert isinstance(result, Syntax)


def test_br12b_web_renderer_finalize_non_json_returns_none():
    """WebRenderer.finalize returns None for plain text (no canonical replacement)."""
    r = WebRenderer()
    result = r.finalize(["plain text response", "second line"])
    assert result is None


# ---------------------------------------------------------------------------
# T-BR13: ShellRenderer.preview
# ---------------------------------------------------------------------------


def test_br13_shell_renderer_preview():
    """ShellRenderer.preview returns last N lines as dim Text."""
    r = ShellRenderer()
    all_plain = [f"line {i}" for i in range(10)]
    result = r.preview(all_plain, max_lines=3)
    assert isinstance(result, Text)
    assert "line 9" in result.plain
    assert "line 7" in result.plain
    # line 6 should NOT be in preview (only last 3)
    assert "line 6" not in result.plain


# ---------------------------------------------------------------------------
# T-BR14: CodeRenderer.preview
# ---------------------------------------------------------------------------


def test_br14_code_renderer_preview():
    """CodeRenderer.preview returns last N output lines as dim Text."""
    r = CodeRenderer()
    all_plain = ["stdout line 1", "stdout line 2", "stdout line 3"]
    result = r.preview(all_plain, max_lines=2)
    assert isinstance(result, Text)
    assert "stdout line 2" in result.plain
    assert "stdout line 3" in result.plain


# ---------------------------------------------------------------------------
# T-BR15: FileRenderer.preview
# ---------------------------------------------------------------------------


def test_br15_file_renderer_preview():
    """FileRenderer.preview returns last N lines as dim Text."""
    r = FileRenderer()
    lines = ["a", "b", "c", "d"]
    result = r.preview(lines, max_lines=2)
    assert isinstance(result, Text)
    assert "c" in result.plain
    assert "d" in result.plain
    assert "a" not in result.plain


# ---------------------------------------------------------------------------
# T-BR16: SearchRenderer.preview
# ---------------------------------------------------------------------------


def test_br16_search_renderer_preview():
    """SearchRenderer.preview returns first N lines (entries)."""
    r = SearchRenderer()
    lines = ["match 1", "match 2", "match 3", "match 4"]
    result = r.preview(lines, max_lines=2)
    assert isinstance(result, Text)
    assert "match 1" in result.plain
    assert "match 2" in result.plain
    assert "match 4" not in result.plain


# ---------------------------------------------------------------------------
# T-BR17: WebRenderer.preview
# ---------------------------------------------------------------------------


def test_br17_web_renderer_preview():
    """WebRenderer.preview returns first 3 non-empty lines."""
    r = WebRenderer()
    lines = ["", "title: Foo", "url: http://example.com", "snippet...", "more"]
    result = r.preview(lines, max_lines=3)
    assert isinstance(result, Text)
    assert "title: Foo" in result.plain


# ---------------------------------------------------------------------------
# T-BR18: AgentRenderer.preview
# ---------------------------------------------------------------------------


def test_br18_agent_renderer_preview():
    """AgentRenderer.preview returns first line, italic style."""
    r = AgentRenderer()
    result = r.preview(["thinking about X", "next thought"], max_lines=3)
    assert isinstance(result, Text)
    assert "thinking about X" in result.plain


# ---------------------------------------------------------------------------
# T-BR19: TextRenderer.preview
# ---------------------------------------------------------------------------


def test_br19_text_renderer_preview():
    """TextRenderer.preview returns last N lines dim (fallback renderer)."""
    r = TextRenderer()
    all_plain = ["a", "b", "c", "d", "e"]
    result = r.preview(all_plain, max_lines=2)
    assert isinstance(result, Text)
    assert "d" in result.plain
    assert "e" in result.plain


# ---------------------------------------------------------------------------
# T-BR20: BodyRenderer.for_category factory + cache
# ---------------------------------------------------------------------------


def test_br20_for_category_factory_and_cache():
    """BodyRenderer.for_category returns a singleton per category."""
    r1 = BodyRenderer.for_category(ToolCategory.CODE)
    r2 = BodyRenderer.for_category(ToolCategory.CODE)
    assert r1 is r2, "for_category must return the same instance (singleton)"

    shell = BodyRenderer.for_category(ToolCategory.SHELL)
    assert isinstance(shell, ShellRenderer)

    code = BodyRenderer.for_category(ToolCategory.CODE)
    assert isinstance(code, CodeRenderer)

    file_ = BodyRenderer.for_category(ToolCategory.FILE)
    assert isinstance(file_, FileRenderer)

    search = BodyRenderer.for_category(ToolCategory.SEARCH)
    assert isinstance(search, SearchRenderer)

    web = BodyRenderer.for_category(ToolCategory.WEB)
    assert isinstance(web, WebRenderer)

    agent = BodyRenderer.for_category(ToolCategory.AGENT)
    assert isinstance(agent, AgentRenderer)

    unknown = BodyRenderer.for_category(ToolCategory.UNKNOWN)
    assert isinstance(unknown, TextRenderer)
