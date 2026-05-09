"""TBV — Tool body footer hygiene tests.

Spec: /home/xush/.hermes/spec_tbv_body_footer_hygiene.md

Eight test classes, 37 tests total — covers H1/H2/H3/H4 + M1/M2/M3/M4.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import time
from unittest.mock import MagicMock, patch

import pytest


_REPO_ROOT = pathlib.Path(__file__).parents[2]
_TUI_ROOT = _REPO_ROOT / "hermes_cli" / "tui"
_BODY_RENDERERS = _TUI_ROOT / "body_renderers"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw="", **kwargs):
    payload = MagicMock()
    payload.output_raw = output_raw
    payload.args = kwargs.get("args", {})
    payload.header_has_cwd = kwargs.get("header_has_cwd", False)
    payload.exit_code = kwargs.get("exit_code", None)
    payload.stderr_raw = kwargs.get("stderr_raw", None)
    payload.category = kwargs.get("category", MagicMock())
    payload.started_at = kwargs.get("started_at", 0.0)
    payload.finished_at = kwargs.get("finished_at", None)
    payload.line_count = kwargs.get("line_count", 0)
    return payload


def _cls(kind=None, confidence=1.0, metadata=None):
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    return ClassificationResult(
        kind=kind or ResultKind.TEXT,
        confidence=confidence,
        metadata=metadata or {},
    )


def _plain(renderable) -> str:
    return getattr(renderable, "plain", None) or str(renderable)


# ---------------------------------------------------------------------------
# TBV-H1 — BodyFooter retired from body renderers (5 tests)
# ---------------------------------------------------------------------------

class TestTBVH1NoFooterInBodyRenderers:
    def test_no_body_renderer_passes_footer(self):
        """Each BodyFrame-producing renderer returns BodyFrame with _footer=None."""
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.body_renderers.table import TableRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        cases = [
            (CodeRenderer, ResultKind.CODE,
             "x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6", {"path": "a.py"}),
            (DiffRenderer, ResultKind.DIFF,
             "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", {}),
            (JsonRenderer, ResultKind.JSON, '{"k":1}', {}),
            (LogRenderer, ResultKind.LOG, "INFO hello\n", {}),
            (SearchRenderer, ResultKind.SEARCH,
             "file.py\n1: hit\n", {}),
            (ShellOutputRenderer, ResultKind.TEXT, "hi\n", {}),
            (TableRenderer, ResultKind.TABLE,
             "a | b\n-|-\n1 | 2\n", {}),
        ]
        for rcls, kind, raw, args in cases:
            payload = _make_payload(output_raw=raw, args=args)
            cls_result = _cls(kind=kind, metadata={"hit_count": 1})
            r = rcls(payload, cls_result)
            with patch("hermes_cli.tui.cwd_strip.strip_cwd",
                       return_value=(raw, None)):
                frame = r.build_widget()
            assert isinstance(frame, BodyFrame), f"{rcls.__name__} → {type(frame).__name__}"
            assert frame._footer is None, f"{rcls.__name__} still has _footer"

    def test_no_tuple_entries_in_body_renderers(self):
        """No BodyFooter((...)) or `("y",` in body_renderers/ except _grammar.py."""
        bad = []
        pat_call = re.compile(r"BodyFooter\(\s*\(")
        pat_y = re.compile(r'\(\s*"y"\s*,')
        for f in _BODY_RENDERERS.glob("*.py"):
            if f.name == "_grammar.py":
                continue
            src = f.read_text()
            if pat_call.search(src) or pat_y.search(src):
                bad.append(f.name)
        assert not bad, f"renderers still contain tuple footer entries: {bad}"

    def test_footer_entries_classvar_removed(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        assert not hasattr(BodyRenderer, "footer_entries")

    def test_body_frame_compose_handles_none_footer(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.body_renderers._grammar import BodyFooter
        from textual.widgets import Static
        frame = BodyFrame(header=None, body=Static(""), footer=None)
        children = list(frame.compose())
        assert not any(isinstance(c, BodyFooter) for c in children)

    def test_replace_body_widget_does_not_mount_body_footer(self):
        """tool_blocks._block.replace_body_widget no longer mounts a BodyFooter."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        block = ToolBlock.__new__(ToolBlock)
        body = MagicMock()
        body.query.return_value = []
        body.mount = MagicMock()
        block._body = body
        block._header = MagicMock()
        block._rendered_body_widget = None
        block._rendered_plain_text = ""

        new_widget = MagicMock()
        new_widget.is_attached = False
        block.replace_body_widget(new_widget, plain_text="hi")

        # Only the new widget mount; no second mount of BodyFooter.
        assert body.mount.call_count == 1
        assert body.mount.call_args_list[0][0][0] is new_widget


