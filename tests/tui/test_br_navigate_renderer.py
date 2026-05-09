"""Tests for BrowserNavigateRenderer (spec BR-NAV-1/2/3)."""
from __future__ import annotations

import json
import types

import pytest

from hermes_cli.tui.tool_category import spec_for, ToolCategory
from hermes_cli.tui.body_renderers.browser_navigate import BrowserNavigateRenderer


def _payload(tool_name: str, output_raw: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(tool_name=tool_name, output_raw=output_raw)


def _make_renderer(tool_name: str, output_raw: str) -> BrowserNavigateRenderer:
    return BrowserNavigateRenderer(payload=_payload(tool_name, output_raw))


class TestCategoryRegistration:
    def test_action_tools_categorise_as_web(self):
        for name in ("browser_click", "browser_type", "browser_scroll", "browser_press", "browser_back"):
            assert spec_for(name).category == ToolCategory.WEB, f"{name} should be WEB"

    def test_navigate_category_unchanged(self):
        assert spec_for("browser_navigate").category == ToolCategory.WEB


class TestBrowserNavigateRenderer:
    def test_nav_success_shows_status_url_title(self):
        data = {"status_code": 200, "url": "https://example.com", "title": "Example", "success": True}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        text = str(result)
        assert "200" in text
        assert "example.com" in text
        assert "Example" in text

    def test_nav_404_shows_red_status_and_error(self):
        data = {"status_code": 404, "url": "https://example.com/missing", "success": False, "error": "Not found"}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        text = str(result)
        assert "404" in text
        assert "Not found" in text

    def test_nav_redirect_uses_final_url(self):
        data = {"url": "https://old.com", "final_url": "https://new.com", "status_code": 200, "success": True}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        text = str(result)
        # final_url takes priority over url in _build_nav
        assert "new.com" in text

    def test_nav_no_title_skips_title_line(self):
        data = {"url": "https://example.com", "status_code": 200, "success": True}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        text = str(result)
        assert "200" in text
        assert "example.com" in text

    def test_action_click_success(self):
        data = {"element": "@e5 More information", "success": True}
        r = _make_renderer("browser_click", json.dumps(data))
        result = r.build()
        text = str(result)
        assert "Clicked" in text
        assert "@e5" in text

    def test_action_type_failure(self):
        data = {"text": "search query", "success": False, "error": "Element not found"}
        r = _make_renderer("browser_type", json.dumps(data))
        result = r.build()
        text = str(result)
        assert "Typed" in text
        assert "Element not found" in text

    def test_action_scroll_no_target(self):
        data = {"success": True}
        r = _make_renderer("browser_scroll", json.dumps(data))
        # should not crash even with no target
        result = r.build()
        text = str(result)
        assert "Scrolled" in text

    def test_malformed_json_passthrough(self):
        r = _make_renderer("browser_navigate", "not valid json {{{")
        result = r.build()
        text = str(result)
        assert "not valid json" in text


class TestSummaryLine:
    def test_summary_nav_shows_title(self):
        data = {"title": "My Page", "url": "https://example.com", "success": True}
        r = _make_renderer("browser_navigate", json.dumps(data))
        assert r.summary_line() == "My Page"

    def test_summary_nav_no_title_shows_url(self):
        data = {"url": "https://example.com/path", "success": True}
        r = _make_renderer("browser_navigate", json.dumps(data))
        assert r.summary_line() == "https://example.com/path"

    def test_summary_action_success_compact(self):
        data = {"element": "@e5", "success": True}
        r = _make_renderer("browser_click", json.dumps(data))
        result = r.summary_line()
        assert result == "✓ click @e5"

    def test_summary_action_failure_compact(self):
        data = {"text": "search query", "success": False}
        r = _make_renderer("browser_type", json.dumps(data))
        result = r.summary_line()
        assert result == "✗ type search query"
