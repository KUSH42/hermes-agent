"""CodeRenderer — syntax-highlighted code display using rich.syntax.Syntax."""
from __future__ import annotations

import os
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


def _detect_lang_from_path(path: str) -> str:
    """Detect language from file extension."""
    ext = os.path.splitext(path)[-1].lower()
    return _EXT_MAP.get(ext, "")


def _detect_lang_from_fence(text: str) -> tuple[str, str]:
    """If text starts with ```lang, return (lang, stripped_code)."""
    if text.startswith("```"):
        first_line_end = text.find("\n")
        if first_line_end > 0:
            lang = text[3:first_line_end].strip()
            code = text[first_line_end + 1:]
            if code.endswith("```"):
                code = code[:-3].rstrip()
            elif code.endswith("```\n"):
                code = code[:-4].rstrip()
            return lang, code
    return "", text


class CodeRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.CODE

    def build(self):
        """Build a rich.syntax.Syntax renderable."""
        from rich.syntax import Syntax

        raw = self.payload.output_raw or ""

        # Detect lang from fence markers first
        fence_lang, code = _detect_lang_from_fence(raw)

        if fence_lang:
            lexer = fence_lang
        else:
            # Try path-based detection
            path = ""
            if self.payload.args:
                path = str(self.payload.args.get("path", ""))
            lexer = _detect_lang_from_path(path) if path else ""
            if not lexer:
                lexer = "text"

        return Syntax(code, lexer, line_numbers=True, theme="monokai")


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    CodeRenderer.kind = ResultKind.CODE


_set_kind()
