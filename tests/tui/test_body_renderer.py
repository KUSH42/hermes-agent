"""Tests for BodyRenderer and MCPBodyRenderer (§1 — UX pass 3)."""

from __future__ import annotations

import pytest
from rich.text import Text

from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# §1: MCPBodyRenderer registration and behavior
# ---------------------------------------------------------------------------


def test_mcp_body_renderer_registered():
    """BodyRenderer.for_category(ToolCategory.MCP) returns non-None without raising."""
    from hermes_cli.tui.body_renderer import BodyRenderer

    renderer = BodyRenderer.for_category(ToolCategory.MCP)
    assert renderer is not None


def test_mcp_finalize_extracts_text_content():
    """JSON with content=[{"type":"text","text":"hi"}] → Text("hi")."""
    from hermes_cli.tui.body_renderer import MCPBodyRenderer
    import json

    renderer = MCPBodyRenderer()
    payload = json.dumps({"content": [{"type": "text", "text": "hello world"}]})
    result = renderer.finalize([payload])
    assert result is not None
    assert "hello world" in result.plain


def test_mcp_finalize_multiple_text_items():
    """Multiple text items joined by double newline."""
    from hermes_cli.tui.body_renderer import MCPBodyRenderer
    import json

    renderer = MCPBodyRenderer()
    payload = json.dumps({
        "content": [
            {"type": "text", "text": "first"},
            {"type": "image", "url": "http://x"},
            {"type": "text", "text": "second"},
        ]
    })
    result = renderer.finalize([payload])
    assert result is not None
    assert "first" in result.plain
    assert "second" in result.plain


def test_mcp_finalize_non_json_returns_none():
    """Plain non-JSON string → returns None."""
    from hermes_cli.tui.body_renderer import MCPBodyRenderer

    renderer = MCPBodyRenderer()
    result = renderer.finalize(["plain text, not json"])
    assert result is None


def test_mcp_finalize_json_no_content_key_returns_none():
    """JSON without 'content' key → returns None."""
    from hermes_cli.tui.body_renderer import MCPBodyRenderer
    import json

    renderer = MCPBodyRenderer()
    payload = json.dumps({"result": "ok"})
    result = renderer.finalize([payload])
    assert result is None


def test_mcp_render_stream_line_passthrough():
    """render_stream_line passes ANSI through as Text."""
    from hermes_cli.tui.body_renderer import MCPBodyRenderer

    renderer = MCPBodyRenderer()
    raw = "\x1b[32mgreen\x1b[0m"
    plain = "green"
    result = renderer.render_stream_line(raw, plain)
    assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# SearchRenderer — web_search JSON formatting
# ---------------------------------------------------------------------------


def test_search_renderer_web_search_json_renders_title():
    """web_search JSON with data.web → Text containing result titles."""
    import json
    from hermes_cli.tui.body_renderer import SearchRenderer

    renderer = SearchRenderer()
    payload = json.dumps({
        "success": True,
        "data": {
            "web": [
                {"url": "https://example.com", "title": "Example Site", "description": "An example"},
                {"url": "https://test.org", "title": "Test Org", "description": "Testing"},
            ]
        }
    })
    result = renderer.finalize([payload])
    assert result is not None
    assert "Example Site" in result.plain
    assert "Test Org" in result.plain


def test_search_renderer_web_search_json_renders_url():
    """web_search JSON result includes URLs."""
    import json
    from hermes_cli.tui.body_renderer import SearchRenderer

    renderer = SearchRenderer()
    payload = json.dumps({
        "success": True,
        "data": {"web": [{"url": "https://example.com", "title": "Ex", "description": ""}]}
    })
    result = renderer.finalize([payload])
    assert result is not None
    assert "https://example.com" in result.plain


def test_search_renderer_web_search_json_truncates_long_description():
    """Descriptions > 120 chars are truncated with ellipsis."""
    import json
    from hermes_cli.tui.body_renderer import SearchRenderer

    renderer = SearchRenderer()
    long_desc = "x" * 200
    payload = json.dumps({
        "success": True,
        "data": {"web": [{"url": "https://a.com", "title": "T", "description": long_desc}]}
    })
    result = renderer.finalize([payload])
    assert result is not None
    assert "…" in result.plain


def test_search_renderer_non_json_falls_back():
    """Plain grep output (non-JSON) → fallback text rendering."""
    from hermes_cli.tui.body_renderer import SearchRenderer

    renderer = SearchRenderer()
    result = renderer.finalize(["src/a.py:10: match", "src/b.py:20: match"])
    assert result is not None
    assert "src/a.py" in result.plain


def test_search_renderer_empty_returns_none():
    """Empty input → None."""
    from hermes_cli.tui.body_renderer import SearchRenderer

    renderer = SearchRenderer()
    result = renderer.finalize([])
    assert result is None
