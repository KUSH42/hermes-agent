"""StreamingBodyRenderer — per-category streaming and finalize rendering strategy.

Architecture: tui-tool-panel-v2-spec.md §5.

Phase 2 delivers the renderer hierarchy and integrates it with the four
existing body-render paths. The streaming state machines in
ExecuteCodeBlock, WriteFileBlock, and StreamingToolBlock are untouched;
they delegate per-line formatting here.

Nine concrete renderers (§5.3):
    ShellRenderer          — ANSI passthrough, no finalize
    StreamingCodeRenderer  — per-line Pygments + rich.Syntax finalize; extends with
                             render_code_line / render_output_line / finalize_code
                             for the two-section ExecuteCodeBlock layout (§5.3.1)
    FileRenderer           — write-file per-line Syntax, full-body rehighlight,
                             diff-line path formatting
    StreamingSearchRenderer — plain stream; structured finalize + extract_sidecar
    WebRenderer            — ANSI passthrough; JSON/text finalize
    AgentRenderer          — ANSI passthrough; no finalize
    TextRenderer           — ANSI passthrough fallback; no finalize
    MCPBodyRenderer        — ANSI passthrough; MCP JSON content extraction
    PlainBodyRenderer      — catch-all fallback; can_render always False

R-2B-2: all nine inherit from BodyRenderer (ABC tier). R-2B-5 deleted
the legacy selection machinery; StreamingBodyRenderer is now aliased to
BodyRenderer for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from hermes_cli.tui.body_renderers.base import BodyRenderer
from hermes_cli.tui.services.tools import ToolCallState
from hermes_cli.tui.tool_payload import ResultKind

if TYPE_CHECKING:
    from rich.console import ConsoleRenderable
    from hermes_cli.tui.tool_category import ToolCategory


# Phases accepted by all streaming-tier renderers.
_STREAMING_PHASES: frozenset[ToolCallState] = frozenset({
    ToolCallState.STARTED,
    ToolCallState.STREAMING,
})


# ---------------------------------------------------------------------------
# StreamingBodyRenderer — BodyRenderer alias for backward compatibility.
# R-2B-5: legacy selection machinery deleted; alias lets out-of-tree importers
# of StreamingBodyRenderer survive until they migrate to BodyRenderer directly.
# ---------------------------------------------------------------------------

StreamingBodyRenderer = BodyRenderer


# ---------------------------------------------------------------------------
# ShellRenderer — terminal / bash (ANSI passthrough)
# ---------------------------------------------------------------------------


class ShellRenderer(BodyRenderer):
    """Shell stdout: Text.from_ansi; JSON/YAML finalize on completion."""

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.SHELL

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    def finalize(self, all_plain: list[str], **kw: object) -> "ConsoleRenderable | None":
        """C3: re-render as syntax-highlighted block when output is JSON or YAML.

        R-X1: skip swap when content contains ANSI escapes or config disables swap.
        Emits a leading rule notice when swap occurs.
        """
        import json as _json
        from rich.syntax import Syntax
        from hermes_cli.tui.body_renderers._grammar import SkinColors, build_rule

        text = "\n".join(all_plain).strip()

        # R-X1: skip swap if content already has ANSI escape sequences
        if "\x1b[" in text:
            return None

        app = kw.get("app")

        # R-X1: config gate — swap_on_complete=false → keep as-streamed
        if app is not None:
            try:
                swap = app.config.get("tui", {}).get("render", {}).get("swap_on_complete", True)
                if not swap:
                    return None
            except Exception:
                pass

        colors = SkinColors.from_app(app)
        theme = colors.syntax_theme

        lang: str | None = None
        if text.startswith(("{", "[")):
            try:
                _json.loads(text)
                lang = "json"
            except Exception:
                pass
        if lang is None and text.startswith("---"):
            lang = "yaml"

        if lang is None:
            return None

        from rich.text import Text as _Text
        notice = _Text()
        notice.append_text(build_rule(f"↻ rendered as {lang}", colors=colors))
        notice.append("\n")
        try:
            syntax = Syntax(text, lang, line_numbers=False, theme=theme, background_color="default")
        except Exception:
            syntax = _Text(text)

        from rich.console import Group
        return Group(notice, syntax)

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


# ---------------------------------------------------------------------------
# StreamingCodeRenderer — execute_code
# ---------------------------------------------------------------------------


class StreamingCodeRenderer(BodyRenderer):
    """execute_code: per-line Pygments during streaming, rich.Syntax on finalize.

    Extends the base interface with three specialised methods (§5.3.1):
        render_code_line   — python line → Pygments ANSI → Text (GEN_STREAMING)
        render_output_line — stdout line → Text.from_ansi (EXEC_STREAMING)
        finalize_code      — full-body rich.Syntax for CodeSection at TOOL_START
    """

    kind = ResultKind.CODE
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.CODE

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        """Generic StreamingBodyRenderer contract: delegate stdout to render_output_line."""
        return self.render_output_line(raw, plain)

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
        return None  # stdout is ANSI; no canonical replacement

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")

    # ------------------------------------------------------------------
    # Specialised execute_code methods
    # ------------------------------------------------------------------

    def render_code_line(
        self, raw: str, plain: str, theme: str = "ansi_dark"
    ) -> "ConsoleRenderable":
        """Python source line → per-line Pygments highlighted Text."""
        return Text.from_ansi(self._highlight_python(plain, theme))

    def render_output_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        """Stdout line → ANSI passthrough Text."""
        return Text.from_ansi(raw)

    def finalize_code(
        self,
        code: str,
        theme: str = "ansi_dark",
        bg: str | None = None,
    ) -> "ConsoleRenderable | None":
        """Full-body rich.Syntax for CodeSection at TOOL_START.

        Returns None when code is empty or single-line (no separate body to
        render — line 0 lives in the header).
        """
        lines = code.splitlines() if code else []
        if len(lines) <= 1:
            return None
        body_code = "\n".join(lines[1:])
        try:
            from rich.syntax import Syntax
            return Syntax(
                body_code,
                lexer="python",
                theme=theme,
                line_numbers=False,
                background_color=bg if bg and bg != "default" else None,
            )
        except Exception:
            return Text(body_code)

    def highlight_line(self, line: str, theme: str = "ansi_dark") -> str:
        """Return Pygments-highlighted ANSI string for a Python line."""
        return self._highlight_python(line, theme)

    def _highlight_python(self, line: str, theme: str) -> str:
        try:
            from pygments import highlight as _hl
            from pygments.lexers import PythonLexer
            from pygments.formatters import TerminalTrueColorFormatter
            return _hl(line, PythonLexer(), TerminalTrueColorFormatter(style=theme)).rstrip("\n")
        except Exception:
            return line


# ---------------------------------------------------------------------------
# FileRenderer — read_file / write_file / patch / diff
# ---------------------------------------------------------------------------

import re as _re

# Matches existing tool_blocks.py regexes exactly for snapshot equivalence.
# Group 1 = "--- " / "+++ " prefix (with space), Group 2 = path (a/ b/ already stripped).
_DIFF_HEADER_RE = _re.compile(r"^((?:---|\+\+\+)\s+)(?:[ab]/)?(.+)$")
# Group 1 = old path, Group 2 = new path (may still have "b/" prefix)
_DIFF_ARROW_RE = _re.compile(r"^(.+?)\s+→\s+(.+)$")

_LANG_MAP: dict[str, str] = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "tsx": "tsx", "jsx": "jsx", "rs": "rust", "go": "go",
    "java": "java", "c": "c", "cpp": "cpp", "cs": "csharp",
    "rb": "ruby", "sh": "bash", "bash": "bash", "zsh": "bash",
    "yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml",
    "md": "markdown", "html": "html", "css": "css", "sql": "sql",
    "xml": "xml", "txt": "text",
}


def _lang_for_path(path: str) -> str:
    suffix = Path(path).suffix.lstrip(".").lower()
    return _LANG_MAP.get(suffix, "text")


class FileRenderer(BodyRenderer):
    """read_file / write_file / patch / diff rendering.

    render_stream_line — per-line Syntax (write_file streaming path)
    finalize           — full-body Syntax (write_file completion re-highlight)
    render_diff_line   — styled Text for diff ---/+++ and "old → new" headers
    preview            — last N lines, dim
    """

    kind = ResultKind.DIFF
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.FILE

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(
        self, raw: str, plain: str, lang: str = "text"
    ) -> "ConsoleRenderable":
        """Per-line Syntax highlight for write_file streaming."""
        try:
            from rich.syntax import Syntax
            return Syntax(
                plain,
                lang,
                theme="ansi_dark",
                background_color="default",
                line_numbers=False,
            )
        except Exception:
            return Text(plain)

    def finalize(
        self,
        all_plain: list[str],
        lang: str = "text",
        **kwargs: object,
    ) -> "ConsoleRenderable | None":
        """Full-body Syntax re-render for write_file at completion.

        R-X1: skip swap when ANSI escapes present or config disables swap.
        Emits a leading rule notice when swap occurs.
        """
        if not all_plain:
            return None

        text = "\n".join(all_plain)

        # R-X1: skip swap if content already has ANSI escape sequences
        if "\x1b[" in text:
            return None

        app = kwargs.get("app")

        # R-X1: config gate
        if app is not None:
            try:
                swap = app.config.get("tui", {}).get("render", {}).get("swap_on_complete", True)
                if not swap:
                    return None
            except Exception:
                pass

        from hermes_cli.tui.body_renderers._grammar import SkinColors, build_rule
        colors = SkinColors.from_app(app)
        theme = colors.syntax_theme

        notice = Text()
        notice.append_text(build_rule(f"↻ rendered as {lang}", colors=colors))
        notice.append("\n")

        try:
            from rich.syntax import Syntax
            syntax = Syntax(text, lang, theme=theme, background_color="default", line_numbers=False)
        except Exception:
            syntax = Text(text)

        from rich.console import Group
        return Group(notice, syntax)

    def render_diff_line(self, plain: str, **kwargs: object) -> "ConsoleRenderable | None":
        """Return styled Rich Text for diff lines with skin-colored gutter.

        R-X3: extend beyond header-only styling to full +/-/context gutter with
        skin-derived colors and background tints. No word-diff during streaming.

        Handles two formats:
        - Raw: '--- a/src/foo.py' / '+++ b/src/foo.py'
        - Rendered: 'a/src/foo.py → b/src/foo.py'
        - Diff lines: '+added', '-removed', ' context'
        - Hunk headers: '@@ ... @@'
        """
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        app = kwargs.get("app")
        colors = SkinColors.from_app(app) if app else SkinColors.default()

        stripped = plain.strip()

        # ---/+++ format: regex already strips a/ / b/ prefix
        m = _DIFF_HEADER_RE.match(stripped)
        if m:
            prefix, path_str = m.group(1), m.group(2).strip()
            path_parts = path_str.rsplit("/", 1)
            if len(path_parts) == 2 and path_parts[0]:
                dir_part, fname = path_parts[0] + "/", path_parts[1]
            else:
                dir_part, fname = "", path_str
            t = Text(prefix, style="dim")
            if dir_part:
                t.append(dir_part, style="dim underline")
            t.append(fname, style="bold underline")
            return t

        # "old_path → new_path" rendered file header
        m2 = _DIFF_ARROW_RE.match(stripped)
        if m2:
            new_path = m2.group(2).strip()
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            parts = new_path.rsplit("/", 1)
            if len(parts) == 2 and parts[0]:
                dir_part, fname = parts[0] + "/", parts[1]
            else:
                dir_part, fname = "", new_path
            prefix_str = m2.group(1) + " → " + (dir_part if dir_part else "")
            t = Text(prefix_str, style="dim")
            t.append(fname, style="bold underline")
            return t

        # Hunk header: @@ ... @@ — dim passthrough
        if plain.startswith("@@"):
            return Text(plain, style="dim")

        # R-X3: diff content lines — 2-col gutter + background tint
        from rich.style import Style
        if plain.startswith("+"):
            content = plain[1:]
            t = Text()
            t.append("+ ", style=Style(color=colors.success))
            t.append(content, style=Style(bgcolor=colors.diff_add_bg))
            return t

        if plain.startswith("-"):
            content = plain[1:]
            t = Text()
            t.append("- ", style=Style(color=colors.error))
            t.append(content, style=Style(bgcolor=colors.diff_del_bg))
            return t

        # Context line
        content = plain[1:] if plain.startswith(" ") else plain
        t = Text()
        t.append("  ", style=Style(color=colors.muted))
        t.append(content, style=Style(color=colors.muted))
        return t

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


# ---------------------------------------------------------------------------
# StreamingSearchRenderer — web_search / grep / glob
# ---------------------------------------------------------------------------


def _render_web_search_results(items: list) -> "ConsoleRenderable":
    """Render web_search JSON result list as a formatted Text block."""
    t = Text()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        desc = str(item.get("description") or "").strip()
        if title:
            t.append(f"{title}\n", style="bold")
        if url:
            t.append(f"  {url}\n", style="cyan link " + url if url.startswith("http") else "cyan")
        if desc:
            # Truncate long descriptions
            if len(desc) > 120:
                desc = desc[:117] + "…"
            t.append(f"  {desc}\n", style="dim")
        if i < len(items) - 1:
            t.append("\n")
    return t


_RG_LINE_RE = _re.compile(r"^([^:]+):(\d+):")


class StreamingSearchRenderer(BodyRenderer):
    """Search results: plain stream with path headers, structured finalize, sidecar path extraction.

    R-X2: emits grammar path headers when the file path changes between lines,
    matching the layout of the post-hoc SearchRenderer (minus hit-count and virtual-scroll).
    """

    kind = ResultKind.SEARCH
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.SEARCH

    def __init__(self, payload: object = None, cls_result: object = None, *, app: object = None) -> None:
        super().__init__(payload, cls_result, app=app)  # type: ignore[arg-type]
        self._last_emitted_path: str | None = None

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        from hermes_cli.tui.body_renderers._grammar import build_path_header
        lines: list = []

        # R-X2: detect path from rg-style "file:line:content" format
        m = _RG_LINE_RE.match(plain)
        if m:
            path = m.group(1)
            if path != self._last_emitted_path:
                header = build_path_header(path, right_meta="", colors=None)
                lines.append(header)
                self._last_emitted_path = path

        lines.append(Text.from_ansi(raw))
        if len(lines) == 1:
            return lines[0]
        from rich.console import Group
        return Group(*lines)

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
        self._last_emitted_path = None
        if not all_plain:
            return None
        joined = "\n".join(all_plain).strip()
        # Detect web_search JSON: {"success": true, "data": {"web": [...]}}
        if joined.startswith("{"):
            try:
                import json as _json
                parsed = _json.loads(joined)
                web_items = parsed.get("data", {}).get("web", [])
                if isinstance(web_items, list) and web_items:
                    return _render_web_search_results(web_items)
            except Exception:
                pass
        result = Text()
        for line in all_plain:
            result.append(line + "\n")
        return result

    def extract_sidecar(self, tool_call: object, all_plain: list[str]) -> None:
        """Populate tool_call.result_paths for grep/glob results."""
        try:
            paths: list[str] = []
            for line in all_plain:
                # grep format: "file:line:content"
                if ":" in line:
                    candidate = line.split(":")[0].strip()
                    if candidate and "/" in candidate:
                        paths.append(candidate)
                # glob: each line is a path
                elif line.strip().startswith("/") or line.strip().startswith("./"):
                    paths.append(line.strip())
            if paths and hasattr(tool_call, "result_paths"):
                tool_call.result_paths[:] = list(dict.fromkeys(paths))
        except Exception:
            pass

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        preview_lines = all_plain[:max_lines] if all_plain else []
        return Text("\n".join(preview_lines), style="dim")


# ---------------------------------------------------------------------------
# WebRenderer — web_extract / fetch / http
# ---------------------------------------------------------------------------


class WebRenderer(BodyRenderer):
    """Web content: ANSI passthrough; JSON finalize when content looks like JSON."""

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.WEB

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
        if not all_plain:
            return None
        joined = "\n".join(all_plain).strip()
        # Attempt JSON pretty-print
        if joined.startswith("{") or joined.startswith("["):
            try:
                import json
                parsed = json.loads(joined)
                pretty = json.dumps(parsed, indent=2)
                from rich.syntax import Syntax
                return Syntax(pretty, "json", theme="ansi_dark", background_color="default")
            except Exception:
                pass
        return None  # leave as-streamed

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        preview_lines = [l for l in all_plain if l.strip()][:max_lines]
        return Text("\n".join(preview_lines), style="dim")


# ---------------------------------------------------------------------------
# AgentRenderer — think / plan / delegate
# ---------------------------------------------------------------------------


class AgentRenderer(BodyRenderer):
    """Agent reasoning output: ANSI passthrough, no finalize."""

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.AGENT

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    # finalize: None (inherited default from BodyRenderer)

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        if not all_plain:
            return Text("")
        first = all_plain[0]
        return Text(first, style="italic dim")


# ---------------------------------------------------------------------------
# TextRenderer — UNKNOWN / fallback
# ---------------------------------------------------------------------------


class TextRenderer(BodyRenderer):
    """Generic fallback: ANSI passthrough, no finalize, no diff intercept."""

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.UNKNOWN

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    # finalize: None (inherited default from BodyRenderer)

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


class MCPBodyRenderer(BodyRenderer):
    """MCP tool body — ANSI passthrough while streaming; finalize extracts text content."""

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        from hermes_cli.tui.tool_category import ToolCategory
        return getattr(payload, "category", None) == ToolCategory.MCP

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
        import json
        joined = "\n".join(all_plain)
        try:
            obj = json.loads(joined)
            items = obj.get("content", []) if isinstance(obj, dict) else []
            texts = [
                i["text"] for i in items
                if isinstance(i, dict) and i.get("type") == "text" and "text" in i
            ]
            if texts:
                return Text("\n\n".join(texts))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return None


class PlainBodyRenderer(BodyRenderer):
    """Streaming-tier catch-all fallback — passes lines through unstyled.

    can_render always returns False; reachable only via the force-return
    in pick_renderer's streaming branch after the REGISTRY walk exhausts.
    """

    kind = ResultKind.TEXT
    supports_streaming = True
    accepted_phases = _STREAMING_PHASES

    @classmethod
    def can_render(cls, cls_result: object, payload: object) -> bool:
        return False

    def build(self) -> "ConsoleRenderable":
        text = (self.payload.output_raw or "").strip() if self.payload else ""
        return Text(text, style="dim")

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)
