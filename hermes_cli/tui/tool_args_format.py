"""Args formatters for ArgsPane (tui-tool-panel-v2-spec.md §5.5).

Pure functions: take args dict, return list of (label, Rich Text) tuples.
Each formatter is keyed by CategoryDefaults.args_formatter.
"""

from __future__ import annotations

from rich.text import Text


# ---------------------------------------------------------------------------
# Path styling helper
# ---------------------------------------------------------------------------


def _style_path(path: str) -> Text:
    """Style a file path: dim directory, bold filename."""
    if not path:
        return Text("", style="dim")
    parts = path.rsplit("/", 1)
    if len(parts) == 2 and parts[0]:
        t = Text(parts[0] + "/", style="dim")
        t.append(parts[1], style="bold")
        return t
    return Text(path, style="bold")


# ---------------------------------------------------------------------------
# Per-category formatters
# ---------------------------------------------------------------------------


def file_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for FILE category (read_file, write_file, patch, etc.)."""
    rows: list[tuple[str, Text]] = []
    if "path" in args:
        rows.append(("path", _style_path(str(args["path"]))))
    if "line_range" in args:
        rows.append(("range", Text(str(args["line_range"]))))
    content = args.get("content", "")
    if content and len(str(content)) > 80:
        rows.append(("content", Text(f"{len(str(content))} chars", style="dim")))
    return rows


def shell_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for SHELL category (terminal, bash)."""
    cmd = str(args.get("command", args.get("cmd", "")))
    if len(cmd) > 1800:
        cmd = cmd[:1800] + f" … (+{len(cmd) - 1800} chars)"
    rows: list[tuple[str, Text]] = [("command", Text(cmd, style="bold"))]
    if args.get("cwd"):
        rows.append(("cwd", _style_path(str(args["cwd"]))))
    if args.get("timeout"):
        rows.append(("timeout", Text(f"{args['timeout']}s", style="dim")))
    return rows


def code_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for CODE category (execute_code)."""
    code = str(args.get("code", ""))
    lines = code.count("\n") + 1 if code else 0
    return [("code", Text(f"{lines} lines", style="dim"))]


def search_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for SEARCH category (web_search, grep, glob)."""
    query = str(args.get("query", args.get("pattern", args.get("glob", ""))))
    rows: list[tuple[str, Text]] = [("query", Text(query, style="italic"))]
    if args.get("path"):
        rows.append(("path", _style_path(str(args["path"]))))
    return rows


def web_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for WEB category (web_extract, fetch, http)."""
    url = str(args.get("url", args.get("query", "")))
    return [("url", _style_path(url))]


def agent_args(args: dict) -> list[tuple[str, Text]]:
    """Formatter for AGENT category (think, plan, delegate)."""
    for key in ("thought", "plan", "task", "description"):
        if key in args:
            val = str(args[key])[:200]
            return [(key, Text(val, style="italic dim"))]
    return []


def generic_args(args: dict) -> list[tuple[str, Text]]:
    """Fallback formatter for UNKNOWN category."""
    rows: list[tuple[str, Text]] = []
    for k, v in list(args.items())[:5]:
        val = str(v)
        if len(val) > 80:
            val = val[:80] + "…"
        rows.append((str(k), Text(val, style="dim")))
    return rows


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_FORMATTERS: dict[str, object] = {
    "file_args":    file_args,
    "shell_args":   shell_args,
    "code_args":    code_args,
    "search_args":  search_args,
    "web_args":     web_args,
    "agent_args":   agent_args,
    "generic_args": generic_args,
}


def get_formatter(name: str):
    """Return formatter function by name; falls back to generic_args."""
    return _FORMATTERS.get(name, generic_args)
