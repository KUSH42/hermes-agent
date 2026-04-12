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

# Same pattern as rich_output._MD_HR_RE — standalone HR line
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_horizontal_rule(line: str) -> bool:
    return bool(_HR_RE.match(line.strip()))


def _detect_lang(code: str) -> str:
    """Best-effort language detection for fences with no language specifier."""
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
        self._prose_log: CopyableRichLog = panel.response_log
        self._skin_vars: dict[str, str] = panel.app.get_css_variables()
        self._pygments_theme: str = self._skin_vars.get("preview-syntax-theme", "monokai")
        self._block_buf: StreamingBlockBuffer = StreamingBlockBuffer()
        self._state: Literal["NORMAL", "IN_CODE"] = "NORMAL"
        self._fence_char: str = "`"
        self._fence_depth: int = 3
        self._active_block: "StreamingCodeBlock | None" = None
        self._prose_section_counter: int = 0  # for unique CopyableBlock IDs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_line(self, raw: str) -> None:
        """Process one complete line (no trailing newline)."""
        from agent.rich_output import apply_block_line, apply_inline_markdown

        # Phase 1: Code block boundary detection (bypass StreamingBlockBuffer)
        if self._state == "NORMAL":
            stripped = raw.strip()
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
        plain = _strip_ansi(inline_ansi)
        self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)

    def flush(self) -> None:
        """Turn ended — close any open code block; flush StreamingBlockBuffer pending state."""
        if self._active_block is not None and self._state == "IN_CODE":
            self._active_block.flush()  # marks FLUSHED, stops spinner
            self._active_block = None
            self._state = "NORMAL"
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
                    plain = _strip_ansi(inline_ansi)
                    self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)

    def _open_code_block(self, lang: str) -> "StreamingCodeBlock":
        """Mount a StreamingCodeBlock + next prose CopyableBlock into MessagePanel."""
        from hermes_cli.tui.widgets import CopyableBlock, StreamingCodeBlock

        # 1. Mount the code block (appended as last child of MessagePanel)
        block = StreamingCodeBlock(lang=lang, pygments_theme=self._pygments_theme)
        self._panel.mount(block)
        self._active_block = block

        # 2. Mount the next prose section immediately after the code block
        self._prose_section_counter += 1
        new_prose: CopyableBlock = CopyableBlock(
            id=f"prose-{self._panel._msg_id}-{self._prose_section_counter}",
            _log_id=f"prose-log-{self._panel._msg_id}-{self._prose_section_counter}",
        )
        self._panel.mount(new_prose)               # appended after the code block
        self._panel._prose_blocks.append(new_prose)
        self._prose_log = new_prose.log            # future prose writes go here

        return block
