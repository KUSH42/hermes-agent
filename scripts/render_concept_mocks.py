#!/usr/bin/env python3
"""Generate colour-rendered SVG mocks for docs/concept.md.

Renders two illustrative mocks from the default skin palette:
  1. HERO + STREAMING + focused  → docs/concept_mocks/hero_streaming.svg
  2. DEFAULT + ERR + unfocused   → docs/concept_mocks/default_err.svg

Inserts/updates content between sentinel comments in concept.md:
  <!-- coloured-mocks-start --> ... <!-- coloured-mocks-end -->

Run: python scripts/render_concept_mocks.py [--concept CONCEPT_MD]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
CONCEPT_MD = DOCS_DIR / "concept.md"
MOCKS_DIR = DOCS_DIR / "concept_mocks"

SENTINEL_START = "<!-- coloured-mocks-start -->"
SENTINEL_END = "<!-- coloured-mocks-end -->"
HEADING = "## Canonical block mocks"

MOCK_REFS = """\
<!-- coloured-mocks-start -->
![HERO + STREAMING + focused](concept_mocks/hero_streaming.svg)
![DEFAULT + ERR + unfocused](concept_mocks/default_err.svg)

> These mocks are regenerated from the bundled default skin palette via
> `scripts/render_concept_mocks.py`. They are illustrative — every shipped
> skin clears the contrast gate, so a skin substitution does not change
> recognition; only hue. If the gate ever changes (e.g. moving from 4.5:1 to
> 7:1 for body text), regenerate and review.
<!-- coloured-mocks-end -->"""


def _get_colors():
    try:
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        return SkinColors.default()
    except Exception:
        class _Fallback:
            accent = "#61AFEF"
            error = "#E06C75"
            success = "#98C379"
            muted = "#5C6370"
            surface = "#282C34"
            border = "#3E4451"
        return _Fallback()


def _hex(color: str) -> str:
    """Ensure color is a hex string."""
    if color.startswith("#"):
        return color
    return "#888888"


def _svg_hero_streaming(colors) -> str:
    acc = _hex(colors.accent)
    suc = _hex(colors.success)
    mut = _hex(colors.muted)
    bg = _hex(getattr(colors, "surface", "#282C34"))
    bd = _hex(getattr(colors, "border", "#3E4451"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="160" font-family="monospace" font-size="13">
  <rect width="640" height="160" fill="{bg}" rx="4"/>
  <rect x="0" y="0" width="4" height="160" fill="{acc}"/>
  <text x="16" y="24" fill="{acc}">▸ </text>
  <text x="36" y="24" fill="{acc}" font-weight="bold">± read_file</text>
  <text x="220" y="24" fill="{mut}">  · streaming · HERO</text>
  <text x="560" y="24" fill="{mut}" font-size="11">~diff</text>
  <text x="16" y="48" fill="{mut}">  ┃ </text>
  <text x="52" y="48" fill="{suc}">diff --git a/src/foo.py b/src/foo.py</text>
  <text x="16" y="68" fill="{mut}">  ┃ </text>
  <text x="52" y="68" fill="{suc}">+++ b/src/foo.py</text>
  <text x="16" y="88" fill="{mut}">  ┃ </text>
  <text x="52" y="88" fill="#E06C75">--- a/src/foo.py</text>
  <text x="16" y="108" fill="{mut}">  ┃ </text>
  <text x="52" y="108" fill="{mut}">@@ -10,4 +10,5 @@</text>
  <text x="16" y="132" fill="{acc}" font-size="11">[y] copy  [c] collapse  [t] kind</text>
</svg>"""


def _svg_default_err(colors) -> str:
    err = _hex(colors.error)
    mut = _hex(colors.muted)
    bg = _hex(getattr(colors, "surface", "#282C34"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120" font-family="monospace" font-size="13">
  <rect width="640" height="120" fill="{bg}" rx="4"/>
  <rect x="0" y="0" width="4" height="120" fill="{err}"/>
  <text x="16" y="24" fill="{err}">▸ </text>
  <text x="36" y="24" fill="{err}" font-weight="bold">✗ bash</text>
  <text x="130" y="24" fill="{err}">  ERR · exit 1</text>
  <text x="360" y="24" fill="{mut}">  · 1.2s</text>
  <text x="16" y="48" fill="{mut}">    Permission denied: /etc/shadow</text>
  <text x="16" y="72" fill="{mut}">    </text>
  <text x="16" y="96" fill="{err}" font-size="11">[r] retry  [y] copy output</text>
</svg>"""


def _update_concept_md(concept_path: Path, mocks_dir: Path) -> None:
    text = concept_path.read_text(encoding="utf-8")
    if SENTINEL_START in text and SENTINEL_END in text:
        # Replace between sentinels.
        pattern = re.compile(
            re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END),
            re.DOTALL,
        )
        text = pattern.sub(MOCK_REFS, text)
    else:
        # Insert after the heading line.
        heading_pos = text.find(HEADING)
        if heading_pos == -1:
            print(f"WARNING: '{HEADING}' not found in {concept_path}; skipping sentinel insert.")
            return
        insert_at = text.find("\n", heading_pos) + 1
        text = text[:insert_at] + "\n" + MOCK_REFS + "\n" + text[insert_at:]
    concept_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concept", type=Path, default=CONCEPT_MD)
    parser.add_argument("--out-dir", type=Path, default=MOCKS_DIR)
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    colors = _get_colors()

    hero_svg = out_dir / "hero_streaming.svg"
    hero_svg.write_text(_svg_hero_streaming(colors), encoding="utf-8")
    print(f"Wrote {hero_svg}")

    err_svg = out_dir / "default_err.svg"
    err_svg.write_text(_svg_default_err(colors), encoding="utf-8")
    print(f"Wrote {err_svg}")

    _update_concept_md(args.concept, out_dir)
    print(f"Updated {args.concept}")


if __name__ == "__main__":
    main()
