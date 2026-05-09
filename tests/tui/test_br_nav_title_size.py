"""Tests for BrowserNavigateRenderer title/size separation (spec BR-NAV-TS-M1)."""
from __future__ import annotations

import json
import types

from rich.style import Style

from hermes_cli.tui.body_renderers.browser_navigate import BrowserNavigateRenderer
from hermes_cli.tui.body_renderers._grammar import SkinColors


def _payload(tool_name: str, output_raw: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(tool_name=tool_name, output_raw=output_raw)


def _make_renderer(tool_name: str, output_raw: str) -> BrowserNavigateRenderer:
    return BrowserNavigateRenderer(payload=_payload(tool_name, output_raw))


_BASE = {"status_code": 200, "url": "https://example.com", "success": True}


class TestBrowserNavigateTitleSize:
    def test_title_and_size_rendered_with_separator(self):
        data = {**_BASE, "title": "Before you continue", "content_length": 2969}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        assert "Before you continue" in plain
        assert " · " in plain
        assert "2.9kb" in plain

    def test_size_segment_uses_muted_style(self):
        data = {**_BASE, "title": "Before you continue", "content_length": 2969}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        muted_color = SkinColors.default().muted
        muted_style = Style(color=muted_color)
        plain = result.plain
        sep_idx = plain.find(" · ")
        size_idx = plain.find("2.9kb")
        assert sep_idx != -1, "separator ' · ' not found in output"
        assert size_idx != -1, "size '2.9kb' not found in output"
        # verify spans covering separator and size use muted style
        sep_spans = [s for s in result._spans if s.start <= sep_idx < s.end]
        size_spans = [s for s in result._spans if s.start <= size_idx < s.end]
        assert any(s.style == muted_style for s in sep_spans), f"separator span not muted: {sep_spans}"
        assert any(s.style == muted_style for s in size_spans), f"size span not muted: {size_spans}"

    def test_title_segment_uses_bold_style(self):
        data = {**_BASE, "title": "Before you continue", "content_length": 2969}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        title_idx = plain.find("Before you continue")
        assert title_idx != -1
        title_spans = [s for s in result._spans if s.start <= title_idx < s.end]
        assert any(s.style == "bold" for s in title_spans), f"title span not bold: {title_spans}"

    def test_empty_title_renders_size_alone(self):
        data = {**_BASE, "content_length": 1024}  # no title key
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        assert "1.0kb" in plain
        assert " · " not in plain

    def test_unknown_size_renders_title_alone(self):
        data = {**_BASE, "title": "My Page"}  # no content_length key
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        assert "My Page" in plain
        assert " · " not in plain

    def test_zero_size_still_shown(self):
        data = {**_BASE, "title": "Empty", "content_length": 0}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        assert "0b" in plain
        assert " · " in plain

    def test_non_numeric_content_length_silently_dropped(self):
        data = {**_BASE, "title": "Title", "content_length": "bad"}
        r = _make_renderer("browser_navigate", json.dumps(data))
        result = r.build()
        plain = result.plain
        assert "Title" in plain
        assert " · " not in plain