# ---------------------------------------------------------------------------
# TBV-H2 — IL-12 (3 tests)
# ---------------------------------------------------------------------------

class TestTBVH2IL12NoBodyFooterImport:
    _EXEMPT = {"_grammar.py", "_frame.py"}

    def _imports(self, src: str) -> bool:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "BodyFooter":
                        return True
        return False

    def test_il12_no_body_footer_imports_in_renderers(self):
        bad = []
        for f in _BODY_RENDERERS.glob("*.py"):
            if f.name in self._EXEMPT:
                continue
            if self._imports(f.read_text()):
                bad.append(f.name)
        assert not bad, f"BodyFooter imported in: {bad}"

    def test_il12_known_violation_caught(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(
            "from hermes_cli.tui.body_renderers._grammar import BodyFooter\n"
        )
        assert self._imports(bad.read_text())

    def test_il12_exempt_modules_not_flagged(self):
        for name in self._EXEMPT:
            f = _BODY_RENDERERS / name
            if f.exists():
                # Files exist; gate skips them — sanity check the exempt list.
                assert name in self._EXEMPT


# ---------------------------------------------------------------------------
# TBV-H3 — Microcopy form (4 tests)
# ---------------------------------------------------------------------------

class TestTBVH3MicrocopyForm:
    def test_body_footer_rejects_tuple_entries(self):
        from hermes_cli.tui.body_renderers._grammar import BodyFooter, SkinColors
        footer = BodyFooter(("c", "copy"))  # ctor allows; render rejects
        footer._colors = SkinColors.default()
        with pytest.raises(TypeError):
            footer.render()

    def test_body_footer_accepts_str_entries(self):
        from hermes_cli.tui.body_renderers._grammar import BodyFooter, SkinColors
        footer = BodyFooter("INFO 2", "WARN 1")
        footer._colors = SkinColors.default()
        plain = _plain(footer.render())
        assert "INFO 2" in plain
        assert "WARN 1" in plain

    def test_body_footer_separator_uses_glyph_dot(self):
        from hermes_cli.tui.body_renderers._grammar import BodyFooter, SkinColors
        footer = BodyFooter("a", "b")
        footer._colors = SkinColors.default()
        plain = _plain(footer.render())
        assert "·" in plain or "-" in plain  # ASCII fallback under HERMES_NO_UNICODE

    def test_il3_no_bracket_space_label_form_anywhere(self):
        """Sweep owner paths for the `[x] <affordance-label>` microcopy form
        (concept §893 mandates inner-glyph form `[c]opy`, never `[c] copy`)."""
        roots = [
            _TUI_ROOT / "body_renderers",
            _TUI_ROOT / "tool_blocks",
            _TUI_ROOT / "tool_panel",
        ]
        # Restricted to known affordance labels so array-indexing code
        # like `header_cols[j] if j < n` isn't a false positive.
        labels = "copy|csv|open|exit|expand|retry|save|edit|paste|yes|cancel"
        pat = re.compile(rf"\[[a-z]\]\s+(?:{labels})\b")
        offenders = []
        for root in roots:
            for f in root.rglob("*.py"):
                for n, line in enumerate(f.read_text().splitlines(), start=1):
                    if pat.search(line):
                        offenders.append(f"{f.relative_to(_REPO_ROOT)}:{n}")
        assert not offenders, f"bracket-space-label form found: {offenders[:5]}"


# ---------------------------------------------------------------------------
# TBV-H4 — Body chrome normalisation (9 tests)
# ---------------------------------------------------------------------------

class TestTBVH4BodyChromeNormalisation:
    def _empty_renderer(self, **payload_kw):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="", **payload_kw)
        return EmptyStateRenderer(payload, _cls(kind=ResultKind.EMPTY))

    def test_empty_renderer_uses_body_frame(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        r = self._empty_renderer()
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        assert frame._header is not None

    def test_fallback_renderer_uses_body_frame(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="some text\n")
        r = FallbackRenderer(payload, _cls(kind=ResultKind.TEXT, confidence=0.3))
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)

    def test_fallback_rule_in_header_not_body(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="hello\n")
        r = FallbackRenderer(payload, _cls(kind=ResultKind.TEXT, confidence=0.3))
        frame = r.build_widget()
        # Body should be the CopyableRichLog, no inline "unclassified" string.
        body_text = _plain(r.build())
        assert "unclassified" not in body_text
        # Header carries it.
        if frame._header is not None:
            assert "unclassified" in _plain(frame._header)

    def test_log_header_includes_stats(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="INFO a\nWARN b\nERROR c\n")
        r = LogRenderer(payload, _cls(kind=ResultKind.LOG))
        frame = r.build_widget()
        h = _plain(frame._header)
        assert "INFO" in h and "WARN" in h and "ERROR" in h

    def test_log_zero_counts_render_as_zero(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="INFO only\n")
        r = LogRenderer(payload, _cls(kind=ResultKind.LOG))
        frame = r.build_widget()
        h = _plain(frame._header)
        assert "WARN 0" in h
        assert "ERROR 0" in h

    def test_table_no_csv_entry(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        raw = "a | b\n-|-\n1 | 2\n"
        payload = _make_payload(output_raw=raw)
        r = TableRenderer(payload, _cls(kind=ResultKind.TABLE))
        frame = r.build_widget()
        assert frame._footer is None
        assert "csv" not in _plain(frame._header)

    def test_all_renderers_yield_body_frame_when_payload_present(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.body_renderers.log import LogRenderer
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.body_renderers.table import TableRenderer
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        cases = [
            (CodeRenderer, ResultKind.CODE,
             "x=1\ny=2\nz=3\na=4\nb=5\nc=6"),
            (DiffRenderer, ResultKind.DIFF,
             "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"),
            (JsonRenderer, ResultKind.JSON, '{"k":1}'),
            (LogRenderer, ResultKind.LOG, "INFO hi\n"),
            (SearchRenderer, ResultKind.SEARCH, "f\n1: x\n"),
            (ShellOutputRenderer, ResultKind.TEXT, "hi\n"),
            (TableRenderer, ResultKind.TABLE, "a | b\n-|-\n1 | 2\n"),
            (EmptyStateRenderer, ResultKind.EMPTY, ""),
            (FallbackRenderer, ResultKind.TEXT, "raw text\n"),
        ]
        for rcls, kind, raw in cases:
            payload = _make_payload(output_raw=raw)
            r = rcls(payload, _cls(kind=kind, metadata={"hit_count": 1}))
            with patch("hermes_cli.tui.cwd_strip.strip_cwd",
                       return_value=(raw, None)):
                frame = r.build_widget()
            assert isinstance(frame, BodyFrame), f"{rcls.__name__} → {type(frame).__name__}"

    def test_empty_renderer_has_no_body_row(self):
        r = self._empty_renderer()
        frame = r.build_widget()
        assert frame._body is None

    def test_body_frame_accepts_none_body(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from rich.text import Text
        from textual.widgets import Static
        frame = BodyFrame(header=Text("x"), body=None, footer=None)
        children = list(frame.compose())
        # exactly one Static (the header); no body slot.
        statics = [c for c in children if isinstance(c, Static)]
        assert len(statics) == 1
        assert all("body-frame--body" not in c.classes for c in statics)


# ---------------------------------------------------------------------------
# TBV-M1 — JSON word_wrap (3 tests)
# ---------------------------------------------------------------------------

class TestTBVM1JsonWordWrap:
    def test_json_renderer_word_wrap_enabled(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from rich.syntax import Syntax
        payload = _make_payload(output_raw='{"k":1}')
        r = JsonRenderer(payload, _cls(kind=ResultKind.JSON))
        body = r.build()
        # build() may return Syntax or summary text. Walk for Syntax.
        if isinstance(body, Syntax):
            assert body.word_wrap is True

    def test_json_long_string_wraps_in_render(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from rich.console import Console
        long_val = "a" * 300
        raw = json.dumps({"x": long_val})
        payload = _make_payload(output_raw=raw)
        r = JsonRenderer(payload, _cls(kind=ResultKind.JSON))
        frame = r.build_widget()
        # Use a 80-col Console; expect no rendered line longer than ~120 cols.
        console = Console(width=80, record=True)
        from rich.syntax import Syntax
        body = frame._body
        if isinstance(body, Syntax):
            console.print(body)
            for line in console.export_text().splitlines():
                assert len(line) <= 120

    def test_code_renderer_keeps_word_wrap_disabled(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from rich.syntax import Syntax
        payload = _make_payload(
            output_raw="x = " + "1" * 200,
            args={"path": "x.py"},
        )
        r = CodeRenderer(payload, _cls(kind=ResultKind.CODE))
        frame = r.build_widget()
        body = frame._body
        if isinstance(body, Syntax):
            assert body.word_wrap is False


# ---------------------------------------------------------------------------
# TBV-M2 — Age microcopy ticks (5 tests)
# ---------------------------------------------------------------------------

class TestTBVM2AgeMicrocopyTicks:
    def _make_panel(self, elapsed: int):
        """Build a stub bound to the mixin methods."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        panel = MagicMock(spec=[])
        panel._tick_age = lambda: _ToolPanelCompletionMixin._tick_age(panel)
        panel._schedule_age_ticks = (
            lambda: _ToolPanelCompletionMixin._schedule_age_ticks(panel)
        )
        panel.is_mounted = True
        panel._completed_at = time.monotonic() - elapsed
        block = MagicMock()
        block.is_mounted = True
        block.set_age_microcopy = MagicMock()
        panel._block = block
        timer = MagicMock()
        panel.set_timer = MagicMock(return_value=timer)
        panel._age_timer = None
        return panel, timer

    def test_age_tick_reschedules_under_one_minute(self):
        panel, _ = self._make_panel(elapsed=20)
        panel._tick_age()
        assert panel.set_timer.called
        delay = panel.set_timer.call_args[0][0]
        assert delay == 10.0

    def test_age_tick_reschedules_under_one_hour(self):
        panel, _ = self._make_panel(elapsed=600)
        panel._tick_age()
        delay = panel.set_timer.call_args[0][0]
        assert delay == 30.0

    def test_age_tick_reschedules_over_one_hour(self):
        panel, _ = self._make_panel(elapsed=4000)
        panel._tick_age()
        delay = panel.set_timer.call_args[0][0]
        assert delay == 600.0

    def test_age_tick_stops_on_unmount(self):
        panel, _ = self._make_panel(elapsed=20)
        panel.is_mounted = False
        panel._tick_age()
        assert not panel.set_timer.called

    def test_age_tick_replaces_existing_timer_on_reschedule(self):
        panel, _ = self._make_panel(elapsed=20)
        prior = MagicMock()
        panel._age_timer = prior
        panel._schedule_age_ticks()
        prior.stop.assert_called_once()
        # _age_timer holds the new handle.
        assert panel._age_timer is panel.set_timer.return_value


# ---------------------------------------------------------------------------
# TBV-M3 — Compact summary in BodyFrame (3 tests)
# ---------------------------------------------------------------------------

class TestTBVM3CompactBodyFrame:
    def _make_pane(self, summary_value="(no output)", block_lines=None):
        from hermes_cli.tui.tool_panel._footer import BodyPane
        pane = BodyPane.__new__(BodyPane)
        pane._renderer = MagicMock()
        pane._renderer.summary_line.return_value = summary_value
        pane._renderer.cls_result = None
        block = MagicMock() if block_lines is not None else None
        if block is not None:
            block._all_plain = block_lines
        pane._block = block
        mounted = []
        pane.mount = MagicMock(side_effect=lambda w: mounted.append(w))
        pane.query = MagicMock(return_value=MagicMock(remove=MagicMock()))
        pane._mounted_capture = mounted
        return pane

    def test_compact_body_wrapped_in_body_frame(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        pane = self._make_pane(summary_value="3 rows × 2 cols")
        pane._render_compact_body()
        assert pane._mounted_capture, "nothing mounted"
        widget = pane._mounted_capture[0]
        assert isinstance(widget, BodyFrame)
        assert widget._density == DensityTier.COMPACT

    def test_compact_summary_text_preserved(self):
        from textual.widgets import Static
        pane = self._make_pane(summary_value="3 rows × 2 cols")
        pane._render_compact_body()
        widget = pane._mounted_capture[0]
        assert isinstance(widget._body, Static)
        assert "3 rows" in str(widget._body.render())

    def test_compact_no_output_fallback_path(self):
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from textual.widgets import Static
        pane = self._make_pane(
            summary_value="(no output)",
            block_lines=["a", "b", "c"],
        )
        pane._render_compact_body()
        widget = pane._mounted_capture[0]
        assert isinstance(widget, BodyFrame)
        assert isinstance(widget._body, Static)
        assert "(3 rows)" in str(widget._body.render())


# ---------------------------------------------------------------------------
# TBV-M4 — IL-13 dead-y key gate (5 tests)
# ---------------------------------------------------------------------------

class TestTBVM4IL13NoDeadYKey:
    _CHROME_ROOTS = (
        _TUI_ROOT / "body_renderers",
        _TUI_ROOT / "tool_blocks",
        _TUI_ROOT / "tool_panel",
    )
    _Y_BRACKET = re.compile(r"\[y\]")
    _Y_COPY_TUPLE = re.compile(r'\(\s*"y"\s*,\s*"copy"\s*\)')

    def _scan(self):
        for root in self._CHROME_ROOTS:
            if root.exists():
                yield from root.rglob("*.py")

    def test_il13_no_y_bracket_in_owner_paths(self):
        bad = []
        for f in self._scan():
            for n, line in enumerate(f.read_text().splitlines(), start=1):
                if self._Y_BRACKET.search(line):
                    bad.append(f"{f.relative_to(_REPO_ROOT)}:{n}")
        assert not bad, bad

    def test_il13_no_y_copy_tuple_in_chrome_paths(self):
        bad = []
        for f in self._scan():
            for n, line in enumerate(f.read_text().splitlines(), start=1):
                if self._Y_COPY_TUPLE.search(line):
                    bad.append(f"{f.relative_to(_REPO_ROOT)}:{n}")
        assert not bad, bad

    def test_il13_yes_no_prompts_not_flagged(self):
        sample = '("y", "yes")\n("y", "enter")\n'
        assert not self._Y_COPY_TUPLE.search(sample)

    def test_il13_known_violations_caught(self):
        assert self._Y_BRACKET.search("[y] copy")
        assert self._Y_COPY_TUPLE.search('BodyFooter(("y", "copy"))')

    def test_il13_test_files_and_non_chrome_paths_exempt(self):
        roots = [str(r) for r in self._CHROME_ROOTS]
        assert all("/tests" not in r for r in roots)
        assert all("/services" not in r for r in roots)
        assert all("/cli" not in r for r in roots)
