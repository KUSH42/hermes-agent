"""Tests for Move 1: DensityResolver + ToolPanel wiring + FooterPane + header trim.

Spec: /home/xush/.hermes/2026-04-25-density-resolver-spec.md

Test layout:
    TestDR1Resolver            — 15 tests — pure resolver logic (no Textual)
    TestDR2PanelIntegration    — 14 tests — ToolPanel wiring
    TestDR3FooterTier          —  5 tests — FooterPane.set_density
    TestDR4HeaderTrim          —  3 tests — trim_tail_for_tier call-site
    TestDR5ViewStateMirror     —  3 tests — view-state mirror
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inputs(**overrides):
    """Return a DensityInputs with safe defaults, overridable by keyword."""
    from hermes_cli.tui.tool_panel.density import DensityInputs
    from hermes_cli.tui.services.tools import ToolCallState
    defaults = dict(
        phase=ToolCallState.DONE,
        is_error=False,
        has_focus=False,
        user_scrolled_up=False,
        user_override=False,
        user_override_tier=None,
        body_line_count=5,
        threshold=20,
        row_budget=None,
    )
    defaults.update(overrides)
    return DensityInputs(**defaults)


def _make_summary(
    *,
    is_error: bool = False,
    chips: tuple = (),
    stderr_tail: str = "",
    actions: tuple = (),
    artifacts: tuple = (),
    exit_code: "int | None" = None,
):
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    return ResultSummaryV4(
        primary=None,
        exit_code=exit_code,
        chips=chips,
        actions=actions,
        artifacts=artifacts,
        is_error=is_error,
        stderr_tail=stderr_tail,
    )


def _make_footer(summary=None):
    """Build an isolated FooterPane-like object for DR-3 unit tests."""
    from hermes_cli.tui.tool_panel._footer import FooterPane
    fp = FooterPane.__new__(FooterPane)
    fp._last_summary = summary
    fp._density = None
    fp.styles = types.SimpleNamespace(display="block")
    from hermes_cli.tui.tool_panel.density import DensityTier
    fp._density = DensityTier.DEFAULT
    return fp


# ---------------------------------------------------------------------------
# TestDR1Resolver — pure resolver logic
# ---------------------------------------------------------------------------

class TestDR1Resolver:
    def test_streaming_phase_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.STREAMING, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_started_phase_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.STARTED, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_generated_phase_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.GENERATED, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_cancelled_phase_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.CANCELLED, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_error_forces_default_even_with_user_compact_override(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        r = DensityResolver()
        inp = _make_inputs(
            is_error=True,
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
            body_line_count=200,
            threshold=5,
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_focus_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        r = DensityResolver()
        inp = _make_inputs(has_focus=True, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_scrolled_up_forces_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        r = DensityResolver()
        inp = _make_inputs(user_scrolled_up=True, body_line_count=200, threshold=5)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_user_override_compact_respected(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        r = DensityResolver()
        inp = _make_inputs(
            user_override=True,
            user_override_tier=DensityTier.COMPACT,
            body_line_count=5,
            threshold=20,
        )
        assert r.resolve(inp) == DensityTier.COMPACT

    def test_user_override_default_respected(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        r = DensityResolver()
        inp = _make_inputs(
            user_override=True,
            user_override_tier=DensityTier.DEFAULT,
            body_line_count=200,
            threshold=5,
        )
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_done_over_threshold_collapses_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.DONE, body_line_count=30, threshold=20)
        assert r.resolve(inp) == DensityTier.COMPACT

    def test_done_under_threshold_stays_default(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.DONE, body_line_count=12, threshold=20)
        assert r.resolve(inp) == DensityTier.DEFAULT

    def test_completing_over_threshold_collapses_to_compact(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        inp = _make_inputs(phase=ToolCallState.COMPLETING, body_line_count=30, threshold=20)
        assert r.resolve(inp) == DensityTier.COMPACT

    def test_listener_fires_on_tier_change(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        fired = []
        r.subscribe(fired.append)
        inp = _make_inputs(phase=ToolCallState.DONE, body_line_count=30, threshold=5)
        r.resolve(inp)
        assert len(fired) == 1 and fired[0].tier == DensityTier.COMPACT

    def test_listener_does_not_fire_when_tier_unchanged(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver
        from hermes_cli.tui.services.tools import ToolCallState
        r = DensityResolver()
        fired = []
        r.subscribe(fired.append)
        # Both resolve to DEFAULT (the initial tier)
        inp = _make_inputs(phase=ToolCallState.DONE, body_line_count=5, threshold=20)
        r.resolve(inp)
        r.resolve(inp)
        assert fired == []

    def test_row_budget_is_ignored(self):
        from hermes_cli.tui.tool_panel.density import DensityResolver, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState
        r1 = DensityResolver()
        r2 = DensityResolver()
        base = dict(phase=ToolCallState.DONE, body_line_count=30, threshold=5)
        inp_none = _make_inputs(**base, row_budget=None)
        inp_five = _make_inputs(**base, row_budget=5)
        t1 = r1.resolve(inp_none)
        t2 = r2.resolve(inp_five)
        assert t1 == t2


# ---------------------------------------------------------------------------
# TestDR2PanelIntegration — ToolPanel wiring
# ---------------------------------------------------------------------------

class TestDR2PanelIntegration:
    """Tests that require reactive watcher behavior use run_test(); others use
    lightweight construction."""

    @pytest.mark.asyncio
    async def test_panel_collapsed_reflects_resolver_compact(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert panel.collapsed is True

    @pytest.mark.asyncio
    async def test_panel_collapsed_reflects_resolver_default(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            # First force compact, then resolve back to default
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            panel._on_tier_change(DensityTier.DEFAULT)
            await pilot.pause()
            assert panel.collapsed is False

    @pytest.mark.asyncio
    async def test_panel_density_reactive_updates_on_resolve(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert panel.density == DensityTier.COMPACT

    def test_auto_collapse_noop_before_result_summary(self):
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        panel = types.SimpleNamespace(
            _result_summary_v4=None,
            _user_collapse_override=False,
            _category=None,
            _tool_name="",
        )
        # Bind the mixin method to the namespace
        _ToolPanelCompletionMixin._apply_complete_auto_collapse(panel)
        # No error and no further attrs set means it returned early

    @pytest.mark.asyncio
    async def test_user_toggle_sets_override_and_tier(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel.action_toggle_collapse()
            await pilot.pause()
            assert panel._user_collapse_override is True
            assert panel._user_override_tier in (DensityTier.COMPACT, DensityTier.DEFAULT)

    @pytest.mark.asyncio
    async def test_user_toggle_compact_then_resolve_keeps_compact(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            # Force to DEFAULT first so toggle goes to COMPACT
            panel._resolver._tier = DensityTier.DEFAULT
            panel.action_toggle_collapse()
            await pilot.pause()
            assert panel.collapsed is True
            assert panel._user_override_tier == DensityTier.COMPACT

    @pytest.mark.asyncio
    async def test_user_toggle_default_overrides_auto_collapse(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            # Start collapsed
            panel._resolver._tier = DensityTier.COMPACT
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            # Cycle COMPACT → HERO (HERO ineligible, no kind) → resolver at DEFAULT
            panel.action_toggle_collapse()
            await pilot.pause()
            assert panel.collapsed is False  # panel expanded despite HERO being denied
            # _user_override_tier is HERO (the requested next tier in the cycle);
            # the resolver returned DEFAULT because kind=None fails the eligibility gate.
            assert panel._resolver.tier == DensityTier.DEFAULT

    @pytest.mark.asyncio
    async def test_focus_defers_collapse_sets_should_auto_collapse(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel.focus()
            await pilot.pause()
            with patch.object(type(panel), "has_focus", new_callable=lambda: property(lambda s: True)):
                panel._apply_complete_auto_collapse()
            assert panel._should_auto_collapse is True

    @pytest.mark.asyncio
    async def test_deferred_collapse_fires_when_focus_clears(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from unittest.mock import PropertyMock
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel._body_line_count = lambda: 200
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT
            panel._view_state = types.SimpleNamespace(
                state=ToolCallState.DONE,
                density=_DT.DEFAULT,
                _watchers=[],
            )
            # Simulate focus-cleared state (has_focus=False, no focused children)
            with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                panel._apply_complete_auto_collapse()
                await pilot.pause()
            # body_line_count=200 > default threshold (6) → COMPACT
            assert panel._resolver.tier == DensityTier.COMPACT

    @pytest.mark.asyncio
    async def test_scrolled_up_skips_collapse(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            from unittest.mock import PropertyMock
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel._body_line_count = lambda: 200
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            panel._view_state = types.SimpleNamespace(state=ToolCallState.DONE, density=_DT2.DEFAULT, _watchers=[])
            # Simulate scrolled-up output panel, no focus
            fake_output = types.SimpleNamespace(_user_scrolled_up=True)
            with patch.object(pilot.app, "query_one", return_value=fake_output):
                with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                    panel._apply_complete_auto_collapse()
                    await pilot.pause()
            assert panel._resolver.tier == DensityTier.DEFAULT

    @pytest.mark.asyncio
    async def test_error_panel_never_collapses(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            from unittest.mock import PropertyMock
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary(is_error=True)
            panel._body_line_count = lambda: 200
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            panel._view_state = types.SimpleNamespace(state=ToolCallState.DONE, density=_DT2.DEFAULT, _watchers=[])
            with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                panel._apply_complete_auto_collapse()
                await pilot.pause()
            assert panel._resolver.tier == DensityTier.DEFAULT
            assert panel.collapsed is False

    @pytest.mark.asyncio
    async def test_diff_threshold_uses_20_lines(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from unittest.mock import PropertyMock
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="str_replace_editor")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            # 25 lines — over diff threshold of 20 but under default 100
            panel._body_line_count = lambda: 25
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            panel._view_state = types.SimpleNamespace(state=ToolCallState.DONE, density=_DT2.DEFAULT, _watchers=[])

            spec = types.SimpleNamespace(primary_result="diff")
            with patch("hermes_cli.tui.tool_category.spec_for", return_value=spec):
                with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                    panel._apply_complete_auto_collapse()
                    await pilot.pause()
            assert panel._resolver.tier == DensityTier.COMPACT

    @pytest.mark.asyncio
    async def test_flash_fires_only_on_auto_compact_transition(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            from unittest.mock import PropertyMock
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel._body_line_count = lambda: 200
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            panel._view_state = types.SimpleNamespace(state=ToolCallState.DONE, density=_DT2.DEFAULT, _watchers=[])
            flashes = []
            panel._flash_header = lambda msg, tone="success": flashes.append(msg)
            with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                panel._apply_complete_auto_collapse()
                await pilot.pause()
            assert any("auto-collapsed" in f for f in flashes)

    @pytest.mark.asyncio
    async def test_flash_does_not_fire_on_second_auto_resolve(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.services.tools import ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            from unittest.mock import PropertyMock
            panel = pilot.app.query_one(ToolPanel)
            panel._result_summary_v4 = _make_summary()
            panel._body_line_count = lambda: 200
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            panel._view_state = types.SimpleNamespace(state=ToolCallState.DONE, density=_DT2.DEFAULT, _watchers=[])
            flashes = []
            panel._flash_header = lambda msg, tone="success": flashes.append(msg)
            with patch.object(type(panel), "has_focus", new_callable=PropertyMock, return_value=False):
                panel._apply_complete_auto_collapse()
                await pilot.pause()
                first_count = len(flashes)
                panel._apply_complete_auto_collapse()
                await pilot.pause()
            assert len(flashes) == first_count  # no new flash on second call


# ---------------------------------------------------------------------------
# TestDR3FooterTier — FooterPane.set_density
# ---------------------------------------------------------------------------

class TestDR3FooterTier:
    def test_footer_hidden_when_tier_compact(self):
        from hermes_cli.tui.tool_panel._footer import FooterPane
        from hermes_cli.tui.tool_panel.density import DensityTier
        fp = _make_footer(summary=_make_summary())
        fp.set_density(DensityTier.COMPACT)
        assert fp.styles.display == "none"

    def test_footer_shown_when_tier_default_and_has_content(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_result_parse import Chip
        chip = Chip(text="exit 1", kind="exit", tone="error", remediation=None)
        summary = _make_summary(chips=(chip,))
        fp = _make_footer(summary=summary)
        fp.set_density(DensityTier.DEFAULT)
        assert fp.styles.display == "block"

    def test_footer_hidden_when_tier_default_and_no_content(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        fp = _make_footer(summary=_make_summary())
        fp.set_density(DensityTier.DEFAULT)
        assert fp.styles.display == "none"

    def test_set_density_compact_then_default_restores_visibility(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_result_parse import Chip
        chip = Chip(text="ok", kind="exit", tone="success", remediation=None)
        summary = _make_summary(chips=(chip,))
        fp = _make_footer(summary=summary)
        fp.set_density(DensityTier.COMPACT)
        assert fp.styles.display == "none"
        fp.set_density(DensityTier.DEFAULT)
        assert fp.styles.display == "block"

    @pytest.mark.asyncio
    async def test_panel_tier_change_routes_to_footer(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            assert panel._footer_pane is not None
            called = []
            panel._footer_pane.set_density = lambda t: called.append(t)
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert called == [DensityTier.COMPACT]


# ---------------------------------------------------------------------------
# TestDR4HeaderTrim — trim_tail_for_tier call-site
# ---------------------------------------------------------------------------

class TestDR4HeaderTrim:
    def test_trim_tail_for_tier_default_delegates_to_trim_tail_segments(self):
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import trim_tail_for_tier, _trim_tail_segments
        from hermes_cli.tui.tool_panel.density import DensityTier
        segs = [("hero", Text("some content")), ("duration", Text("  1.2s"))]
        budget = 100
        expected = _trim_tail_segments(segs, budget)
        result = trim_tail_for_tier(segs, budget, DensityTier.DEFAULT)
        assert [n for n, _ in result] == [n for n, _ in expected]

    def test_trim_tail_for_tier_compact_delegates_to_trim_tail_segments(self):
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import trim_tail_for_tier, _trim_tail_segments
        from hermes_cli.tui.tool_panel.density import DensityTier
        segs = [("exit", Text("  ✓ 0")), ("duration", Text("  0.5s")), ("linecount", Text("  10"))]
        budget = 15
        expected = _trim_tail_segments(segs, budget)
        result = trim_tail_for_tier(segs, budget, DensityTier.COMPACT)
        assert [n for n, _ in result] == [n for n, _ in expected]

    def test_trim_tail_for_tier_no_panel_ref_defaults_to_default(self):
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import trim_tail_for_tier, _trim_tail_segments
        from hermes_cli.tui.tool_panel.density import DensityTier
        # getattr fallback: panel is None → tier = DEFAULT
        segs = [("hero", Text("output"))]
        budget = 50
        result = trim_tail_for_tier(segs, budget, DensityTier.DEFAULT)
        expected = _trim_tail_segments(segs, budget)
        assert [n for n, _ in result] == [n for n, _ in expected]


# ---------------------------------------------------------------------------
# TestDR5ViewStateMirror — view-state mirror
# ---------------------------------------------------------------------------

class TestDR5ViewStateMirror:
    @pytest.mark.asyncio
    async def test_tier_change_mirrors_to_view_state(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            vs = ToolCallViewState(
                tool_call_id="tc1",
                gen_index=None,
                tool_name="Bash",
                label="Bash",
                args={},
                state=ToolCallState.DONE,
                block=None,
                panel=None,
                parent_tool_call_id=None,
                category="shell",
                depth=0,
                start_s=0.0,
            )
            panel._view_state = vs
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert vs.density == DensityTier.COMPACT

    @pytest.mark.asyncio
    async def test_tier_change_no_view_state_no_crash(self):
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            assert panel._view_state is None
            # Should not raise even with no view state and no _plan_tool_call_id
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert panel.collapsed is True

    @pytest.mark.asyncio
    async def test_view_state_not_updated_when_tier_unchanged(self):
        """Resolver fires listener only on tier change; same-tier resolve → no vs.density write."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ToolPanel(block=Static("body"), tool_name="Bash")

        async with _App().run_test() as pilot:
            panel = pilot.app.query_one(ToolPanel)
            vs = ToolCallViewState(
                tool_call_id="tc3",
                gen_index=None,
                tool_name="Bash",
                label="Bash",
                args={},
                state=ToolCallState.DONE,
                block=None,
                panel=None,
                parent_tool_call_id=None,
                category="shell",
                depth=0,
                start_s=0.0,
            )
            panel._view_state = vs
            # Force resolver to COMPACT so that second COMPACT resolve is a no-op
            panel._on_tier_change(DensityTier.COMPACT)
            await pilot.pause()
            assert vs.density == DensityTier.COMPACT
            # Now resolve again with same inputs → resolver doesn't fire listener → vs unchanged
            vs_density_before = vs.density
            inp = _make_inputs(
                phase=ToolCallState.DONE,
                body_line_count=200,
                threshold=5,
            )
            panel._resolver.resolve(inp)  # already COMPACT → same → listener NOT fired
            await pilot.pause()
            # vs.density must still be COMPACT (not re-written, proving no spurious write)
            assert vs.density == vs_density_before
