"""StreamingBodyRenderer — per-category streaming and finalize rendering strategy.

Architecture: tui-tool-panel-v2-spec.md §5.

Phase 2 delivers the renderer hierarchy and integrates it with the four
existing body-render paths. The streaming state machines in
ExecuteCodeBlock, WriteFileBlock, and StreamingToolBlock are untouched;
they delegate per-line formatting here.

Seven concrete renderers (§5.3):
    ShellRenderer   — ANSI passthrough, no finalize
    CodeRenderer    — per-line Pygments + rich.Syntax finalize; extends with
                       render_code_line / render_output_line / finalize_code
                       for the two-section ExecuteCodeBlock layout (§5.3.1)
    FileRenderer    — write-file per-line Syntax, full-body rehighlight,
                       diff-line path formatting
    SearchRenderer  — plain stream; structured finalize + extract_sidecar
    WebRenderer     — ANSI passthrough; JSON/text finalize
    AgentRenderer   — ANSI passthrough; no finalize
    TextRenderer    — ANSI passthrough fallback; no finalize

Registry + factory live on StreamingBodyRenderer.for_category (§5.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from rich.console import ConsoleRenderable
    from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class StreamingBodyRenderer:
    """Stateless base renderer. Concrete subclasses override 1–3 methods.

    Renderers are stateless singletons (§5.2) — per-panel state lives on
    the ToolCall and the streaming block. One instance per category is
    reused across all ToolPanels.

    Signature conventions
    ---------------------
    render_stream_line(raw, plain)
        raw   — original ANSI-encoded string from the tool
        plain — stripped plain-text version (for copy buffers)
        Returns a Rich ConsoleRenderable (typically Text).

    finalize(all_plain, **kw)
        Optional. Called once at tool_complete. Return None to skip
        (shell-style ANSI passthrough stays as-streamed).

    preview(all_plain, max_lines)
        Lightweight L1 preview; must not call rich.Syntax.

    extract_sidecar(tool_call, all_plain)
        Optional post-finalize hook to mutate ToolCall fields.
        Only SearchRenderer overrides this in Phase 2.
    """

    _CACHE: dict["ToolCategory", "StreamingBodyRenderer"] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def for_category(cls, category: "ToolCategory") -> "StreamingBodyRenderer":
        """Return the stateless singleton renderer for *category*."""
        if category not in cls._CACHE:
            cls._CACHE[category] = _RENDERERS[category]()
        return cls._CACHE[category]

    # ------------------------------------------------------------------
    # Interface — override in subclasses
    # ------------------------------------------------------------------

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        raise NotImplementedError

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
        return None

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")

    def extract_sidecar(self, tool_call: object, all_plain: list[str]) -> None:
        return


# ---------------------------------------------------------------------------
# ShellRenderer — terminal / bash (ANSI passthrough)
# ---------------------------------------------------------------------------


class ShellRenderer(StreamingBodyRenderer):
    """Shell stdout: Text.from_ansi; JSON/YAML finalize on completion."""

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    def finalize(self, all_plain: list[str], **kw: object) -> "ConsoleRenderable | None":
        """C3: re-render as syntax-highlighted block when output is JSON or YAML."""
        import json as _json
        from rich.syntax import Syntax

        text = "\n".join(all_plain).strip()
        if text.startswith(("{", "[")):
            try:
                _json.loads(text)
                return Syntax(text, "json", line_numbers=False, theme="monokai")
            except Exception:
                pass
        if text.startswith("---"):
            return Syntax(text, "yaml", line_numbers=False, theme="monokai")
        return None

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


# ---------------------------------------------------------------------------
# CodeRenderer — execute_code
# ---------------------------------------------------------------------------


class CodeRenderer(StreamingBodyRenderer):
    """execute_code: per-line Pygments during streaming, rich.Syntax on finalize.

    Extends the base interface with three specialised methods (§5.3.1):
        render_code_line   — python line → Pygments ANSI → Text (GEN_STREAMING)
        render_output_line — stdout line → Text.from_ansi (EXEC_STREAMING)
        finalize_code      — full-body rich.Syntax for CodeSection at TOOL_START
    """

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
        self, raw: str, plain: str, theme: str = "monokai"
    ) -> "ConsoleRenderable":
        """Python source line → per-line Pygments highlighted Text."""
        return Text.from_ansi(self._highlight_python(plain, theme))

    def render_output_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        """Stdout line → ANSI passthrough Text."""
        return Text.from_ansi(raw)

    def finalize_code(
        self,
        code: str,
        theme: str = "monokai",
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

    def highlight_line(self, line: str, theme: str = "monokai") -> str:
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


class FileRenderer(StreamingBodyRenderer):
    """read_file / write_file / patch / diff rendering.

    render_stream_line — per-line Syntax (write_file streaming path)
    finalize           — full-body Syntax (write_file completion re-highlight)
    render_diff_line   — styled Text for diff ---/+++ and "old → new" headers
    preview            — last N lines, dim
    """

    def render_stream_line(
        self, raw: str, plain: str, lang: str = "text"
    ) -> "ConsoleRenderable":
        """Per-line Syntax highlight for write_file streaming."""
        try:
            from rich.syntax import Syntax
            return Syntax(
                plain,
                lang,
                theme="monokai",
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
        """Full-body Syntax re-render for write_file at completion."""
        if not all_plain:
            return None
        try:
            from rich.syntax import Syntax
            return Syntax(
                "\n".join(all_plain),
                lang,
                theme="monokai",
                background_color="default",
                line_numbers=False,
            )
        except Exception:
            return Text("\n".join(all_plain))

    def render_diff_line(self, plain: str) -> "ConsoleRenderable | None":
        """Return styled Rich Text for diff path lines, else None.

        Matches ToolBlock._render_diff_line exactly for snapshot equivalence.

        Handles two formats:
        - Raw: '--- a/src/foo.py' / '+++ b/src/foo.py'
        - Rendered: 'a/src/foo.py → b/src/foo.py'

        File paths are styled with underline to indicate they are interactive
        (left-click opens via ToolHeader, right-click shows context menu).
        """
        stripped = plain.strip()
        # ---/+++ format: regex already strips a/ / b/ prefix; group 1 = "--- ", group 2 = path
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
        return None

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


# ---------------------------------------------------------------------------
# SearchRenderer — web_search / grep / glob
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


class SearchRenderer(StreamingBodyRenderer):
    """Search results: plain stream, structured finalize, sidecar path extraction."""

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    def finalize(self, all_plain: list[str], **kwargs: object) -> "ConsoleRenderable | None":
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


class WebRenderer(StreamingBodyRenderer):
    """Web content: ANSI passthrough; JSON finalize when content looks like JSON."""

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
                return Syntax(pretty, "json", theme="monokai", background_color="default")
            except Exception:
                pass
        return None  # leave as-streamed

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        preview_lines = [l for l in all_plain if l.strip()][:max_lines]
        return Text("\n".join(preview_lines), style="dim")


# ---------------------------------------------------------------------------
# AgentRenderer — think / plan / delegate
# ---------------------------------------------------------------------------


class AgentRenderer(StreamingBodyRenderer):
    """Agent reasoning output: ANSI passthrough, no finalize."""

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    # finalize: None (inherited default)

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        if not all_plain:
            return Text("")
        first = all_plain[0]
        return Text(first, style="italic dim")


# ---------------------------------------------------------------------------
# TextRenderer — UNKNOWN / fallback
# ---------------------------------------------------------------------------


class TextRenderer(StreamingBodyRenderer):
    """Generic fallback: ANSI passthrough, no finalize, no diff intercept."""

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        return Text.from_ansi(raw)

    # finalize: None (inherited default)

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")


class MCPBodyRenderer(StreamingBodyRenderer):
    """MCP tool body — ANSI passthrough while streaming; finalize extracts text content."""

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


# ---------------------------------------------------------------------------
# Registry (must come after all concrete classes)
# ---------------------------------------------------------------------------


def _build_renderers() -> "dict[ToolCategory, type[StreamingBodyRenderer]]":
    from hermes_cli.tui.tool_category import ToolCategory
    return {
        ToolCategory.FILE:    FileRenderer,
        ToolCategory.SHELL:   ShellRenderer,
        ToolCategory.CODE:    CodeRenderer,
        ToolCategory.SEARCH:  SearchRenderer,
        ToolCategory.WEB:     WebRenderer,
        ToolCategory.AGENT:   AgentRenderer,
        ToolCategory.MCP:     MCPBodyRenderer,
        ToolCategory.UNKNOWN: TextRenderer,
    }


_RENDERERS: "dict[ToolCategory, type[StreamingBodyRenderer]]" = {}


def _ensure_renderers() -> "dict[ToolCategory, type[StreamingBodyRenderer]]":
    global _RENDERERS
    if not _RENDERERS:
        _RENDERERS = _build_renderers()
    return _RENDERERS


# Patch for_category to use lazy registry (avoids circular import at module load)
_orig_for_category = StreamingBodyRenderer.for_category.__func__  # type: ignore[attr-defined]


@classmethod  # type: ignore[misc]
def _lazy_for_category(cls, category: "ToolCategory") -> "StreamingBodyRenderer":
    _ensure_renderers()
    if category not in cls._CACHE:
        cls._CACHE[category] = _RENDERERS[category]()
    return cls._CACHE[category]


StreamingBodyRenderer.for_category = _lazy_for_category  # type: ignore[method-assign]


class PlainBodyRenderer(StreamingBodyRenderer):
    """Fallback renderer — passes lines through unstyled."""
    pass
