"""Tool category taxonomy and per-category defaults.

Phase 1 of the Tool Panel v2 architecture (tui-tool-panel-v2-spec.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ToolCategory(Enum):
    FILE    = "file"
    SHELL   = "shell"
    CODE    = "code"
    SEARCH  = "search"
    WEB     = "web"
    AGENT   = "agent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CategoryDefaults:
    accent_var: str             # TCSS variable name (without $) for accent color
    glyph_var: str              # TCSS variable name for nerd-font glyph
    ascii_fallback: str         # single-char ASCII fallback when nerd-font absent
    args_formatter: str         # args_preview function name (Phase 3)
    result_parser: str          # result parser function name (Phase 3)
    default_detail: int         # default initial detail level 0–3
    default_collapsed_lines: int  # line threshold for auto-collapse


_CATEGORY_DEFAULTS: dict[ToolCategory, CategoryDefaults] = {
    ToolCategory.FILE:    CategoryDefaults("tool-file-accent",    "tool-glyph-file",    "F", "file_args",    "file_result",    1, 3),
    ToolCategory.SHELL:   CategoryDefaults("tool-shell-accent",   "tool-glyph-shell",   "$", "shell_args",   "shell_result",   1, 3),
    ToolCategory.CODE:    CategoryDefaults("tool-code-accent",    "tool-glyph-code",    "P", "code_args",    "code_result",    2, 3),
    ToolCategory.SEARCH:  CategoryDefaults("tool-search-accent",  "tool-glyph-search",  "?", "search_args",  "search_result",  1, 6),
    ToolCategory.WEB:     CategoryDefaults("tool-web-accent",     "tool-glyph-web",     "@", "web_args",     "web_result",     1, 6),
    ToolCategory.AGENT:   CategoryDefaults("tool-agent-accent",   "tool-glyph-agent",   "*", "agent_args",   "agent_result",   0, 1),
    ToolCategory.UNKNOWN: CategoryDefaults("tool-unknown-accent", "tool-glyph-unknown", "?", "generic_args", "generic_result", 1, 3),
}

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
    "grep":               ToolCategory.SEARCH,
    "glob":               ToolCategory.SEARCH,
    "web_extract":        ToolCategory.WEB,
    "fetch":              ToolCategory.WEB,
    "http":               ToolCategory.WEB,
    "think":              ToolCategory.AGENT,
    "plan":               ToolCategory.AGENT,
    "delegate":           ToolCategory.AGENT,
}


def classify_tool(name: str) -> ToolCategory:
    """Return the ToolCategory for a given tool name, defaulting to UNKNOWN."""
    return _TOOL_CATEGORY.get(name, ToolCategory.UNKNOWN)
