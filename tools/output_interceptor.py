from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent.redact import redact_sensitive_text
from hermes_constants import get_hermes_home
from tools.ansi_strip import strip_ansi

Verbosity = Literal["summary", "medium", "full"]

_RAW_HEAD_RATIO = 0.4
_DEFAULT_RAW_CAP = 50_000
_DIFF_EXCERPT_CHARS = 4_000


@dataclass
class CommandExecutionResult:
    command: str
    cwd: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    combined_output: str
    duration_seconds: float | None = None
    source: str = "terminal"


@dataclass
class InterceptorRequest:
    execution: CommandExecutionResult
    verbosity: Verbosity = "summary"
    task_id: str | None = None
    background_context: bool = False


@dataclass
class InterceptorResult:
    output: str
    summary: str | None
    structured: dict[str, Any] | None
    raw_available: bool
    interceptor_kind: str | None
    derived: bool
    truncated: bool
    confidence: str | None = None
    raw_output_path: str | None = None
    exit_code_meaning: str | None = None
    fallback_reason: str | None = None
    notes: list[str] | None = None
    capture_mode: str = "none"


@dataclass
class NormalizedOutput:
    stdout: str
    stderr: str
    full_output: str
    combined_output: str
    truncated: bool
    raw_total_chars: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_verbosity(name: str, default: Verbosity) -> Verbosity:
    raw = str(os.getenv(name, default)).strip().lower()
    if raw in {"summary", "medium", "full"}:
        return raw
    return default


def interceptor_enabled() -> bool:
    return _env_bool("TERMINAL_OUTPUT_INTERCEPTOR_ENABLED", True)


def resolve_output_verbosity(requested: str | None) -> Verbosity:
    if requested in {"summary", "medium", "full"}:
        return requested
    return _env_verbosity("TERMINAL_OUTPUT_DEFAULT_VERBOSITY", "summary")


def _persist_threshold_chars() -> int:
    return _env_int("TERMINAL_INTERCEPTOR_PERSIST_THRESHOLD_CHARS", _DEFAULT_RAW_CAP)


def _medium_diff_max_files() -> int:
    return _env_int("TERMINAL_INTERCEPTOR_MEDIUM_DIFF_MAX_FILES", 5)


def _medium_diff_max_lines() -> int:
    return _env_int("TERMINAL_INTERCEPTOR_MEDIUM_DIFF_MAX_LINES", 200)


def _min_savings_chars() -> int:
    return _env_int("TERMINAL_INTERCEPTOR_MIN_SAVINGS_CHARS", 0)


def _min_savings_ratio() -> float:
    raw = os.getenv("TERMINAL_INTERCEPTOR_MIN_SAVINGS_RATIO")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _include_fallback_reason() -> bool:
    return _env_bool("TERMINAL_INTERCEPTOR_INCLUDE_FALLBACK_REASON", False)


def _capture_summarized_raw_enabled() -> bool:
    return _env_bool("TERMINAL_INTERCEPTOR_CAPTURE_SUMMARIZED_RAW", True)


def _force_capture_background() -> bool:
    return _env_bool("TERMINAL_INTERCEPTOR_FORCE_CAPTURE_BACKGROUND", True)


def _force_capture_truncated() -> bool:
    return _env_bool("TERMINAL_INTERCEPTOR_FORCE_CAPTURE_TRUNCATED", True)


def _optional_capture_max_raw_chars() -> int:
    return _env_int("TERMINAL_INTERCEPTOR_OPTIONAL_CAPTURE_MAX_RAW_CHARS", 512)


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head_chars = int(max_chars * _RAW_HEAD_RATIO)
    tail_chars = max_chars - head_chars
    omitted = len(text) - head_chars - tail_chars
    notice = (
        f"\n\n... [OUTPUT TRUNCATED - {omitted} chars omitted "
        f"out of {len(text)} total] ...\n\n"
    )
    return text[:head_chars] + notice + text[-tail_chars:], True


