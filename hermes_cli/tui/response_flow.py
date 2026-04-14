"""ResponseFlowEngine — per-turn streaming markdown processor for the TUI.

Receives complete lines from LiveLineWidget._commit_lines(); routes prose
through StreamingBlockBuffer + apply_inline_markdown/apply_block_line, and
mounts StreamingCodeBlock widgets for fenced code blocks.

Reuses the existing PT-mode pipeline from agent/rich_output.py without
modification.  New code is a thin integration layer.

Architecture
------------
- One ResponseFlowEngine per MessagePanel (per assistant turn).
- Created lazily in MessagePanel.on_mount() so panel.app is available.
- State machine: NORMAL ↔ IN_CODE (fence open/close detection).
- Multi-section prose: each fence open mounts a new CopyableBlock after the
  StreamingCodeBlock so post-code prose renders in DOM order below the block.

Kill switch
-----------
HERMES_MARKDOWN=0  →  MARKDOWN_ENABLED = False  →  engine not created in
on_mount()  →  raw text path used (no markdown processing).
MARKDOWN_ENABLED is read once at module import time; monkeypatch-safe because
MessagePanel.on_mount() imports it fresh each time it runs.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Literal

from rich.text import Text

if TYPE_CHECKING:
    from hermes_cli.tui.widgets import CopyableBlock, CopyableRichLog, MessagePanel, StreamingCodeBlock

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

MARKDOWN_ENABLED: bool = (
    os.environ.get("HERMES_MARKDOWN", "1").strip() not in ("0", "false", "no")
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Matches opening fence: ```lang or ~~~lang (3+ backticks or tildes)
# Group 1: fence chars (length = fence depth)
# Group 2: language specifier (may be empty string)
_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})(\S*)\s*$")

# Matches closing fence (no language specifier)
# Group 1: fence chars
_FENCE_CLOSE_RE = re.compile(r"^(`{3,}|~{3,})\s*$")
_INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)(.*)$")
_SOURCE_KEYWORD_RE = re.compile(
    r"\b(class|public|private|protected|static|void|func|function|def|return|import|from|package|const|let|var|fn|use|SELECT|INSERT|CREATE|UPDATE)\b"
)
_SOURCE_COMMAND_RE = re.compile(
    r"^(javac|java|python|python3|node|npm|yarn|pnpm|pip|pip3|pytest|cargo|go|git|make|uv|bash|sh)\b"
)
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_CODE_INTRO_LABEL_RE = re.compile(
    r"^(?:to run it|run it|output|result|results|response|command|commands|example|examples|stderr|stdout|log|logs)\s*:$",
    re.IGNORECASE,
)
_INLINE_CODE_LABEL_RE = re.compile(
    r"^(to run it|run it|output|result|results|response|command|commands|example|examples|stderr|stdout|log|logs)\s*:\s*(.+)$",
    re.IGNORECASE,
)

# Same pattern as rich_output._MD_HR_RE — standalone HR line
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_horizontal_rule(line: str) -> bool:
    return bool(_HR_RE.match(line.strip()))


def _detect_lang(code: str) -> str:
    """Best-effort language detection for fences with no language specifier."""
    stripped = code.strip()
    if not stripped:
        return "text"

    # Fast-path heuristics for short snippets where Pygments guess_lexer()
    # often falls back to plain text.
    if any(token in code for token in ("System.out.", "public class ", "String[] args", "import java.", "package ")):
        return "java"
    if any(token in code for token in ("def ", "__name__ == ", "print(", "import ", "from ")):
        return "python"
    if all(
        line.strip() == "" or _SOURCE_COMMAND_RE.match(line.strip())
        for line in stripped.splitlines()
    ):
        return "bash"

    try:
        from pygments.lexers import guess_lexer  # type: ignore[import-untyped]
        lexer = guess_lexer(code)
        return lexer.aliases[0] if lexer.aliases else "text"
    except Exception:
        return "text"


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences (re-use same pattern as widgets.py)."""
    import re as _re
    _ANSI_RE = _re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
    return _ANSI_RE.sub("", text)


def _looks_like_source_line(raw: str) -> bool:
    stripped = raw.strip()
    if not stripped:
        return False
    if stripped.endswith(":"):
        return False
    if _LIST_PREFIX_RE.match(raw):
        return False
    if " - " in stripped or " – " in stripped:
        return False
    if _SOURCE_COMMAND_RE.match(stripped):
        return True
    if _SOURCE_KEYWORD_RE.search(stripped):
        return True
    if any(tok in raw for tok in ("{", "}", "();", ");", "->", "::", "#include", "System.out.", "fmt.", "println!")):
        return True
    if "=" in raw and "==" not in raw and len(stripped.split()) <= 8:
        return True
    return False


def _is_code_intro_label(line: str) -> bool:
    return bool(_CODE_INTRO_LABEL_RE.match(line.strip()))


# ---------------------------------------------------------------------------
# ResponseFlowEngine
# ---------------------------------------------------------------------------

