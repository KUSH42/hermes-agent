"""Result parsers — v2 (tui-tool-panel-v2-spec.md §5.6) and v4 (sub-spec C).

v2 parsers: `shell_result(result: str) -> ResultSummary` (mutable, backwards-compat).
v4 parsers: `parse(ctx: ParseContext) -> ResultSummaryV4` (pure, frozen, all 8 categories).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from hermes_cli.tui.tool_category import ToolSpec


# ---------------------------------------------------------------------------
# ResultSummary
# ---------------------------------------------------------------------------


@dataclass
class ResultSummary:
    """Normalized tool-result metadata for FooterPane rendering.

    All fields are optional — parsers populate what they can.
    FooterPane only renders non-None / non-empty fields.
    """

    exit_code: int | None = None
    stat_badges: list[str] = field(default_factory=list)
    stderr_tail: str = ""
    retry_hint: str | None = None
    is_error: bool = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_EXIT_RE = re.compile(r"exit(?:\s+code)?[:\s]+(\d+)", re.IGNORECASE)
_DIFF_PLUS_RE = re.compile(r"\+(\d+)")
_DIFF_MINUS_RE = re.compile(r"(?<!\+)-(\d+)")
_HTTP_STATUS_RE = re.compile(r"\b([45]\d\d)\b")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]?B)\b", re.IGNORECASE)


def _extract_exit_code(result: str) -> int | None:
    m = _EXIT_RE.search(result[:500])
    return int(m.group(1)) if m else None


def _last_nonempty_line(result: str, max_chars: int = 80) -> str:
    for line in reversed(result.strip().splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:max_chars]
    return ""


# ---------------------------------------------------------------------------
# Per-category parsers
# ---------------------------------------------------------------------------


def shell_result(result: str) -> ResultSummary:
    """Parser for SHELL category (terminal, bash)."""
    exit_code = _extract_exit_code(result)
    is_error = exit_code is not None and exit_code != 0
    stderr_tail = _last_nonempty_line(result) if is_error else ""
    return ResultSummary(
        exit_code=exit_code,
        stat_badges=[],
        stderr_tail=stderr_tail,
        is_error=is_error,
    )


def code_result(result: str) -> ResultSummary:
    """Parser for CODE category (execute_code)."""
    return shell_result(result)


def file_result(result: str) -> ResultSummary:
    """Parser for FILE category (read_file, write_file, patch, etc.)."""
    badges: list[str] = []
    plus_m = _DIFF_PLUS_RE.search(result)
    minus_m = _DIFF_MINUS_RE.search(result)
    if plus_m:
        badges.append(f"+{plus_m.group(1)}")
    if minus_m:
        badges.append(f"-{minus_m.group(1)}")
    lines = [l for l in result.strip().splitlines() if l.strip()]
    if not badges and lines:
        badges.append(f"{len(lines)} lines")
    is_error = "error" in result.lower()[:200] or "failed" in result.lower()[:200]
    return ResultSummary(stat_badges=badges, is_error=is_error)


def search_result(result: str) -> ResultSummary:
    """Parser for SEARCH category (web_search, grep, glob)."""
    lines = [l for l in result.strip().splitlines() if l.strip()]
    count = len(lines)
    badges = [f"{count} matches"] if count else []
    return ResultSummary(stat_badges=badges)


def web_result(result: str) -> ResultSummary:
    """Parser for WEB category (web_extract, fetch, http)."""
    badges: list[str] = []
    head = result[:300]
    # HTTP status badge
    status_m = re.search(r"\b(\d{3})\s+([A-Z][A-Z]+)\b", head)
    if status_m:
        badges.append(f"{status_m.group(1)} {status_m.group(2)}")
    # Size badge
    size_m = _SIZE_RE.search(head)
    if size_m:
        badges.append(f"{size_m.group(1)}{size_m.group(2).upper()}")
    is_error = bool(_HTTP_STATUS_RE.search(head))
    return ResultSummary(stat_badges=badges, is_error=is_error)


def agent_result(result: str) -> ResultSummary:
    """Parser for AGENT category (think, plan, delegate)."""
    return ResultSummary()


def generic_result(result: str) -> ResultSummary:
    """Fallback parser for UNKNOWN category."""
    is_error = (
        "error" in result.lower()[:200]
        or "exception" in result.lower()[:200]
        or "traceback" in result.lower()[:200]
    )
    return ResultSummary(is_error=is_error)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_PARSERS: dict[str, object] = {
    "shell_result":   shell_result,
    "code_result":    code_result,
    "file_result":    file_result,
    "search_result":  search_result,
    "web_result":     web_result,
    "agent_result":   agent_result,
    "generic_result": generic_result,
}


def get_parser(name: str):
    """Return parser function by name; falls back to generic_result."""
    return _PARSERS.get(name, generic_result)


# ===========================================================================
# v4 schema (sub-spec C) — frozen dataclasses, pure parsers
# ===========================================================================

ChipKind = Literal["diff+", "diff-", "bytes", "count", "status", "exit", "mcp-source", "mcp-error"]
ChipTone = Literal["success", "warning", "error", "neutral", "accent"]
ActionKind = Literal[
    "copy_err", "retry", "edit_cmd", "open_first", "copy_paths",
    "copy_body", "copy_json", "open_url", "reconnect",
]
ArtifactKind = Literal["file", "url", "image"]

_PAYLOAD_CAP = 65536  # 64 KiB
_ARTIFACT_CAP = 5        # legacy alias
_ARTIFACT_DISPLAY_CAP = 5  # B3: render-time display cap; parse stores ALL


@dataclass(frozen=True, slots=True)
class Chip:
    text: str
    kind: ChipKind
    tone: ChipTone = "neutral"
    remediation: str | None = None  # A2: hint shown in footer for error chips


@dataclass(frozen=True, slots=True)
class Action:
    label: str
    hotkey: str
    kind: ActionKind
    payload: str | None
    payload_truncated: bool = False


@dataclass(frozen=True, slots=True)
class Artifact:
    label: str
    path_or_url: str
    kind: ArtifactKind


@dataclass(frozen=True, slots=True)
class ResultSummaryV4:
    primary: str | None
    exit_code: int | None
    chips: tuple[Chip, ...]
    stderr_tail: str
    actions: tuple[Action, ...]
    artifacts: tuple[Artifact, ...]
    is_error: bool
    error_kind: str | None = None
    artifacts_truncated: bool = False  # B3: True when artifacts > _ARTIFACT_DISPLAY_CAP


# ---------------------------------------------------------------------------
# v4 context structs
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ToolStart:
    name: str
    args: dict
    cwd: str | None = None


@dataclass(frozen=True, slots=True)
class ToolComplete:
    name: str
    raw_result: object  # str | dict
    exit_code: int | None = None
    is_error: bool = False
    error_kind: str | None = None
    duration_ms: float | None = None


@dataclass(frozen=True)
class ParseContext:
    complete: ToolComplete
    start: ToolStart
    spec: "ToolSpec"


# ---------------------------------------------------------------------------
# v4 shared helpers
# ---------------------------------------------------------------------------

def _humanize_bytes(b: int) -> str:
    if b < 1024:
        return f"{b}b"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f}kb"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f}mb"
    return f"{b / 1024 ** 3:.1f}gb"


def _last_line_v4(text: str, max_len: int = 80) -> str:
    for line in reversed(str(text).strip().splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:max_len]
    return ""


_STDERR_CAP = 300


def _last_n_chars_v4(text: str, n: int = _STDERR_CAP) -> str:
    """Return last N chars of stripped text, preserving internal newlines."""
    stripped = str(text).strip()
    return stripped[-n:] if len(stripped) > n else stripped


def _raw_str(raw) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)


def _truncate_payload(text: str) -> tuple[str, bool]:
    if len(text) > _PAYLOAD_CAP:
        return text[:_PAYLOAD_CAP], True
    return text, False


def _make_copy_body(raw_result) -> Action:
    text = _raw_str(raw_result)
    payload, truncated = _truncate_payload(text)
    return Action("copy body", "c", "copy_body", payload, truncated)


def _make_copy_err(stderr_tail: str, raw_result=None) -> Action:
    payload = stderr_tail or _last_line_v4(_raw_str(raw_result or ""))
    payload, truncated = _truncate_payload(payload)
    return Action("copy err", "e", "copy_err", payload, truncated)


def _make_action(label: str, hotkey: str, kind: ActionKind,
                 payload: str | None = None, truncated: bool = False) -> Action:
    return Action(label, hotkey, kind, payload, truncated)


# ---------------------------------------------------------------------------
# v4 file_result
# ---------------------------------------------------------------------------

def _count_diff_hunks(text: str) -> tuple[int, int]:
    additions = deletions = 0
    for line in text.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            additions += 1
        elif line.startswith('-') and not line.startswith('---'):
            deletions += 1
    return additions, deletions


def file_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    is_error = ctx.complete.is_error
    error_kind = ctx.complete.error_kind
    path_arg = ctx.start.args.get("path") or ctx.start.args.get("file_path") or ""
    cwd = ctx.start.cwd or os.getcwd()
    is_write = ctx.spec.primary_result not in ("lines", "bytes")

    if is_error:
        stderr_tail = _last_n_chars_v4(raw)
        return ResultSummaryV4(
            primary="✗ error", exit_code=None, chips=(),
            stderr_tail=stderr_tail, actions=(_make_copy_err(stderr_tail, raw),),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    artifacts: tuple[Artifact, ...] = ()
    if path_arg:
        abs_path = path_arg if os.path.isabs(path_arg) else os.path.join(cwd, path_arg)
        artifacts = (Artifact(label=os.path.basename(abs_path), path_or_url=abs_path, kind="file"),)

    if is_write:
        additions, deletions = _count_diff_hunks(raw)
        if additions == 0 and deletions == 0:
            # Check for "no changes" indicators
            if not raw.strip() or "no change" in raw.lower() or "unchanged" in raw.lower():
                return ResultSummaryV4(
                    primary="✓ no changes", exit_code=None, chips=(),
                    stderr_tail="", actions=(_make_action("open first", "o", "open_first"),),
                    artifacts=artifacts, is_error=False,
                )
            # Fallback: count written lines
            n = len([l for l in raw.splitlines() if l.strip()])
            # C5: suppress count chip when n <= 1 (uninformative for short responses)
            count_chips: tuple = (Chip(f"{n}", "count", "neutral"),) if n > 1 else ()
            return ResultSummaryV4(
                primary=f"✓ wrote {n} lines", exit_code=None,
                chips=count_chips,
                stderr_tail="", actions=(_make_action("open first", "o", "open_first"),),
                artifacts=artifacts, is_error=False,
            )
        chips: list[Chip] = []
        if additions:
            chips.append(Chip(f"+{additions}", "diff+", "success"))
        if deletions:
            chips.append(Chip(f"-{deletions}", "diff-", "warning"))
        return ResultSummaryV4(
            primary=f"✓ +{additions} -{deletions}", exit_code=None,
            chips=tuple(chips), stderr_tail="",
            actions=(_make_action("open first", "o", "open_first"),),
            artifacts=artifacts, is_error=False,
        )
    else:
        # Read: bytes
        size = len(raw.encode("utf-8", errors="replace"))
        size_str = _humanize_bytes(size)
        copy_body = _make_copy_body(raw)
        return ResultSummaryV4(
            primary=f"✓ {size_str}", exit_code=None,
            chips=(Chip(size_str, "bytes", "neutral"),),
            stderr_tail="",
            actions=(_make_action("open first", "o", "open_first"), copy_body),
            artifacts=artifacts, is_error=False,
        )


# ---------------------------------------------------------------------------
# v4 shell_result
# ---------------------------------------------------------------------------

def _count_nonempty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


# C2: shell remediation hints
_SHELL_REMEDIATIONS: dict[str, str | None] = {
    "timeout": "increase timeout_sec parameter",
    "signal":  "process was killed — check memory or resource limits",
    "auth":    "check file permissions or run with sudo",
    "exit":    None,  # generic — no hint
}


def shell_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    exit_code = ctx.complete.exit_code
    is_error = ctx.complete.is_error or (exit_code is not None and exit_code != 0)
    error_kind = ctx.complete.error_kind
    cmd = str(ctx.start.args.get("command") or ctx.start.args.get("cmd") or "")
    stderr_tail = _last_n_chars_v4(raw) if is_error else ""

    # C1: detect timeout/signal error kinds from exit code and output content
    if is_error and error_kind is None:
        raw_lower = raw.lower()
        if exit_code == 124 or "timed out" in raw_lower or "timeout expired" in raw_lower:
            error_kind = "timeout"
        elif exit_code in (137, 143) or any(s in raw_lower for s in ("killed", "sigkill", "sigterm")):
            error_kind = "signal"

    # C2: determine remediation hint
    remediation: str | None = None
    if is_error:
        if exit_code == 127:
            remediation = "command not found — check PATH"
        elif error_kind in _SHELL_REMEDIATIONS:
            remediation = _SHELL_REMEDIATIONS[error_kind]

    if error_kind == "timeout":
        chips = (Chip("timeout", "exit", "error", remediation=remediation),)
        return ResultSummaryV4(
            primary="✗ timeout", exit_code=exit_code,
            chips=chips,
            stderr_tail=stderr_tail,
            actions=(
                _make_copy_err(stderr_tail, raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", cmd),
            ),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    if is_error:
        code_str = str(exit_code) if exit_code is not None else "?"
        chips = (Chip(f"exit {code_str}", "exit", "error", remediation=remediation),)
        return ResultSummaryV4(
            primary=f"✗ exit {code_str}", exit_code=exit_code,
            chips=chips,
            stderr_tail=stderr_tail,
            actions=(
                _make_copy_err(stderr_tail, raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", cmd),
            ),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    n = _count_nonempty_lines(raw)
    copy_body = _make_copy_body(raw)
    return ResultSummaryV4(
        primary=f"✓ {n} lines", exit_code=exit_code,
        chips=(), stderr_tail="",
        actions=(copy_body,),
        artifacts=(), is_error=False,
    )


# ---------------------------------------------------------------------------
# v4 code_result
# ---------------------------------------------------------------------------

_MEDIA_LINE_RE_V4 = re.compile(r'^MEDIA:\s*(.+)$', re.MULTILINE | re.IGNORECASE)
_IMAGE_EXTS_V4 = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'})


def _extract_media_artifacts(raw: str) -> tuple[Artifact, ...]:
    """Extract ALL media artifacts (no cap — caller handles B3 truncation)."""
    arts: list[Artifact] = []
    for m in _MEDIA_LINE_RE_V4.finditer(raw):
        path = m.group(1).strip()
        ext = os.path.splitext(path)[1].lower()
        kind: ArtifactKind = "image" if ext in _IMAGE_EXTS_V4 else "file"
        arts.append(Artifact(label=os.path.basename(path), path_or_url=path, kind=kind))
    return tuple(arts)


# C2: code remediation hints
_CODE_REMEDIATIONS: dict[str, str | None] = {
    "timeout": "increase execution timeout in config",
    "signal":  "script was killed — check for infinite loops or memory use",
}


def code_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    exit_code = ctx.complete.exit_code
    is_error = ctx.complete.is_error or (exit_code is not None and exit_code != 0)
    error_kind = ctx.complete.error_kind
    code_text = str(ctx.start.args.get("code") or "")
    stderr_tail = _last_n_chars_v4(raw) if is_error else ""
    artifacts = _extract_media_artifacts(raw)
    artifacts_truncated = len(artifacts) > _ARTIFACT_DISPLAY_CAP  # B3

    # C1: detect timeout/signal error kinds from exit code and output content
    if is_error and error_kind is None:
        raw_lower = raw.lower()
        if exit_code == 124 or "timed out" in raw_lower or "timeout expired" in raw_lower:
            error_kind = "timeout"
        elif exit_code in (137, 143) or any(s in raw_lower for s in ("killed", "sigkill", "sigterm")):
            error_kind = "signal"

    # C2: determine remediation hint
    code_remediation: str | None = None
    if is_error:
        if "ModuleNotFoundError" in raw or "ImportError" in raw:
            code_remediation = "install missing package via pip"
        elif error_kind in _CODE_REMEDIATIONS:
            code_remediation = _CODE_REMEDIATIONS[error_kind]

    if error_kind == "timeout" or is_error:
        code_str = str(exit_code) if exit_code is not None else "?"
        primary = "✗ timeout" if error_kind == "timeout" else f"✗ exit {code_str}"
        return ResultSummaryV4(
            primary=primary, exit_code=exit_code,
            chips=(Chip(primary[2:], "exit", "error", remediation=code_remediation),),
            stderr_tail=stderr_tail,
            actions=(
                _make_copy_err(stderr_tail, raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", code_text),
            ),
            artifacts=artifacts, is_error=True, error_kind=error_kind,
            artifacts_truncated=artifacts_truncated,
        )

    n = _count_nonempty_lines(raw)
    dur = ctx.complete.duration_ms
    if dur is not None:
        primary = f"✓ {int(dur)}ms · stdout {n} lines"
    else:
        primary = f"✓ {n} lines"
    return ResultSummaryV4(
        primary=primary, exit_code=exit_code, chips=(),
        stderr_tail="", actions=(_make_copy_body(raw),),
        artifacts=artifacts, is_error=False,
        artifacts_truncated=artifacts_truncated,
    )


# ---------------------------------------------------------------------------
# v4 search_result
# ---------------------------------------------------------------------------

_SEARCH_FILE_RE = re.compile(r'^([\w./_-]+\.[\w]+|/[\w./_-]+)')
_URL_RE = re.compile(r'^https?://', re.IGNORECASE)


def _extract_search_artifacts(result: str) -> tuple[Artifact, ...]:
    """Extract ALL search artifacts (no cap — caller handles B3 truncation)."""
    arts: list[Artifact] = []
    seen: set[str] = set()
    for line in result.splitlines():
        # URL result lines
        stripped = line.strip()
        if _URL_RE.match(stripped):
            url = stripped.split()[0]
            if url not in seen:
                try:
                    from urllib.parse import urlparse
                    host = urlparse(url).hostname or url[:40]
                except Exception:
                    host = url[:40]
                arts.append(Artifact(label=host, path_or_url=url, kind="url"))
                seen.add(url)
        else:
            colon_idx = line.find(':')
            if colon_idx > 0:
                candidate = line[:colon_idx]
                if _SEARCH_FILE_RE.match(candidate) and candidate not in seen:
                    arts.append(Artifact(
                        label=os.path.basename(candidate),
                        path_or_url=candidate, kind="file",
                    ))
                    seen.add(candidate)
    return tuple(arts)


def _count_distinct_files(artifacts: tuple[Artifact, ...]) -> int:
    return sum(1 for a in artifacts if a.kind == "file")


def search_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    is_error = ctx.complete.is_error

    if is_error:
        return ResultSummaryV4(
            primary="✗ error", exit_code=None, chips=(),
            stderr_tail=_last_n_chars_v4(raw),
            actions=(_make_copy_err("", raw),),
            artifacts=(), is_error=True, error_kind=ctx.complete.error_kind,
        )

    lines = [l for l in raw.splitlines() if l.strip()]
    # For web_search JSON responses, count actual result objects not raw lines
    try:
        import json as _json
        _parsed = _json.loads(raw)
        _web = _parsed.get("data", {}).get("web", [])
        match_count = len(_web) if isinstance(_web, list) else len(lines)
    except Exception:
        match_count = len(lines)
    artifacts = _extract_search_artifacts(raw)
    artifacts_truncated = len(artifacts) > _ARTIFACT_DISPLAY_CAP  # B3
    file_count = _count_distinct_files(artifacts)
    has_urls = any(a.kind == "url" for a in artifacts)

    if has_urls:
        primary = f"✓ {match_count} results"
        chips = (Chip(f"{match_count} results", "count", "neutral"),)
    elif file_count > 0:
        primary = f"✓ {match_count} matches · {file_count} files"
        chips = (Chip(f"{match_count} matches", "count", "neutral"),)
    else:
        primary = f"✓ {match_count} matches"
        chips = () if match_count == 0 else (Chip(f"{match_count} matches", "count", "neutral"),)

    query = str(ctx.start.args.get("query") or ctx.start.args.get("pattern") or "")
    file_paths = "\n".join(a.path_or_url for a in artifacts if a.kind == "file")
    actions: list[Action] = []
    if artifacts:
        actions.append(_make_action("open first", "o", "open_first"))
    if file_paths:
        actions.append(_make_action("copy paths", "p", "copy_paths", file_paths))
    if query:
        actions.append(_make_action("edit cmd", "e", "edit_cmd", query))

    return ResultSummaryV4(
        primary=primary, exit_code=None, chips=chips,
        stderr_tail="", actions=tuple(actions),
        artifacts=artifacts, is_error=False,
        artifacts_truncated=artifacts_truncated,
    )


# ---------------------------------------------------------------------------
# v4 web_result
# ---------------------------------------------------------------------------

_HTTP_STATUS_LINE_RE = re.compile(r'HTTP/\d(?:\.\d)?\s+(\d{3})\s+(.+?)$', re.MULTILINE)
_CONTENT_LENGTH_RE = re.compile(r'Content-Length:\s*(\d+)', re.MULTILINE | re.IGNORECASE)


def _parse_http_response(raw) -> tuple[int | None, str | None, int | None]:
    if isinstance(raw, dict):
        code = raw.get("status_code") or raw.get("status")
        reason = raw.get("reason", "")
        length = raw.get("content_length")
        # C4: detect redirect from location/redirect_url fields when no status code
        if code is None and (raw.get("redirect_url") or raw.get("location")):
            code = 302
            reason = "Found"
        return (int(code) if code else None, str(reason) if reason else None,
                int(length) if length else None)
    text = str(raw)
    sm = _HTTP_STATUS_LINE_RE.search(text)
    lm = _CONTENT_LENGTH_RE.search(text)
    code = int(sm.group(1)) if sm else None
    reason = sm.group(2).strip() if sm else None
    length = int(lm.group(1)) if lm else len(text.encode("utf-8", errors="replace"))
    if code is None:
        # Fallback for bare "200 OK" patterns
        fb = re.search(r'\b(\d{3})\s+([A-Z][A-Za-z ]+)', text[:300])
        if fb:
            code = int(fb.group(1))
            reason = fb.group(2).strip()
    return code, reason, length


def web_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = ctx.complete.raw_result
    is_error = ctx.complete.is_error
    error_kind = ctx.complete.error_kind
    url = str(ctx.start.args.get("url") or "")

    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or url[:40]
    except Exception:
        host = url[:40]

    artifacts = (Artifact(label=host or url[:40], path_or_url=url, kind="url"),) if url else ()

    if error_kind == "timeout":
        return ResultSummaryV4(
            primary="✗ timeout",
            exit_code=None, chips=(Chip("timeout", "status", "error"),),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", url),
            ),
            artifacts=artifacts, is_error=True, error_kind=error_kind,
        )

    if error_kind == "auth":
        code, _, _ = _parse_http_response(raw)
        code_str = f" · {code}" if code else ""
        return ResultSummaryV4(
            primary=f"✗ auth{code_str}", exit_code=code,
            chips=(Chip("auth", "status", "error"),),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", url),
            ),
            artifacts=artifacts, is_error=True, error_kind=error_kind,
        )

    code, reason, length = _parse_http_response(raw)
    size_str = _humanize_bytes(length or 0)
    is_http_error = code is not None and code >= 400

    if is_error or is_http_error:
        display_code = f"{code}" if code else "?"
        display_reason = f" {reason}" if reason else ""
        primary = f"✗ {display_code}{display_reason}"
        return ResultSummaryV4(
            primary=primary, exit_code=code,
            chips=(Chip(f"{display_code}{display_reason}".strip(), "status", "error"),),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("retry", "r", "retry"),
                _make_action("edit cmd", "e", "edit_cmd", url),
            ),
            artifacts=artifacts, is_error=True, error_kind=error_kind,
        )

    # C1: when code is None (no HTTP status detected), don't show misleading "?"
    if code is None:
        primary = f"✓ {size_str}"
        return ResultSummaryV4(
            primary=primary, exit_code=None,
            chips=(Chip(size_str, "bytes", "neutral"),),
            stderr_tail="",
            actions=(
                _make_action("open url", "o", "open_url"),
                _make_copy_body(raw),
            ),
            artifacts=artifacts, is_error=False,
        )

    display_code = f"{code}"
    display_reason = f" {reason}" if reason else ""
    primary = f"✓ {display_code}{display_reason} · {size_str}"
    # B5: 3xx redirects use warning tone; 2xx use success; else neutral
    if code < 300:
        tone: ChipTone = "success"
    elif code < 400:
        tone = "warning"  # B5: 3xx redirect
    else:
        tone = "neutral"
    return ResultSummaryV4(
        primary=primary, exit_code=code,
        chips=(
            Chip(f"{display_code}{display_reason}".strip(), "status", tone),
            Chip(size_str, "bytes", "neutral"),
        ),
        stderr_tail="",
        actions=(
            _make_action("open url", "o", "open_url"),
            _make_copy_body(raw),
        ),
        artifacts=artifacts, is_error=False,
    )


# ---------------------------------------------------------------------------
# v4 agent_result
# ---------------------------------------------------------------------------

def agent_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    if ctx.complete.is_error:
        return ResultSummaryV4(
            primary="✗ error", exit_code=None, chips=(),
            stderr_tail=_last_n_chars_v4(raw),
            actions=(_make_copy_err("", raw),),
            artifacts=(), is_error=True, error_kind=ctx.complete.error_kind,
        )
    # C3: include copy_body action so [c] copy works in footer
    return ResultSummaryV4(
        primary="✓ done", exit_code=None, chips=(),
        stderr_tail="", actions=(_make_copy_body(raw),), artifacts=(), is_error=False,
    )


# ---------------------------------------------------------------------------
# v4 mcp_result
# ---------------------------------------------------------------------------

def _mcp_server_name(ctx: ParseContext) -> str:
    prov = getattr(ctx.spec, "provenance", None) or ""
    if prov.startswith("mcp:"):
        return prov[4:]
    # Fallback: parse tool name mcp__{server}__{tool}
    name = ctx.complete.name or ""
    parts = name.split("__")
    if len(parts) >= 3 and parts[0] == "mcp":
        return parts[1]
    return "?"


def mcp_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = ctx.complete.raw_result
    is_error = ctx.complete.is_error
    error_kind = ctx.complete.error_kind
    server = _mcp_server_name(ctx)

    content, json_is_error = _parse_mcp_content(raw)
    is_error = is_error or json_is_error

    source_chip = Chip(f"mcp:{server}", "mcp-source", "accent")

    if error_kind == "disconnect":
        return ResultSummaryV4(
            primary=f"✗ mcp · disconnected · {server}",
            exit_code=None,
            chips=(
                source_chip,
                Chip("mcp · disconnected", "mcp-error", "error",
                     remediation=f"restart {server} or check server logs"),
            ),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("reconnect", "R", "reconnect"),
            ),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    if error_kind == "auth":
        return ResultSummaryV4(
            primary=f"✗ mcp · auth · {server}",
            exit_code=None,
            chips=(
                source_chip,
                Chip("mcp · auth", "mcp-error", "error",
                     remediation=f"re-authenticate {server} with /mcp auth"),
            ),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("reconnect", "R", "reconnect"),
            ),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    if error_kind == "timeout" or is_error:
        err_label = f"mcp · {error_kind}" if error_kind else "mcp · error"
        remediation = _MCP_REMEDIATIONS.get(error_kind or "", None)
        return ResultSummaryV4(
            primary=f"✗ {err_label} · {server}",
            exit_code=None,
            chips=(source_chip, Chip(err_label, "mcp-error", "error", remediation=remediation)),
            stderr_tail="",
            actions=(
                _make_copy_err("", raw),
                _make_action("retry", "r", "retry"),
            ),
            artifacts=(), is_error=True, error_kind=error_kind,
        )

    artifacts = _extract_mcp_artifacts(content)
    artifacts_truncated = len(artifacts) > _ARTIFACT_DISPLAY_CAP  # B3
    n = len(content)
    if n == 0:
        primary = "✓ empty"
    elif n == 1:
        primary = "✓ done"
    else:
        primary = f"✓ {n} results"

    chips: list[Chip] = []
    if n >= 2:
        chips.append(Chip(f"{n} results", "count", "neutral"))
    chips.append(source_chip)

    raw_str_v = _raw_str(raw)
    raw_payload, truncated = _truncate_payload(raw_str_v)
    actions: list[Action] = [Action("copy json", "j", "copy_json", raw_payload, truncated)]
    if artifacts:
        actions.append(_make_action("open first", "o", "open_first"))
    file_paths = "\n".join(a.path_or_url for a in artifacts if a.kind == "file")
    if len([a for a in artifacts if a.kind == "file"]) >= 2:
        actions.append(_make_action("copy paths", "p", "copy_paths", file_paths))

    return ResultSummaryV4(
        primary=primary, exit_code=None, chips=tuple(chips),
        stderr_tail="", actions=tuple(actions),
        artifacts=artifacts, is_error=False,
        artifacts_truncated=artifacts_truncated,
    )


def _parse_mcp_content(raw) -> tuple[list, bool]:
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(str(raw))
        except Exception:
            return [{"type": "text", "text": str(raw)}], False
    is_err = bool(data.get("isError", False))
    content = data.get("content", [])
    if not isinstance(content, list):
        content = []
    return content, is_err


def _extract_mcp_artifacts(content: list) -> tuple[Artifact, ...]:
    """Extract ALL artifacts from MCP content (no cap — caller handles B3 truncation)."""
    arts: list[Artifact] = []
    for i, item in enumerate(content):
        if not isinstance(item, dict):
            continue
        kind_str = item.get("type", "")
        if kind_str == "resource":
            resource = item.get("resource", {})
            uri = resource.get("uri", "")
            if uri:
                arts.append(_uri_to_artifact(uri, i))
        elif kind_str == "image":
            mime = item.get("mimeType", "image/png")
            data_b64 = item.get("data", "")
            data_uri = f"data:{mime};base64,{data_b64[:50]}…" if data_b64 else ""
            arts.append(Artifact(label=f"inline image {i}", path_or_url=data_uri, kind="image"))
        elif kind_str == "file":
            resource = item.get("resource", {})
            uri = resource.get("uri", "")
            if uri:
                arts.append(_uri_to_artifact(uri, i))
    return tuple(arts)


def _uri_to_artifact(uri: str, idx: int) -> Artifact:
    if uri.startswith("file://"):
        path = uri[7:]
        return Artifact(label=os.path.basename(path) or path, path_or_url=path, kind="file")
    if uri.startswith("http://") or uri.startswith("https://"):
        try:
            from urllib.parse import urlparse
            host = urlparse(uri).hostname or uri[:40]
        except Exception:
            host = uri[:40]
        return Artifact(label=host, path_or_url=uri, kind="url")
    if uri.startswith("data:image/"):
        return Artifact(label=f"inline image {idx}", path_or_url=uri, kind="image")
    return Artifact(label=os.path.basename(uri) or uri, path_or_url=uri, kind="file")


# ---------------------------------------------------------------------------
# v4 generic_result
# ---------------------------------------------------------------------------

def generic_result_v4(ctx: ParseContext) -> ResultSummaryV4:
    raw = _raw_str(ctx.complete.raw_result)
    is_error = ctx.complete.is_error
    if is_error:
        return ResultSummaryV4(
            primary="✗ error", exit_code=None, chips=(),
            stderr_tail=_last_n_chars_v4(raw),
            actions=(_make_copy_err("", raw),),
            artifacts=(), is_error=True, error_kind=ctx.complete.error_kind,
        )
    n = _count_nonempty_lines(raw)
    if n == 0:
        primary = "✓ done"
    elif n == 1:
        primary = "✓ 1 line"
    else:
        primary = f"✓ {n} lines"
    return ResultSummaryV4(
        primary=primary, exit_code=None, chips=(),
        stderr_tail="", actions=(_make_copy_body(raw),),
        artifacts=(), is_error=False,
    )


# ---------------------------------------------------------------------------
# v4 error display helpers (A1/E1)
# ---------------------------------------------------------------------------

_ERROR_DISPLAY: dict[str, tuple[str, str, str, str]] = {
    # kind:       (nerdfont,  emoji,  ascii,   css_var)
    "timeout":  ("\U000f0513", "⏳",   "[T]",  "error-timeout"),
    "exit":     ("\U000f0159", "💢",   "[X]",  "error-critical"),
    "signal":   ("\U000f140b", "⚡",   "[K]",  "error-critical"),
    "auth":     ("\U000f033e", "🔑",   "[A]",  "error-auth"),
    "network":  ("\U000f092e", "📡",   "[W]",  "error-network"),
    "parse":    ("\U000f02fd", "❓",   "[?]",  "error-network"),
}
_MODE_IDX: dict[str, int] = {"nerdfont": 0, "emoji": 1, "ascii": 2}

_MCP_REMEDIATIONS: dict[str, str] = {
    "timeout": "increase timeout or check server load",
    "parse":   "check server output — invalid JSON response",
    "signal":  "server may have crashed — check logs",
}


def _error_kind_display(kind: str, detail: str, icon_mode: str) -> tuple[str, str, str]:
    """Return (icon, label, css_var_name) for an error kind.

    label = detail passthrough (already-formatted string like "exit 1").
    css_var_name: key for app.get_css_variables() — no $ prefix.
    """
    entry = _ERROR_DISPLAY.get(kind, _ERROR_DISPLAY["network"])
    icon = entry[_MODE_IDX.get(icon_mode, 2)]
    return (icon, detail, entry[3])


# ---------------------------------------------------------------------------
# v4 dispatch
# ---------------------------------------------------------------------------

_V4_PARSERS: dict = {}  # populated after imports resolve


def _get_v4_parsers() -> dict:
    if not _V4_PARSERS:
        _V4_PARSERS.update({
            "file":    file_result_v4,
            "shell":   shell_result_v4,
            "code":    code_result_v4,
            "search":  search_result_v4,
            "web":     web_result_v4,
            "agent":   agent_result_v4,
            "mcp":     mcp_result_v4,
            "unknown": generic_result_v4,
        })
    return _V4_PARSERS


def parse(ctx: ParseContext) -> ResultSummaryV4:
    """Dispatch to the correct v4 parser based on spec.category."""
    try:
        cat = ctx.spec.category.value
    except Exception:
        cat = "unknown"
    parsers = _get_v4_parsers()
    parser_fn = parsers.get(cat, generic_result_v4)
    return parser_fn(ctx)
