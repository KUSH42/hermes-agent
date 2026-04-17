"""Content classifier — Phase B stub.

Phase B: only EMPTY / TEXT classification.
Phase C: full heuristics (search/diff/json/log/table/code/binary).

LRU cache (32 entries) keyed by output_raw string.
Cache can be cleared in tests via classify_content.cache_clear().
"""
from __future__ import annotations

from functools import lru_cache

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind


@lru_cache(maxsize=32)
def _cached_classify(output_raw: str) -> ClassificationResult:
    if not output_raw.strip():
        return ClassificationResult(ResultKind.EMPTY, 1.0)
    return ClassificationResult(ResultKind.TEXT, 1.0)


def classify_content(payload: object) -> ClassificationResult:
    """Classify tool output. Returns ClassificationResult.

    Phase B: EMPTY (empty/whitespace-only) or TEXT (everything else).
    Phase C adds: SEARCH, DIFF, JSON, LOG, TABLE, CODE, BINARY.
    """
    output_raw = getattr(payload, "output_raw", None) or ""
    return _cached_classify(output_raw)


# Expose cache_clear for tests
classify_content.cache_clear = _cached_classify.cache_clear  # type: ignore[attr-defined]