class ResponseFlowEngine:
    """Stateful per-turn markdown processor for TUI streaming output.

    One instance per MessagePanel (per assistant turn).  Created in
    MessagePanel.on_mount() so self.app is available.

    Receives complete lines from LiveLineWidget._commit_lines(); routes
    prose to the panel's CopyableRichLog and code to StreamingCodeBlock widgets.

    Wraps agent.rich_output.StreamingBlockBuffer for block-level state.
    Wraps apply_inline_markdown() and apply_block_line() for line-level prose.
    """

    def __init__(self, *, panel: "MessagePanel") -> None:
        from agent.rich_output import StreamingBlockBuffer
        self._panel = panel
        getter = getattr(type(panel), "current_prose_log", None)
        self._prose_log: CopyableRichLog = (
            panel.current_prose_log() if callable(getter) else panel.response_log
        )
        self._skin_vars: dict[str, str] = panel.app.get_css_variables()
        self._pygments_theme: str = self._skin_vars.get("preview-syntax-theme", "monokai")
        self._block_buf: StreamingBlockBuffer = StreamingBlockBuffer()
        self._state: Literal["NORMAL", "IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE"] = "NORMAL"
        self._fence_char: str = "`"
        self._fence_depth: int = 3
        self._active_block: "StreamingCodeBlock | None" = None
        self._pending_source_line: str | None = None
        self._pending_code_intro: bool = False
        self._prose_section_counter: int = 0  # for unique CopyableBlock IDs

    def _sync_prose_log(self) -> None:
        """Refresh the active prose destination from the owning message panel."""
        getter = getattr(type(self._panel), "current_prose_log", None)
        self._prose_log = (
            self._panel.current_prose_log()
            if callable(getter)
            else self._panel.response_log
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_line(self, raw: str) -> None:
        """Process one complete line (no trailing newline)."""
        from agent.rich_output import apply_block_line, apply_inline_markdown

        # Phase 1: Code block boundary detection (bypass StreamingBlockBuffer)
        intro_candidate = _is_code_intro_label(raw)
        if self._state == "NORMAL":
            stripped = raw.strip()
            was_pending_code_intro = self._pending_code_intro
            if was_pending_code_intro:
                self._pending_code_intro = False
                if (
                    stripped
                    and not _FENCE_OPEN_RE.match(stripped)
                    and not _INDENTED_CODE_RE.match(raw)
                    and not _looks_like_source_line(raw)
                    and not _LIST_PREFIX_RE.match(raw)
                    and not stripped.endswith(":")
                ):
                    self._flush_block_buf()
                    self._emit_complete_code_block([raw])
                    return
            if intro_candidate:
                self._pending_code_intro = True
            if self._pending_source_line is not None:
                if _looks_like_source_line(raw):
                    self._flush_block_buf()
                    self._state = "IN_SOURCE_LIKE"
                    self._active_block = self._open_code_block("")
                    self._active_block.append_line(self._pending_source_line)
                    self._active_block.append_line(raw)
                    self._pending_source_line = None
                    return
                pending = self._pending_source_line
                self._pending_source_line = None
                block_result = self._block_buf.process_line(pending)
                if block_result is not None:
                    if _is_horizontal_rule(block_result):
                        self._emit_rule()
                    else:
                        block_ansi = apply_block_line(block_result)
                        inline_ansi = apply_inline_markdown(block_ansi)
                        plain = _strip_ansi(inline_ansi)
                        self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)
            m = _FENCE_OPEN_RE.match(stripped)
            if m:
                lang = m.group(2).strip() if m.group(2) else ""
                fence_char = m.group(1)[0]          # '`' or '~'
                fence_depth = len(m.group(1))        # minimum closing fence length
                # Flush pending setext/table state BEFORE changing state (state-safe)
                self._flush_block_buf()
                # Change state and record fence params only after pending prose is emitted
                self._state = "IN_CODE"
                self._fence_char = fence_char
                self._fence_depth = fence_depth
                self._active_block = self._open_code_block(lang)
                return  # fence open line itself not written to any log
            indent_m = _INDENTED_CODE_RE.match(raw)
            if indent_m:
                # Treat Markdown-style indented code blocks as first-class code widgets.
                self._flush_block_buf()
                self._state = "IN_INDENTED_CODE"
                self._active_block = self._open_code_block("")
                self._active_block.append_line(indent_m.group(1))
                return
            inline_label_m = _INLINE_CODE_LABEL_RE.match(stripped)
            if inline_label_m:
                value = inline_label_m.group(2).strip()
                if value and not stripped.endswith(":"):
                    self._flush_block_buf()
                    label = f"{inline_label_m.group(1)}:"
                    block_ansi = apply_block_line(label)
                    inline_ansi = apply_inline_markdown(block_ansi)
                    plain = _strip_ansi(inline_ansi)
                    self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)
                    self._emit_complete_code_block([value])
                    return
            if _looks_like_source_line(raw):
                self._pending_source_line = raw
                return

        if self._state == "IN_CODE":
            stripped = raw.strip()
            close_m = _FENCE_CLOSE_RE.match(stripped)
            if (
                close_m
                and close_m.group(1)[0] == self._fence_char     # same fence char type
                and len(close_m.group(1)) >= self._fence_depth  # same or greater depth
            ):
                assert self._active_block is not None
                self._active_block.complete(self._skin_vars)
                self._active_block = None
                self._state = "NORMAL"
                return  # fence close line itself not written to any log
            assert self._active_block is not None
            self._active_block.append_line(raw)
            return  # code lines go to StreamingCodeBlock, not prose log

        if self._state == "IN_INDENTED_CODE":
            assert self._active_block is not None
            indent_m = _INDENTED_CODE_RE.match(raw)
            if raw == "":
                self._active_block.append_line("")
                return
            if indent_m:
                self._active_block.append_line(indent_m.group(1))
                return
            self._active_block.complete(self._skin_vars)
            self._active_block = None
            self._state = "NORMAL"

        if self._state == "IN_SOURCE_LIKE":
            assert self._active_block is not None
            if _looks_like_source_line(raw):
                self._active_block.append_line(raw)
                return
            self._active_block.complete(self._skin_vars)
            self._active_block = None
            self._state = "NORMAL"

        # Phase 2: Prose — through StreamingBlockBuffer (setext, tables, BQ continuation)
        block_result = self._block_buf.process_line(raw)
        if block_result is None:
            return  # buffered (table row or setext lookahead pending)

        # Phase 3: Horizontal rule intercept — emit Rich Rule renderable
        if _is_horizontal_rule(block_result):
            self._emit_rule()
            return

        # Phase 4: Block + inline rendering via existing PT-mode pipeline
        block_ansi = apply_block_line(block_result)
        inline_ansi = apply_inline_markdown(block_ansi)

        # Phase 5: Write to prose log
        self._sync_prose_log()
        plain = _strip_ansi(inline_ansi)
        self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)
        self._pending_code_intro = intro_candidate or _is_code_intro_label(plain)

    def flush(self) -> None:
        """Turn ended — close any open code block; flush StreamingBlockBuffer pending state."""
        if self._active_block is not None and self._state == "IN_CODE":
            self._active_block.flush()  # marks FLUSHED, stops spinner
            self._active_block = None
            self._state = "NORMAL"
        elif self._active_block is not None and self._state in ("IN_INDENTED_CODE", "IN_SOURCE_LIKE"):
            self._active_block.complete(self._skin_vars)
            self._active_block = None
            self._state = "NORMAL"
        if self._pending_source_line is not None:
            pending = self._pending_source_line
            self._pending_source_line = None
            block_result = self._block_buf.process_line(pending)
            if block_result is not None:
                if _is_horizontal_rule(block_result):
                    self._emit_rule()
                else:
                    block_ansi = apply_block_line(block_result)
                    inline_ansi = apply_inline_markdown(block_ansi)
                    plain = _strip_ansi(inline_ansi)
                    self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)
        # Flush any prose pending in StreamingBlockBuffer (setext, tables)
        self._flush_block_buf()

    def refresh_skin(self, css_vars: dict[str, str]) -> None:
        """Called from HermesApp.apply_skin() after hot-reload.

        Updates _skin_vars and _pygments_theme.  Effect on existing blocks: none
        (completed and streaming blocks keep their construction-time theme).
        Effect on new blocks: next _open_code_block() uses the updated theme.
        """
        self._skin_vars = css_vars
        self._pygments_theme = css_vars.get("preview-syntax-theme", "monokai")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _emit_rule(self) -> None:
        """Emit a resize-responsive horizontal rule to the prose log."""
        from rich.rule import Rule as RichRule
        self._sync_prose_log()
        self._prose_log.write(RichRule(style="dim"))
        self._prose_log._plain_lines.append("---")  # plain copy source

    def _flush_block_buf(self) -> None:
        """Emit any pending StreamingBlockBuffer state to the prose log."""
        from agent.rich_output import apply_block_line, apply_inline_markdown
        result = self._block_buf.flush()
        if result:
            # result may be multi-line (e.g. rendered table) — split and emit each
            for line in result.splitlines():
                if _is_horizontal_rule(line):
                    self._emit_rule()
                else:
                    block_ansi = apply_block_line(line)
                    inline_ansi = apply_inline_markdown(block_ansi)
                    self._sync_prose_log()
                    plain = _strip_ansi(inline_ansi)
                    self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)

    def _open_code_block(self, lang: str) -> "StreamingCodeBlock":
        """Mount a StreamingCodeBlock in timeline order and retarget prose."""
        from hermes_cli.tui.widgets import StreamingCodeBlock

        block = StreamingCodeBlock(lang=lang, pygments_theme=self._pygments_theme)
        self._panel._mount_nonprose_block(block)
        self._active_block = block
        self._sync_prose_log()
        return block

    def _emit_complete_code_block(self, lines: list[str], lang: str = "") -> None:
        """Mount a code block and finalize it after the next refresh."""
        block = self._open_code_block(lang)
        for line in lines:
            block.append_line(line)
        self._active_block = None
        self._panel.call_after_refresh(block.complete, dict(self._skin_vars))
