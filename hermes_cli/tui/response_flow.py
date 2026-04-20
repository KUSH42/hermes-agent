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
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from rich.text import Text

if TYPE_CHECKING:
    from hermes_cli.tui.widgets import CopyableBlock, CopyableRichLog, MathBlockWidget, MessagePanel, ReasoningPanel, StreamingCodeBlock

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
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(?=\S)")
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

# Footnote definition line — [^N]: text — collected and suppressed in NORMAL state
_FOOTNOTE_DEF_RE = re.compile(r'^\s*\[\^(\d{1,4})\]:\s*(.*)')

# Citation tag: [CITE:N Title \u2014 https://url] — suppress and collect
_CITE_RE = re.compile(
    r'^\[CITE:(\d{1,4})\s+(.+?)\s+\u2014\s+(https?://\S+)\]$'
)

# Block math delimiters — checked BEFORE fence detection to avoid $$ colliding with _FENCE_OPEN_RE
_BLOCK_MATH_OPEN_RE = re.compile(
    r"^\$\$\s*$"
    r"|^\\\[\s*$"
    r"|^\\begin\{(equation|align|gather|multline|eqnarray)\*?\}\s*$"
)
_BLOCK_MATH_CLOSE_RE = re.compile(
    r"^\$\$\s*$"
    r"|^\\\]\s*$"
    r"|^\\end\{(equation|align|gather|multline|eqnarray)\*?\}\s*$"
)
# Single-line: $$expr$$ on one line (no newline inside)
_BLOCK_MATH_ONELINE_RE = re.compile(r"^\$\$(.+)\$\$\s*$")

# Inline math: $expr$ in prose — conservative, requires math indicators
_INLINE_MATH_RE = re.compile(
    r"(?<!\$)\$"          # open $, not preceded by $
    r"([^$\n]{1,120})"    # content: 1–120 chars, no newline
    r"(?<!\s)\$"          # close $, not preceded by whitespace
)

# Custom emoji substitution — matches :name: tokens known to the registry
_EMOJI_RE = re.compile(r":([a-zA-Z0-9_-]+):")

# Lazy singleton — loaded on first use (avoids import cost at module load)
_math_renderer: "MathRenderer | None" = None


def _get_math_renderer() -> "MathRenderer":
    global _math_renderer
    if _math_renderer is None:
        from hermes_cli.tui.math_renderer import MathRenderer
        _math_renderer = MathRenderer()
    return _math_renderer


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

    # Diff detection — must come before language heuristics so `+def ...` lines
    # don't trigger the Python fast-path.  Without this, diff output gets lexed
    # as Python: `+` becomes a unary operator, `+def` is invalid → no syntax
    # highlighting, wrong bg on affected lines.
    lines = stripped.splitlines()
    nonempty = [l for l in lines if l.strip()]
    if nonempty:
        # Count lines starting with +/- (unified diff markers).
        # In Python source, +/- only appear as mid-line operators, never at col 0.
        # Threshold 35%: pure diff ≈100%, mixed diff ≈50-70%, regular code ≈0%.
        diff_markers = sum(
            1 for l in nonempty
            if l[0] == "+"
        ) + sum(
            1 for l in nonempty
            if l[0] == "-" and not l.startswith("---")
        ) + sum(1 for l in nonempty if l.startswith("@@"))
        if diff_markers >= len(nonempty) * 0.35:
            return "diff"

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
# List continuation indent helpers
# ---------------------------------------------------------------------------

_MD_UL_RE = re.compile(r"^(\s*)([-*+])\s+(.+)")
_MD_OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)")

# Approximate available width for pre-wrapping list items.
# Accounts for CopyableBlock margin (0 2 = 4 chars) + scrollbar (1 char).
_LIST_WRAP_WIDTH = 75


def _detect_list_cont_indent(line: str) -> str:
    """Return continuation indent string if *line* is a list item, else ``""``."""
    m = _MD_UL_RE.match(line)
    if m:
        return " " * (len(m.group(1)) + 2)  # indent + bullet+spc
    m = _MD_OL_RE.match(line)
    if m:
        return " " * (len(m.group(1)) + len(m.group(2)) + 2)  # indent + num+dot+spc
    return ""


