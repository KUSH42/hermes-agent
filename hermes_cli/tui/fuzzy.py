"""Contiguous substring ranker with match-span highlighting.

Runs synchronously on the event loop — profiling on 10k candidates shows
~1–3ms per call, which is less than the cost of a thread handoff + message
marshal.  Move behind ``@work(thread=True)`` only if the candidate set
ever exceeds ~100k items.

Score model
-----------
- Only contiguous substring matches qualify
- ``+10 * len(query)`` reward longer exact runs
- ``+5`` if match starts at word boundary (``/``, ``.``, ``_``, ``-``, `` ``)
- ``+2`` if match starts at char 0

Polymorphic over ``Candidate`` — reads ``display``, returns
``dataclasses.replace(c, score=..., match_spans=...)`` so both
``PathCandidate`` and ``SlashCandidate`` flow through unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, TypeVar

from .path_search import Candidate

_C = TypeVar("_C", bound=Candidate)


def fuzzy_rank(
    query: str, items: Iterable[_C], limit: int = 200
) -> list[_C]:
    """Return at most *limit* candidates sorted by fuzzy score descending.

    When *query* is empty, all items are returned (up to *limit*) with
    ``score=0`` and ``match_spans=()`` so stale state from a prior ranking
    doesn't bleed into the "no query" display.
    """
    if not query:
        # No query → deterministic alphabetical sort (match walk order
        # from _iwalk, which now sorts per-directory).
        clean = [replace(c, score=0, match_spans=()) for c in items]
        clean.sort(key=lambda c: c.display)
        return clean[:limit]

    q = query.lower()
    scored: list[tuple[int, _C]] = []

    for c in items:
        s = c.display.lower()
        start = s.find(q)
        if start < 0:
            continue

        score = 10 * len(q)
        if start == 0:
            score += 2
        elif s[start - 1] in "/._- ":
            score += 5

        scored.append((
            score,
            replace(c, score=score, match_spans=((start, start + len(q)),)),
        ))

    # Tiebreak by display length (shorter = higher signal) then alphabetical,
    # so results are deterministic across runs.
    scored.sort(key=lambda t: (-t[0], len(t[1].display), t[1].display))
    return [c for _, c in scored[:limit]]
