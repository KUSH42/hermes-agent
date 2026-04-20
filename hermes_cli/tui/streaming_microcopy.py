"""Streaming microcopy — per-category progress line for v4 §3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from rich.text import Text

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


def _thinking_shimmer(elapsed_s: float) -> Text:
    """Animated shimmer for AGENT category microcopy."""
    from hermes_cli.tui.animation import lerp_color
    label = "Thinking…"
    phase = (elapsed_s * 0.5) % 2.0
    t = phase if phase <= 1.0 else 2.0 - phase
    ACCENT = "#00ff99"
    DIM = "#446644"
    result = Text("▸ ", style="dim")
    for i, ch in enumerate(label):
        char_t = (t + i / len(label)) % 1.0
        color = lerp_color(DIM, ACCENT, char_t)
        result.append(ch, style=f"bold {color}")
    elapsed_str = f"  {int(elapsed_s)}s" if elapsed_s >= 1.0 else ""
    result.append(elapsed_str, style="dim")
    return result


def microcopy_line(spec: "ToolSpec", state: StreamingState) -> "Union[str, Text]":
    """Return microcopy for current streaming state, or '' for no line."""
    from hermes_cli.tui.tool_category import ToolCategory

    cat = spec.category

    if cat == ToolCategory.SHELL:
        return f"▸ {state.lines_received} lines · {_kb(state.bytes_received)}"

    if cat == ToolCategory.FILE:
        if spec.primary_result in ("lines", "bytes"):
            return f"▸ {state.lines_received} lines · {_kb(state.bytes_received)}"
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

    if cat == ToolCategory.CODE:
        return f"▸ {state.lines_received} lines · {_kb(state.bytes_received)}"

    if cat == ToolCategory.AGENT:
        return _thinking_shimmer(state.elapsed_s)

    if cat == ToolCategory.UNKNOWN:
        return f"▸ {state.lines_received} lines"

    return ""