def _apply_cont_indent(line: str, indent: str, width: int = _LIST_WRAP_WIDTH) -> str:
    """Pre-wrap *line* with hanging *indent* so indent survives RichLog wrapping."""
    if not indent:
        return line
    visual_line_len = len(_strip_ansi(line))
    if visual_line_len <= width:
        return line
    # Pre-wrap: first line up to (width), rest at (width - len(indent))
    first_width = width
    rest_width = max(width - len(indent), 20)
    words = line.split(" ")
    out_lines: list[str] = []
    cur = ""
    cur_vis = 0
    is_first = True
    limit = first_width if is_first else rest_width
    for word in words:
        wlen = len(word)
        if cur:
            if cur_vis + 1 + wlen > limit:
                out_lines.append(cur)
                is_first = False
                limit = rest_width
                cur = indent + word
                cur_vis = len(indent) + wlen
            else:
                cur += " " + word
                cur_vis += 1 + wlen
        else:
            cur = word
            cur_vis = wlen
    if cur:
        out_lines.append(cur)
    return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# _DimRichLogProxy
# ---------------------------------------------------------------------------

class _DimRichLogProxy:
    """Proxy around CopyableRichLog that injects dim italic on every prose write.

    Used by ReasoningFlowEngine so ResponseFlowEngine.process_line() logic
    runs unchanged, but every write_with_source() call wraps text in dim italic
    and appends to panel._plain_lines instead of the log's internal list.
    """

    def __init__(self, real_log: "CopyableRichLog", plain_list: list[str]) -> None:
        self._log = real_log
        self._plain_list = plain_list

    def write_with_source(self, text: "Text", plain: str) -> None:
        from rich.text import Text as RichText
        wrapped = RichText(style="dim italic")
        wrapped.append_text(text)
        self._log.write(wrapped, expand=True)
        self._plain_list.append(plain)

    def write(self, renderable, **kw) -> None:
        self._log.write(renderable, **kw)

    def __getattr__(self, name: str):
        return getattr(self._log, name)


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
        self._state: Literal["NORMAL", "IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE", "IN_MATH"] = "NORMAL"
        self._fence_char: str = "`"
        self._fence_depth: int = 3
        self._active_block: "StreamingCodeBlock | None" = None
        # Math rendering state
        _app = getattr(panel, "app", None)
        self._math_lines: list[str] = []
        self._math_env: str = ""
        self._math_enabled: bool = getattr(_app, "_math_enabled", True)
        self._math_renderer_mode: str = getattr(_app, "_math_renderer", "auto")
        self._math_dpi: int = getattr(_app, "_math_dpi", 150)
        self._math_max_rows: int = getattr(_app, "_math_max_rows", 12)
        self._mermaid_enabled: bool = getattr(_app, "_mermaid_enabled", True)
        self._pending_source_line: str | None = None
        self._pending_code_intro: bool = False
        self._prose_section_counter: int = 0  # for unique CopyableBlock IDs
        self._list_cont_indent: str = ""  # continuation indent for list items
        self._footnote_defs: dict[str, str] = {}   # label → definition text
        self._footnote_order: list[str] = []       # labels in order of first definition
        self._footnote_def_open: str | None = None  # label of continuation-in-progress
        self._partial: str = ""                     # accumulated partial tail of current line
        # Citation tag state
        self._cite_entries: dict[int, tuple[str, str]] = {}   # N → (title, url)
        self._cite_order: list[int] = []                       # insertion order
        self._citations_enabled: bool = getattr(_app, "_citations_enabled", True)
        # Media URL detection
        self._mount_media_callback: "Callable[[str, str], None] | None" = None
        self._emitted_media_urls: set[str] = set()
        # Custom emoji substitution
        self._emoji_registry = getattr(_app, "_emoji_registry", None)
        self._emoji_images_enabled: bool = getattr(_app, "_emoji_images_enabled", True)
        self._emitted_emoji_anchors: set[int] = set()  # id() of mounted positions
        # Optional callback fired for each committed prose line (non-blank plain text)
        self._prose_callback: "Callable[[str], None] | None" = None

    def _write_prose(self, rich_text: "Text", plain: str) -> None:
        """Write a prose line and optionally fire the prose callback."""
        self._prose_log.write_with_source(rich_text, plain)
        if self._prose_callback is not None and plain.strip():
            try:
                self._prose_callback(plain)
            except Exception:
                pass

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

    def feed(self, chunk: str) -> None:
        """Update partial preview for the in-progress line.

        Called from _consume_output() on every chunk.  Does NOT process
        complete lines — that remains _commit_lines() → process_line().
        Manages _partial so flush() can drain it at end-of-turn.
        """
        if "\n" in chunk:
            self._clear_partial_preview()
            self._partial = chunk.rsplit("\n", 1)[1]
        else:
            self._partial += chunk
        if self._partial:
            self._route_partial(self._partial)

    def _route_partial(self, fragment: str) -> None:
        if self._state in ("IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE"):
            if self._active_block is not None:
                self._active_block.feed_partial(fragment)

    def _clear_partial_preview(self) -> None:
        if self._state in ("IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE"):
            if self._active_block is not None:
                self._active_block.clear_partial()
        self._partial = ""

    def process_line(self, raw: str) -> None:
        """Process one complete line (no trailing newline)."""
        from agent.rich_output import apply_block_line, apply_inline_markdown

        # Media URL scan — runs first so early-return paths don't skip it
        if self._state == "NORMAL" and self._mount_media_callback is not None:
            self._scan_media_urls(raw)

        # Phase 1: Code block boundary detection (bypass StreamingBlockBuffer)
        intro_candidate = _is_code_intro_label(raw)
        if self._state == "NORMAL":
            # Footnote definition: collect and suppress from main output.
            # Must be first — runs before pending-code-intro and fence checks.
            _fn_m = _FOOTNOTE_DEF_RE.match(raw)
            if _fn_m:
                label, body = _fn_m.group(1), _fn_m.group(2).strip()
                if label not in self._footnote_defs:
                    self._footnote_order.append(label)
                self._footnote_defs[label] = body
                self._footnote_def_open = label
                return
            # Multi-line continuation (4-space or tab indent):
            if self._footnote_def_open and (raw.startswith("    ") or raw.startswith("\t")):
                self._footnote_defs[self._footnote_def_open] += " " + raw.strip()
                return
            self._footnote_def_open = None

            # Citation tag detection — suppress line and collect entry
            if self._citations_enabled:
                _cite_m = _CITE_RE.match(raw.strip())
                if _cite_m:
                    _n = int(_cite_m.group(1))
                    _title = _cite_m.group(2).strip()
                    _url = _cite_m.group(3)
                    self._cite_entries[_n] = (_title, _url)
                    if _n not in self._cite_order:
                        self._cite_order.append(_n)
                    return  # suppress from main output

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
                    self._list_cont_indent = ""
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
                        self._write_prose(Text.from_ansi(inline_ansi), plain)
            # Block math — checked BEFORE fence detection ($$ would match _FENCE_OPEN_RE)
            if self._math_enabled:
                oneline_m = _BLOCK_MATH_ONELINE_RE.match(stripped)
                if oneline_m:
                    self._flush_block_buf()
                    self._flush_math_block(oneline_m.group(1))
                    return
                if _BLOCK_MATH_OPEN_RE.match(stripped):
                    self._flush_block_buf()
                    self._math_lines = []
                    self._math_env = stripped
                    self._state = "IN_MATH"
                    return
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
                self._list_cont_indent = ""
                self._active_block = self._open_code_block(lang)
                return  # fence open line itself not written to any log
            indent_m = _INDENTED_CODE_RE.match(raw)
            if indent_m:
                # Treat Markdown-style indented code blocks as first-class code widgets.
                self._flush_block_buf()
                self._state = "IN_INDENTED_CODE"
                self._list_cont_indent = ""
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
                    self._write_prose(Text.from_ansi(inline_ansi), plain)
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

        if self._state == "IN_MATH":
            stripped = raw.strip()
            if _BLOCK_MATH_CLOSE_RE.match(stripped):
                self._flush_math_block("\n".join(self._math_lines))
                self._math_lines = []
                self._math_env = ""
                self._state = "NORMAL"
            else:
                self._math_lines.append(raw)
            return

        # Phase 2: Prose — through StreamingBlockBuffer (setext, tables, BQ continuation)
        # Apply inline math substitution on raw text before markdown processing
        if self._math_enabled:
            raw = self._apply_inline_math(raw)
        block_result = self._block_buf.process_line(raw)
        if block_result is None:
            return  # buffered (table row or setext lookahead pending)

        # Phase 3: Horizontal rule intercept — emit Rich Rule renderable
        if _is_horizontal_rule(block_result):
            self._emit_rule()
            return

        # Phase 4: Block + inline rendering via existing PT-mode pipeline
        # Track list state for continuation indent
        list_ci = _detect_list_cont_indent(block_result)
        if list_ci:
            # List item — pre-wrap with hanging indent so wrapped lines
            # align with text after marker, not flush-left
            self._list_cont_indent = list_ci
            indented = _apply_cont_indent(block_result, list_ci)
            block_ansi = apply_block_line(indented)
        else:
            block_ansi = apply_block_line(block_result)
            # Reset list state on blank line or structural elements
            stripped = block_result.strip()
            if (stripped == ""
                or _HR_RE.match(stripped)
                or _FENCE_OPEN_RE.match(stripped)
                or _LIST_PREFIX_RE.match(block_result)):
                self._list_cont_indent = ""
            elif self._list_cont_indent and not block_result[0:1].isspace():
                # Non-list prose after list — reset indent, don't apply it
                self._list_cont_indent = ""
        inline_ansi = apply_inline_markdown(block_ansi)

        # Phase 5: Write to prose log
        # Phase 6 (interleaved): strip :name: emoji tokens from displayed text when
        # images are enabled so the rendered widget replaces the token instead of
        # appearing below a duplicate text copy of it.
        self._sync_prose_log()
        plain = _strip_ansi(inline_ansi)
        emoji_names = self._extract_emoji_refs(plain)
        if emoji_names:
            display_ansi = _EMOJI_RE.sub("", inline_ansi)
            display_plain = _EMOJI_RE.sub("", plain)
            self._write_prose(Text.from_ansi(display_ansi), display_plain)
        else:
            self._write_prose(Text.from_ansi(inline_ansi), plain)
        self._pending_code_intro = intro_candidate or _is_code_intro_label(plain)

        for _ename in emoji_names:
            self._mount_emoji(_ename)

    def _scan_media_urls(self, line: str) -> None:
        """Scan a NORMAL-state line for media URLs and invoke _mount_media_callback."""
        from hermes_cli.tui.media_player import (
            _YOUTUBE_RE, _VIDEO_EXT_RE, _AUDIO_EXT_RE, _inline_media_config,
        )
        cfg = _inline_media_config()
        if not cfg.enabled:
            return
        if cfg.youtube:
            for url in _YOUTUBE_RE.findall(line):
                if url not in self._emitted_media_urls:
                    self._emitted_media_urls.add(url)
                    if self._mount_media_callback:
                        self._mount_media_callback("youtube", url)
        for url in _VIDEO_EXT_RE.findall(line):
            if url not in self._emitted_media_urls:
                self._emitted_media_urls.add(url)
                if self._mount_media_callback:
                    self._mount_media_callback("video", url)
        if cfg.audio:
            for url in _AUDIO_EXT_RE.findall(line):
                if url not in self._emitted_media_urls:
                    self._emitted_media_urls.add(url)
                    if self._mount_media_callback:
                        self._mount_media_callback("audio", url)

    def _has_image_support(self) -> bool:
        from hermes_cli.tui.kitty_graphics import get_caps, GraphicsCap
        cap = get_caps()
        return cap in (GraphicsCap.TGP, GraphicsCap.SIXEL)

    def _extract_emoji_refs(self, text: str) -> "list[str]":
        """Return distinct emoji names found in text that exist in the registry."""
        if self._emoji_registry is None or not self._emoji_images_enabled:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for m in _EMOJI_RE.finditer(text):
            name = m.group(1).lower()
            if name not in seen and self._emoji_registry.get(name) is not None:
                seen.add(name)
                out.append(name)
        return out

    def _mount_emoji(self, name: str) -> None:
        """Mount an emoji image widget. Safe to call from either event-loop or worker thread."""
        registry = self._emoji_registry
        if registry is None:
            return
        entry = registry.get(name)
        if entry is None:
            return
        panel = self._panel
        app = getattr(panel, "app", None)
        if app is None:
            return
        use_images = self._has_image_support() and entry.pil_image is not None

        def _do_mount() -> None:
            try:
                if entry.n_frames > 1 and use_images:
                    from hermes_cli.tui.emoji_registry import get_animated_emoji_widget_class
                    cls = get_animated_emoji_widget_class()
                    widget = cls(entry)
                    panel.mount(widget)
                elif use_images:
                    from hermes_cli.tui.widgets import InlineImage
                    # Pass image as constructor arg so watch_image fires after
                    # mount when size is valid, not before.
                    img = InlineImage(image=entry.pil_image, max_rows=entry.cell_height)
                    panel.mount(img)
                # No text fallback — :name: token was stripped from the prose
                # line in process_line before write_with_source was called.
            except Exception:
                pass

        import threading
        if threading.get_ident() == getattr(app, "_thread_id", None):
            # Already on the event-loop thread (async worker path) — call directly.
            _do_mount()
        else:
            app.call_from_thread(_do_mount)

    def flush(self) -> None:
        """Turn ended — close any open code block; flush StreamingBlockBuffer pending state."""
        if self._partial:
            pending = self._partial
            self._clear_partial_preview()
            self.process_line(pending)
        if self._state == "IN_MATH" and self._math_lines:
            self._flush_math_block("\n".join(self._math_lines))
            self._math_lines = []
            self._math_env = ""
            self._state = "NORMAL"
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
        self._render_footnote_section()
        self._footnote_defs.clear()
        self._footnote_order.clear()
        self._footnote_def_open = None
        # Mount SourcesBar if any citations were collected
        if self._cite_entries and self._citations_enabled:
            self._mount_sources_bar()   # captures entries before clear below
        self._cite_entries.clear()
        self._cite_order.clear()
        self._emitted_media_urls.clear()

    def _mount_sources_bar(self) -> None:
        """Mount SourcesBar below the panel after the next refresh."""
        from hermes_cli.tui.widgets import SourcesBar
        entries = [(n, *self._cite_entries[n]) for n in self._cite_order]
        panel = self._panel

        def _do_mount() -> None:
            try:
                panel.mount(SourcesBar(entries))
            except Exception:
                pass

        panel.call_after_refresh(_do_mount)

    def _render_footnote_section(self) -> None:
        from agent.rich_output import apply_inline_markdown, _to_superscript
        if not self._footnote_defs:
            return
        self._sync_prose_log()
        sep = Text("─" * 40, style="dim")
        self._prose_log.write_with_source(sep, "─" * 40)
        ref_style = self._skin_vars.get("footnote-ref-color", "dim")
        for label in self._footnote_order:
            body = self._footnote_defs.get(label, "")
            sup = _to_superscript(label)
            styled_body = Text.from_ansi(apply_inline_markdown(body))
            line = Text()
            line.append(sup + " ", style=ref_style)
            line.append_text(styled_body)
            self._prose_log.write_with_source(line, sup + " " + body)

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------

    def _apply_inline_math(self, line: str) -> str:
        """Replace $...$ spans in a prose line with unicode approximations."""
        if "$" not in line:
            return line

        def replace_math(m: re.Match) -> str:  # type: ignore[type-arg]
            inner = m.group(1)
            # Only substitute when it looks like math (not currency / shell vars)
            if "\\" in inner or "^" in inner or "_" in inner:
                return _get_math_renderer().render_unicode(inner)
            return m.group(0)

        return _INLINE_MATH_RE.sub(replace_math, line)

    def _flush_math_block(self, latex: str) -> None:
        """Render a collected block-math expression and mount/write result."""
        from hermes_cli.tui.kitty_graphics import get_caps, GraphicsCap
        caps = get_caps()
        use_image = (
            self._math_enabled
            and self._math_renderer_mode != "unicode"
            and caps != GraphicsCap.NONE
        )
        if not use_image:
            # Synchronous unicode fallback — write as italic prose
            unicode_repr = _get_math_renderer().render_unicode(latex)
            self._sync_prose_log()
            t = Text(f"  {unicode_repr}  ", style="italic")
            self._prose_log.write_with_source(t, unicode_repr)
            return

        # Async image path — dispatch to worker thread
        dpi = self._math_dpi
        max_rows = self._math_max_rows
        latex_copy = latex  # avoid closure over mutable

        def _render_worker() -> None:
            path = _get_math_renderer().render_block(latex_copy, dpi=dpi)
            if path is None:
                # Fallback: write unicode on the app thread
                unicode_repr = _get_math_renderer().render_unicode(latex_copy)
                self._panel.app.call_from_thread(
                    self._mount_math_unicode, unicode_repr
                )
            else:
                self._panel.app.call_from_thread(
                    self._mount_math_image, path, max_rows
                )

        self._panel.app.run_worker(_render_worker, thread=True)

    def _mount_math_unicode(self, unicode_repr: str) -> None:
        """App-thread: write unicode math fallback to prose log."""
        self._sync_prose_log()
        t = Text(f"  {unicode_repr}  ", style="italic")
        self._prose_log.write_with_source(t, unicode_repr)

    def _mount_math_image(self, path: "Path", max_rows: int) -> None:
        """App-thread: mount MathBlockWidget for a rendered PNG."""
        try:
            from hermes_cli.tui.widgets import MathBlockWidget
            widget = MathBlockWidget(image_path=path, max_rows=max_rows)
            self._panel._mount_nonprose_block(widget)
        except Exception:
            pass

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
        if result is not None:
            # result may be multi-line (e.g. rendered table) — split and emit each
            # empty string = trailing blank line, must still be emitted
            lines_out = result.splitlines() if result else [""]
            for line in lines_out:
                if _is_horizontal_rule(line):
                    self._emit_rule()
                    continue
                list_ci = _detect_list_cont_indent(line)
                if list_ci:
                    self._list_cont_indent = list_ci
                    indented = _apply_cont_indent(line, list_ci)
                    block_ansi = apply_block_line(indented)
                else:
                    block_ansi = apply_block_line(line)
                    stripped = line.strip()
                    if (stripped == ""
                        or _HR_RE.match(stripped)
                        or _FENCE_OPEN_RE.match(stripped)
                        or _LIST_PREFIX_RE.match(line)):
                        self._list_cont_indent = ""
                    elif self._list_cont_indent and not line[0:1].isspace():
                        self._list_cont_indent = ""
                inline_ansi = apply_inline_markdown(block_ansi)
                self._sync_prose_log()
                plain = _strip_ansi(inline_ansi)
                self._prose_log.write_with_source(Text.from_ansi(inline_ansi), plain)

    def _mount_code_block(self, block: "StreamingCodeBlock") -> None:
        """Mount block into output DOM. Override in subclasses."""
        self._panel._mount_nonprose_block(block)

    def _open_code_block(self, lang: str) -> "StreamingCodeBlock":
        """Mount a StreamingCodeBlock in timeline order and retarget prose."""
        from hermes_cli.tui.widgets import StreamingCodeBlock

        block = StreamingCodeBlock(lang=lang, pygments_theme=self._pygments_theme)
        self._mount_code_block(block)
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


