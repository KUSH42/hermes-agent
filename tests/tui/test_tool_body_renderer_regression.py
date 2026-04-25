"""Tool body renderer regression tests — TBR spec (19 tests).

TBR-HIGH-01: swap renderer body content, not the whole ToolBlock.
TBR-HIGH-02: classify known search/web JSON shapes semantically.
TBR-MED-01:  SearchRenderer parses web/extract JSON shapes.
TBR-MED-02:  shell renderer selection tests match the documented rule.
TBR-LOW-01:  renderer-local BodyFooter mounts inside the body block.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(
    output_raw: str = "some output",
    tool_name: str = "bash",
    category: object = None,
) -> ToolPayload:
    if category is None:
        category = ToolCategory.SHELL
    return ToolPayload(
        tool_name=tool_name,
        category=category,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _cls(kind: ResultKind, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(kind, confidence)


def _make_app():
    from hermes_cli.tui.app import HermesApp
    return HermesApp(cli=MagicMock())


async def _pause(pilot, n: int = 3) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# TestRendererBodySwapContract — 6 tests
# ---------------------------------------------------------------------------

class TestRendererBodySwapContract:

    @pytest.mark.asyncio
    async def test_swap_renderer_keeps_tool_block_mounted(self):
        """Original ToolBlock/StreamingToolBlock remains attached after a JSON swap."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.body_renderers.json import JsonRenderer

        app = _make_app()
        async with app.run_test(size=(100, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app.mount_tool_block(
                "bash", ['{"key": "val"}'], ['{"key": "val"}'], tool_name="bash"
            )
            await _pause(pilot, 5)

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)
            old_block = panel._block

            payload = _payload('{"key": "val"}', category=ToolCategory.SHELL)
            cls_result = _cls(ResultKind.JSON, 0.95)
            panel._swap_renderer(JsonRenderer, payload, cls_result)
            await _pause(pilot, 3)

            assert panel._block is old_block
            assert old_block.is_attached

    @pytest.mark.asyncio
    async def test_swap_renderer_replaces_only_body_contents(self):
        """The new renderer widget is mounted under the block body, not as a BodyPane sibling."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel, CopyableRichLog
        from hermes_cli.tui.body_renderers.json import JsonRenderer

        app = _make_app()
        async with app.run_test(size=(100, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app.mount_tool_block(
                "bash", ['{"k": "v"}'], ['{"k": "v"}'], tool_name="bash"
            )
            await _pause(pilot, 5)

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)

            payload = _payload('{"k": "v"}', category=ToolCategory.SHELL)
            cls_result = _cls(ResultKind.JSON, 0.95)
            panel._swap_renderer(JsonRenderer, payload, cls_result)
            await _pause(pilot, 3)

            # The block's _body should contain a CopyableRichLog (JsonRenderer output)
            body = panel._block._body
            assert body.is_attached
            logs = list(body.query(CopyableRichLog))
            assert len(logs) > 0, "Renderer widget not mounted inside block body"

            # panel._block must still be an actual block (not a CopyableRichLog)
            from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
            from hermes_cli.tui.tool_blocks._block import ToolBlock
            assert isinstance(panel._block, (ToolBlock, StreamingToolBlock))

    @pytest.mark.asyncio
    async def test_swap_renderer_preserves_tool_header(self):
        """The header still exists and is attached after swap."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.body_renderers.json import JsonRenderer

        app = _make_app()
        async with app.run_test(size=(100, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app.mount_tool_block(
                "bash", ['{"x": 1}'], ['{"x": 1}'], tool_name="bash"
            )
            await _pause(pilot, 5)

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)

            payload = _payload('{"x": 1}', category=ToolCategory.SHELL)
            cls_result = _cls(ResultKind.JSON, 0.95)
            panel._swap_renderer(JsonRenderer, payload, cls_result)
            await _pause(pilot, 3)

            header = panel._block._header
            assert header is not None
            assert header.is_attached

    @pytest.mark.asyncio
    async def test_swap_renderer_preserves_tool_panel_footer(self):
        """Action/footer pane remains controlled by ToolPanel after swap."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.body_renderers.json import JsonRenderer

        app = _make_app()
        async with app.run_test(size=(100, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app.mount_tool_block(
                "bash", ['{"y": 2}'], ['{"y": 2}'], tool_name="bash"
            )
            await _pause(pilot, 5)

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)

            payload = _payload('{"y": 2}', category=ToolCategory.SHELL)
            cls_result = _cls(ResultKind.JSON, 0.95)
            panel._swap_renderer(JsonRenderer, payload, cls_result)
            await _pause(pilot, 3)

            # ToolPanel still owns _footer_pane
            assert panel._footer_pane is not None
            assert panel._footer_pane.is_attached
            assert panel._footer_pane.parent is panel

    def test_copy_content_uses_renderer_plain_text_after_swap(self):
        """copy_content() returns renderer plain text after replace_body_widget."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock

        block = ToolBlock.__new__(ToolBlock)
        block._plain_lines = ["original line 1", "original line 2"]
        block._rendered_plain_text = ""

        assert block.copy_content() == "original line 1\noriginal line 2"

        # Simulate what replace_body_widget stores
        block._rendered_plain_text = "renderer line 1\nrenderer line 2"

        assert block.copy_content() == "renderer line 1\nrenderer line 2"

    def test_renderer_swap_failure_keeps_original_body(self):
        """When build_widget() raises, old body remains and _block is unchanged."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        panel = _ToolPanelCompletionMixin()
        mock_block = MagicMock()
        panel._block = mock_block
        panel._body_pane = MagicMock()
        panel.app = MagicMock()

        class _BrokenBuildRenderer:
            def __init__(self, payload, cls_result, *, app=None):
                self.payload = payload
                self.cls_result = cls_result

            def build_widget(self):
                raise RuntimeError("intentional build failure")

        payload = _payload('{"k": "v"}')
        cls_result = _cls(ResultKind.JSON, 0.95)

        # Should not raise; exception is logged
        panel._swap_renderer(_BrokenBuildRenderer, payload, cls_result)

        # _block unchanged
        assert panel._block is mock_block


# ---------------------------------------------------------------------------
# TestSearchWebClassification — 5 tests
# ---------------------------------------------------------------------------

class TestSearchWebClassification:

    def setup_method(self):
        from hermes_cli.tui.content_classifier import classify_content
        classify_content.cache_clear()

    def test_classify_web_search_json_as_search(self):
        from hermes_cli.tui.content_classifier import classify_content

        raw = json.dumps({
            "data": {
                "web": [{"url": "https://example.com", "title": "Example", "description": "A site"}]
            }
        })
        payload = _payload(raw, tool_name="web_search", category=ToolCategory.SEARCH)
        result = classify_content(payload)

        assert result.kind == ResultKind.SEARCH
        assert result.metadata.get("source") == "web"
        assert result.metadata.get("hit_count") == 1

    def test_classify_news_json_as_search(self):
        from hermes_cli.tui.content_classifier import classify_content

        raw = json.dumps({
            "data": {
                "news": [{"url": "https://news.com/a", "title": "News Item"}]
            }
        })
        payload = _payload(raw, tool_name="news_search", category=ToolCategory.SEARCH)
        result = classify_content(payload)

        assert result.kind == ResultKind.SEARCH
        assert result.metadata.get("source") == "news"

    def test_classify_extract_results_json_as_search(self):
        from hermes_cli.tui.content_classifier import classify_content

        raw = json.dumps({
            "results": [{"url": "https://example.com", "title": "Page", "content": "Some content"}]
        })
        payload = _payload(raw, tool_name="extract", category=ToolCategory.SEARCH)
        result = classify_content(payload)

        assert result.kind == ResultKind.SEARCH
        assert result.metadata.get("source") == "extract"

    def test_classify_search_json_keeps_error_payload_search_kind(self):
        """success=False with data.web still classifies as SEARCH."""
        from hermes_cli.tui.content_classifier import classify_content

        raw = json.dumps({
            "success": False,
            "data": {
                "web": [{"url": "https://x.com", "title": "X"}]
            }
        })
        payload = _payload(raw, tool_name="web_search", category=ToolCategory.SEARCH)
        result = classify_content(payload)

        assert result.kind == ResultKind.SEARCH
        assert result.metadata.get("source") == "web"

    def test_classify_unrecognized_json_stays_json(self):
        from hermes_cli.tui.content_classifier import classify_content

        raw = json.dumps({"key": "value", "count": 42})
        payload = _payload(raw, tool_name="misc", category=ToolCategory.UNKNOWN)
        result = classify_content(payload)

        assert result.kind == ResultKind.JSON


# ---------------------------------------------------------------------------
# TestSearchRendererJsonShapes — 4 tests
# ---------------------------------------------------------------------------

class TestSearchRendererJsonShapes:

    def _make_renderer(self, raw: str, source: str | None = None) -> "object":
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        meta = {"hit_count": 1, "json": True, "query": None}
        if source:
            meta["source"] = source
        payload = _payload(raw, tool_name="web_search", category=ToolCategory.SEARCH)
        cls_result = ClassificationResult(ResultKind.SEARCH, 0.9, meta)
        return SearchRenderer(payload, cls_result)

    def test_search_renderer_renders_web_json_titles_and_urls(self):
        from hermes_cli.tui.body_renderers.search import _parse_search_json

        raw = json.dumps({
            "data": {
                "web": [
                    {"url": "https://example.com", "title": "Example", "description": "A site"}
                ]
            }
        })
        groups = _parse_search_json(raw)
        assert groups is not None
        assert len(groups) == 1
        group_name, hits = groups[0]
        assert group_name == "web results"
        assert len(hits) == 1
        line_num, content, is_hit = hits[0]
        assert is_hit is True
        assert "Example" in content
        assert "https://example.com" in content

    def test_search_renderer_renders_extract_results_json(self):
        from hermes_cli.tui.body_renderers.search import _parse_search_json

        raw = json.dumps({
            "results": [
                {"url": "https://a.com", "title": "A", "content": "First line\nSecond line"},
                {"url": "https://b.com", "title": "B"},
            ]
        })
        groups = _parse_search_json(raw)
        assert groups is not None
        assert len(groups) == 1
        group_name, hits = groups[0]
        assert group_name == "extracted results"
        assert len(hits) == 2
        # First hit includes title, url, and first content line
        _, content0, is_hit0 = hits[0]
        assert is_hit0 is True
        assert "First line" in content0

    def test_search_renderer_empty_web_json_renders_zero_hit_state(self):
        """Empty data.web list returns an empty group, not None."""
        from hermes_cli.tui.body_renderers.search import _parse_search_json

        raw = json.dumps({"data": {"web": []}})
        groups = _parse_search_json(raw)
        assert groups is not None
        group_name, hits = groups[0]
        assert group_name == "web results"
        assert hits == []

    def test_search_renderer_copy_text_uses_normalized_results(self):
        """copy_text() returns normalized hit content, one line per hit."""
        from hermes_cli.tui.body_renderers.search import SearchRenderer

        raw = json.dumps({
            "data": {
                "web": [
                    {"url": "https://a.com", "title": "A"},
                    {"url": "https://b.com", "title": "B"},
                ]
            }
        })
        payload = _payload(raw, tool_name="web_search", category=ToolCategory.SEARCH)
        cls_result = ClassificationResult(
            ResultKind.SEARCH, 0.9,
            {"hit_count": 2, "json": True, "source": "web"},
        )
        renderer = SearchRenderer(payload, cls_result)
        text = renderer.copy_text()

        lines = text.splitlines()
        assert len(lines) == 2
        assert any("A" in line for line in lines)
        assert any("B" in line for line in lines)


# ---------------------------------------------------------------------------
# TestShellSelectionPolicy — 3 tests
# ---------------------------------------------------------------------------

class TestShellSelectionPolicy:

    def test_pick_renderer_shell_text_stays_shell(self):
        """Shell TEXT always returns ShellOutputRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer, ShellOutputRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _payload(category=ToolCategory.SHELL)
        cls_result = _cls(ResultKind.TEXT, confidence=1.0)
        assert pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is ShellOutputRenderer

    def test_pick_renderer_shell_low_confidence_json_stays_shell(self):
        """Shell JSON with confidence 0.79 returns ShellOutputRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer, ShellOutputRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _payload(category=ToolCategory.SHELL)
        cls_result = _cls(ResultKind.JSON, confidence=0.79)
        assert pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is ShellOutputRenderer

    def test_pick_renderer_shell_high_confidence_json_uses_json_renderer(self):
        """Shell JSON with confidence >= 0.8 routes to JsonRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer, JsonRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _payload(category=ToolCategory.SHELL)
        cls_result = _cls(ResultKind.JSON, confidence=0.95)
        assert pick_renderer(cls_result, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is JsonRenderer


# ---------------------------------------------------------------------------
# TestRendererLocalFooter — 1 test
# ---------------------------------------------------------------------------

class TestRendererLocalFooter:

    @pytest.mark.asyncio
    async def test_body_footer_mounts_inside_tool_body_after_renderer_swap(self):
        """After a JSON swap, BodyFooter's parent is the block body, not BodyPane."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        app = _make_app()
        async with app.run_test(size=(100, 40)) as pilot:
            await _pause(pilot)
            app.agent_running = True
            await _pause(pilot)
            app.mount_tool_block(
                "bash", ['{"z": 99}'], ['{"z": 99}'], tool_name="bash"
            )
            await _pause(pilot, 5)

            output = app.query_one(OutputPanel)
            panel = output.query_one(ToolPanel)

            payload = _payload('{"z": 99}', category=ToolCategory.SHELL)
            cls_result = _cls(ResultKind.JSON, 0.95)
            panel._swap_renderer(JsonRenderer, payload, cls_result)
            await _pause(pilot, 3)

            # BodyFooter should be inside panel._block._body, not BodyPane
            body = panel._block._body
            footers = list(body.query(BodyFooter))
            assert len(footers) > 0, "BodyFooter not mounted inside block body"
            assert footers[0].parent is body
