"""Grapheme cluster utilities for MSG-DEDUP Sub-fix C.

Pure functions — no widget or Textual dependencies.
"""
from __future__ import annotations
import unicodedata


def suffix_grapheme_count(s: str) -> int:
    """Count grapheme clusters in *s* using a ZWJ-aware codepoint scanner.

    Rules applied in order for each codepoint:
    - ZWJ (U+200D): skip; the following codepoint belongs to the current cluster.
    - Variation selectors U+FE00–U+FE0F: skip (part of preceding cluster).
    - Emoji skin-tone modifiers U+1F3FB–U+1F3FF: skip (part of preceding cluster).
    - Unicode general category Mn (non-spacing combining marks): skip.
    - Anything else: start a new cluster, count += 1; then consume any trailing
      modifiers listed above.

    Example results: '👨‍👩‍👧' → 1, '👋🏽' → 1, '🛳️' → 1, ' 🛳️' → 2, 'foo' → 3.
    """
    count = 0
    i = 0
    cps = list(s)
    n = len(cps)
    while i < n:
        c = cps[i]
        cp = ord(c)
        cat = unicodedata.category(c)
        # Skip: ZWJ, VS, skin-tone, non-spacing combining
        if (
            cp == 0x200D
            or 0xFE00 <= cp <= 0xFE0F
            or 0x1F3FB <= cp <= 0x1F3FF
            or cat == "Mn"
        ):
            i += 1
            continue
        # New cluster base
        count += 1
        i += 1
        # Consume trailing modifiers belonging to this cluster
        while i < n:
            nc = cps[i]
            ncp = ord(nc)
            ncat = unicodedata.category(nc)
            if (
                ncp == 0x200D
                or 0xFE00 <= ncp <= 0xFE0F
                or 0x1F3FB <= ncp <= 0x1F3FF
                or ncat == "Mn"
            ):
                i += 1
                if ncp == 0x200D and i < n:
                    # ZWJ: the immediately following grapheme base also joins
                    i += 1
            else:
                break
    return count
