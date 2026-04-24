"""tests/tui/test_render_visual_grammar.py

Unit tests for the shared visual-grammar module and related G-1..G-4 changes.
All tests are pure-unit (no run_test) except TestBodyFooter mount-order tests.
"""
from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# G-1 — TestGlyphs
# ---------------------------------------------------------------------------


class TestGlyphs:
    def test_glyph_unicode_default(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        monkeypatch.delenv("HERMES_ACCESSIBLE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import glyph
        assert glyph("▸") == "▸"
        assert glyph("│") == "│"
        assert glyph("·") == "·"

    def test_glyph_ascii_fallback_env(self, monkeypatch):
        monkeypatch.setenv("HERMES_NO_UNICODE", "1")
        from hermes_cli.tui.body_renderers._grammar import glyph
        assert glyph("▸") == ">"
        assert glyph("│") == "|"
        assert glyph("★") == "★"  # unknown glyph falls through unchanged


# ---------------------------------------------------------------------------
# G-1 — TestBuildPathHeader
# ---------------------------------------------------------------------------


class TestBuildPathHeader:
    def test_build_path_header_layout(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import build_path_header
        t = build_path_header("src/foo.py", right_meta="247 lines")
        plain = t.plain
        assert "▸" in plain
        assert "src/foo.py" in plain
        assert "·" in plain
        assert "247 lines" in plain

    def test_build_path_header_accent(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import build_path_header, SkinColors
        colors = SkinColors.default()
        t = build_path_header("src/foo.py", right_meta="247 lines", colors=colors)
        # Check spans: glyph span is bold=False but has color=accent
        # path span has bold=True
        spans = list(t._spans)
        # find the span for "src/foo.py"
        path_start = t.plain.index("src/foo.py")
        path_spans = [s for s in spans if s.start <= path_start < s.end]
        assert any(getattr(s.style, "bold", False) for s in path_spans)

    def test_build_path_header_no_meta(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import build_path_header
        t = build_path_header("src/foo.py")
        plain = t.plain
        assert "src/foo.py" in plain
        assert "·" not in plain


# ---------------------------------------------------------------------------
# G-1 — TestBuildGutterAndRule
# ---------------------------------------------------------------------------


class TestBuildGutterAndRule:
    def test_build_gutter_line_num_padding(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import build_gutter_line_num
        t = build_gutter_line_num(7)
        plain = t.plain
        # "     7 │ " — 5 leading spaces, total width=6, then " │ "
        assert "     7" in plain
        assert "│" in plain

    def test_build_rule_with_label(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import build_rule
        t_label = build_rule("hunk @@ -1,3 +1,4 @@")
        assert "──" in t_label.plain
        assert "hunk @@ -1,3 +1,4 @@" in t_label.plain

        t_empty = build_rule()
        assert "──" in t_empty.plain


# ---------------------------------------------------------------------------
# G-2 — TestSkinColors
# ---------------------------------------------------------------------------


class TestSkinColors:
    def test_skin_colors_from_app_resolves_primary(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {"primary": "#00aaff"}
        colors = SkinColors.from_app(mock_app)
        assert colors.accent == "#00aaff"

    def test_skin_colors_from_app_unresolved_falls_back(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {}
        colors = SkinColors.from_app(mock_app)
        default = SkinColors.default()
        assert colors == default

    def test_skin_colors_default_has_all_fields(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        d = SkinColors.default()
        hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
        for field_name in ("accent", "muted", "success", "error", "warning", "info",
                           "diff_add_bg", "diff_del_bg"):
            val = getattr(d, field_name)
            assert hex_re.match(val), f"{field_name}={val!r} is not a 6-digit hex"
        assert d.syntax_theme == "ansi_dark"

    def test_bodyrenderer_colors_lazy(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = {}
        payload = types.SimpleNamespace(output_raw="hi", category=None)
        cls_result = types.SimpleNamespace(metadata=None, kind=None, confidence=1.0)
        r = FallbackRenderer(payload, cls_result, app=mock_app)
        assert r._colors is None
        _ = r.colors
        assert r._colors is not None

    def test_bodyrenderer_colors_no_app(self):
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        payload = types.SimpleNamespace(output_raw="hi", category=None)
        cls_result = types.SimpleNamespace(metadata=None, kind=None, confidence=1.0)
        r = FallbackRenderer(payload, cls_result)
        assert r.colors == SkinColors.default()


# ---------------------------------------------------------------------------
# G-2 — TestSkinVarDeclarations
# ---------------------------------------------------------------------------


class TestSkinVarDeclarations:
    def test_new_skin_vars_declared_in_tcss(self):
        import pathlib
        tcss_path = pathlib.Path("hermes_cli/tui/hermes.tcss")
        tcss_text = tcss_path.read_text()
        assert "$diff-add-bg" in tcss_text, "hermes.tcss missing $diff-add-bg"
        assert "$diff-del-bg" in tcss_text, "hermes.tcss missing $diff-del-bg"
        assert "$info" in tcss_text, "hermes.tcss missing $info"
        # $syntax-theme is a non-hex theme name — loaded from skins; no tcss declaration needed

        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        # syntax-theme is a non-hex string — kept only in hermes.tcss and skins
        for key in ("diff-add-bg", "diff-del-bg", "info"):
            assert key in COMPONENT_VAR_DEFAULTS, f"COMPONENT_VAR_DEFAULTS missing {key!r}"


# ---------------------------------------------------------------------------
# G-3 — TestBuildWidgetCollapse
# ---------------------------------------------------------------------------


class TestBuildWidgetCollapse:
    def test_shell_renderer_no_build_widget_override(self):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        assert "build_widget" not in ShellOutputRenderer.__dict__

    def test_fallback_renderer_no_build_widget_override(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert "build_widget" not in FallbackRenderer.__dict__

    def test_search_renderer_le_100_uses_base(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer, VirtualSearchList
        from hermes_cli.tui.widgets import CopyableRichLog

        payload = types.SimpleNamespace(
            output_raw="src/foo.py\n  42: hello world\n",
            category=None,
        )
        cls_result = types.SimpleNamespace(
            metadata={"hit_count": 3, "query": "hello"},
            kind=None,
            confidence=1.0,
        )
        r = SearchRenderer(payload, cls_result)
        widget = r.build_widget()
        assert isinstance(widget, CopyableRichLog)
        assert not isinstance(widget, VirtualSearchList)

    def test_no_redundant_build_widget_overrides(self):
        from hermes_cli.tui.body_renderers import REGISTRY

        for cls in REGISTRY:
            if "build_widget" not in cls.__dict__:
                continue
            source = textwrap.dedent(inspect.getsource(cls.build_widget))
            tree = ast.parse(source)
            # Walk all Call nodes in the method body
            call_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name):
                        call_names.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        call_names.add(func.attr)
            # The override must instantiate something other than CopyableRichLog
            non_base = call_names - {"CopyableRichLog", "write", "build"}
            assert non_base, (
                f"{cls.__name__}.build_widget has no calls other than CopyableRichLog — "
                "delete the override and let the base handle it"
            )


# ---------------------------------------------------------------------------
# G-4 — TestBodyFooter
# ---------------------------------------------------------------------------


class TestBodyFooter:
    def test_body_footer_renders_keys(self, monkeypatch):
        monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
        from hermes_cli.tui.body_renderers._grammar import BodyFooter
        from rich.text import Text

        footer = BodyFooter()
        rendered = footer.render()
        if hasattr(rendered, "plain"):
            plain = rendered.plain
        else:
            plain = str(rendered)
        assert "[c]" in plain
        assert "copy" in plain
        assert "·" in plain
        assert "[o]" in plain
        assert "open in $EDITOR" in plain

    def test_body_footer_accessibility_ascii(self, monkeypatch):
        monkeypatch.setenv("HERMES_NO_UNICODE", "1")
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        footer = BodyFooter()
        rendered = footer.render()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "-" in plain
        assert "·" not in plain

    @pytest.mark.asyncio
    async def test_body_footer_hidden_when_streaming(self):
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        class _App(App):
            CSS = "#container.--streaming BodyFooter { display: none; }"

            def compose(self) -> ComposeResult:
                yield Vertical(id="container")

        async with _App().run_test(size=(80, 24)) as pilot:
            container = pilot.app.query_one("#container")
            container.add_class("--streaming")
            footer = BodyFooter()
            await container.mount(footer)
            await pilot.pause()
            assert footer.styles.display == "none"

    @pytest.mark.asyncio
    async def test_body_footer_visible_after_complete(self):
        """CSS rule .--streaming BodyFooter {display:none} lifts when class removed."""
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        class _App(App):
            CSS = "#container.--streaming BodyFooter { display: none; }"

            def compose(self) -> ComposeResult:
                yield Vertical(id="container")

        async with _App().run_test(size=(80, 24)) as pilot:
            container = pilot.app.query_one("#container")
            container.add_class("--streaming")
            footer = BodyFooter()
            await container.mount(footer)
            await pilot.pause()
            assert footer.styles.display == "none"
            container.remove_class("--streaming")
            await pilot.pause()
            assert footer.styles.display != "none"

    @pytest.mark.asyncio
    async def test_body_footer_hidden_compact(self):
        from textual.app import App, ComposeResult
        from hermes_cli.tui.body_renderers._grammar import BodyFooter

        class _App(App):
            CSS = "App.density-compact BodyFooter { display: none; }"

            def compose(self) -> ComposeResult:
                yield BodyFooter()

        async with _App().run_test(size=(80, 24)) as pilot:
            footer = pilot.app.query_one(BodyFooter)
            pilot.app.add_class("density-compact")
            await pilot.pause()
            assert footer.styles.display == "none"

    def test_body_footer_not_mounted_empty_category(self):
        """_swap_renderer should not mount BodyFooter when cls_result.kind == EMPTY."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        from hermes_cli.tui.body_renderers._grammar import BodyFooter
        from hermes_cli.tui.tool_payload import ResultKind

        mounted_widgets: list = []

        mock_body_pane = MagicMock()
        mock_body_pane.mount.side_effect = lambda w: mounted_widgets.append(w)
        mock_body_pane.query.return_value = []

        panel = types.SimpleNamespace()
        panel._body_pane = mock_body_pane
        panel._block = None
        panel.app = MagicMock()

        payload = types.SimpleNamespace(output_raw="")

        mock_renderer_cls = MagicMock()
        mock_renderer_cls.return_value.build_widget.return_value = MagicMock()
        mock_renderer_cls.return_value.build_widget.return_value.is_attached = False

        _ToolPanelCompletionMixin._swap_renderer(
            panel, mock_renderer_cls, payload,
            types.SimpleNamespace(kind=ResultKind.EMPTY, confidence=1.0, metadata=None),
        )

        footer_mounts = [w for w in mounted_widgets if isinstance(w, BodyFooter)]
        assert len(footer_mounts) == 0
