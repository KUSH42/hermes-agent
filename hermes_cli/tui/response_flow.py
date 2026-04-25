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

import logging
import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from rich.text import Text
from textual.widget import Widget
from textual.app import ComposeResult

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
# Single-line: \[expr\] on one line
_BLOCK_MATH_ONELINE_BRACKET_RE = re.compile(r"^\\\[(.+)\\\]\s*$")

# Inline $$expr$$ embedded within a prose line (text before/after $$)
_INLINE_DOUBLE_MATH_RE = re.compile(r"\$\$([^$\n]+)\$\$")

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
# §5.11.1 ANSI literal replacement
# ---------------------------------------------------------------------------

_LITERAL_ANSI_RE = re.compile(r"\\x1b\[[0-9;?]*[a-zA-Z]")


def _replace_ansi_literals(text: str) -> str:
    """Replace literal \\x1b[...X strings with dim bracket notation [?...X]."""
    def _replace(m: re.Match) -> str:
        seq = m.group(0)[4:]  # strip leading "\\x1b" — remaining is [...]X
        return f"[?{seq}]"
    return _LITERAL_ANSI_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# §5.11.2 InlineCodeFence — numbered-line code widget
# ---------------------------------------------------------------------------

_NUMBERED_LINE_RE = re.compile(r"^\s*\d{1,3}\s*\|\s+\S")

_ORPHANED_CSI_RE = re.compile(r"(?<!\x1b)\[[0-9;]+[A-Za-z]")

_ANSI_STRIP_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]"
)
_STRIP_ORPHAN_RE = re.compile(r"(?<!\x1b)(?:;[0-9;]+[A-Za-z]|\[[0-9;]*m)")
_NORM_ORPHAN_RE = re.compile(r"(?<![\x1b0-9;])(?:;[0-9;]+[A-Za-z]|\[[0-9;]*m)")

logger = logging.getLogger(__name__)


