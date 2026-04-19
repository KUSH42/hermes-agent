"""Tests for ToolSpec, ToolCategory, and icon resolution (v4 P1 sub-spec B §11)."""

from __future__ import annotations

import threading
import pytest

from hermes_cli.tui.tool_category import (
    ToolCategory,
    ToolSpec,
    MCPServerInfo,
    CategoryDefaults,
    TOOL_REGISTRY,
    MCP_SERVER_REGISTRY,
    _CATEGORY_DEFAULTS,
    _category_glyph,
    _classify_by_schema,
    _derive_mcp_spec,
    _parse_mcp_name,
    _resolve_icon,
    resolve_icon_final,
    register_mcp_server,
    register_tool,
    spec_for,
    classify_tool,
    _SEED_SPECS,
    _MCP_SERVER_ICON_SEED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_registry(*names: str) -> None:
    """Remove test entries from TOOL_REGISTRY without touching seed specs."""
    for name in names:
        TOOL_REGISTRY.pop(name, None)

def _clean_mcp_server(*servers: str) -> None:
    for s in servers:
        MCP_SERVER_REGISTRY.pop(s, None)


# ---------------------------------------------------------------------------
# §11 T1-T3: ToolSpec invariants
# ---------------------------------------------------------------------------

class TestToolSpecInvariants:
    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            ToolSpec(name="")

    def test_malformed_provenance_raises(self):
        with pytest.raises(ValueError, match="provenance"):
            ToolSpec(name="x", provenance="bad provenance!")

    def test_bad_primary_result_raises(self):
        with pytest.raises(ValueError, match="primary_result"):
            ToolSpec(name="x", primary_result="INVALID")

    def test_valid_spec_constructs(self):
        s = ToolSpec(
            name="my_tool",
            category=ToolCategory.FILE,
            primary_arg="path",
            primary_result="bytes",
            provenance="mcp:myserver",
        )
        assert s.name == "my_tool"
        assert s.provenance == "mcp:myserver"

    def test_frozen_immutable(self):
        s = ToolSpec(name="x")
        with pytest.raises((AttributeError, TypeError)):
            s.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# §11 T4-T8: register_tool / register_mcp_server
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_duplicate_raises(self):
        spec = ToolSpec(name="__dup_test__", category=ToolCategory.UNKNOWN, primary_result="none")
        try:
            register_tool(spec)
            with pytest.raises(ValueError, match="already registered"):
                register_tool(spec)
        finally:
            _clean_registry("__dup_test__")

    def test_register_overwrite_succeeds(self):
        spec = ToolSpec(name="__ow_test__", category=ToolCategory.UNKNOWN, primary_result="none")
        spec2 = ToolSpec(name="__ow_test__", category=ToolCategory.FILE, primary_result="bytes")
        try:
            register_tool(spec)
            register_tool(spec2, overwrite=True)
            assert TOOL_REGISTRY["__ow_test__"].category == ToolCategory.FILE
        finally:
            _clean_registry("__ow_test__")

    def test_register_mcp_server_empty_name_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            register_mcp_server("")

    def test_register_mcp_server_double_underscore_raises(self):
        with pytest.raises(ValueError, match="__"):
            register_mcp_server("bad__server")

    def test_register_mcp_server_explicit_empty_icon_nf_raises(self):
        with pytest.raises(ValueError):
            register_mcp_server("test-svc-empty", icon_nf="")

    def test_register_mcp_server_succeeds(self):
        try:
            register_mcp_server("test-svc", icon_nf="\uf408", icon_ascii="G")
            assert "test-svc" in MCP_SERVER_REGISTRY
            info = MCP_SERVER_REGISTRY["test-svc"]
            assert info.icon_nf == "\uf408"
            assert info.icon_ascii == "G"
        finally:
            _clean_mcp_server("test-svc")


# ---------------------------------------------------------------------------
# §11 T9-T12: Seed specs and classify_tool back-compat
# ---------------------------------------------------------------------------

class TestSeedSpecs:
    def test_seed_specs_present(self):
        assert "read_file" in TOOL_REGISTRY
        assert "bash" in TOOL_REGISTRY
        assert "web_search" in TOOL_REGISTRY

    def test_classify_tool_read_file(self):
        assert classify_tool("read_file") == ToolCategory.FILE

    def test_spec_for_read_file_primary_arg(self):
        assert spec_for("read_file").primary_arg == "path"

    def test_spec_for_terminal_render_header_false(self):
        s = spec_for("terminal")
        assert s.render_header is False
        assert s.terminal_inline is True


# ---------------------------------------------------------------------------
# §11 T13-T14: MCP name parsing
# ---------------------------------------------------------------------------

class TestMcpNameParse:
    def test_parse_valid_mcp_name(self):
        result = _parse_mcp_name("mcp__github__search_repositories")
        assert result == ("github", "search_repositories")

    def test_parse_invalid_name_returns_none(self):
        assert _parse_mcp_name("regular_tool") is None
        assert _parse_mcp_name("mcp__bad") is None
        assert _parse_mcp_name("") is None


# ---------------------------------------------------------------------------
# §11 T15-T20: _derive_mcp_spec and registry interaction
# ---------------------------------------------------------------------------

class TestDeriveMcpSpec:
    def test_inherits_inner_category(self):
        inner = ToolSpec(name="read_file", category=ToolCategory.FILE, primary_result="bytes")
        derived = _derive_mcp_spec("mcp__fs__read_file", "fs", "read_file", inner, None)
        assert derived.category == ToolCategory.FILE

    def test_falls_back_to_server_default_when_inner_unknown(self):
        try:
            MCP_SERVER_REGISTRY["test-mysvr"] = MCPServerInfo(
                server="test-mysvr", default_category=ToolCategory.MCP
            )
            inner = ToolSpec(name="mystery_tool", category=ToolCategory.UNKNOWN, primary_result="none")
            derived = _derive_mcp_spec("mcp__test-mysvr__mystery_tool", "test-mysvr", "mystery_tool", inner, None)
            assert derived.category == ToolCategory.MCP
        finally:
            _clean_mcp_server("test-mysvr")

    def test_provenance_set_correctly(self):
        inner = ToolSpec(name="search", category=ToolCategory.SEARCH, primary_result="results")
        derived = _derive_mcp_spec("mcp__gh__search", "gh", "search", inner, None)
        assert derived.provenance == "mcp:gh"

    def test_display_name_format(self):
        inner = ToolSpec(name="create_issue", category=ToolCategory.UNKNOWN, primary_result="none")
        derived = _derive_mcp_spec("mcp__github__create_issue", "github", "create_issue", inner, None)
        assert derived.display_name == "github.create_issue"

    def test_mcp_derived_not_in_tool_registry(self):
        name = "mcp__testsvr__some_tool_xyz"
        TOOL_REGISTRY.pop(name, None)
        _ = spec_for(name)
        assert name not in TOOL_REGISTRY

    def test_explicit_register_overrides_derived(self):
        name = "mcp__fs__read_file"
        try:
            register_tool(
                ToolSpec(name=name, category=ToolCategory.MCP, primary_result="done",
                         icon_nf="\uf868", icon_ascii="#", provenance="mcp:fs"),
                overwrite=True,
            )
            assert spec_for(name).category == ToolCategory.MCP
        finally:
            # Restore: remove the override so seed-fs wins next time
            TOOL_REGISTRY.pop(name, None)


# ---------------------------------------------------------------------------
# §11 T21-T25: Arg-name heuristic (spec_for with live args)
# ---------------------------------------------------------------------------

class TestArgHeuristic:
    def test_command_arg_yields_shell(self):
        s = spec_for("unknown_shell_tool", args={"command": "ls -la"})
        assert s.category == ToolCategory.SHELL
        assert s.primary_arg == "command"

    def test_path_arg_yields_file(self):
        s = spec_for("my_reader", args={"path": "/etc/hosts"})
        assert s.category == ToolCategory.FILE

    def test_path_and_command_yields_shell(self):
        s = spec_for("hybrid_tool", args={"path": "/tmp/x", "command": "cat"})
        assert s.category == ToolCategory.SHELL  # SHELL > FILE per §4.1

    def test_thought_arg_yields_agent(self):
        s = spec_for("my_think", args={"thought": "reconsider"})
        assert s.category == ToolCategory.AGENT
        assert s.primary_arg == "thought"

    def test_no_match_yields_unknown(self):
        s = spec_for("mystery_tool_abc", args={"foo": "bar"})
        assert s.category == ToolCategory.UNKNOWN
        assert s.primary_arg is None


# ---------------------------------------------------------------------------
# §11 T26-T30: Icon resolution
# ---------------------------------------------------------------------------

class TestIconResolution:
    def test_resolve_icon_nerd_font_uses_spec_icon_nf(self):
        s = ToolSpec(name="x", category=ToolCategory.FILE, primary_result="bytes",
                     icon_nf="\ue926", icon_ascii="F")
        assert _resolve_icon(s, nerd_font=True) == "\ue926"

    def test_resolve_icon_empty_icon_nf_falls_through_to_category_default(self):
        s = ToolSpec(name="x", category=ToolCategory.MCP, primary_result="done",
                     icon_nf="", icon_ascii="")
        glyph = _resolve_icon(s, nerd_font=True)
        assert glyph == "\uf868"  # MCP category static glyph

    def test_resolve_icon_ascii_fallback_chain(self):
        s = ToolSpec(name="x", category=ToolCategory.SHELL, primary_result="lines",
                     icon_nf="", icon_ascii="")
        result = _resolve_icon(s, nerd_font=False)
        assert result == "$"  # SHELL ascii_fallback

    def test_resolve_icon_final_mcp_override_swaps_server_icon(self):
        try:
            register_mcp_server("svr-icon", icon_nf="\uf408", icon_ascii="G")
            s = ToolSpec(name="mcp__svr-icon__x", category=ToolCategory.MCP,
                         primary_result="done", icon_nf="", icon_ascii="",
                         provenance="mcp:svr-icon")
            assert resolve_icon_final(s, nerd_font=True) == "\uf408"
            assert resolve_icon_final(s, nerd_font=False) == "G"
        finally:
            _clean_mcp_server("svr-icon")

    def test_resolve_icon_final_mcp_no_server_falls_through(self):
        _clean_mcp_server("no-svr")
        s = ToolSpec(name="x", category=ToolCategory.MCP, primary_result="done",
                     icon_nf="", icon_ascii="", provenance="mcp:no-svr")
        result = resolve_icon_final(s, nerd_font=True)
        assert result == "\uf868"  # category MCP static glyph


# ---------------------------------------------------------------------------
# §11 T31-T34: ToolSpec.from_mcp_meta
# ---------------------------------------------------------------------------

class TestFromMcpMeta:
    def test_produces_display_name_provenance_canonical(self):
        meta = {"name": "search_repos", "inputSchema": {"type": "object", "properties": {"query": {}}}}
        spec = ToolSpec.from_mcp_meta(meta, server="github")
        assert spec.display_name == "github.search_repos"
        assert spec.provenance == "mcp:github"
        assert spec.name == "mcp__github__search_repos"

    def test_schema_query_yields_search(self):
        meta = {"name": "search", "inputSchema": {"type": "object", "properties": {"query": {}}}}
        spec = ToolSpec.from_mcp_meta(meta, server="gh")
        assert spec.category == ToolCategory.SEARCH
        assert spec.primary_arg == "query"

    def test_x_hermes_heartbeat_true_sets_emit_heartbeat(self):
        meta = {
            "name": "slow_tool",
            "x-hermes-heartbeat": True,
            "inputSchema": {"type": "object", "properties": {}},
        }
        spec = ToolSpec.from_mcp_meta(meta, server="slow_svc")
        assert spec.emit_heartbeat is True

    def test_web_category_default_emit_heartbeat(self):
        meta = {
            "name": "fetch_page",
            "inputSchema": {"type": "object", "properties": {"url": {}}},
        }
        spec = ToolSpec.from_mcp_meta(meta, server="browser")
        assert spec.category == ToolCategory.WEB
        assert spec.emit_heartbeat is True


# ---------------------------------------------------------------------------
# §11 T35: Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_register_tool_does_not_corrupt(self):
        names = [f"__thread_test_{i}__" for i in range(20)]
        errors: list[Exception] = []

        def registrar(name: str) -> None:
            try:
                spec = ToolSpec(name=name, category=ToolCategory.UNKNOWN, primary_result="none")
                register_tool(spec, overwrite=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=registrar, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for name in names:
            assert name in TOOL_REGISTRY

        for name in names:
            _clean_registry(name)


# ---------------------------------------------------------------------------
# §11 T38-T39: MCP seed icon table
# ---------------------------------------------------------------------------

class TestMcpSeedIcons:
    def test_github_seed_icon(self):
        assert "github" in _MCP_SERVER_ICON_SEED
        nf, ascii_ = _MCP_SERVER_ICON_SEED["github"]
        assert nf  # non-empty nerd-font glyph
        assert ascii_ == "G"

    def test_unknown_server_falls_back_to_generic_mcp_icon(self):
        inner = ToolSpec(name="x", category=ToolCategory.UNKNOWN, primary_result="none")
        derived = _derive_mcp_spec("mcp__xyzzy_unknown__x", "xyzzy_unknown", "x", inner, None)
        assert derived.icon_nf == "\uf868"
        assert derived.icon_ascii == "#"


# ---------------------------------------------------------------------------
# §11 T40: TCSS $tool-glyph-mcp declared
# ---------------------------------------------------------------------------

class TestTcssVarDeclared:
    def test_tool_glyph_mcp_in_tcss(self):
        from pathlib import Path
        tcss = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
        content = tcss.read_text()
        assert "$tool-glyph-mcp" in content, "$tool-glyph-mcp must be declared in hermes.tcss"
