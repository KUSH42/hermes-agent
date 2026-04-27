"""Tests for spec_streaming_legibility_rhythm.md — SLR-1 / SLR-2 / SLR-3."""
from __future__ import annotations

import sys
import textwrap
import types
from dataclasses import field as _field
from unittest.mock import MagicMock, patch
import pytest

# Module-level CSS constant — class bodies cannot access instance/local variables.
# Verbatim copy of the SLR-1 rhythm block from hermes.tcss.
_SLR1_CSS = textwrap.dedent("""\
    ToolPanel { margin-bottom: 0; }
    ToolPanel.tool-panel--tier-hero,
    ToolPanel.tool-panel--tier-default { margin-bottom: 1; }
    ToolPanel.tool-panel--tier-compact,
    ToolPanel.tool-panel--tier-trace   { margin-bottom: 0; }
    ChildPanel.tool-panel--tier-hero,
    ChildPanel.tool-panel--tier-default,
    ChildPanel.tool-panel--tier-compact,
    ChildPanel.tool-panel--tier-trace { margin-bottom: 0; }
    ToolPanel.tool-panel--error,
    ChildPanel.tool-panel--error { margin-bottom: 1; }
""")


# ---------------------------------------------------------------------------
# SLR-1: block rhythm contract + tier-class application
# ---------------------------------------------------------------------------

class TestBlockRhythm:
    """SLR-1: tier-keyed margin contract + tier-class application."""

    @pytest.mark.asyncio
    async def test_tier_class_applied_via_apply_layout(self):
        """Each DensityTier produces exactly one matching CSS class, others removed."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel, _TIER_CLASS_NAMES
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        all_class_names = set(_TIER_CLASS_NAMES.values())

        class _Block(Widget):
            """Minimal block stub."""
            pass

        class _TestApp(App):
            CSS = "ToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            for tier in (DensityTier.HERO, DensityTier.DEFAULT, DensityTier.COMPACT, DensityTier.TRACE):
                decision = LayoutDecision(tier=tier, footer_visible=False, width=80, reason="auto")
                panel._apply_layout(decision)
                await pilot.pause()
                expected = _TIER_CLASS_NAMES[tier]
                assert panel.has_class(expected), f"Expected {expected!r} for tier {tier}"
                for other in all_class_names - {expected}:
                    assert not panel.has_class(other), f"Did not expect {other!r} for tier {tier}"

    @pytest.mark.asyncio
    async def test_tier_class_toggles_on_d_keybind_path(self):
        """Calling _apply_layout twice with different tiers swaps the class correctly."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel, _TIER_CLASS_NAMES
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = "ToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d1 = LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")
            panel._apply_layout(d1)
            await pilot.pause()
            assert panel.has_class(_TIER_CLASS_NAMES[DensityTier.DEFAULT])
            d2 = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="user")
            panel._apply_layout(d2)
            await pilot.pause()
            assert panel.has_class(_TIER_CLASS_NAMES[DensityTier.COMPACT])
            assert not panel.has_class(_TIER_CLASS_NAMES[DensityTier.DEFAULT])

    # CSS margin contract — use inline CSS on a minimal App shell.
    # HermesApp.run_test() crashes with VarSpec error (memory feedback_hermesapp_css_varspec_crash).
    # Textual type selectors match the widget's Python class name; tests must mount
    # actual ToolPanel / ChildPanel instances (not generic Widget subclasses).

    @pytest.mark.asyncio
    async def test_default_tier_has_rest_gap(self):
        """DEFAULT tier earns margin-bottom: 1."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d = LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")
            panel._apply_layout(d)
            await pilot.pause()
            assert panel.styles.margin.bottom == 1

    @pytest.mark.asyncio
    async def test_compact_tier_packs_tight(self):
        """COMPACT tier → margin-bottom: 0."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="user")
            panel._apply_layout(d)
            await pilot.pause()
            assert panel.styles.margin.bottom == 0

    @pytest.mark.asyncio
    async def test_err_class_overrides_compact_rhythm(self):
        """tool-panel--error forces margin-bottom: 1 even at COMPACT tier."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="user")
            panel._apply_layout(d)
            panel.add_class("tool-panel--error")
            await pilot.pause()
            assert panel.styles.margin.bottom == 1

    @pytest.mark.asyncio
    async def test_child_panel_has_no_separator(self):
        """ChildPanel always has margin-bottom: 0 (group header is the rhythm landmark)."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._child import ChildPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nChildPanel { height: 4; } ToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ChildPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ChildPanel)
            d = LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")
            panel._apply_layout(d)
            await pilot.pause()
            assert panel.styles.margin.bottom == 0

    @pytest.mark.asyncio
    async def test_child_panel_with_err_class_still_has_gap(self):
        """ChildPanel.tool-panel--error earns margin-bottom: 1 (last-rule wins)."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._child import ChildPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nChildPanel { height: 4; } ToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ChildPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ChildPanel)
            d = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="user")
            panel._apply_layout(d)
            panel.add_class("tool-panel--error")
            await pilot.pause()
            assert panel.styles.margin.bottom == 1

    @pytest.mark.asyncio
    async def test_trace_plus_err_still_has_gap(self):
        """TRACE + error class → margin-bottom: 1."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d = LayoutDecision(tier=DensityTier.TRACE, footer_visible=False, width=80, reason="auto")
            panel._apply_layout(d)
            panel.add_class("tool-panel--error")
            await pilot.pause()
            assert panel.styles.margin.bottom == 1

    @pytest.mark.asyncio
    async def test_hero_tier_has_rest_gap(self):
        """HERO tier earns margin-bottom: 1."""
        from textual.app import App, ComposeResult
        from textual.widget import Widget
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier, LayoutDecision

        class _Block(Widget):
            pass

        class _TestApp(App):
            CSS = _SLR1_CSS + "\nToolPanel { height: 4; } _Block { height: 2; }"

            def compose(self) -> ComposeResult:
                yield ToolPanel(_Block(), tool_name="bash")

        async with _TestApp().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            d = LayoutDecision(tier=DensityTier.HERO, footer_visible=True, width=80, reason="auto")
            panel._apply_layout(d)
            await pilot.pause()
            assert panel.styles.margin.bottom == 1


