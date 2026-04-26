"""Tests for tool_result_parse.py — v4 parsers."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# search_result_v4 — web_search JSON count fix
# ---------------------------------------------------------------------------


def _make_search_ctx(raw, query="test"):
    """Build a ParseContext for web_search."""
    from hermes_cli.tui.tool_result_parse import search_result_v4, ParseContext, ToolStart, ToolComplete
    from hermes_cli.tui.tool_category import spec_for
    spec = spec_for("web_search")
    return ParseContext(
        complete=ToolComplete(name="web_search", raw_result=raw),
        start=ToolStart(name="web_search", args={"query": query}),
        spec=spec,
    )


def test_search_result_v4_json_count():
    """search_result_v4 counts data.web entries, not raw lines."""
    import json
    from hermes_cli.tui.tool_result_parse import search_result_v4

    payload = json.dumps({
        "success": True,
        "data": {
            "web": [
                {"url": "https://a.com", "title": "A", "description": "desc a"},
                {"url": "https://b.com", "title": "B", "description": "desc b"},
                {"url": "https://c.com", "title": "C", "description": "desc c"},
            ]
        }
    })
    result = search_result_v4(_make_search_ctx(payload))
    assert "3" in result.primary


def test_search_result_v4_json_count_fallback():
    """Non-JSON raw falls back to line count."""
    from hermes_cli.tui.tool_result_parse import search_result_v4

    raw = "match1\nmatch2\nmatch3\n"
    result = search_result_v4(_make_search_ctx(raw))
    assert "3" in result.primary


def test_search_result_v4_json_empty_web_array():
    """JSON with empty data.web falls back gracefully."""
    import json
    from hermes_cli.tui.tool_result_parse import search_result_v4

    payload = json.dumps({"success": True, "data": {"web": []}})
    result = search_result_v4(_make_search_ctx(payload))
    assert result is not None
