"""Tests for ResultSummaryV4 schema + all 8 v4 parsers (sub-spec C §8)."""

from __future__ import annotations

import pytest

from hermes_cli.tui.tool_result_parse import (
    Action,
    Artifact,
    Chip,
    ParseContext,
    ResultSummaryV4,
    ToolComplete,
    ToolStart,
    _humanize_bytes,
    parse,
)
from hermes_cli.tui.tool_category import ToolCategory, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(category: ToolCategory, primary_result: str = "none", name: str = "test") -> ToolSpec:
    return ToolSpec(
        name=name,
        category=category,
        primary_result=primary_result,
    )


def _ctx(
    raw_result="",
    is_error: bool = False,
    error_kind: str | None = None,
    exit_code: int | None = None,
    duration_ms: float | None = None,
    args: dict | None = None,
    spec: ToolSpec | None = None,
    cwd: str | None = None,
) -> ParseContext:
    name = "test"
    start = ToolStart(name=name, args=args or {}, cwd=cwd)
    complete = ToolComplete(
        name=name,
        raw_result=raw_result,
        exit_code=exit_code,
        is_error=is_error,
        error_kind=error_kind,
        duration_ms=duration_ms,
    )
    if spec is None:
        spec = _spec(ToolCategory.UNKNOWN)
    return ParseContext(complete=complete, start=start, spec=spec)


# ---------------------------------------------------------------------------
# §1 _humanize_bytes
# ---------------------------------------------------------------------------

class TestHumanizeBytes:
    def test_sub_1024(self):
        assert _humanize_bytes(0) == "0b"
        assert _humanize_bytes(512) == "512b"
        assert _humanize_bytes(1023) == "1023b"

    def test_exactly_1024(self):
        assert _humanize_bytes(1024) == "1.0kb"

    def test_kilobytes(self):
        assert _humanize_bytes(1536) == "1.5kb"

    def test_megabytes(self):
        assert _humanize_bytes(1024 * 1024) == "1.0mb"

    def test_gigabytes(self):
        assert _humanize_bytes(1024 ** 3) == "1.0gb"


# ---------------------------------------------------------------------------
# §2 Schema frozen invariants
# ---------------------------------------------------------------------------