# ---------------------------------------------------------------------------
# SLR-2: render_concept_mocks.py smoke + idempotence
# ---------------------------------------------------------------------------

class TestColouredMockGenerator:
    """SLR-2: render_concept_mocks.py script — sentinel insert + idempotence."""

    def _run_script(self, concept_path, out_dir):
        """Import and run the generator against a temporary concept.md."""
        import importlib.util, sys
        from pathlib import Path
        script = Path(__file__).parent.parent.parent / "scripts" / "render_concept_mocks.py"
        spec = importlib.util.spec_from_file_location("render_concept_mocks", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._update_concept_md(concept_path, out_dir)
        return mod

    def test_render_concept_mocks_script_creates_sentinels_when_missing(self, tmp_path):
        """Script inserts sentinels and SVG refs when none present."""
        concept = tmp_path / "concept.md"
        concept.write_text(
            "# Title\n\n## Canonical block mocks\n\nSome text here.\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "concept_mocks"
        mod = self._run_script(concept, out_dir)
        text = concept.read_text()
        assert "<!-- coloured-mocks-start -->" in text
        assert "<!-- coloured-mocks-end -->" in text
        assert "hero_streaming.svg" in text
        assert "default_err.svg" in text

    def test_render_concept_mocks_idempotent_with_sentinels_present(self, tmp_path):
        """Running the script twice produces identical output (no duplicated sentinels)."""
        concept = tmp_path / "concept.md"
        concept.write_text(
            "# Title\n\n## Canonical block mocks\n\nSome text.\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "concept_mocks"
        mod = self._run_script(concept, out_dir)
        first = concept.read_text()
        self._run_script(concept, out_dir)
        second = concept.read_text()
        assert first == second, "Second run must produce identical output"
        assert first.count("<!-- coloured-mocks-start -->") == 1
        assert first.count("<!-- coloured-mocks-end -->") == 1


# ---------------------------------------------------------------------------
# SLR-3: per-renderer streaming_kind_hint sniff
# ---------------------------------------------------------------------------

class TestStreamingKindHintRenderers:
    """SLR-3: per-renderer streaming_kind_hint classmethod sniff."""

    def test_diff_renderer_hints_on_git_diff(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        result = DiffRenderer.streaming_kind_hint("diff --git a/foo.py b/foo.py\nindex abc..def 100644\n")
        assert result == ResultKind.DIFF

    def test_diff_renderer_hints_on_unified_header_pair(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        result = DiffRenderer.streaming_kind_hint("--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,4 @@\n")
        assert result == ResultKind.DIFF

    def test_diff_renderer_no_hint_on_plain_text(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        result = DiffRenderer.streaming_kind_hint("Hello world\nThis is plain text\n")
        assert result is None

    def test_json_renderer_hints_on_brace(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        result = JsonRenderer.streaming_kind_hint('{\n  "key": "value"\n}')
        assert result == ResultKind.JSON

    def test_json_renderer_hints_on_bracket(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        result = JsonRenderer.streaming_kind_hint("[1, 2, 3]")
        assert result == ResultKind.JSON

    def test_code_renderer_hints_on_shebang(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        result = CodeRenderer.streaming_kind_hint("#!/usr/bin/env python\nprint('hi')\n")
        assert result == ResultKind.CODE

    def test_code_renderer_no_hint_on_plain_text(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        result = CodeRenderer.streaming_kind_hint("Hello world\nThis is plain text\n")
        assert result is None


# ---------------------------------------------------------------------------
# SLR-3: service + view-state + header integration wiring
# ---------------------------------------------------------------------------

class TestStreamingKindHintWiring:
    """SLR-3: service-level sniff buffer, view-state, header watcher wiring."""

    def _make_view(self, tool_call_id="tc1"):
        """Minimal ToolCallViewState for wiring tests."""
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        return ToolCallViewState(
            tool_call_id=tool_call_id,
            gen_index=0,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.STREAMING,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.0,
        )

    def _make_service(self):
        """ToolRenderingService with mocked Textual app."""
        from hermes_cli.tui.services.tools import ToolRenderingService
        app = MagicMock()
        app._thread_id = None
        svc = ToolRenderingService.__new__(ToolRenderingService)
        svc._app = app
        svc._tool_views_by_id = {}
        svc._state_lock = __import__("threading").RLock()
        svc._plan_broker = None
        return svc

    def test_streaming_hint_buffers_until_threshold(self):
        """Hint fires exactly once when accumulated non-whitespace >= MIN_HINT_PREFIX_BYTES."""
        # Build diff header gradually: "di" (2) + "ff " (3) + "--git a/f b/f\n" (14)
        # After 3 chunks buffer = "diff --git a/f b/f\n" (18 non-ws >= 8).
        view = self._make_view()
        svc = self._make_service()
        calls = []
        import hermes_cli.tui.services.tools as tools_mod
        orig_set_axis = tools_mod.set_axis
        def spy_set_axis(v, axis, val):
            if axis == "streaming_kind_hint":
                calls.append(val)
            orig_set_axis(v, axis, val)
        with patch.object(tools_mod, "set_axis", spy_set_axis):
            svc._run_sniff_buffer(view, "di")             # 2 non-ws, < 8
            assert len(calls) == 0
            svc._run_sniff_buffer(view, "ff ")            # 5 non-ws, < 8
            assert len(calls) == 0
            svc._run_sniff_buffer(view, "--git a/f b/f\n")  # 18 non-ws, >= 8
        assert len(calls) == 1
        from hermes_cli.tui.tool_payload import ResultKind
        assert calls[0] == ResultKind.DIFF

    def test_streaming_hint_skips_empty_first_chunk(self):
        """Whitespace-only chunks don't trigger sniff; diff header does."""
        view = self._make_view()
        svc = self._make_service()
        calls = []
        import hermes_cli.tui.services.tools as tools_mod
        orig = tools_mod.set_axis
        def spy(v, axis, val):
            if axis == "streaming_kind_hint":
                calls.append(val)
            orig(v, axis, val)
        with patch.object(tools_mod, "set_axis", spy):
            svc._run_sniff_buffer(view, "")
            svc._run_sniff_buffer(view, "   ")
            svc._run_sniff_buffer(view, "diff --git a/f b/f\n")
        assert len(calls) == 1

    def test_streaming_hint_does_not_mutate_kind(self):
        """Hint sets streaming_kind_hint; view.kind stays None."""
        view = self._make_view()
        svc = self._make_service()
        svc._run_sniff_buffer(view, "diff --git a/foo b/foo\n")
        from hermes_cli.tui.tool_payload import ResultKind
        assert view.streaming_kind_hint == ResultKind.DIFF
        assert view.kind is None

    def test_streaming_hint_does_not_swap_body_widget(self):
        """pick_renderer is not called during STREAMING."""
        view = self._make_view()
        svc = self._make_service()
        import hermes_cli.tui.body_renderers as br_mod
        with patch.object(br_mod, "pick_renderer", side_effect=AssertionError("pick_renderer called")) as pr:
            svc._run_sniff_buffer(view, "diff --git a/x b/x\n")
            # If pick_renderer was called the patch raises; silence means no call.

    def test_hint_cleared_on_state_transition(self):
        """Hint clears on COMPLETING, ERROR, CANCELLED, DONE via _set_view_state."""
        from hermes_cli.tui.services.tools import ToolCallState, set_axis
        from hermes_cli.tui.tool_payload import ResultKind
        for terminal in (
            ToolCallState.COMPLETING,
            ToolCallState.ERROR,
            ToolCallState.CANCELLED,
            ToolCallState.DONE,
        ):
            view = self._make_view()
            set_axis(view, "streaming_kind_hint", ResultKind.DIFF)
            assert view.streaming_kind_hint == ResultKind.DIFF
            svc = self._make_service()
            svc._set_view_state(view, terminal)
            assert view.streaming_kind_hint is None, f"Hint not cleared on {terminal}"

    def test_streaming_hint_does_not_fire_twice(self):
        """Buffer is discarded after sniff — second run is a no-op."""
        view = self._make_view()
        svc = self._make_service()
        calls = []
        import hermes_cli.tui.services.tools as tools_mod
        orig = tools_mod.set_axis
        def spy(v, axis, val):
            if axis == "streaming_kind_hint":
                calls.append(val)
            orig(v, axis, val)
        with patch.object(tools_mod, "set_axis", spy):
            svc._run_sniff_buffer(view, "diff --git a/f b/f\n")
            svc._run_sniff_buffer(view, "diff --git a/g b/g\n")  # buffer is None after first
        assert len(calls) == 1

    def test_hint_classmethod_raising_logs_and_returns_none(self, caplog):
        """Raising streaming_kind_hint is caught, logged, treated as None."""
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        import logging

        view = self._make_view()
        svc = self._make_service()

        def boom(chunk):
            raise ValueError("boom")

        with patch.object(JsonRenderer, "streaming_kind_hint", staticmethod(boom)):
            with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.services.tools"):
                svc._run_sniff_buffer(view, '{"key": "value"}\n')  # would normally match JSON

        # streaming_kind_hint should not be set for JsonRenderer (it raised);
        # other renderers that don't match should also leave it None.
        assert view.streaming_kind_hint is None
        # caplog should have an exception record referencing JsonRenderer.
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("JsonRenderer" in r.getMessage() for r in error_records), \
            f"Expected JsonRenderer in error log; got: {[r.getMessage() for r in error_records]}"

    @pytest.mark.asyncio
    async def test_header_swaps_icon_on_hint_set(self):
        """set_axis(view, 'streaming_kind_hint', JSON) → header shows { icon + ~json chip."""
        from textual.app import App, ComposeResult
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState, add_axis_watcher, set_axis
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_panel.density import DensityTier

        view = ToolCallViewState(
            tool_call_id="hdr-test",
            gen_index=0,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.STREAMING,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.0,
        )

        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.tool_blocks._shared import ToolHeaderStats

        posted_flashes = []

        class _TestApp(App):
            CSS = "ToolHeader { height: 1; }"

            def compose(self) -> ComposeResult:
                hdr = ToolHeader(
                    label="bash",
                    line_count=5,
                    tool_name="bash",
                )
                yield hdr

            def post_message(self, msg):
                if "Flash" in type(msg).__name__:
                    posted_flashes.append(msg)
                return super().post_message(msg)

        async with _TestApp().run_test() as pilot:
            hdr = pilot.app.query_one(ToolHeader)
            hdr.attach_stream_axis_watcher(view)
            set_axis(view, "streaming_kind_hint", ResultKind.JSON)
            await pilot.pause()
            assert hdr._streaming_kind_hint == ResultKind.JSON
            # icon should be the JSON hint icon
            ToolHeader._build_kind_hint_maps()
            assert hdr._KIND_HINT_ICON.get(ResultKind.JSON) is not None
            # No flash messages posted.
            assert posted_flashes == []
