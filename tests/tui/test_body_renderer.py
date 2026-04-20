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
