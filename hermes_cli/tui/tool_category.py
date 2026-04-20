"""Tool category taxonomy, ToolSpec registry, and icon resolution.

Phase 1 of the Tool Panel v4 architecture.  Additive on v2 — all existing
public symbols (ToolCategory, CategoryDefaults, classify_tool, _TOOL_CATEGORY)
are preserved with unchanged semantics.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# ToolCategory
# ---------------------------------------------------------------------------

class ToolCategory(Enum):
    FILE    = "file"
    SHELL   = "shell"
    CODE    = "code"
    SEARCH  = "search"
    WEB     = "web"
    AGENT   = "agent"
    MCP     = "mcp"       # v4: fallback for unclassifiable MCP tools
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# CategoryDefaults — static per-category display metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CategoryDefaults:
    accent_var: str             # TCSS variable name (without $) for accent color
    glyph_var: str              # TCSS variable name for nerd-font glyph
    ascii_fallback: str         # single-char ASCII fallback when nerd-font absent
    result_parser: str          # result parser function name
    default_collapsed_lines: int  # line threshold for auto-collapse at completion
    icon_nf: str = ""           # static nerd-font glyph; "" = no static glyph


_CATEGORY_DEFAULTS: dict[ToolCategory, CategoryDefaults] = {
    ToolCategory.FILE:    CategoryDefaults("tool-file-accent",    "tool-glyph-file",    "F", "file_result",    10),
    ToolCategory.SHELL:   CategoryDefaults("tool-shell-accent",   "tool-glyph-shell",   "$", "shell_result",   8),
    ToolCategory.CODE:    CategoryDefaults("tool-code-accent",    "tool-glyph-code",    "P", "code_result",    5),
    ToolCategory.SEARCH:  CategoryDefaults("tool-search-accent",  "tool-glyph-search",  "?", "search_result",  6),
    ToolCategory.WEB:     CategoryDefaults("tool-web-accent",     "tool-glyph-web",     "@", "web_result",     6),
    ToolCategory.AGENT:   CategoryDefaults("tool-agent-accent",   "tool-glyph-agent",   "*", "agent_result",   15),
    ToolCategory.MCP:     CategoryDefaults("tool-mcp-accent",     "tool-glyph-mcp",     "#", "mcp_result",     6, icon_nf="\uf868"),  # 󰡨
    ToolCategory.UNKNOWN: CategoryDefaults("tool-unknown-accent", "tool-glyph-unknown", "?", "generic_result", 6),
}


# ---------------------------------------------------------------------------
# ToolSpec — per-tool canonical schema (v4 §1.1)
# ---------------------------------------------------------------------------

_VALID_PRIMARY_RESULTS = frozenset({
    "diff", "lines", "matches", "status", "bytes", "results", "done", "none"
})
_PROVENANCE_RE = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    # Identity
    name: str
    display_name: str | None = None
    category: ToolCategory = ToolCategory.UNKNOWN

    # Arg / result schema hints
    primary_arg: str | None = None
    primary_result: str = "none"

    # Icon (v4 §16.3 precedence)
    icon_nf: str = ""
    icon_ascii: str = ""

    # Streaming
    streaming: bool = True
    emit_heartbeat: bool = False

    # Provenance
    provenance: str | None = None

    # Rendering flags
    render_header: bool = True
    terminal_inline: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ToolSpec.name must be non-empty")
        if self.primary_result not in _VALID_PRIMARY_RESULTS:
            raise ValueError(
                f"ToolSpec.primary_result must be one of {sorted(_VALID_PRIMARY_RESULTS)!r}, "
                f"got {self.primary_result!r}"
            )
        if self.provenance is not None and not _PROVENANCE_RE.match(self.provenance):
            raise ValueError(
                f"ToolSpec.provenance must match '<kind>:<source>', got {self.provenance!r}"
            )

    @classmethod
    def from_mcp_meta(cls, meta: dict, *, server: str) -> "ToolSpec":
        """Convert a single MCP tool-list entry into a ToolSpec (v4 §7)."""
        tool_short = meta["name"]
        canonical = f"mcp__{server}__{tool_short}"
        schema = meta.get("inputSchema") or {}
        category, primary_arg = _classify_by_schema(schema)
        inner = cls(
            name=tool_short,
            category=category,
            primary_arg=primary_arg,
            primary_result=_infer_primary_result(category, meta),
        )
        return _derive_mcp_spec(canonical, server, tool_short, inner, schema, meta)


# ---------------------------------------------------------------------------
# MCPServerInfo
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MCPServerInfo:
    server: str
    icon_nf: str = ""
    icon_ascii: str = ""
    default_category: ToolCategory = ToolCategory.MCP


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolSpec] = {}
MCP_SERVER_REGISTRY: dict[str, MCPServerInfo] = {}
_REGISTRY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# MCP name parser (v4 §4.3)
# ---------------------------------------------------------------------------

_MCP_NAME_RE = re.compile(r"^mcp__(?P<server>[A-Za-z0-9_.-]+)__(?P<tool>.+)$")


def _parse_mcp_name(name: str) -> tuple[str, str] | None:
    m = _MCP_NAME_RE.match(name)
    return (m["server"], m["tool"]) if m else None


# ---------------------------------------------------------------------------
# Classification pipeline (v4 §4)
# ---------------------------------------------------------------------------

def _classify_by_schema(schema: dict) -> tuple[ToolCategory, str | None]:
    """Apply §4.1 heuristic to a JSON-Schema properties dict."""
    props: set[str] = set((schema.get("properties") or {}).keys())
    if props & {"command", "cmd"}:
        return ToolCategory.SHELL, next(k for k in ("command", "cmd") if k in props)
    if "code" in props and "language" in props:
        return ToolCategory.CODE, "code"
    if "code" in props:
        return ToolCategory.CODE, "code"
    if props & {"query", "pattern"}:
        return ToolCategory.SEARCH, next(k for k in ("query", "pattern") if k in props)
    if "url" in props:
        return ToolCategory.WEB, "url"
    if "thought" in props:
        return ToolCategory.AGENT, "thought"
    if "description" in props and not (props - {"description"}):
        return ToolCategory.AGENT, "description"
    if "task" in props:
        return ToolCategory.AGENT, "task"
    if props & {"path", "file", "filename"}:
        return ToolCategory.FILE, next(k for k in ("path", "file", "filename") if k in props)
    return ToolCategory.UNKNOWN, None


def _classify_args(args: dict) -> tuple[ToolCategory, str | None]:
    """Apply §4.1 heuristic to a live args dict."""
    keys = set(args.keys())
    if keys & {"command", "cmd"}:
        return ToolCategory.SHELL, next(k for k in ("command", "cmd") if k in keys)
    if "code" in keys and "language" in keys:
        return ToolCategory.CODE, "code"
    if "code" in keys:
        return ToolCategory.CODE, "code"
    if keys & {"query", "pattern"}:
        return ToolCategory.SEARCH, next(k for k in ("query", "pattern") if k in keys)
    if "url" in keys:
        return ToolCategory.WEB, "url"
    if "thought" in keys:
        return ToolCategory.AGENT, "thought"
    if "description" in keys and not (keys - {"description"}):
        return ToolCategory.AGENT, "description"
    if "task" in keys:
        return ToolCategory.AGENT, "task"
    if keys & {"path", "file", "filename"}:
        return ToolCategory.FILE, next(k for k in ("path", "file", "filename") if k in keys)
    return ToolCategory.UNKNOWN, None


def _infer_primary_result(category: ToolCategory, meta: dict | None = None) -> str:
    """Infer primary_result from category (v4 §7.3)."""
    if meta is not None and category == ToolCategory.MCP:
        out_schema = meta.get("outputSchema") or {}
        if out_schema.get("type") == "array":
            return "results"
        props = out_schema.get("properties") or {}
        if "results" in props or "items" in props:
            return "results"
    table: dict[ToolCategory, str] = {
        ToolCategory.FILE:    "bytes",
        ToolCategory.SHELL:   "lines",
        ToolCategory.CODE:    "lines",
        ToolCategory.SEARCH:  "results",
        ToolCategory.WEB:     "status",
        ToolCategory.AGENT:   "done",
        ToolCategory.MCP:     "done",
        ToolCategory.UNKNOWN: "none",
    }
    return table[category]


# ---------------------------------------------------------------------------
# MCP spec derivation (v4 §4.4)
# ---------------------------------------------------------------------------

_MCP_SERVER_ICON_SEED: dict[str, tuple[str, str]] = {
    "github":       ("\uf408", "G"),
    "gitlab":       ("\uf296", "G"),
    "notion":       ("\ue685", "N"),
    "slack":        ("\uf198", "S"),
    "linear":       ("\uf0e8", "L"),
    "google_drive": ("\uf74a", "D"),
    "jira":         ("\uf4b6", "J"),
    "confluence":   ("\uf4b6", "C"),
    "stripe":       ("\uf076", "$"),
    "fs":           ("\uf4a5", "F"),
}


def _derive_mcp_spec(
    name: str, server: str, tool_short: str,
    inner_spec: ToolSpec, schema: dict | None,
    meta: dict | None = None,
) -> ToolSpec:
    server_info = MCP_SERVER_REGISTRY.get(server)
    category = (
        inner_spec.category
        if inner_spec.category != ToolCategory.UNKNOWN
        else (server_info.default_category if server_info else ToolCategory.MCP)
    )
    seed = _MCP_SERVER_ICON_SEED.get(server)
    icon_nf = (
        server_info.icon_nf if server_info and server_info.icon_nf
        else (seed[0] if seed else "\uf868")
    )
    icon_ascii = (
        server_info.icon_ascii if server_info and server_info.icon_ascii
        else (seed[1] if seed else "#")
    )
    emit_hb = False
    if meta is not None:
        if meta.get("x-hermes-heartbeat") is True:
            emit_hb = True
        elif category in (ToolCategory.WEB, ToolCategory.MCP):
            emit_hb = True  # MCP meta has no streaming annotation; assume slow req/resp
    return ToolSpec(
        name=name,
        display_name=f"{server}.{tool_short}",
        category=category,
        primary_arg=inner_spec.primary_arg,
        primary_result=inner_spec.primary_result,
        icon_nf=icon_nf,
        icon_ascii=icon_ascii,
        streaming=inner_spec.streaming,
        emit_heartbeat=emit_hb,
        provenance=f"mcp:{server}",
        render_header=True,
        terminal_inline=False,
    )


# ---------------------------------------------------------------------------
# Icon resolution (v4 §6)
# ---------------------------------------------------------------------------

def _category_glyph(cat: ToolCategory) -> str:
    """Return the static nerd-font glyph for a category, or '' if none."""
    return _CATEGORY_DEFAULTS[cat].icon_nf


def _resolve_icon(spec: ToolSpec, nerd_font: bool) -> str:
    """Internal icon resolver — category path only. Use resolve_icon_final."""
    defaults = _CATEGORY_DEFAULTS[spec.category]
    if nerd_font:
        if spec.icon_nf:
            return spec.icon_nf
        glyph = _category_glyph(spec.category)
        if glyph:
            return glyph
    if spec.icon_ascii:
        return spec.icon_ascii
    return defaults.ascii_fallback


def resolve_icon_final(spec: ToolSpec, nerd_font: bool) -> str:
    """Canonical public entry point for all icon resolution (v4 §6.1, §9)."""
    if spec.provenance and spec.provenance.startswith("mcp:"):
        if not (nerd_font and spec.icon_nf) and not (not nerd_font and spec.icon_ascii):
            server = spec.provenance.split(":", 1)[1]
            info = MCP_SERVER_REGISTRY.get(server)
            if info:
                if nerd_font and info.icon_nf:
                    return info.icon_nf
                if info.icon_ascii:
                    return info.icon_ascii
    return _resolve_icon(spec, nerd_font)


# ---------------------------------------------------------------------------
# Plugin API (v4 §5)
# ---------------------------------------------------------------------------

def register_tool(spec: ToolSpec, *, overwrite: bool = False) -> None:
    """Register an explicit ToolSpec.

    Raises ValueError if name empty, provenance malformed, or name already
    registered and overwrite=False.
    """
    if not spec.name:
        raise ValueError("ToolSpec.name must be non-empty")
    with _REGISTRY_LOCK:
        if spec.name in TOOL_REGISTRY and not overwrite:
            raise ValueError(
                f"Tool {spec.name!r} already registered; pass overwrite=True to replace"
            )
        TOOL_REGISTRY[spec.name] = spec


def register_mcp_server(
    server: str,
    *,
    default_category: ToolCategory = ToolCategory.MCP,
    icon_nf: str | None = None,
    icon_ascii: str = "",
) -> None:
    """Record server metadata. Called once per server connect.

    Pass icon_nf=<glyph> to set a nerd-font icon, or omit entirely (None).
    Passing icon_nf='' (explicit empty string) raises ValueError — ambiguous.
    """
    if not server:
        raise ValueError("server must be non-empty")
    if "__" in server:
        raise ValueError(f"server name must not contain '__', got {server!r}")
    if icon_nf == "":
        raise ValueError(
            "Do not pass icon_nf='' explicitly; omit the argument or pass icon_nf=<glyph>"
        )
    with _REGISTRY_LOCK:
        MCP_SERVER_REGISTRY[server] = MCPServerInfo(
            server=server,
            icon_nf=icon_nf or "",
            icon_ascii=icon_ascii,
            default_category=default_category,
        )


# ---------------------------------------------------------------------------
# spec_for — lookup + derivation (v4 §3.1)
# ---------------------------------------------------------------------------

def spec_for(
    name: str,
    args: dict | None = None,
    schema: dict | None = None,
) -> ToolSpec:
    """Return the ToolSpec for a tool name, with full fallback chain (v4 §3.1)."""
    if not name:
        return ToolSpec(name="_unknown_", category=ToolCategory.UNKNOWN, primary_arg=None, primary_result="none")
    # 1. Explicit registry entry wins unconditionally
    entry = TOOL_REGISTRY.get(name)
    if entry is not None:
        return entry
    # 2. MCP-wrapped name → recurse on inner + derive
    parsed = _parse_mcp_name(name)
    if parsed is not None:
        server, tool_short = parsed
        inner = spec_for(tool_short, args, schema)
        return _derive_mcp_spec(name, server, tool_short, inner, schema)
    # 3. Arg-name heuristic (live args first, then schema)
    if args:
        category, primary_arg = _classify_args(args)
        if category != ToolCategory.UNKNOWN:
            return ToolSpec(
                name=name, category=category, primary_arg=primary_arg,
                primary_result=_infer_primary_result(category),
            )
    if schema:
        category, primary_arg = _classify_by_schema(schema)
        if category != ToolCategory.UNKNOWN:
            return ToolSpec(
                name=name, category=category, primary_arg=primary_arg,
                primary_result=_infer_primary_result(category),
            )
    # 5. Fallback: UNKNOWN
    return ToolSpec(name=name, category=ToolCategory.UNKNOWN, primary_arg=None, primary_result="none")


# ---------------------------------------------------------------------------
# Back-compat shim
# ---------------------------------------------------------------------------

def classify_tool(name: str) -> ToolCategory:
    """Return the ToolCategory for a given tool name, defaulting to UNKNOWN."""
    return spec_for(name).category


# ---------------------------------------------------------------------------
# Seed specs (v4 §8.1) — populate TOOL_REGISTRY at import time
# ---------------------------------------------------------------------------

# Local aliases for brevity
_FILE   = ToolCategory.FILE
_SHELL  = ToolCategory.SHELL
_CODE   = ToolCategory.CODE
_SEARCH = ToolCategory.SEARCH
_WEB    = ToolCategory.WEB
_AGENT  = ToolCategory.AGENT

_SEED_SPECS: list[ToolSpec] = [
    ToolSpec(name="read_file",          category=_FILE,   primary_arg="path",        primary_result="bytes",   streaming=False),
    ToolSpec(name="write_file",         category=_FILE,   primary_arg="path",        primary_result="diff",    streaming=False),
    ToolSpec(name="create_file",        category=_FILE,   primary_arg="path",        primary_result="diff",    streaming=False),
    ToolSpec(name="edit_file",          category=_FILE,   primary_arg="path",        primary_result="diff",    streaming=False),
    ToolSpec(name="str_replace_editor", category=_FILE,   primary_arg="path",        primary_result="diff",    streaming=False),
    ToolSpec(name="patch",              category=_FILE,   primary_arg="path",        primary_result="diff",    streaming=False),
    ToolSpec(name="view",               category=_FILE,   primary_arg="path",        primary_result="lines",   streaming=False),
    ToolSpec(name="terminal",           category=_SHELL,  primary_arg="command",     primary_result="lines",   streaming=True,  render_header=False, terminal_inline=True),
    ToolSpec(name="bash",               category=_SHELL,  primary_arg="command",     primary_result="lines",   streaming=True),
    ToolSpec(name="execute_code",       category=_CODE,   primary_arg="code",        primary_result="lines",   streaming=True),
    ToolSpec(name="web_search",         category=_SEARCH, primary_arg="query",       primary_result="results", streaming=False),
    ToolSpec(name="search_files",       category=_SEARCH, primary_arg="query",       primary_result="matches", streaming=True),
    ToolSpec(name="grep",               category=_SEARCH, primary_arg="query",       primary_result="matches", streaming=True),
    ToolSpec(name="glob",               category=_SEARCH, primary_arg="query",       primary_result="matches", streaming=True),
    ToolSpec(name="web_extract",        category=_WEB,    primary_arg="url",         primary_result="status",  streaming=False),
    ToolSpec(name="fetch",              category=_WEB,    primary_arg="url",         primary_result="status",  streaming=False),
    ToolSpec(name="http",               category=_WEB,    primary_arg="url",         primary_result="status",  streaming=False),
    ToolSpec(name="think",              category=_AGENT,  primary_arg="thought",     primary_result="done",    streaming=False),
    ToolSpec(name="plan",               category=_AGENT,  primary_arg="description", primary_result="done",    streaming=False),
    ToolSpec(name="delegate",           category=_AGENT,  primary_arg="task",        primary_result="done",    streaming=False),
]


def _install_seed_specs() -> None:
    with _REGISTRY_LOCK:
        for s in _SEED_SPECS:
            TOOL_REGISTRY.setdefault(s.name, s)


_install_seed_specs()


# ---------------------------------------------------------------------------
# Deprecated static dict — kept for legacy imports (v4 §8.3)
# ---------------------------------------------------------------------------

# DEPRECATED: use classify_tool() or spec_for() instead of direct dict access.
_TOOL_CATEGORY: dict[str, ToolCategory] = {
    "read_file":          ToolCategory.FILE,
    "write_file":         ToolCategory.FILE,
    "create_file":        ToolCategory.FILE,
    "edit_file":          ToolCategory.FILE,
    "str_replace_editor": ToolCategory.FILE,
    "patch":              ToolCategory.FILE,
    "view":               ToolCategory.FILE,
    "terminal":           ToolCategory.SHELL,
    "bash":               ToolCategory.SHELL,
    "execute_code":       ToolCategory.CODE,
    "web_search":         ToolCategory.SEARCH,
    "search_files":       ToolCategory.SEARCH,
    "grep":               ToolCategory.SEARCH,
    "glob":               ToolCategory.SEARCH,
    "web_extract":        ToolCategory.WEB,
    "fetch":              ToolCategory.WEB,
    "http":               ToolCategory.WEB,
    "think":              ToolCategory.AGENT,
    "plan":               ToolCategory.AGENT,
    "delegate":           ToolCategory.AGENT,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ToolCategory",
    "ToolSpec",
    "MCPServerInfo",
    "CategoryDefaults",
    "TOOL_REGISTRY",
    "MCP_SERVER_REGISTRY",
    "register_tool",
    "register_mcp_server",
    "spec_for",
    "classify_tool",          # back-compat legacy shim
    "resolve_icon_final",     # canonical public entry point — use this everywhere
    # Internal: _resolve_icon, _category_glyph, _classify_by_schema, _derive_mcp_spec
]
