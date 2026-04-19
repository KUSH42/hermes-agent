"""Streaming microcopy — per-category progress line for v4 §3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.tool_category import ToolSpec


@dataclass
class StreamingState:
    lines_received: int
    bytes_received: int
    elapsed_s: float
    total_lines: int | None = None
    total_bytes: int | None = None
    last_status: str | None = None
    matches_so_far: int | None = None


def _kb(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    return f"{b / 1024:.1f}kB"


def microcopy_line(spec: "ToolSpec", state: StreamingState) -> str:
    """Return microcopy string for current streaming state, or '' for no line."""
    from hermes_cli.tui.tool_category import ToolCategory

    cat = spec.category

    if cat == ToolCategory.SHELL:
        return f"▸ {state.lines_received} lines · {_kb(state.bytes_received)}"

    if cat == ToolCategory.FILE:
        if spec.primary_result in ("lines", "bytes"):
            total_str = str(state.total_lines) if state.total_lines is not None else "?"
            total_kb = _kb(state.total_bytes) if state.total_bytes is not None else "?"
            return (
                f"▸ {state.lines_received}/{total_str} lines"
                f" · {_kb(state.bytes_received)}/{total_kb}"
            )
        return f"▸ {state.lines_received} lines written"

    if cat == ToolCategory.SEARCH:
        count = (
            state.matches_so_far
            if state.matches_so_far is not None
            else state.lines_received
        )
        return f"▸ {count} matches so far…"

    if cat == ToolCategory.WEB:
        status = state.last_status or "connecting"
        return f"▸ {status} · {_kb(state.bytes_received)}"

    if cat == ToolCategory.MCP:
        prov = spec.provenance or ""
        server = prov[4:] if prov.startswith("mcp:") else "?"
        return f"▸ mcp · {server} server"

    # CODE (uses ExecuteCodeBlock sections), AGENT, UNKNOWN → no microcopy
    return ""
