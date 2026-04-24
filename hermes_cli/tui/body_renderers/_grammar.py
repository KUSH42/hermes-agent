"""Shared visual grammar for all body renderers — glyphs, colors, header/gutter builders."""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------

GLYPH_HEADER   = "▸"
GLYPH_GUTTER   = "│"
GLYPH_META_SEP = "·"
GLYPH_RULE     = "──"
GLYPH_ELLIPSIS = "…"

GUTTER_LINE_NUM_WIDTH = 6
GUTTER_SIGN_WIDTH     = 2

_ASCII_GLYPHS: dict[str, str] = {
    "▸": ">",
    "│": "|",
    "·": "-",
    "──": "--",
    "…": "...",
}


def glyph(g: str) -> str:
    """Return ASCII fallback when accessibility_mode() is on."""
    from hermes_cli.tui.constants import accessibility_mode
    return _ASCII_GLYPHS[g] if accessibility_mode() and g in _ASCII_GLYPHS else g


# ---------------------------------------------------------------------------
# SkinColors — resolved at widget-mount time, passed into builders
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkinColors:
    accent:       str  # hex, e.g. "#0178D4"
    muted:        str  # hex text-muted
    success:      str  # hex success fg
    error:        str  # hex error fg
    warning:      str  # hex warning fg
    info:         str  # hex info fg (distinct from accent)
    diff_add_bg:  str  # low-saturation add background
    diff_del_bg:  str  # low-saturation del background
    syntax_theme: str  # pygments theme name

    @classmethod
    def from_app(cls, app) -> "SkinColors":
        """Resolve skin vars at mount time. Falls back to defaults when unresolved."""
        if app is None:
            return cls.default()
        try:
            css_vars: dict[str, str] = app.get_css_variables()
        except Exception:
            return cls.default()
        d = cls.default()

        _hex_re = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")

        def _get(key: str, fallback: str) -> str:
            v = css_vars.get(key, "").strip()
            if not v:
                return fallback
            # Accept plain theme names for syntax-theme; require hex for color fields
            if fallback == "ansi_dark" or key == "syntax-theme":
                return v
            return v if _hex_re.match(v) else fallback

        return cls(
            accent=_get("primary",        d.accent),
            muted=_get("text-muted",      d.muted),
            success=_get("success",       d.success),
            error=_get("error",           d.error),
            warning=_get("warning",       d.warning),
            info=_get("info",             d.info),
            diff_add_bg=_get("diff-add-bg", d.diff_add_bg),
            diff_del_bg=_get("diff-del-bg", d.diff_del_bg),
            syntax_theme=_get("syntax-theme", d.syntax_theme),
        )

    @classmethod
    def default(cls) -> "SkinColors":
        """Hex defaults used when no app is available."""
        return cls(
            accent="#0178D4",
            muted="#888888",
            success="#4CAF50",
            error="#E06C75",
            warning="#FEA62B",
            info="#58A6FF",
            diff_add_bg="#0e2a16",
            diff_del_bg="#2a0e0e",
            syntax_theme="ansi_dark",
        )


# ---------------------------------------------------------------------------
# Header / gutter / rule builders
# ---------------------------------------------------------------------------

def build_path_header(path: str, *, right_meta: str = "", colors: "SkinColors | None" = None) -> "object":
    """Render '▸ path/to/file.py  · N' with accent ▸, bold path, dim meta."""
    from rich.text import Text
    from rich.style import Style

    d = SkinColors.default()
    accent = colors.accent if colors else d.accent
    muted  = colors.muted  if colors else d.muted

    t = Text()
    t.append(glyph("▸") + " ", style=Style(color=accent))
    t.append(path, style=Style(bold=True))
    if right_meta:
        t.append(f"  {glyph('·')} ", style=Style(color=muted))
        t.append(right_meta, style=Style(color=muted))
    return t


def build_gutter_line_num(line_num: int, *, colors: "SkinColors | None" = None) -> "object":
    """Render `    42 │ ` right-padded to 6 chars + gutter glyph."""
    from rich.text import Text
    from rich.style import Style

    muted = colors.muted if colors else SkinColors.default().muted

    t = Text()
    t.append(f"{line_num:>{GUTTER_LINE_NUM_WIDTH}}", style=Style(color=muted))
    t.append(f" {glyph('│')} ", style=Style(color=muted))
    return t


def build_rule(label: str = "", *, colors: "SkinColors | None" = None) -> "object":
    """Render '── label ──' as a dim horizontal rule; empty label → just '──'."""
    from rich.text import Text
    from rich.style import Style

    muted = colors.muted if colors else SkinColors.default().muted

    t = Text(style=Style(color=muted))
    t.append(glyph("──"))
    if label:
        t.append(f" {label} ")
        t.append(glyph("──"))
    return t


# ---------------------------------------------------------------------------
# BodyFooter — sticky per-panel affordance footer
# ---------------------------------------------------------------------------

from textual.widgets import Static


class BodyFooter(Static):
    """Sticky single-line footer advertising [c] copy · [o] open in $EDITOR."""

    DEFAULT_CSS = """
BodyFooter {
    dock: bottom;
    height: 1;
    color: $text-muted 70%;
    padding: 0 1;
}
"""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._colors: SkinColors | None = None

    def on_mount(self) -> None:
        try:
            self._colors = SkinColors.from_app(self.app)
        except Exception:
            self._colors = SkinColors.default()
        self.refresh()

    def render(self) -> "object":
        from rich.text import Text
        from rich.style import Style

        colors = self._colors if self._colors is not None else SkinColors.default()
        sep = glyph("·")
        t = Text()
        t.append("[c]", style=Style(color=colors.muted, bold=True))
        t.append(f" copy {sep} ", style=Style(color=colors.muted))
        t.append("[o]", style=Style(color=colors.muted, bold=True))
        t.append(" open in $EDITOR", style=Style(color=colors.muted))
        return t
