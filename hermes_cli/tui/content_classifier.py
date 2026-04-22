"""Content classifier — full Phase C heuristics."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind

_LOG_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"|\b(INFO|WARN(?:ING)?|ERROR|DEBUG|TRACE|FATAL)\b)"
)

_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".c", ".cpp",
              ".h", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
              ".zsh", ".json", ".yaml", ".yml", ".toml", ".sql", ".html", ".css", ".md")


def _is_table(lines: list[str]) -> bool:
    delim = "|" if sum(1 for l in lines if "|" in l) > sum(1 for l in lines if "\t" in l) else "\t"
    cols = [len(l.split(delim)) for l in lines if l.strip()]
    if not cols:
        return False
    modal = max(set(cols), key=cols.count)
    if modal < (3 if delim == "|" else 2):
        return False
    return sum(1 for c in cols if c == modal) / len(cols) >= 0.85


@lru_cache(maxsize=32)
def _cached_classify(output_raw: str, tool_name: str, arg_query: str | None) -> ClassificationResult:
    text = output_raw
    if not text.strip():
        return ClassificationResult(ResultKind.EMPTY, 1.0)

    # Binary check: ASCII control chars (< 0x20) excluding tab/newline/CR/ESC
    sample = text[:4096].encode("utf-8", errors="replace")
    nonprint = sum(1 for b in sample if b < 0x20 and b not in (0x09, 0x0A, 0x0D, 0x1B))
    if nonprint / max(1, min(4096, len(sample))) > 0.05:
        return ClassificationResult(ResultKind.BINARY, 0.95)

    # Diff: unified diff markers at line start
    if re.search(r"^(---|\+\+\+|@@)", text, re.MULTILINE):
        return ClassificationResult(ResultKind.DIFF, 0.9)

    # Search: ≥ 3 lines with line-number prefix
    hits = len(re.findall(r"^\s*\d+[:\-]\s", text, re.MULTILINE))
    if hits >= 3:
        return ClassificationResult(
            ResultKind.SEARCH, 0.85,
            {"hit_count": hits, "query": arg_query}
        )

    # JSON: only if starts with { or [ and has some content
    s = text.lstrip()
    if s and s[0] in "{[" and (len(text) > 20 or "\n" in text):
        try:
            parsed = json.loads(text)
            # JSON-format search result: {matches:[{path,line,content}], ...}
            if isinstance(parsed, dict):
                matches = parsed.get("matches")
                if isinstance(matches, list) and matches and isinstance(matches[0], dict) \
                        and ("path" in matches[0] or "file" in matches[0]):
                    return ClassificationResult(
                        ResultKind.SEARCH, 0.9,
                        {"hit_count": len(matches), "query": arg_query, "json": True},
                    )
            return ClassificationResult(ResultKind.JSON, 0.95)
        except (json.JSONDecodeError, MemoryError):
            pass

    # Table: consistent column structure
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if len(lines) >= 3 and _is_table(lines):
        return ClassificationResult(ResultKind.TABLE, 0.8)

    # Log: level tokens or timestamps
    log_hits = sum(1 for ln in text.splitlines()[:20] if _LOG_RE.search(ln))
    if log_hits >= 2:
        return ClassificationResult(ResultKind.LOG, 0.7)

    # Code: fenced block or file extension match
    if text.startswith("```") or (tool_name and any(
        (arg_query or "").endswith(ext) for ext in _CODE_EXTS
    )):
        return ClassificationResult(ResultKind.CODE, 0.75)

    return ClassificationResult(ResultKind.TEXT, 1.0)


def classify_content(payload: object) -> ClassificationResult:
    """Classify tool output. Returns ClassificationResult."""
    output_raw = getattr(payload, "output_raw", None) or ""
    tool_name = getattr(payload, "tool_name", None) or ""
    args = getattr(payload, "args", None) or {}
    # Extract query from common arg keys
    query = None
    if args:
        for key in ("query", "pattern", "regex", "search"):
            val = args.get(key)
            if val:
                query = str(val)
                break
        # Also check path for code extension detection
        if not query:
            query = str(args.get("path", "")) or None
    return _cached_classify(output_raw, tool_name, query)


# Expose cache_clear for tests
classify_content.cache_clear = _cached_classify.cache_clear  # type: ignore[attr-defined]