class TestSchemaFrozen:
    def test_result_summary_v4_is_frozen(self):
        r = ResultSummaryV4(
            primary="✓", exit_code=None, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        with pytest.raises((AttributeError, TypeError)):
            r.primary = "new"  # type: ignore[misc]

    def test_chip_is_frozen(self):
        c = Chip(text="ok", kind="count", tone="neutral")
        with pytest.raises((AttributeError, TypeError)):
            c.text = "bad"  # type: ignore[misc]

    def test_action_is_frozen(self):
        a = Action(label="x", hotkey="x", kind="copy_body", payload=None)
        with pytest.raises((AttributeError, TypeError)):
            a.label = "y"  # type: ignore[misc]

    def test_artifact_is_frozen(self):
        art = Artifact(label="f", path_or_url="/tmp/f", kind="file")
        with pytest.raises((AttributeError, TypeError)):
            art.label = "g"  # type: ignore[misc]

    def test_payload_truncated_default_false(self):
        a = Action(label="x", hotkey="x", kind="copy_body", payload=None)
        assert a.payload_truncated is False

    def test_error_kind_default_none(self):
        r = ResultSummaryV4(
            primary=None, exit_code=None, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        assert r.error_kind is None


# ---------------------------------------------------------------------------
# §3 file_result_v4
# ---------------------------------------------------------------------------

class TestFileResultV4:
    def _file_ctx(self, raw="", is_error=False, error_kind=None, primary_result="lines", args=None):
        spec = _spec(ToolCategory.FILE, primary_result=primary_result)
        return _ctx(raw_result=raw, is_error=is_error, error_kind=error_kind,
                    args=args or {}, spec=spec)

    def test_error_path(self):
        ctx = self._file_ctx("permission denied", is_error=True)
        r = parse(ctx)
        assert r.is_error
        assert r.primary is not None and "✗" in r.primary
        assert len(r.actions) >= 1 and r.actions[0].kind == "copy_err"

    def test_read_file_bytes(self):
        ctx = self._file_ctx("hello world\n" * 10, primary_result="lines")
        r = parse(ctx)
        assert r.primary is not None and "✓" in r.primary
        assert not r.is_error
        assert any(c.kind == "bytes" for c in r.chips)

    def test_write_file_with_diff(self):
        diff_content = "+added line\n-removed line\n"
        ctx = self._file_ctx(diff_content, primary_result="done")
        r = parse(ctx)
        assert not r.is_error
        assert any(c.kind == "diff+" for c in r.chips)
        assert any(c.kind == "diff-" for c in r.chips)

    def test_write_no_diff_uses_line_count(self):
        ctx = self._file_ctx("wrote 5 lines\n" * 5, primary_result="done")
        r = parse(ctx)
        assert not r.is_error

    def test_artifact_created_when_path_arg(self, tmp_path):
        spec = _spec(ToolCategory.FILE, primary_result="lines")
        ctx = _ctx(raw_result="content", args={"path": str(tmp_path)}, spec=spec)
        r = parse(ctx)
        assert len(r.artifacts) == 1
        assert r.artifacts[0].kind == "file"


# ---------------------------------------------------------------------------
# §4 shell_result_v4
# ---------------------------------------------------------------------------

class TestShellResultV4:
    def _shell_ctx(self, raw="", exit_code=None, is_error=False, error_kind=None, args=None):
        spec = _spec(ToolCategory.SHELL)
        return _ctx(raw_result=raw, exit_code=exit_code, is_error=is_error,
                    error_kind=error_kind, args=args or {}, spec=spec)

    def test_success(self):
        ctx = self._shell_ctx("output line\n" * 5)
        r = parse(ctx)
        assert not r.is_error
        assert r.primary is not None and "✓" in r.primary
        assert any(a.kind == "copy_body" for a in r.actions)

    def test_nonzero_exit(self):
        ctx = self._shell_ctx("error\n", exit_code=1, is_error=True)
        r = parse(ctx)
        assert r.is_error
        assert r.exit_code == 1
        assert any(c.kind == "exit" for c in r.chips)
        assert any(a.kind == "retry" for a in r.actions)
        assert any(a.kind == "edit_cmd" for a in r.actions)

    def test_timeout(self):
        ctx = self._shell_ctx("timed out", error_kind="timeout", is_error=True)
        r = parse(ctx)
        assert r.is_error
        assert r.error_kind == "timeout"
        assert "timeout" in (r.primary or "")


# ---------------------------------------------------------------------------
# §5 code_result_v4
# ---------------------------------------------------------------------------

class TestCodeResultV4:
    def _code_ctx(self, raw="", exit_code=None, is_error=False, error_kind=None, duration_ms=None):
        spec = _spec(ToolCategory.CODE)
        return _ctx(raw_result=raw, exit_code=exit_code, is_error=is_error,
                    error_kind=error_kind, duration_ms=duration_ms, spec=spec)

    def test_success_with_duration(self):
        ctx = self._code_ctx("ok\n", duration_ms=123.0)
        r = parse(ctx)
        assert not r.is_error
        assert "123ms" in (r.primary or "")

    def test_success_without_duration(self):
        ctx = self._code_ctx("output\n")
        r = parse(ctx)
        assert not r.is_error
        assert r.primary is not None

    def test_media_artifact_extracted(self):
        ctx = self._code_ctx("result\nMEDIA: /tmp/out.png\n")
        r = parse(ctx)
        assert any(a.kind == "image" for a in r.artifacts)

    def test_error_path(self):
        ctx = self._code_ctx("traceback", exit_code=2, is_error=True)
        r = parse(ctx)
        assert r.is_error


# ---------------------------------------------------------------------------
# §6 search_result_v4
# ---------------------------------------------------------------------------

class TestSearchResultV4:
    def _search_ctx(self, raw="", is_error=False):
        spec = _spec(ToolCategory.SEARCH)
        return _ctx(raw_result=raw, is_error=is_error, spec=spec)

    def test_file_matches(self):
        ctx = self._search_ctx("src/foo.py:10: found\nsrc/bar.py:5: found\n")
        r = parse(ctx)
        assert not r.is_error
        assert r.primary is not None and "matches" in r.primary
        assert any(a.kind == "file" for a in r.artifacts)

    def test_url_matches(self):
        ctx = self._search_ctx("https://example.com/a\nhttps://example.com/b\n")
        r = parse(ctx)
        assert "results" in (r.primary or "")
        assert any(a.kind == "url" for a in r.artifacts)

    def test_empty_result(self):
        ctx = self._search_ctx("")
        r = parse(ctx)
        assert not r.is_error
        assert r.primary is not None

    def test_error_path(self):
        ctx = self._search_ctx("grep: error", is_error=True)
        r = parse(ctx)
        assert r.is_error


# ---------------------------------------------------------------------------
# §7 web_result_v4
# ---------------------------------------------------------------------------

class TestWebResultV4:
    def _web_ctx(self, raw="", is_error=False, error_kind=None, args=None):
        spec = _spec(ToolCategory.WEB)
        return _ctx(raw_result=raw, is_error=is_error, error_kind=error_kind,
                    args=args or {}, spec=spec)

    def test_200_response(self):
        ctx = self._web_ctx("HTTP/1.1 200 OK\nContent-Length: 1024\nbody", args={"url": "https://example.com"})
        r = parse(ctx)
        assert not r.is_error
        assert r.primary is not None and "200" in r.primary
        assert any(a.kind == "url" for a in r.artifacts)

    def test_4xx_error(self):
        ctx = self._web_ctx("HTTP/1.1 404 Not Found\n", is_error=True, args={"url": "https://x.com"})
        r = parse(ctx)
        assert r.is_error

    def test_timeout(self):
        ctx = self._web_ctx("", error_kind="timeout", is_error=True, args={"url": "https://x.com"})
        r = parse(ctx)
        assert r.error_kind == "timeout"
        assert "timeout" in (r.primary or "")

    def test_auth_error(self):
        ctx = self._web_ctx("401", error_kind="auth", is_error=True, args={"url": "https://x.com"})
        r = parse(ctx)
        assert r.error_kind == "auth"


# ---------------------------------------------------------------------------
# §8 agent_result_v4
# ---------------------------------------------------------------------------

class TestAgentResultV4:
    def test_success_primary_done(self):
        spec = _spec(ToolCategory.AGENT)
        ctx = _ctx(raw_result="done", spec=spec)
        r = parse(ctx)
        assert not r.is_error
        assert r.primary == "✓ done"
        assert len(r.chips) == 0

    def test_error_path(self):
        spec = _spec(ToolCategory.AGENT)
        ctx = _ctx(raw_result="error", is_error=True, spec=spec)
        r = parse(ctx)
        assert r.is_error


# ---------------------------------------------------------------------------
# §9 mcp_result_v4
# ---------------------------------------------------------------------------

class TestMcpResultV4:
    def _mcp_ctx(self, raw="", is_error=False, error_kind=None, provenance=None):
        spec = ToolSpec(
            name="mcp__test-svc__do_thing",
            category=ToolCategory.MCP,
            primary_result="results",
            provenance=provenance or "mcp:test-svc",
        )
        return _ctx(raw_result=raw, is_error=is_error, error_kind=error_kind, spec=spec)

    def test_success_json_content(self):
        raw = '{"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}'
        ctx = self._mcp_ctx(raw=raw)
        r = parse(ctx)
        assert not r.is_error
        assert any(c.kind == "mcp-source" for c in r.chips)

    def test_empty_content(self):
        raw = '{"content": []}'
        ctx = self._mcp_ctx(raw=raw)
        r = parse(ctx)
        assert r.primary == "✓ empty"

    def test_disconnect_error(self):
        ctx = self._mcp_ctx(error_kind="disconnect", is_error=True)
        r = parse(ctx)
        assert r.is_error
        assert any(a.kind == "reconnect" for a in r.actions)

    def test_server_name_from_provenance(self):
        raw = '{"content": [{"type": "text", "text": "ok"}]}'
        ctx = self._mcp_ctx(raw=raw, provenance="mcp:github")
        r = parse(ctx)
        source_chips = [c for c in r.chips if c.kind == "mcp-source"]
        assert len(source_chips) >= 1
        assert "github" in source_chips[0].text


# ---------------------------------------------------------------------------
# §10 generic_result_v4 + parse() dispatch
# ---------------------------------------------------------------------------

class TestGenericResultV4:
    def test_success(self):
        spec = _spec(ToolCategory.UNKNOWN)
        ctx = _ctx(raw_result="ok", spec=spec)
        r = parse(ctx)
        assert not r.is_error
        assert r.primary.startswith("✓"), f"Expected success primary, got: {r.primary!r}"

    def test_error(self):
        spec = _spec(ToolCategory.UNKNOWN)
        ctx = _ctx(raw_result="fail", is_error=True, spec=spec)
        r = parse(ctx)
        assert r.is_error


class TestParseDispatch:
    @pytest.mark.parametrize("category", [
        ToolCategory.FILE,
        ToolCategory.SHELL,
        ToolCategory.CODE,
        ToolCategory.SEARCH,
        ToolCategory.WEB,
        ToolCategory.AGENT,
        ToolCategory.MCP,
        ToolCategory.UNKNOWN,
    ])
    def test_parse_dispatches_all_categories(self, category):
        spec = ToolSpec(
            name="mcp__test-svc__x" if category == ToolCategory.MCP else "test",
            category=category,
            primary_result="results" if category == ToolCategory.MCP else "none",
            provenance="mcp:test-svc" if category == ToolCategory.MCP else None,
        )
        ctx = _ctx(raw_result="some output", spec=spec)
        r = parse(ctx)
        assert isinstance(r, ResultSummaryV4)


# ---------------------------------------------------------------------------
# §11 FooterPane.update_summary_v4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_footer_pane_renders_chips():
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import FooterPane

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        summary = ResultSummaryV4(
            primary="✓ ok",
            exit_code=None,
            chips=(Chip("5 lines", "count", "neutral"),),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=False,
        )
        fp.update_summary_v4(summary)
        await pilot.pause(0.05)
        # Should not raise; content updated
        assert fp._content is not None


@pytest.mark.asyncio
async def test_footer_pane_renders_error_chip():
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import FooterPane

    class _App(App):
        def compose(self) -> ComposeResult:
            yield FooterPane()

    async with _App().run_test() as pilot:
        fp = pilot.app.query_one(FooterPane)
        summary = ResultSummaryV4(
            primary="✗ exit 1",
            exit_code=1,
            chips=(Chip("exit 1", "exit", "error"),),
            stderr_tail="command not found",
            actions=(Action("copy err", "c", "copy_err", "command not found"),),
            artifacts=(),
            is_error=True,
        )
        fp.update_summary_v4(summary)
        await pilot.pause(0.05)
        assert fp._content is not None


# ---------------------------------------------------------------------------
# §12 ToolPanel.set_result_summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_panel_set_result_summary_sets_hero():
    from textual.app import App, ComposeResult
    from textual.widgets import Static
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            block = StreamingToolBlock(label="bash", tool_name="bash")
            yield ToolPanel(block=block, tool_name="bash")

    async with _App().run_test() as pilot:
        tp = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✓ 10 lines",
            exit_code=0,
            chips=(),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=False,
        )
        tp.set_result_summary(summary)
        await pilot.pause(0.05)
        stb = pilot.app.query_one(StreamingToolBlock)
        assert stb._header._primary_hero == "✓ 10 lines"


@pytest.mark.asyncio
async def test_tool_panel_set_result_summary_error_promotes_level():
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            block = StreamingToolBlock(label="bash", tool_name="bash")
            yield ToolPanel(block=block, tool_name="bash")

    async with _App().run_test() as pilot:
        tp = pilot.app.query_one(ToolPanel)
        # Manually collapse (binary collapse)
        tp.collapsed = True
        summary = ResultSummaryV4(
            primary="✗ exit 1",
            exit_code=1,
            chips=(Chip("exit 1", "exit", "error"),),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=True,
        )
        tp.set_result_summary(summary)
        await pilot.pause(0.05)
        # Error → force expand (error promotion rule)
        assert tp.collapsed is False
