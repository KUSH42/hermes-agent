"""CodeRenderer — syntax-highlighted code display using rich.syntax.Syntax."""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_EXT_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".rs": "rust", ".go": "go", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala", ".sh": "bash", ".bash": "bash",
    ".zsh": "zsh", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".sql": "sql", ".html": "html", ".css": "css", ".md": "markdown",
}

# Anchored fence regex: opening ``` must start the string; body cannot contain ```;
# closing ``` must end the string (trailing whitespace only after).
_FENCE_RE = re.compile(r"^```([a-zA-Z0-9_+-]*)\n((?:(?!```)[\s\S])*)\n```\s*\Z")


def _detect_lang_from_path(path: str) -> str:
    """Detect language from file extension."""
    ext = os.path.splitext(path)[-1].lower()
    return _EXT_MAP.get(ext, "")


def _detect_lang_from_fence(text: str) -> tuple[str, str]:
    """If text is a single fenced code block, return (lang, body). Otherwise ("", text)."""
    m = _FENCE_RE.match(text)
    if not m:
        return "", text
    return m.group(1), m.group(2)


class CodeRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "head"
    kind_icon: ClassVar[str] = "<>"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.CODE

    @classmethod
    def streaming_kind_hint(cls, first_chunk: str) -> "ResultKind | None":
        from hermes_cli.tui.tool_payload import ResultKind
        chunk = first_chunk[:256]
        if chunk.startswith("#!"):
            return ResultKind.CODE
        # triple-backtick fence with a known language tag
        if chunk.startswith("```") and len(chunk) > 3:
            tag_end = chunk.find("\n")
            tag = chunk[3:tag_end].strip() if tag_end != -1 else chunk[3:].strip()
            if tag and tag.isidentifier():
                return ResultKind.CODE
        return None

    def _parse_code(self):
        """Return (code, lexer, origin_path, start_line, show_line_numbers)."""
        from rich.syntax import Syntax

        raw = self.payload.output_raw or ""
        fence_lang, code = _detect_lang_from_fence(raw)

        if fence_lang:
            lexer = fence_lang
        else:
            path = ""
            if self.payload.args:
                path = str(self.payload.args.get("path", ""))
            lexer = _detect_lang_from_path(path) if path else ""
            if not lexer:
                lexer = "text"

        args = self.payload.args or {}
        try:
            start_line = int(args.get("start_line") or 1)
        except (ValueError, TypeError):
            start_line = 1
        lines = code.splitlines()
        show_line_numbers = len(lines) >= 6 or "start_line" in args
        origin_path = str(args.get("path", ""))
        return code, lexer, origin_path, start_line, show_line_numbers

    def build(self):
        """Build a Rich Group(header, Syntax) renderable."""
        from rich.syntax import Syntax
        from rich.console import Group
        from hermes_cli.tui.body_renderers._grammar import build_path_header

        code, lexer, origin_path, start_line, show_line_numbers = self._parse_code()
        lines = code.splitlines()

        syntax = Syntax(
            code, lexer,
            line_numbers=show_line_numbers,
            start_line=start_line if show_line_numbers else 1,
            theme=self.colors.syntax_theme,
            background_color="default",
        )

        right_meta = f"{lexer or 'text'}  ·  {len(lines)} lines"
        header = build_path_header(
            origin_path or f"({lexer or 'text'})",
            right_meta=right_meta,
            colors=self.colors,
        )
        return Group(header, syntax)

    def build_widget(self, density=None, clamp_rows=None):
        from rich.syntax import Syntax
        from hermes_cli.tui.body_renderers._grammar import build_path_header, BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        code, lexer, origin_path, start_line, show_line_numbers = self._parse_code()
        lines = code.splitlines()

        syntax = Syntax(
            code, lexer,
            line_numbers=show_line_numbers,
            start_line=start_line if show_line_numbers else 1,
            theme=self.colors.syntax_theme,
            background_color="default",
        )

        right_meta = f"{lexer or 'text'}  ·  {len(lines)} lines"
        header = build_path_header(
            origin_path or f"({lexer or 'text'})",
            right_meta=right_meta,
            colors=self.colors,
        )
        return BodyFrame(
            header=header,
            body=syntax,
            footer=BodyFooter(("y", "copy")),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    CodeRenderer.kind = ResultKind.CODE


_set_kind()
