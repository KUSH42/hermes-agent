"""Tests for BrowserSnapshotRenderer (BR-SNAP-1/2/3)."""
from __future__ import annotations

import json
import types

import pytest

from hermes_cli.tui.body_renderers.browser_snapshot import (
    BrowserSnapshotRenderer,
    _count_nodes,
    _walk_tree,
    _MAX_TREE_LINES,
)
from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(tool_name: str, data: dict | None = None) -> types.SimpleNamespace:
    raw = json.dumps(data) if data is not None else ""
    return types.SimpleNamespace(tool_name=tool_name, output_raw=raw, category=None)


def _cls_json() -> ClassificationResult:
    return ClassificationResult(kind=ResultKind.JSON, confidence=1.0)


def _renderer(tool_name: str, data: dict | None = None) -> BrowserSnapshotRenderer:
    payload = _make_payload(tool_name, data)
    return BrowserSnapshotRenderer(payload=payload, cls_result=_cls_json())


# ---------------------------------------------------------------------------
# TestCategoryRegistration (BR-SNAP-1)
# ---------------------------------------------------------------------------

class TestCategoryRegistration:
    def test_snapshot_categorises_as_web(self):
        from hermes_cli.tui.tool_category import spec_for, ToolCategory
        spec = spec_for("browser_snapshot")
        assert spec.category == ToolCategory.WEB

    def test_get_images_categorises_as_web(self):
        from hermes_cli.tui.tool_category import spec_for, ToolCategory
        spec = spec_for("browser_get_images")
        assert spec.category == ToolCategory.WEB


# ---------------------------------------------------------------------------
# TestBrowserSnapshotRenderer (BR-SNAP-2)
# ---------------------------------------------------------------------------

class TestBrowserSnapshotRenderer:
    def test_success_renders_header_and_tree(self):
        from rich.console import Group
        data = {
            "success": True,
            "url": "https://example.com",
            "title": "Example Domain",
            "snapshot": {"role": "document", "children": [
                {"role": "heading", "name": "Welcome"},
            ]},
        }
        r = _renderer("browser_snapshot", data)
        result = r.build()
        # Group is returned with header content
        assert isinstance(result, Group)
        renderables = list(result.renderables)
        assert len(renderables) >= 3  # header text, rule, at least one tree line

    def test_failure_shows_error(self):
        from rich.console import Group
        from rich.text import Text
        data = {"success": False, "url": "https://fail.com", "error": "timeout"}
        r = _renderer("browser_snapshot", data)
        result = r.build()
        assert isinstance(result, Group)
        renderables = list(result.renderables)
        # Last element should be the error text
        last = renderables[-1]
        assert isinstance(last, Text)
        assert "timeout" in str(last)

    def test_empty_snapshot_shows_placeholder(self):
        from rich.console import Group
        from rich.text import Text
        data = {"success": True}
        r = _renderer("browser_snapshot", data)
        result = r.build()
        assert isinstance(result, Group)
        renderables = list(result.renderables)
        assert any("empty snapshot" in str(item) for item in renderables)

    def test_landmark_roles_are_bold_cyan(self):
        lines: list = []
        node = {"role": "heading", "name": "Main Title", "children": []}
        _walk_tree(node, lines, depth=0)
        assert len(lines) == 1
        text = lines[0]
        # Check that the role span uses bold cyan style
        spans_str = " ".join(str(s.style) for s in text._spans)
        assert "cyan" in spans_str

    def test_leaf_text_node_dim(self):
        lines: list = []
        node = {"role": "StaticText", "name": "Hello world", "children": []}
        _walk_tree(node, lines, depth=0)
        assert len(lines) == 1
        text = lines[0]
        spans_str = " ".join(str(s.style) for s in text._spans)
        assert "dim" in spans_str

    def test_leaf_without_name_skipped(self):
        lines: list = []
        node = {"role": "text", "children": []}
        _walk_tree(node, lines, depth=0)
        assert lines == []

    def test_href_appended_to_link(self):
        lines: list = []
        node = {"role": "link", "name": "Click me", "href": "https://target.com", "children": []}
        _walk_tree(node, lines, depth=0)
        assert len(lines) == 1
        plain = lines[0].plain
        assert "→ https://target.com" in plain

    def test_tree_truncated_at_max(self):
        from rich.console import Group
        # Build a flat tree with > _MAX_TREE_LINES children
        children = [{"role": "listitem", "name": f"item{i}"} for i in range(_MAX_TREE_LINES + 10)]
        data = {"success": True, "snapshot": {"role": "list", "children": children}}
        r = _renderer("browser_snapshot", data)
        result = r.build()
        assert isinstance(result, Group)
        renderables = list(result.renderables)
        # Last element should be the ellipsis dim line
        last = renderables[-1]
        from rich.text import Text
        assert isinstance(last, Text)
        assert "more nodes" in last.plain

    def test_can_render_only_for_snapshot(self):
        cls_json = _cls_json()
        snap_payload = _make_payload("browser_snapshot", {})
        other_payload = _make_payload("browser_navigate", {})
        assert BrowserSnapshotRenderer.can_render(cls_json, snap_payload) is True
        assert BrowserSnapshotRenderer.can_render(cls_json, other_payload) is False

    def test_malformed_json_passthrough(self):
        from rich.text import Text
        payload = types.SimpleNamespace(
            tool_name="browser_snapshot",
            output_raw="not json at all {{{",
            category=None,
        )
        r = BrowserSnapshotRenderer(payload=payload, cls_result=_cls_json())
        result = r.build()
        assert isinstance(result, Text)
        assert "not json" in result.plain

    def test_no_url_no_title_skips_header(self):
        from rich.console import Group
        data = {"success": True, "snapshot": {"role": "document", "children": []}}
        r = _renderer("browser_snapshot", data)
        result = r.build()
        # Group should exist but have no Rule (no header)
        from rich.rule import Rule
        renderables = list(result.renderables)
        assert not any(isinstance(item, Rule) for item in renderables)