def normalize_output(stdout: str = "", stderr: str = "", combined_output: str = "", max_chars: int | None = None) -> NormalizedOutput:
    def _clean(text: str) -> str:
        if not text:
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = strip_ansi(text)
        text = redact_sensitive_text(text)
        return text.strip()

    normalized_stdout = _clean(stdout)
    normalized_stderr = _clean(stderr)
    combined_source = combined_output or "\n".join(part for part in (stdout, stderr) if part)
    normalized_combined = _clean(combined_source)
    capped_text, truncated = _truncate_text(
        normalized_combined,
        max_chars=max_chars or _persist_threshold_chars(),
    )
    return NormalizedOutput(
        stdout=normalized_stdout,
        stderr=normalized_stderr,
        full_output=normalized_combined,
        combined_output=capped_text,
        truncated=truncated,
        raw_total_chars=len(normalized_combined),
    )


def _capture_dir() -> Path:
    path = get_hermes_home() / "tmp" / "terminal-output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def persist_raw_output(text: str, task_id: str | None = None, source: str = "terminal") -> str | None:
    if not text:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
    prefix = re.sub(r"[^a-z0-9_-]+", "-", (task_id or source or "terminal").lower()).strip("-") or "terminal"
    path = _capture_dir() / f"{stamp}-{prefix}-{digest}.log"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _split_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    idx = 0
    while idx < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[idx]):
        idx += 1
    return tokens[idx:]


def _contains_complex_shell(command: str) -> bool:
    return any(op in command for op in ("|", "&&", "||", ";", "$(", "`"))


def classify_command(command: str) -> str | None:
    if not command.strip() or _contains_complex_shell(command):
        return None
    tokens = _split_command(command)
    if not tokens:
        return None
    exe = Path(tokens[0]).name
    if exe == "git" and len(tokens) >= 2 and tokens[1] == "status":
        return "git_status"
    if exe == "git" and len(tokens) >= 2 and tokens[1] == "diff":
        return "git_diff"
    if exe == "pytest":
        return "pytest"
    if exe in {"python", "python3"} and any(tok == "pytest" or tok.endswith("/pytest") for tok in tokens[1:]):
        return "python_pytest"
    return None


def _parse_git_status_porcelain(text: str) -> tuple[dict[str, Any], str | None]:
    branch = None
    ahead = 0
    behind = 0
    data = {
        "branch": None,
        "ahead": 0,
        "behind": 0,
        "modified": [],
        "added": [],
        "deleted": [],
        "renamed": [],
        "untracked": [],
    }
    for line in text.splitlines():
        if line.startswith("## "):
            header = line[3:]
            main = header.split("...")[0].strip()
            branch = main
            m = re.search(r"ahead (\d+)", header)
            if m:
                ahead = int(m.group(1))
            m = re.search(r"behind (\d+)", header)
            if m:
                behind = int(m.group(1))
            continue
        if line.startswith("?? "):
            data["untracked"].append(line[3:].strip())
            continue
        if len(line) < 3:
            continue
        status = line[:2]
        path = line[3:].strip()
        if "->" in path:
            old, new = [part.strip() for part in path.split("->", 1)]
            data["renamed"].append({"from": old, "to": new})
            continue
        flags = set(status)
        if "M" in flags:
            data["modified"].append(path)
        elif "A" in flags:
            data["added"].append(path)
        elif "D" in flags:
            data["deleted"].append(path)
        elif "R" in flags:
            data["renamed"].append({"from": path, "to": path})
    data["branch"] = branch
    data["ahead"] = ahead
    data["behind"] = behind
    return data, branch


