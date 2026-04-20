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
    rate_bps: float | None = None  # B2: streaming rate in bytes/s


def _kb(b: int) -> str:
    """Legacy alias — prefer _human_size for new call sites."""
    return _human_size(b)


def _human_size(b: int) -> str:
    """D1: human-readable byte count with B/kB/MB suffixes."""
    if b < 1024:
        return f"{b}B"
    if b < 1_048_576:
        return f"{b / 1024:.1f}kB"
    return f"{b / 1_048_576:.1f}MB"


def _thinking_shimmer(shimmer_phase: float, elapsed_s: float = 0.0) -> Text:
    """Animated shimmer for AGENT category microcopy."""
    from hermes_cli.tui.animation import lerp_color
    label = "Thinking…"
    phase = shimmer_phase % 2.0
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


def microcopy_line(
    spec: "ToolSpec",
    state: StreamingState,
    reduced_motion: bool = False,
    shimmer_phase: float = 0.0,
) -> "Union[str, Text]":
    """Return microcopy for current streaming state, or '' for no line.

    D2: reduced_motion=True → static text for AGENT category.
    D3: all categories append elapsed when state.elapsed_s > 2.0.
    """
    from hermes_cli.tui.tool_category import ToolCategory

    cat = spec.category
    elapsed_s = state.elapsed_s

    def _elapsed_suffix() -> str:
        """D3: append · N.Ns when elapsed > 2s."""
        if elapsed_s > 2.0:
            return f" · {elapsed_s:.1f}s"
        return ""

    if cat == ToolCategory.SHELL:
        base = f"▸ {state.lines_received} lines · {_human_size(state.bytes_received)}"
        if state.rate_bps is not None and state.rate_bps > 0:
            base += f" · {state.rate_bps / 1024:.0f} kB/s"
        return base + _elapsed_suffix()

    if cat == ToolCategory.FILE:
        if spec.primary_result in ("lines", "bytes"):
            base = f"▸ {state.lines_received} lines · {_human_size(state.bytes_received)}"
            if state.rate_bps is not None and state.rate_bps > 0:
                base += f" · {state.rate_bps / 1024:.0f} kB/s"
            return base + _elapsed_suffix()
        return f"▸ {state.lines_received} lines written" + _elapsed_suffix()

    if cat == ToolCategory.SEARCH:
        count = (
            state.matches_so_far
            if state.matches_so_far is not None
            else state.lines_received
        )
        return f"▸ {count} matches so far…" + _elapsed_suffix()

    if cat == ToolCategory.WEB:
        status = state.last_status or "connecting"
        return f"▸ {status} · {_human_size(state.bytes_received)}" + _elapsed_suffix()

    if cat == ToolCategory.MCP:
        prov = spec.provenance or ""
        server = prov[4:] if prov.startswith("mcp:") else ""
        if not server and "__" in spec.name:
            server = spec.name.split("__")[-1]
        if not server:
            server = spec.name or "?"
        return f"▸ mcp · {server} server" + _elapsed_suffix()

    if cat == ToolCategory.CODE:
        return f"▸ {state.lines_received} lines · {_human_size(state.bytes_received)}" + _elapsed_suffix()

    if cat == ToolCategory.AGENT:
        # D2: static text when reduced_motion
        if reduced_motion:
            return Text("▸ thinking…")
        return _thinking_shimmer(shimmer_phase, state.elapsed_s)

    if cat == ToolCategory.UNKNOWN:
        return f"▸ {state.lines_received} lines" + _elapsed_suffix()

    return ""