class InlineCodeFence(Widget):
    """Inline code fence widget for numbered-line code in prose.

    Detected when ≥ 2 consecutive lines match `^\\s*\\d{1,3}\\s*|\\s+\\S`.
    Rendered as a dim left-bordered block.
    """

    DEFAULT_CSS = """
    InlineCodeFence {
        padding: 0 0 0 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """
    # Note: border-left is in hermes.tcss (uses $text-muted CSS var which
    # cannot be referenced in DEFAULT_CSS at parse time — TCSS variable gotcha)

    def __init__(self, lines: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines = lines

    def compose(self) -> ComposeResult:
        from textual.widgets import Static
        t = Text()
        for ln in self._lines:
            t.append(ln + "\n", style="dim")
        yield Static(t)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_horizontal_rule(line: str) -> bool:
    return bool(_HR_RE.match(line.strip()))


def _resolve_log_width(log_widget: "Any") -> int:
    """Resolve the visual width a log write should target."""
    try:
        region_w = log_widget.scrollable_content_region.width
    except Exception:
        region_w = 0  # widget not yet laid out — dimension unavailable
    if region_w > 0:
        return region_w
    try:
        size_w = log_widget.size.width
    except Exception:
        size_w = 0  # widget not yet laid out — dimension unavailable
    if size_w > 0:
        return size_w
    try:
        # Same pre-layout fallback as CopyableRichLog.write():
        # app width minus scrollbar + prose margins.
        return max(log_widget.app.size.width - 5, 20)
    except Exception:
        return 80  # app not available pre-mount — use safe default


def _make_rule(log_widget: "Any") -> "Text":
    """Return a dim rule sized to the log widget width, not the terminal width.

    Caps the width at `app.size.width - 5` to account for CopyableBlock margin
    (0 2 = 4) + OutputPanel scrollbar (1). Observed overflow: `scrollable_
    content_region.width` can briefly report the pre-chrome width during
    reflow, letting the rule spill under the scrollbar / outside the viewport.
    """
    w = _resolve_log_width(log_widget)
    if w <= 0:
        try:
            w = log_widget.app.size.width
        except Exception:
            w = 80  # app not available pre-mount
    try:
        app_cap = max(log_widget.app.size.width - 5, 20)
        w = min(w, app_cap)
    except Exception:
        pass  # app size unavailable; skip cap — rule may overflow by ≤5 cells
    return Text("─" * w, style="dim")


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
        # pygments.ClassNotFound / any lexer detection failure — plain text is the safe fallback
        return "text"


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences, including orphaned CSI residuals.

    Also strips bare `;digits...m` or `[digits...m` fragments that result from
    interceptors stripping the ESC byte but leaving the rest of the sequence.
    """
    text = _ANSI_STRIP_RE.sub("", text)
    return _STRIP_ORPHAN_RE.sub("", text)


def _normalize_ansi_for_render(text: str) -> str:
    """Normalize ANSI-like text before passing it to Rich."""
    if not text:
        return ""
    if "\x9b" in text:
        text = text.replace("\x9b", "\x1b[")
    # (?<![\x1b0-9;]) prevents matching `;37m` inside `\x1b[1;37m` — the `;`
    # there is preceded by a digit, not a true orphan.
    return _NORM_ORPHAN_RE.sub("", text)


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
    if re.match(r'^\s*\w+\s*=\s*\S', raw) and "==" not in raw and len(stripped.split()) <= 6:
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
    limit = first_width
    for word in words:
        wlen = len(word)
        if cur:
            if cur_vis + 1 + wlen > limit:
                out_lines.append(cur)
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
        # Forwards without dim wrap and without _plain_list update.
        # Callers that need copy-source MUST use write_with_source instead.
        self._log.write(renderable, **kw)

    def write_inline(self, spans) -> None:
        """Forward to the wrapped log with TextSpan content wrapped in dim italic.

        ImageSpans pass through unchanged. Plain text equivalent is appended to
        _plain_list so copy buffer stays consistent.
        """
        from hermes_cli.tui.inline_prose import ImageSpan, TextSpan
        from rich.text import Text as RichText

        wrapped: list[object] = []
        plain_parts: list[str] = []
        for span in spans:
            if isinstance(span, TextSpan):
                new_text = RichText(style="dim italic")
                new_text.append_text(span.text)
                wrapped.append(TextSpan(text=new_text))
                plain_parts.append(span.text.plain)
            elif isinstance(span, ImageSpan):
                wrapped.append(span)
                plain_parts.append(getattr(span, "alt_text", "") or "")
            else:
                wrapped.append(span)
        self._log.write_inline(wrapped)
        self._plain_list.append("".join(plain_parts))

    def __getattr__(self, name: str):
        return getattr(self._log, name)


# ---------------------------------------------------------------------------
# _LineClassifier
# ---------------------------------------------------------------------------

class _LineClassifier:
    """Pure line-type detection for ResponseFlowEngine.process_line().

    Wraps module-level regexes and predicate functions.  Holds no mutable
    state — every method is a pure function of its arguments.
    """

    def is_footnote_def(self, raw: str) -> "tuple[str, str] | None":
        m = _FOOTNOTE_DEF_RE.match(raw)
        if m:
            return m.group(1), m.group(2).strip()
        return None

    def is_footnote_continuation(self, raw: str, footnote_open: bool) -> bool:
        return bool(footnote_open and (raw.startswith("    ") or raw.startswith("\t")))

    def is_citation(self, raw: str) -> "tuple[int, str, str] | None":
        m = _CITE_RE.match(raw.strip())
        if m:
            return int(m.group(1)), m.group(2).strip(), m.group(3)
        return None

    def is_fence_open(self, raw: str) -> "tuple[str, str, int] | None":
        m = _FENCE_OPEN_RE.match(raw.strip())
        if m:
            lang = m.group(2).strip() if m.group(2) else ""
            return lang, m.group(1)[0], len(m.group(1))
        return None

    def is_fence_close(self, raw: str, fence_char: str, fence_depth: int) -> bool:
        m = _FENCE_CLOSE_RE.match(raw.strip())
        return bool(m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_depth)

    def is_indented_code(self, raw: str) -> "str | None":
        m = _INDENTED_CODE_RE.match(raw)
        return m.group(1) if m else None

    def is_block_math_oneline(self, raw: str) -> "str | None":
        stripped = raw.strip()
        m = _BLOCK_MATH_ONELINE_RE.match(stripped) or _BLOCK_MATH_ONELINE_BRACKET_RE.match(stripped)
        return m.group(1) if m else None

    def is_block_math_open(self, raw: str) -> bool:
        return bool(_BLOCK_MATH_OPEN_RE.match(raw.strip()))

    def is_block_math_close(self, raw: str) -> bool:
        return bool(_BLOCK_MATH_CLOSE_RE.match(raw.strip()))

    def is_inline_code_label(self, raw: str) -> "tuple[str, str] | None":
        m = _INLINE_CODE_LABEL_RE.match(raw.strip())
        if m:
            return m.group(1), m.group(2).strip()
        return None

    def is_code_intro_label(self, raw: str) -> bool:
        return _is_code_intro_label(raw)

    def is_horizontal_rule(self, raw: str) -> bool:
        return _is_horizontal_rule(raw)

    def looks_like_source_line(self, raw: str) -> bool:
        return _looks_like_source_line(raw)


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

    _MAX_EMOJI_MOUNTS: int = 50

    def _init_fields(self) -> None:
        """Initialise all app-independent instance fields.

        Called first by __init__ and by ReasoningFlowEngine.__init__ so that
        every field is guaranteed to exist regardless of which subclass is
        constructed.  ReasoningFlowEngine overrides a subset of these after
        calling _init_fields().
        """
        from agent.rich_output import StreamingBlockBuffer
        self._block_buf: "StreamingBlockBuffer" = StreamingBlockBuffer()
        self._state: Literal["NORMAL", "IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE", "IN_MATH"] = "NORMAL"
        self._fence_char: str = "`"
        self._fence_depth: int = 3
        self._active_block: "StreamingCodeBlock | None" = None
        self._math_lines: list[str] = []
        self._math_env: str = ""
        self._math_enabled: bool = True
        self._math_renderer_mode: str = "auto"
        self._math_dpi: int = 150
        self._math_max_rows: int = 12
        self._mermaid_enabled: bool = True
        self._pending_source_line: str | None = None
        self._pending_code_intro: bool = False
        self._prose_section_counter: int = 0
        self._list_cont_indent: str = ""
        self._footnote_defs: dict[str, str] = {}
        self._footnote_order: list[str] = []
        self._footnote_def_open: str | None = None
        self._partial: str = ""
        self._detached: bool = False
        self._emoji_mounts: int = 0
        self._cite_entries: dict[int, tuple[str, str]] = {}
        self._cite_order: list[int] = []
        self._citations_enabled: bool = True
        self._mount_media_callback: "Callable[[str, str], None] | None" = None
        self._emitted_media_urls: set[str] = set()
        self._emoji_registry = None
        self._emoji_images_enabled: bool = True
        self._emitted_emoji_anchors: set[int] = set()
        self._prose_callback: "Callable[[str], None] | None" = None
        self._code_fence_buffer: list[str] = []
        self._clf: _LineClassifier = _LineClassifier()

    def __init__(self, *, panel: "MessagePanel") -> None:
        self._init_fields()
        self._panel = panel
        getter = getattr(type(panel), "current_prose_log", None)
        self._prose_log: "CopyableRichLog" = (
            panel.current_prose_log() if callable(getter) else panel.response_log
        )
        _app = getattr(panel, "app", None)
        self._skin_vars: dict[str, str] = (
            _app.get_css_variables()
            if _app is not None and hasattr(_app, "get_css_variables")
            else {}
        )
        self._pygments_theme: str = self._skin_vars.get("preview-syntax-theme", "monokai")
        self._math_enabled = getattr(_app, "_math_enabled", True)
        self._math_renderer_mode = getattr(_app, "_math_renderer", "auto")
        self._math_dpi = getattr(_app, "_math_dpi", 150)
        self._math_max_rows = getattr(_app, "_math_max_rows", 12)
        self._mermaid_enabled = getattr(_app, "_mermaid_enabled", True)
        self._citations_enabled = getattr(_app, "_citations_enabled", True)
        self._emoji_registry = getattr(_app, "_emoji_registry", None)
        self._emoji_images_enabled = getattr(_app, "_emoji_images_enabled", True)

    def _write_prose(self, rich_text: "Text", plain: str) -> None:
        """Write a prose line and optionally fire the prose callback."""
        self._prose_log.write_with_source(rich_text, plain)
        if self._prose_callback is not None and plain.strip():
            try:
                self._prose_callback(plain)
            except Exception:
                logger.exception("prose callback failed in _write_prose")

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
        if self._detached:
            return
        if "\n" in chunk:
            self._clear_partial_preview()
            self._partial = chunk.rsplit("\n", 1)[1]
        else:
            self._partial += chunk
        if self._partial:
            clean = _ORPHANED_CSI_RE.sub("", self._partial)
            if clean:
                self._route_partial(clean)

    def _route_partial(self, fragment: str) -> None:
        if self._state in ("IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE"):
            if self._active_block is not None:
                self._active_block.feed_partial(fragment)

    def _clear_partial_preview(self) -> None:
        if self._state in ("IN_CODE", "IN_INDENTED_CODE", "IN_SOURCE_LIKE"):
            if self._active_block is not None:
                self._active_block.clear_partial()
        self._partial = ""

    # ------------------------------------------------------------------
    # process_line helpers
    # ------------------------------------------------------------------

    def _handle_footnote(self, raw: str) -> bool:
        """Collect or continue a footnote definition. Returns True if consumed."""
        fn = self._clf.is_footnote_def(raw)
        if fn is not None:
            label, body = fn
            if label not in self._footnote_defs:
                self._footnote_order.append(label)
            self._footnote_defs[label] = body
            self._footnote_def_open = label
            return True
        if self._clf.is_footnote_continuation(raw, self._footnote_def_open is not None):
            self._footnote_defs[self._footnote_def_open] += " " + raw.strip()
            return True
        self._footnote_def_open = None
        return False

    def _handle_citation_line(self, raw: str) -> bool:
        """Collect a citation tag line. Returns True if consumed."""
        cite = self._clf.is_citation(raw)
        if cite is not None:
            _n, title, url = cite
            self._cite_entries[_n] = (title, url)
            if _n not in self._cite_order:
                self._cite_order.append(_n)
            return True
        return False

    def _dispatch_normal_state(self, raw: str, intro_candidate: bool) -> bool:
        """Handle code-detection paths in NORMAL state.

        Returns True when the line is fully consumed (code block opened/emitted,
        pending source resolved, math opened, etc.).  Returns False when no
        code-detection path matched and prose rendering should proceed.
        """
        from agent.rich_output import apply_block_line, apply_inline_markdown
        stripped = raw.strip()

        was_pending_code_intro = self._pending_code_intro
        if was_pending_code_intro:
            self._pending_code_intro = False
            if (
                stripped
                and self._clf.is_fence_open(raw) is None
                and self._clf.is_indented_code(raw) is None
                and not self._clf.looks_like_source_line(raw)
                and not _LIST_PREFIX_RE.match(raw)
                and not stripped.endswith(":")
            ):
                self._flush_code_fence_buffer()
                self._flush_block_buf()
                self._emit_complete_code_block([raw])
                return True
        if intro_candidate:
            self._pending_code_intro = True

        if self._pending_source_line is not None:
            if self._clf.looks_like_source_line(raw):
                self._flush_code_fence_buffer()
                self._flush_block_buf()
                self._state = "IN_SOURCE_LIKE"
                self._list_cont_indent = ""
                self._active_block = self._open_code_block("")
                self._active_block.append_line(self._pending_source_line)
                self._active_block.append_line(raw)
                self._pending_source_line = None
                return True
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
                    self._write_prose(Text.from_ansi(_normalize_ansi_for_render(inline_ansi)), plain)

        # Block math — checked BEFORE fence detection ($$ would match _FENCE_OPEN_RE)
        if self._math_enabled:
            oneline = self._clf.is_block_math_oneline(raw)
            if oneline is not None:
                self._flush_code_fence_buffer()
                self._flush_block_buf()
                self._flush_math_block(oneline)
                return True
            if self._clf.is_block_math_open(raw):
                self._flush_code_fence_buffer()
                self._flush_block_buf()
                self._math_lines = []
                self._math_env = stripped
                self._state = "IN_MATH"
                return True

        fence = self._clf.is_fence_open(raw)
        if fence is not None:
            lang, fchar, fdepth = fence
            self._flush_code_fence_buffer()
            self._flush_block_buf()
            self._state = "IN_CODE"
            self._fence_char = fchar
            self._fence_depth = fdepth
            self._list_cont_indent = ""
            self._active_block = self._open_code_block(lang)
            return True

        indent_content = self._clf.is_indented_code(raw)
        if indent_content is not None:
            self._flush_code_fence_buffer()
            self._flush_block_buf()
            self._state = "IN_INDENTED_CODE"
            self._list_cont_indent = ""
            self._active_block = self._open_code_block("")
            self._active_block.append_line(indent_content)
            return True

        inline_label = self._clf.is_inline_code_label(raw)
        if inline_label is not None:
            value = inline_label[1].strip()
            if value and not stripped.endswith(":"):
                self._flush_code_fence_buffer()
                self._flush_block_buf()
                label = f"{inline_label[0]}:"
                block_ansi = apply_block_line(label)
                inline_ansi = apply_inline_markdown(block_ansi)
                plain = _strip_ansi(inline_ansi)
                self._write_prose(Text.from_ansi(_normalize_ansi_for_render(inline_ansi)), plain)
                self._emit_complete_code_block([value])
                return True

        if self._clf.looks_like_source_line(raw):
            self._pending_source_line = raw
            return True

        return False

    def _handle_unknown_state(self, raw: str) -> bool:
        """Recover from an unknown _state. Logs once and falls through to prose."""
        logger.warning(
            "response_flow: unknown _state=%r; resetting to NORMAL", self._state
        )
        if self._active_block is not None:
            try:
                self._active_block.flush()
            except Exception:
                # flush on an orphaned block may fail if the widget was already removed
                logger.debug(
                    "response_flow: _handle_unknown_state: flush on orphaned block failed",
                    exc_info=True,
                )
        self._state = "NORMAL"
        self._active_block = None
        return False  # caller falls through to NORMAL classification + prose

    def _dispatch_non_normal_state(self, raw: str) -> bool:
        """Handle a line while in a non-NORMAL state.

        Returns True when the line is fully consumed.
        Returns False for IN_INDENTED_CODE/IN_SOURCE_LIKE block-close paths —
        caller must fall through to prose rendering for the closing line.
        """
        if self._state == "IN_CODE":
            if self._active_block is None:
                self._state = "NORMAL"
                return False  # re-classify via A-1 path
            if self._clf.is_fence_close(raw, self._fence_char, self._fence_depth):
                self._active_block.complete(self._skin_vars)
                self._active_block = None
                self._state = "NORMAL"
                return True
            self._active_block.append_line(raw)
            return True

        if self._state == "IN_INDENTED_CODE":
            if self._active_block is None:
                self._state = "NORMAL"
                return False
            if raw == "":
                self._active_block.append_line("")
                return True
            indent_m = self._clf.is_indented_code(raw)
            if indent_m is not None:
                self._active_block.append_line(indent_m)
                return True
            self._active_block.complete(self._skin_vars)
            self._active_block = None
            self._state = "NORMAL"
            return False  # fall through to prose for the closing line

        if self._state == "IN_SOURCE_LIKE":
            if self._active_block is None:
                self._state = "NORMAL"
                return False
            if self._clf.looks_like_source_line(raw):
                self._active_block.append_line(raw)
                return True
            self._active_block.complete(self._skin_vars)
            self._active_block = None
            self._state = "NORMAL"
            return False  # fall through to prose for the closing line

        if self._state == "IN_MATH":
            if self._clf.is_block_math_close(raw):
                self._flush_math_block("\n".join(self._math_lines))
                self._math_lines = []
                self._math_env = ""
                self._state = "NORMAL"
            else:
                self._math_lines.append(raw)
            return True

        return self._handle_unknown_state(raw)

    def _dispatch_prose(self, raw: str, intro_candidate: bool) -> None:
        """Render raw as prose through StreamingBlockBuffer + markdown pipeline."""
        from agent.rich_output import apply_block_line, apply_inline_markdown
        if self._math_enabled:
            raw = self._apply_inline_math(raw)
        block_result = self._block_buf.process_line(raw)
        if block_result is None:
            return  # buffered (setext/table lookahead)
        if _is_horizontal_rule(block_result):
            self._emit_rule()
            return
        list_ci = _detect_list_cont_indent(block_result)
        if list_ci:
            self._list_cont_indent = list_ci
            block_ansi = apply_block_line(_apply_cont_indent(block_result, list_ci))
        else:
            block_ansi = apply_block_line(block_result)
            stripped = block_result.strip()
            if (stripped == ""
                or _HR_RE.match(stripped)
                or _FENCE_OPEN_RE.match(stripped)
                or _LIST_PREFIX_RE.match(block_result)):
                self._list_cont_indent = ""
            elif self._list_cont_indent and not block_result[0:1].isspace():
                self._list_cont_indent = ""
        inline_ansi = apply_inline_markdown(block_ansi)
        self._sync_prose_log()
        plain = _strip_ansi(inline_ansi)
        rich_text = Text.from_ansi(_normalize_ansi_for_render(inline_ansi))
        if not self._write_prose_inline_emojis(rich_text, plain):
            self._commit_prose_line(inline_ansi, plain)
        else:
            self._flush_code_fence_buffer()
        self._pending_code_intro = intro_candidate or _is_code_intro_label(plain)

    def process_line(self, raw: str) -> None:
        """Process one complete line (no trailing newline)."""
        if self._detached:
            return
        if self._state == "NORMAL" and self._mount_media_callback is not None:
            self._scan_media_urls(raw)
        intro_candidate = _is_code_intro_label(raw)
        if self._state != "NORMAL":
            if self._dispatch_non_normal_state(raw):
                return
            # State just fell back to NORMAL on a block close. The closing line
            # itself still needs full NORMAL-state classification — see A-1.
        if self._state == "NORMAL":
            if self._handle_footnote(raw) or (
                self._citations_enabled and self._handle_citation_line(raw)
            ):
                # Handler consumed the footnote/citation. Drain any held pending
                # source line NOW so it appears in prose BEFORE the footnote footer
                # that flush() renders later. Must be inside this branch — draining
                # unconditionally here would clear _pending_source_line before
                # _dispatch_normal_state's source-like lookahead, breaking
                # IN_SOURCE_LIKE detection.
                self._flush_code_fence_buffer()  # drain before footnote footer
                self._drain_pending_source()
                return
            if self._dispatch_normal_state(raw, intro_candidate):
                return
        self._dispatch_prose(raw, intro_candidate)

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
        # Custom emoji are mounted inline inside prose flow. Accept any current
        # image-capable renderer here. Capability preference still comes from
        # kitty_graphics.get_caps(), which already prefers TGP over SIXEL when
        # both are available.
        return cap in (GraphicsCap.TGP, GraphicsCap.SIXEL, GraphicsCap.HALFBLOCK)

    def _extract_emoji_refs(self, text: str) -> "list[str]":
        """Return distinct emoji names found in text that exist in the registry.

        NOTE: Test-only public surface. Production emoji rendering goes through
        `_write_prose_inline_emojis`. Do not call from new production code.
        """
        if (
            self._emoji_registry is None
            or not self._emoji_images_enabled
            or not self._has_image_support()
        ):
            return []
        seen: set[str] = set()
        out: list[str] = []
        for m in _EMOJI_RE.finditer(text):
            name = m.group(1).lower()
            if name not in seen and self._emoji_registry.get(name) is not None:
                seen.add(name)
                out.append(name)
        return out

    def _write_prose_inline_emojis(self, rich_text: "Text", plain: str) -> bool:
        """Write one prose line using InlineProseLog image spans when possible."""
        registry = self._emoji_registry
        prose_log = self._prose_log
        if (
            registry is None
            or not self._emoji_images_enabled
            or not self._has_image_support()
            or not hasattr(prose_log, "write_inline")
        ):
            return False

        from hermes_cli.tui.inline_prose import ImageSpan, TextSpan

        spans: list[object] = []
        cursor = 0
        found_image = False
        for match in _EMOJI_RE.finditer(plain):
            name = match.group(1).lower()
            entry = registry.get(name)
            if entry is None:
                continue
            start, end = match.span()
            if start > cursor:
                spans.append(TextSpan(text=rich_text[cursor:start]))
            image_path = Path(entry.path)
            spans.append(
                ImageSpan(
                    image_path=image_path,
                    cell_width=max(1, int(getattr(entry, "cell_width", 2) or 2)),
                    cell_height=max(1, int(getattr(entry, "cell_height", 1) or 1)),
                    alt_text=plain[start:end],
                    cache_key=f"emoji:{name}:{image_path}",
                )
            )
            cursor = end
            found_image = True

        if not found_image:
            return False

        if cursor < len(plain):
            spans.append(TextSpan(text=rich_text[cursor:]))

        prose_log.write_inline(spans)
        if self._prose_callback is not None and plain.strip():
            try:
                self._prose_callback(plain)
            except Exception:
                logger.exception("prose callback failed in _write_prose_inline_emojis")
        return True

    def _mount_emoji(self, name: str) -> None:
        """Mount an emoji image widget. Safe to call from either event-loop or worker thread.

        NOTE: Test-only public surface — see `_extract_emoji_refs` note.
        """
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
            if self._emoji_mounts >= self._MAX_EMOJI_MOUNTS:
                logger.debug(
                    "ResponseFlowEngine._mount_emoji: cap reached (%d), skipping '%s'",
                    self._MAX_EMOJI_MOUNTS, name,
                )
                return
            self._emoji_mounts += 1
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
                # Panel may be removed between call_from_thread scheduling and execution;
                # treat as a no-op. Log at debug so programming errors are still visible.
                logger.debug(
                    "ResponseFlowEngine._mount_emoji: mount failed for '%s'", name, exc_info=True
                )

        if threading.get_ident() == getattr(app, "_thread_id", None):
            # Already on the event-loop thread (async worker path) — call directly.
            _do_mount()
        else:
            app.call_from_thread(_do_mount)

    def flush(self) -> None:
        """Turn ended — close any open code block; flush StreamingBlockBuffer pending state."""
        if self._detached:
            # Panel is gone; discard any pending partial — no widget to write to
            return
        if self._partial:
            pending = self._partial
            self._clear_partial_preview()
            self.process_line(pending)
        if self._state == "IN_MATH":
            if self._math_lines:
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
        # Orphaned state: _active_block was already cleared by dispatch but
        # _state was not reset.  Reset BEFORE _flush_block_buf below so any
        # state-sensitive buffer logic sees NORMAL.  IN_MATH is handled by the
        # explicit branch above — exclude it here to avoid second-order interference.
        if self._state not in ("NORMAL", "IN_MATH"):
            logger.debug(
                "ResponseFlowEngine.flush: unexpected state=%r with no active block; resetting",
                self._state,
            )
            self._state = "NORMAL"
        # Drain any _block_buf state from process_line(_partial) above so
        # _emit_prose_line starts with an empty buffer (see R-18).
        self._flush_block_buf()
        if self._pending_source_line is not None:
            pending = self._pending_source_line
            self._pending_source_line = None
            self._emit_prose_line(pending)
        # Flush any prose pending in StreamingBlockBuffer (setext, tables)
        self._flush_block_buf()
        self._flush_code_fence_buffer()
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
        self._emoji_mounts = 0

    def _mount_sources_bar(self) -> None:
        """Mount SourcesBar below the panel after the next refresh."""
        from hermes_cli.tui.widgets import SourcesBar
        entries = [(n, *self._cite_entries[n]) for n in self._cite_order]
        panel = self._panel

        def _do_mount() -> None:
            try:
                panel.mount(SourcesBar(entries))
            except Exception:
                logger.warning("_mount_sources_bar: failed to mount SourcesBar", exc_info=True)

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
        """Replace $...$ and $$...$$ spans in a prose line with unicode approximations."""
        if "$" not in line:
            return line

        # $$...$$ inline (within a line, not the full line) — always treat as math
        def replace_double_math(m: re.Match) -> str:  # type: ignore[type-arg]
            return _get_math_renderer().render_unicode(m.group(1))

        line = _INLINE_DOUBLE_MATH_RE.sub(replace_double_math, line)

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
        _app = getattr(self._panel, "app", None)
        if _app is None or not hasattr(_app, "run_worker"):
            # Panel detached / app missing — fall back to synchronous unicode write.
            unicode_repr = _get_math_renderer().render_unicode(latex)
            self._sync_prose_log()
            t = Text(f"  {unicode_repr}  ", style="italic")
            self._prose_log.write_with_source(t, unicode_repr)
            return

        dpi = self._math_dpi
        max_rows = self._math_max_rows
        latex_copy = latex  # avoid closure over mutable

        def _render_worker() -> None:
            path = _get_math_renderer().render_block(latex_copy, dpi=dpi)
            _app2 = getattr(self._panel, "app", None)
            if _app2 is None:
                return  # panel disappeared mid-render; drop result
            if path is None:
                # Fallback: write unicode on the app thread
                unicode_repr = _get_math_renderer().render_unicode(latex_copy)
                _app2.call_from_thread(self._mount_math_unicode, unicode_repr)
            else:
                _app2.call_from_thread(self._mount_math_image, path, max_rows)

        _app.run_worker(_render_worker, thread=True)

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
            logger.warning(
                "ResponseFlowEngine._mount_math_image: mount failed (path=%s)", path, exc_info=True
            )


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

    def _commit_prose_line(self, inline_ansi: str, plain: str) -> None:
        """Write a prose line, buffering numbered-code lines for InlineCodeFence.

        §5.11.2: lines matching ^\\s*\\d{1,3}\\s*|\\s+\\S are buffered.
        When ≥ 2 buffered lines and the next line doesn't match (or paragraph
        break), flush as InlineCodeFence widget. Lines that don't match go
        to normal prose path.
        """
        if _NUMBERED_LINE_RE.match(plain):
            self._code_fence_buffer.append(plain)
        else:
            self._flush_code_fence_buffer()
            self._write_prose(Text.from_ansi(_normalize_ansi_for_render(inline_ansi)), plain)

    def _flush_code_fence_buffer(self) -> None:
        """Flush any buffered numbered-code lines.

        If buffer has ≥ 2 lines → mount InlineCodeFence widget.
        If buffer has < 2 → write to prose log normally.
        """
        buf = self._code_fence_buffer
        if not buf:
            return
        self._code_fence_buffer = []
        if len(buf) >= 2:
            # Mount as InlineCodeFence widget
            fence = InlineCodeFence(lines=buf)
            try:
                self._panel._mount_nonprose_block(fence)
                self._sync_prose_log()
            except Exception:
                logger.debug(
                    "ResponseFlowEngine._flush_code_fence_buffer: InlineCodeFence mount failed;"
                    " falling back to prose (%d lines)",
                    len(buf),
                    exc_info=True,
                )
                # Fallback: write as plain prose
                for line in buf:
                    self._prose_log.write_with_source(Text.from_ansi(line), line)
        else:
            # Single line — write as plain prose
            for line in buf:
                self._prose_log.write_with_source(Text.from_ansi(line), line)

    def _emit_prose_line(self, raw: str) -> None:
        """Render one already-resolved prose line through the full inline pipeline."""
        from agent.rich_output import apply_block_line, apply_inline_markdown
        block_result = self._block_buf.process_line(raw)
        if block_result is None:
            return
        if _is_horizontal_rule(block_result):
            self._emit_rule()
            return
        block_ansi = apply_block_line(block_result)
        inline_ansi = apply_inline_markdown(block_ansi)
        self._sync_prose_log()
        plain = _strip_ansi(inline_ansi)
        rich_text = Text.from_ansi(_normalize_ansi_for_render(inline_ansi))
        if not self._write_prose_inline_emojis(rich_text, plain):
            self._commit_prose_line(inline_ansi, plain)
        else:
            self._flush_code_fence_buffer()

    def _drain_pending_source(self) -> None:
        """Flush any held _pending_source_line as prose. Idempotent."""
        if self._pending_source_line is None:
            return
        pending = self._pending_source_line
        self._pending_source_line = None
        self._emit_prose_line(pending)

    def _emit_rule(self) -> None:
        """Emit a width-bounded horizontal rule to the prose log."""
        self._sync_prose_log()
        rule = _make_rule(self._prose_log)
        self._prose_log.write_with_source(rule, "---")

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
                self._commit_prose_line(inline_ansi, plain)

    def _mount_code_block(self, block: "StreamingCodeBlock") -> None:
        """Mount block into output DOM. Override in subclasses."""
        if not getattr(self._panel, "is_mounted", False):
            logger.debug(
                "ResponseFlowEngine._mount_code_block: panel unmounted, skipping block mount"
            )
            self._detached = True
            return
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
        self._init_fields()
        self._panel = panel  # type: ignore[assignment]
        self._prose_log: _DimRichLogProxy = _DimRichLogProxy(  # type: ignore[assignment]
            panel._reasoning_log, panel._plain_lines
        )
        # Pull skin vars from the owning app so reasoning code blocks + footnote
        # refs honour the active skin (see B-1). Safe even when app is missing in
        # tests — fall back to the previous defaults.
        _app_b1 = getattr(panel, "app", None)
        if _app_b1 is not None and hasattr(_app_b1, "get_css_variables"):
            self._skin_vars = _app_b1.get_css_variables()
        else:
            self._skin_vars = {}
        self._pygments_theme = self._skin_vars.get("preview-syntax-theme", "monokai")
        # Math disabled in reasoning output (Non-Goal per spec)
        self._math_enabled = False
        self._math_renderer_mode = "unicode"
        self._mermaid_enabled = False
        # Citations gated on BOTH app flag AND _reasoning_rich_prose
        _rp = getattr(_app_b1, "_reasoning_rich_prose", True)
        self._citations_enabled = getattr(_app_b1, "_citations_enabled", True) and _rp
        # Emoji gated on _emoji_reasoning
        _rp_emoji = getattr(_app_b1, "_emoji_reasoning", True)
        _app = _app_b1
        self._emoji_registry = getattr(_app, "_emoji_registry", None) if _rp_emoji else None
        self._emoji_images_enabled = getattr(_app, "_emoji_images_enabled", True) and _rp_emoji

    def process_line(self, raw: str) -> None:
        """Override: flush block buffer immediately after every line.

        ResponseFlowEngine keeps one line pending in StreamingBlockBuffer for
        setext/table lookahead, which causes visible lag during streaming and a
        flash in typewriter mode (content disappears from live_line before
        appearing in the log). Flushing after every call eliminates the lag.

        Tradeoff: setext headings (`Heading\\n========`) and pipe tables render
        as their constituent lines (no setext promotion, no table widget). Both
        are rare in reasoning output. Pinned by
        test_reasoning_engine_setext_renders_as_two_prose_lines.
        """
        super().process_line(raw)
        self._flush_block_buf()

    def _sync_prose_log(self) -> None:
        """No-op — proxy is stable; ReasoningPanel has one log section."""
        pass

    def _mount_code_block(self, block: "StreamingCodeBlock") -> None:
        """Mount dim code block inside ReasoningPanel, above the live line."""
        if not getattr(self._panel, "is_mounted", False):
            logger.debug(
                "ReasoningFlowEngine._mount_code_block: panel unmounted, skipping block mount"
            )
            self._detached = True
            return
        block.add_class("reasoning-code-block")
        self._panel.mount(block, before=self._panel._live_line)

    def _render_footnote_section(self) -> None:
        _app = getattr(self._panel, "app", None)
        if not getattr(_app, "_reasoning_rich_prose", True):
            return
        super()._render_footnote_section()

    def _emit_rule(self) -> None:
        super()._emit_rule()  # parent uses write_with_source which the proxy handles