def _parse_git_status_human(text: str) -> dict[str, Any]:
    data = {
        "branch": None,
        "ahead": 0,
        "behind": 0,
        "modified": [],
        "added": [],
        "deleted": [],
        "renamed": [],
        "untracked": [],
    }
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("On branch "):
            data["branch"] = stripped[len("On branch "):].strip()
        elif stripped.startswith("Your branch is ahead of"):
            m = re.search(r"by (\d+) commit", stripped)
            if m:
                data["ahead"] = int(m.group(1))
        elif stripped.startswith("Your branch is behind"):
            m = re.search(r"by (\d+) commit", stripped)
            if m:
                data["behind"] = int(m.group(1))
        elif stripped.startswith("Changes to be committed:"):
            current = "added"
        elif stripped.startswith("Changes not staged for commit:"):
            current = "modified"
        elif stripped.startswith("Untracked files:"):
            current = "untracked"
        elif stripped.startswith("deleted:"):
            data["deleted"].append(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("modified:"):
            data["modified"].append(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("new file:"):
            data["added"].append(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("renamed:"):
            rename = stripped.split(":", 1)[1].strip()
            if "->" in rename:
                old, new = [part.strip() for part in rename.split("->", 1)]
                data["renamed"].append({"from": old, "to": new})
        elif current == "untracked" and stripped and not stripped.startswith("("):
            data["untracked"].append(stripped)
    return data


def _looks_like_git_status(text: str) -> bool:
    markers = (
        "On branch ",
        "Changes not staged for commit:",
        "Changes to be committed:",
        "Untracked files:",
        "nothing to commit, working tree clean",
        "nothing added to commit but untracked files present",
    )
    return any(marker in text for marker in markers)


def _git_status_parse_confident(data: dict[str, Any], text: str) -> bool:
    if data.get("branch"):
        return True
    if any(data.get(key) for key in ("modified", "added", "deleted", "renamed", "untracked")):
        return True
    return "working tree clean" in text or "nothing to commit" in text


def _render_git_status_summary(data: dict[str, Any]) -> str:
    branch = data.get("branch") or "(detached)"
    counts = []
    for key in ("modified", "added", "deleted", "renamed", "untracked"):
        items = data.get(key) or []
        if items:
            counts.append(f"{len(items)} {key}")
    if not counts:
        return f"Clean on {branch}"
    prefix = ", ".join(counts)
    suffix = []
    if data.get("ahead"):
        suffix.append(f"ahead {data['ahead']}")
    if data.get("behind"):
        suffix.append(f"behind {data['behind']}")
    suffix_text = f" ({', '.join(suffix)})" if suffix else ""
    return f"{prefix} on {branch}{suffix_text}"


def _status_counts(data: dict[str, Any]) -> dict[str, int]:
    return {
        "modified": len(data.get("modified") or []),
        "added": len(data.get("added") or []),
        "deleted": len(data.get("deleted") or []),
        "renamed": len(data.get("renamed") or []),
        "untracked": len(data.get("untracked") or []),
    }


def _structured_git_status(data: dict[str, Any], verbosity: Verbosity) -> tuple[dict[str, Any] | None, list[str] | None]:
    if verbosity == "full":
        return None, None
    counts = {key: value for key, value in _status_counts(data).items() if value}
    structured: dict[str, Any] = {}
    if data.get("branch"):
        structured["branch"] = data["branch"]
    if data.get("ahead"):
        structured["ahead"] = data["ahead"]
    if data.get("behind"):
        structured["behind"] = data["behind"]
    if counts:
        structured["counts"] = counts
    notes: list[str] = []
    if verbosity == "summary":
        return structured or None, None

    files: dict[str, list[str]] = {}
    for key in ("modified", "added", "deleted", "untracked"):
        items = [str(item) for item in (data.get(key) or []) if item]
        if items:
            files[key] = items[:10]
            if len(items) > 10:
                notes.append(f"{key} list truncated to first 10 entries.")
    renamed = data.get("renamed") or []
    if renamed:
        files["renamed"] = [f"{item['from']} -> {item['to']}" for item in renamed[:10]]
        if len(renamed) > 10:
            notes.append("renamed list truncated to first 10 entries.")
    if files:
        structured["files"] = files
    return structured, notes or None


def _handle_git_status(request: InterceptorRequest, normalized: NormalizedOutput) -> InterceptorResult:
    text = normalized.full_output
    porcelain_requested = "--porcelain" in request.execution.command
    if porcelain_requested and ("## " in text or re.search(r"^(.. |\?\? )", text, flags=re.MULTILINE)):
        data, _ = _parse_git_status_porcelain(text)
        confident = _git_status_parse_confident(data, text)
    else:
        if not _looks_like_git_status(text):
            raise ValueError("ambiguous_git_status_output")
        # Human-readable status remains best-effort only. If the output mixes
        # staged and unstaged sections, the current schema cannot represent the
        # nuance faithfully enough to claim strong support.
        if "Changes to be committed:" in text and "Changes not staged for commit:" in text:
            raise ValueError("ambiguous_git_status_output")
        data = _parse_git_status_human(text)
        confident = _git_status_parse_confident(data, text)
    if not confident:
        raise ValueError("ambiguous_git_status_output")
    summary = _render_git_status_summary(data)
    output = summary
    structured, notes = _structured_git_status(data, request.verbosity)
    if request.verbosity == "medium":
        detail_lines = []
        for key in ("modified", "added", "deleted", "untracked"):
            items = data.get(key) or []
            if items:
                detail_lines.append(f"{key}: {', '.join(items[:10])}")
        renamed = data.get("renamed") or []
        if renamed:
            rendered = [f"{item['from']} -> {item['to']}" for item in renamed[:10]]
            detail_lines.append(f"renamed: {', '.join(rendered)}")
        if detail_lines:
            output = summary + "\n" + "\n".join(detail_lines)
    return InterceptorResult(
        output=output,
        summary=summary,
        structured=structured,
        raw_available=True,
        interceptor_kind="git_status",
        derived=True,
        truncated=normalized.truncated,
        confidence="high" if porcelain_requested else "medium",
        notes=notes,
    )


def _parse_git_diff(text: str) -> dict[str, Any]:
    files: list[str] = []
    insertions = 0
    deletions = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                files.append(path)
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return {
        "files": files,
        "file_count": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "line_count": len(text.splitlines()),
    }


def _structured_git_diff(data: dict[str, Any], verbosity: Verbosity) -> dict[str, Any] | None:
    if verbosity == "full":
        return None
    structured: dict[str, Any] = {
        "file_count": data["file_count"],
        "insertions": data["insertions"],
        "deletions": data["deletions"],
    }
    if data["files"]:
        structured["files"] = data["files"][: _medium_diff_max_files()]
    if verbosity == "summary":
        return structured
    return structured


def _handle_git_diff(request: InterceptorRequest, normalized: NormalizedOutput) -> InterceptorResult:
    data = _parse_git_diff(normalized.full_output)
    if data["file_count"] == 0:
        raise ValueError("ambiguous_git_diff_output")
    file_count = data["file_count"]
    summary = (
        f"{file_count} file{'s' if file_count != 1 else ''} changed, "
        f"{data['insertions']} insertions(+), {data['deletions']} deletions(-)"
    )
    output = summary
    notes: list[str] = []
    shown_files = data["files"][: _medium_diff_max_files()]
    hidden_files = max(0, data["file_count"] - len(shown_files))
    if request.verbosity == "summary" and shown_files:
        detail = f"Files: {', '.join(shown_files)}"
        if hidden_files:
            detail += f"; +{hidden_files} more"
        output = summary + "\n" + detail
    if request.verbosity == "medium":
        detail_lines = []
        if shown_files:
            detail_lines.append(f"Files: {', '.join(shown_files)}")
        if hidden_files:
            detail_lines.append(f"+{hidden_files} more files")
        if data["line_count"] > _medium_diff_max_lines():
            notes.append("Raw diff hunks omitted at medium verbosity because the diff is larger than the configured line limit.")
        elif data["file_count"] > _medium_diff_max_files():
            notes.append("Only the first few changed files are listed at medium verbosity.")
        output = summary + ("\n" + "\n".join(detail_lines) if detail_lines else "")
    return InterceptorResult(
        output=output,
        summary=summary,
        structured=_structured_git_diff(data, request.verbosity),
        raw_available=True,
        interceptor_kind="git_diff",
        derived=True,
        truncated=normalized.truncated,
        confidence="high",
        notes=notes or None,
    )


def _parse_pytest_summary(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "errors": 0,
        "failing_tests": [],
    }
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            name = stripped[len("FAILED "):].split(" - ", 1)[0].strip()
            data["failing_tests"].append(name)
    summary_line = None
    for line in reversed(text.splitlines()):
        if re.search(r"\b(passed|failed|skipped|error|errors|xfailed|xpassed)\b", line):
            summary_line = line
            break
    if summary_line:
        for count, label in re.findall(r"(\d+)\s+(passed|failed|skipped|error|errors|xfailed|xpassed)", summary_line):
            normalized_label = "errors" if label in {"error", "errors"} else label
            data[normalized_label] = int(count)
    return data


def _collect_failure_excerpts(text: str, limit: int = 3) -> list[str]:
    excerpts: list[str] = []
    current: list[str] = []
    collecting = False
    for line in text.splitlines():
        if line.startswith("_") and "FAILURES" in line:
            collecting = False
            current = []
            continue
        if line.startswith("________________________________"):
            if current:
                excerpts.append("\n".join(current[:20]).strip())
                if len(excerpts) >= limit:
                    break
            current = [line]
            collecting = True
            continue
        if collecting:
            current.append(line)
    if current and len(excerpts) < limit:
        excerpts.append("\n".join(current[:20]).strip())
    return [excerpt for excerpt in excerpts if excerpt]


def _extract_pytest_clues(text: str) -> list[str]:
    clues: list[str] = []
    seen: set[str] = set()

    def _add(clue: str) -> None:
        if clue and clue not in seen:
            seen.add(clue)
            clues.append(clue)

    for match in re.finditer(r'\["([^"]+)"\]\s+is\s+(True|False)', text):
        key, value = match.groups()
        _add(f"{key} expected {value.lower()}")
    if "wrong-" in text:
        _add("expected prefix wrong-")
    for match in re.finditer(r"^[E>\s]*([A-Za-z]+Error):\s*(.+)$", text, flags=re.MULTILINE):
        _add(f"{match.group(1)}: {match.group(2).strip()}")
    for match in re.finditer(r"KeyError: '([^']+)'", text):
        _add(f"missing key {match.group(1)}")
    for match in re.finditer(r"AssertionError:\s*(.+)", text):
        message = match.group(1).strip()
        if message:
            _add(message[:120])
    return clues[:4]


def _structured_pytest(
    data: dict[str, Any],
    verbosity: Verbosity,
    excerpts: list[str] | None = None,
    clues: list[str] | None = None,
) -> dict[str, Any] | None:
    if verbosity == "full":
        return None
    structured: dict[str, Any] = {}
    for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"):
        value = int(data.get(key, 0) or 0)
        if value:
            structured[key] = value
    failing_tests = list(data.get("failing_tests") or [])
    if failing_tests:
        structured["failing_tests"] = failing_tests[:4 if verbosity == "summary" else 8]
    if clues:
        structured["failure_clues"] = clues[:3 if verbosity == "summary" else 4]
    if verbosity == "medium" and excerpts:
        structured["failure_excerpt_count"] = len(excerpts)
    return structured or None


def _handle_pytest(request: InterceptorRequest, normalized: NormalizedOutput, kind: str) -> InterceptorResult:
    data = _parse_pytest_summary(normalized.full_output)
    has_pytest_markers = (
        "test session starts" in normalized.full_output
        or "FAILURES" in normalized.full_output
        or "collected " in normalized.full_output
        or bool(data["failing_tests"])
    )
    has_counts = any(data.get(key, 0) for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"))
    if not has_pytest_markers and not has_counts:
        raise ValueError("ambiguous_pytest_output")
    summary_parts = []
    for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"):
        count = data.get(key, 0)
        if count:
            summary_parts.append(f"{count} {key}")
    if not summary_parts:
        summary_parts.append("pytest run completed")
    if data["failing_tests"]:
        summary_parts.append(f"failing: {', '.join(data['failing_tests'][:8])}")
    clues = _extract_pytest_clues(normalized.full_output)
    if clues:
        summary_parts.append(f"clues: {', '.join(clues[:2])}")
    summary = ", ".join(summary_parts)
    output = summary
    excerpts: list[str] = []
    if request.verbosity == "medium":
        excerpts = _collect_failure_excerpts(normalized.full_output)
        if excerpts:
            output = summary + "\n\n" + "\n\n".join(excerpts)
    return InterceptorResult(
        output=output,
        summary=summary,
        structured=_structured_pytest(data, request.verbosity, excerpts, clues),
        raw_available=True,
        interceptor_kind=kind,
        derived=True,
        truncated=normalized.truncated,
        confidence="high",
    )


def _fallback_raw_result(
    raw_text: str,
    truncated: bool,
    exit_code_meaning: str | None = None,
    fallback_reason: str | None = None,
    confidence: str = "fallback",
) -> InterceptorResult:
    return InterceptorResult(
        output=raw_text,
        summary=None,
        structured=None,
        raw_available=bool(raw_text),
        interceptor_kind=None,
        derived=False,
        truncated=truncated,
        confidence=confidence,
        exit_code_meaning=exit_code_meaning,
        fallback_reason=fallback_reason,
        capture_mode="none",
    )


def _estimate_model_payload_chars(
    result: InterceptorResult,
    verbosity: Verbosity,
    *,
    raw_output_path: str | None = None,
    capture_mode: str | None = None,
) -> int:
    payload: dict[str, Any] = {
        "output": result.output,
        "summary": result.summary,
        "structured": result.structured,
        "verbosity": verbosity,
        "raw_available": result.raw_available,
        "derived_output": result.derived,
        "interceptor_kind": result.interceptor_kind,
        "raw_output_path": raw_output_path,
        "truncated": result.truncated,
        "confidence": result.confidence,
        "capture_mode": capture_mode or result.capture_mode,
    }
    if result.exit_code_meaning:
        payload["exit_code_meaning"] = result.exit_code_meaning
    if result.fallback_reason and _include_fallback_reason():
        payload["fallback_reason"] = result.fallback_reason
    if result.notes:
        payload["notes"] = result.notes
    return len(json.dumps(payload, ensure_ascii=False))


def serialization_mode() -> str:
    return "debug" if _include_fallback_reason() else "production"


def _prefer_derived_payload(
    derived: InterceptorResult,
    raw: InterceptorResult,
    verbosity: Verbosity,
    *,
    raw_capture_path_included: bool,
    capture_mode: str,
) -> tuple[bool, str | None]:
    raw_chars = _estimate_model_payload_chars(raw, verbosity)
    derived_chars = _estimate_model_payload_chars(
        derived,
        verbosity,
        raw_output_path="__persisted__" if raw_capture_path_included else None,
        capture_mode=capture_mode,
    )
    if derived_chars >= raw_chars:
        return False, "summary_not_smaller"

    savings_chars = raw_chars - derived_chars
    savings_ratio = 0.0 if raw_chars == 0 else savings_chars / raw_chars
    if savings_chars >= _min_savings_chars() or savings_ratio >= _min_savings_ratio():
        return True, None
    return False, "summary_not_smaller"


def _should_force_recovery_capture(result: InterceptorResult) -> bool:
    return result.interceptor_kind in {"pytest", "python_pytest"}


def _eligible_for_optional_capture(result: InterceptorResult, request: InterceptorRequest, normalized: NormalizedOutput) -> bool:
    if request.background_context:
        return False
    if result.truncated:
        return False
    if normalized.raw_total_chars > _optional_capture_max_raw_chars():
        return False
    if result.interceptor_kind not in {"git_status", "git_diff"}:
        return False
    if result.interceptor_kind == "git_status" and "--porcelain" not in request.execution.command:
        return False
    return True


def _resolve_capture_policy(
    result: InterceptorResult,
    request: InterceptorRequest,
    normalized: NormalizedOutput,
) -> tuple[bool, str]:
    if not result.derived:
        return False, "none"
    if not _capture_summarized_raw_enabled():
        return False, "derived_capture_disabled"
    if request.background_context and _force_capture_background():
        return True, "derived_required_background"
    if result.truncated and _force_capture_truncated():
        return True, "derived_required_truncated"
    if _should_force_recovery_capture(result):
        return True, "derived_required_recovery"
    if _eligible_for_optional_capture(result, request, normalized):
        return False, "derived_optional_skipped"
    return True, "derived_optional"


def intercept_output(request: InterceptorRequest, exit_code_meaning: str | None = None) -> InterceptorResult:
    normalized = normalize_output(
        stdout=request.execution.stdout,
        stderr=request.execution.stderr,
        combined_output=request.execution.combined_output,
    )
    raw_text = normalized.combined_output
    full_raw_text = normalized.full_output
    kind = classify_command(request.execution.command)

    if request.verbosity == "full" or not interceptor_enabled():
        raw_path = None
        if _env_bool("TERMINAL_INTERCEPTOR_PERSIST_LARGE_OUTPUT", True) and normalized.raw_total_chars >= _persist_threshold_chars():
            raw_path = persist_raw_output(full_raw_text, task_id=request.task_id, source=request.execution.source)
        result = _fallback_raw_result(
            raw_text=raw_text,
            truncated=normalized.truncated,
            exit_code_meaning=exit_code_meaning,
            confidence="raw",
        )
        result.raw_output_path = raw_path
        return result

    raw_result = _fallback_raw_result(
        raw_text=raw_text,
        truncated=normalized.truncated,
        exit_code_meaning=exit_code_meaning,
        confidence="raw",
    )
    try:
        if kind == "git_status":
            result = _handle_git_status(request, normalized)
        elif kind == "git_diff":
            result = _handle_git_diff(request, normalized)
        elif kind in {"pytest", "python_pytest"}:
            result = _handle_pytest(request, normalized, kind)
        else:
            result = _fallback_raw_result(
                raw_text=raw_text,
                truncated=normalized.truncated,
                exit_code_meaning=exit_code_meaning,
                confidence="raw",
            )
    except ValueError as exc:
        result = _fallback_raw_result(
            raw_text=raw_text,
            truncated=normalized.truncated,
            exit_code_meaning=exit_code_meaning,
            fallback_reason=str(exc),
        )

    if result.derived:
        capture_raw, capture_mode = _resolve_capture_policy(result, request, normalized)
        prefer_derived, _fallback_reason = _prefer_derived_payload(
            result,
            raw_result,
            request.verbosity,
            raw_capture_path_included=capture_raw,
            capture_mode=capture_mode,
        )
        if not prefer_derived:
            result = _fallback_raw_result(
                raw_text=raw_text,
                truncated=normalized.truncated,
                exit_code_meaning=exit_code_meaning,
                confidence="raw",
            )
        else:
            result.capture_mode = capture_mode

    if result.derived and result.capture_mode != "derived_optional_skipped" and result.capture_mode != "derived_capture_disabled":
        result.raw_output_path = persist_raw_output(full_raw_text, task_id=request.task_id, source=request.execution.source)
    elif result.derived:
        result.raw_output_path = None
    elif _env_bool("TERMINAL_INTERCEPTOR_PERSIST_LARGE_OUTPUT", True) and normalized.raw_total_chars >= _persist_threshold_chars():
        result.raw_output_path = persist_raw_output(full_raw_text, task_id=request.task_id, source=request.execution.source)
        result.capture_mode = "raw_large_output"

    result.exit_code_meaning = exit_code_meaning
    return result


def result_to_json_dict(result: InterceptorResult, verbosity: Verbosity) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "output": result.output,
        "summary": result.summary,
        "structured": result.structured,
        "verbosity": verbosity,
        "raw_available": result.raw_available,
        "derived_output": result.derived,
        "interceptor_kind": result.interceptor_kind,
        "raw_output_path": result.raw_output_path,
        "truncated": result.truncated,
        "confidence": result.confidence,
        "capture_mode": result.capture_mode,
    }
    if result.exit_code_meaning:
        payload["exit_code_meaning"] = result.exit_code_meaning
    if result.fallback_reason and _include_fallback_reason():
        payload["fallback_reason"] = result.fallback_reason
    if result.notes:
        payload["notes"] = result.notes
    return payload