# ---------------------------------------------------------------------------
# ReasoningFlowEngine
# ---------------------------------------------------------------------------

class ReasoningFlowEngine(ResponseFlowEngine):
    """ResponseFlowEngine variant for ReasoningPanel.

    Key differences vs ResponseFlowEngine:
    - _prose_log is a _DimRichLogProxy — all prose writes get dim italic
    - _sync_prose_log is a no-op (proxy is stable; no section switching)
    - Code blocks mounted inside ReasoningPanel, not MessagePanel
    - _emit_rule writes directly to _reasoning_log (no _plain_lines proxy needed)
    """

    def __init__(self, *, panel: "ReasoningPanel") -> None:  # type: ignore[override]
        from agent.rich_output import StreamingBlockBuffer
        self._panel = panel  # type: ignore[assignment]
        self._prose_log: _DimRichLogProxy = _DimRichLogProxy(  # type: ignore[assignment]
            panel._reasoning_log, panel._plain_lines
        )
        self._skin_vars: dict[str, str] = {}
        self._pygments_theme: str = "monokai"
        self._block_buf: StreamingBlockBuffer = StreamingBlockBuffer()
        self._state: Literal["NORMAL", "IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE", "IN_MATH"] = "NORMAL"
        self._fence_char: str = "`"
        self._fence_depth: int = 3
        self._active_block: "StreamingCodeBlock | None" = None
        self._pending_source_line: str | None = None
        self._pending_code_intro: bool = False
        self._prose_section_counter: int = 0
        self._list_cont_indent: str = ""
        self._footnote_defs: dict[str, str] = {}
        self._footnote_order: list[str] = []
        self._footnote_def_open: str | None = None
        self._partial: str = ""
        # Citations — mirrored from ResponseFlowEngine.__init__
        # Gated on BOTH _citations_enabled AND _reasoning_rich_prose
        _rp = getattr(panel.app, "_reasoning_rich_prose", True)
        self._cite_entries: dict[int, tuple[str, str]] = {}
        self._cite_order: list[int] = []
        self._citations_enabled: bool = getattr(panel.app, "_citations_enabled", True) and _rp
        # Math rendering — disabled in reasoning output (Non-Goal per spec)
        self._math_lines: list[str] = []
        self._math_env: str = ""
        self._math_enabled: bool = False
        self._math_renderer_mode: str = "unicode"
        self._math_dpi: int = 150
        self._math_max_rows: int = 12
        self._mermaid_enabled: bool = False
        # Media URL detection — disabled in reasoning output
        self._mount_media_callback: "Callable[[str, str], None] | None" = None
        self._emitted_media_urls: set[str] = set()
        # Custom emoji — gated on _emoji_reasoning
        _rp_emoji = getattr(panel.app, "_emoji_reasoning", True)
        _app = getattr(panel, "app", None)
        self._emoji_registry = getattr(_app, "_emoji_registry", None) if _rp_emoji else None
        self._emoji_images_enabled: bool = getattr(_app, "_emoji_images_enabled", True) and _rp_emoji
        self._emitted_emoji_anchors: set[int] = set()

    def process_line(self, raw: str) -> None:
        """Override: flush block buffer immediately after every line.

        ResponseFlowEngine keeps one line pending in StreamingBlockBuffer for
        setext/table lookahead, which causes visible lag during streaming and a
        flash in typewriter mode (content disappears from live_line before
        appearing in the log).  Flushing after every call eliminates the lag.
        Tradeoff: setext headings render as prose + HR; tables as plain rows.
        Both are rare in reasoning output.
        """
        super().process_line(raw)
        self._flush_block_buf()

    def _sync_prose_log(self) -> None:
        """No-op — proxy is stable; ReasoningPanel has one log section."""
        pass

    def _mount_code_block(self, block: "StreamingCodeBlock") -> None:
        """Mount dim code block inside ReasoningPanel, above the live line."""
        block.add_class("reasoning-code-block")
        self._panel.mount(block, before=self._panel._live_line)

    def _render_footnote_section(self) -> None:
        if not getattr(self._panel.app, "_reasoning_rich_prose", True):
            return
        super()._render_footnote_section()

    def _emit_rule(self) -> None:
        from rich.rule import Rule as RichRule
        self._panel._reasoning_log.write(RichRule(style="dim"))
        self._panel._plain_lines.append("---")
