"""CWD token stripping for shell output.

The hermes agent wraps directory context in tokens:
  __HERMES_CWD_<hex>__/path/to/dir__HERMES_CWD_<hex>__

strip_cwd() extracts and removes these tokens, returning the cleaned
text and the detected CWD path.

Architecture: tui-tool-panel-v3-spec.md §5.6.1 (D1 fix)
"""
from __future__ import annotations

import re

_CWD_RE = re.compile(
    r"__HERMES_CWD_[0-9a-f]{8,32}__(.*?)__HERMES_CWD_[0-9a-f]{8,32}__",
    re.DOTALL,
)


def strip_cwd(text: str) -> tuple[str, str | None]:
    """Remove CWD tokens from text; return (cleaned_text, cwd_or_None)."""
    m = _CWD_RE.search(text)
    if not m:
        return text, None
    cwd = m.group(1).strip()
    cleaned = _CWD_RE.sub("", text).rstrip()
    return cleaned, cwd or None


def has_cwd_token(text: str) -> bool:
    """Return True if text contains a CWD token."""
    return bool(_CWD_RE.search(text))
