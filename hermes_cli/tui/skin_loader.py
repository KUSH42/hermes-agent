"""Skin loader — JSON/YAML → Textual CSS variable dict.

Translates user-authored semantic skin keys (``fg``, ``bg``, ``accent``, …)
into the Textual CSS variable names that ``HermesApp.get_css_variables``
merges at render time.  Also passes through glass keys (``glass-tint``,
``glass-border``, ``glass-edge``) and raw ``vars`` blocks for users who want
direct control over Textual internals.

PyYAML is a declared dependency but is lazy-imported so JSON-only users never
pay the import cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SEMANTIC_MAP: dict[str, tuple[str, ...]] = {
    "fg":         ("foreground", "text"),
    "bg":         ("background", "surface", "panel"),
    "accent":     ("primary", "accent"),
    "accent-dim": ("primary-darken-2", "primary-darken-3"),
    "success":    ("success",),
    "warning":    ("warning",),
    "error":      ("error",),
    "muted":      ("text-muted",),
    "border":     ("panel-lighten-1",),
    "selection":  ("boost",),
}

_GLASS_KEYS = {"glass-tint", "glass-border", "glass-edge"}


class SkinError(ValueError):
    """Raised when a skin file cannot be parsed or has an invalid structure."""


def load_skin(path: Path) -> dict[str, str]:
    """Load a JSON or YAML skin file and return a Textual CSS variable dict.

    Semantic keys fan out to all their Textual targets.  Raw ``vars`` take
    precedence (they are applied in pass 1 and ``setdefault`` is used for
    semantic expansion in pass 2).  Glass keys pass through unchanged.
    """
    data = _read_structured(path)
    if not isinstance(data, dict):
        raise SkinError(f"{path}: top level must be a mapping")

    out: dict[str, str] = {}

    # Pass 1 — raw vars win on conflict; user opt-out of semantic mapping.
    raw = data.get("vars", {})
    if not isinstance(raw, dict):
        raise SkinError(f"{path}: 'vars' must be a mapping")
    out.update({str(k): str(v) for k, v in raw.items()})

    # Pass 2 — semantic keys fan out to all their Textual targets.
    for semantic, value in data.items():
        if semantic == "vars" or not isinstance(value, str):
            continue
        for target in _SEMANTIC_MAP.get(semantic, ()):
            out.setdefault(target, value)
        if semantic in _GLASS_KEYS:
            out.setdefault(semantic, value)

    return out


def _read_structured(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yml", ".yaml"):
        import yaml  # lazy — keeps JSON-only callers off the PyYAML import cost
        return yaml.safe_load(text)
    return json.loads(text)