# ---------------------------------------------------------------------------
# TestSummaryLine (BR-SNAP-3)
# ---------------------------------------------------------------------------

class TestSummaryLine:
    def test_summary_with_title_and_nodes(self):
        data = {
            "title": "Example Domain",
            "snapshot": {"role": "document", "children": [
                {"role": "heading", "name": "h1"},
                {"role": "paragraph"},
                {"role": "link", "name": "More info"},
                {"role": "link", "name": "More info 2"},
                {"role": "link", "name": "More info 3"},
                {"role": "link", "name": "More info 4"},
            ]},
        }
        r = _renderer("browser_snapshot", data)
        line = r.summary_line()
        assert "Example Domain" in line
        assert "nodes" in line

    def test_summary_no_title_uses_url(self):
        data = {"url": "https://example.com/page"}
        r = _renderer("browser_snapshot", data)
        line = r.summary_line()
        assert "example.com" in line

    def test_summary_url_elided(self):
        long_url = "https://example.com/" + "a" * 60
        data = {"url": long_url}
        r = _renderer("browser_snapshot", data)
        line = r.summary_line()
        # No node count → label[:60] path; label is url[:50] since no title/snapshot
        assert len(line) <= 60

    def test_summary_no_snapshot_key(self):
        data = {"title": "No tree here"}
        r = _renderer("browser_snapshot", data)
        line = r.summary_line()
        # node_count == 0, so no "(N nodes)" suffix
        assert "nodes" not in line
        assert "No tree here" in line

    def test_summary_empty_data(self):
        data: dict = {}
        r = _renderer("browser_snapshot", data)
        line = r.summary_line()
        assert line == "snapshot"

    def test_summary_malformed_json(self):
        payload = types.SimpleNamespace(
            tool_name="browser_snapshot",
            output_raw="[[broken",
            category=None,
        )
        r = BrowserSnapshotRenderer(payload=payload, cls_result=_cls_json())
        line = r.summary_line()
        assert line == "(snapshot)"
