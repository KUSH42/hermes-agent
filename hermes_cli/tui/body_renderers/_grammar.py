"""Shared visual grammar for all body renderers — glyphs, colors, header/gutter builders."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

_log = logging.getLogger(__name__)

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
    accent:        str  # hex, e.g. "#0178D4"
    muted:         str  # hex text-muted
    success:       str  # hex success fg
    error:         str  # hex error fg
    warning:       str  # hex warning fg
    info:          str  # hex info fg (distinct from accent)
    icon_dim:      str  # spinner low-end / dimmed tool icon
    separator_dim: str  # header tail separators (chevron slot, meta sep)
    diff_add_bg:   str  # low-saturation add background
    diff_del_bg:   str  # low-saturation del background
    syntax_theme:  str  # pygments theme name
    syntax_scheme: str  # SYNTAX_SCHEMES key (logical token palette)

    @classmethod
    def from_app(cls, app) -> "SkinColors":
        """Resolve skin vars at mount time. Falls back to defaults when unresolved."""
        if app is None:
            return cls.default()
        try:
            css_vars: dict[str, str] = app.get_css_variables()
        except Exception:
            _log.debug("SkinColors.from_app: get_css_variables failed", exc_info=True)
            return cls.default()
        d = cls.default()

        _hex_re = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")
        _NON_HEX_KEYS = {"syntax-theme", "syntax-scheme"}

        def _get(key: str, fallback: str) -> str:
            v = css_vars.get(key, "").strip()
            if not v:
                return fallback
            # Non-hex string keys (syntax-theme, syntax-scheme) bypass hex validation.
            if key in _NON_HEX_KEYS or fallback == "ansi_dark":
                return v
            return v if _hex_re.match(v) else fallback

        return cls(
            accent=_get("primary",        d.accent),
            muted=_get("text-muted",      d.muted),
            success=_get("success",       d.success),
            error=_get("error",           d.error),
            warning=_get("warning",       d.warning),
            info=_get("info",             d.info),
            icon_dim=_get("icon-dim",           d.icon_dim),
            separator_dim=_get("separator-dim", d.separator_dim),
            diff_add_bg=_get("diff-add-bg", d.diff_add_bg),
            diff_del_bg=_get("diff-del-bg", d.diff_del_bg),
            syntax_theme=_get("syntax-theme",   d.syntax_theme),
            syntax_scheme=_get("syntax-scheme", d.syntax_scheme),
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
            icon_dim="#6e6e6e",
            separator_dim="#444444",
            diff_add_bg="#1a3a1a",  # aligned with COMPONENT_VAR_DEFAULTS["diff-add-bg"]
            diff_del_bg="#3a1a1a",  # aligned with COMPONENT_VAR_DEFAULTS["diff-del-bg"]
            syntax_theme="ansi_dark",
            syntax_scheme="hermes",
        )

    def resolve_syntax_palette(
        self, overrides: "dict[str, str] | None" = None
    ) -> "dict[str, str]":
        """Return SYNTAX_SCHEMES[self.syntax_scheme] merged with optional overrides.

        Unknown scheme → empty dict (caller falls back). Returned dict is a
        fresh copy; mutating it does not affect SYNTAX_SCHEMES.
        """
        from hermes_cli.skin_engine import SYNTAX_SCHEMES
        base = dict(SYNTAX_SCHEMES.get(self.syntax_scheme, {}))
        if overrides:
            base.update({k: v for k, v in overrides.items() if isinstance(v, str)})
        return base


# ---------------------------------------------------------------------------
# Header / gutter / rule builders
# ---------------------------------------------------------------------------

def build_path_header(
    path: str,
    *,
    right_meta: "str | Text" = "",
    colors: "SkinColors | None" = None,
) -> "object":
    """Render '▸ path/to/file.py  · N' with accent ▸, bold path, dim meta."""
    d = SkinColors.default()
    accent = colors.accent if colors else d.accent
    muted  = colors.muted  if colors else d.muted

    t = Text()
    t.append(glyph("▸") + " ", style=Style(color=accent))
    t.append(path, style=Style(bold=True))
    if right_meta:
        t.append(f"  {glyph('·')} ", style=Style(color=muted))
        if isinstance(right_meta, str):
            t.append(right_meta, style=Style(color=muted))
        else:
            t.append_text(right_meta)
    return t


def build_gutter_line_num(line_num: int, *, colors: "SkinColors | None" = None) -> "object":
    """Render `    42 │ ` right-padded to 6 chars + gutter glyph."""
    muted = colors.muted if colors else SkinColors.default().muted

    t = Text()
    t.append(f"{line_num:>{GUTTER_LINE_NUM_WIDTH}}", style=Style(color=muted))
    t.append(f" {glyph('│')} ", style=Style(color=muted))
    return t


def build_rule(label: str = "", *, colors: "SkinColors | None" = None) -> "object":
    """Render '── label ──' as a dim horizontal rule; empty label → just '──'."""
    muted = colors.muted if colors else SkinColors.default().muted

    t = Text(style=Style(color=muted))
    t.append(glyph("──"))
    if label:
        t.append(f" {label} ")
        t.append(glyph("──"))
    return t


def truncation_footer(
    *,
    hidden_n: int,
    unit: str = "lines",
    action: str = "expand",
    colors: "SkinColors | None" = None,
) -> "object":
    """'── 47 lines hidden · expand ──' — single wording, dim muted."""
    label = f"{hidden_n} {unit} hidden {glyph('·')} {action}"
    return build_rule(label, colors=colors)


def diff_gutter(sign: str, *, colors: SkinColors) -> Text:
    """Return a fixed-width non-copyable diff gutter."""
    if sign not in ("+", "-", " "):
        raise ValueError(f"diff_gutter: sign must be '+', '-', or ' ', got {sign!r}")
    color = {"+": colors.success, "-": colors.error, " ": colors.muted}[sign]
    t = Text()
    t.append(sign + " ", style=Style(color=color, meta={"copyable": False}))
    return t


# ---------------------------------------------------------------------------
# BodyFooter — sticky per-panel affordance footer
# ---------------------------------------------------------------------------

from textual.widgets import Static


class BodyFooter(Static):
    """Sticky single-line footer advertising key affordances.

    Each entry: either plain str or (key, label) tuple.
    Entries separated by ' · ' (GLYPH_META_SEP).
    """

    DEFAULT_CSS = """
BodyFooter {
    dock: bottom;
    height: 1;
    color: $text-muted 70%;
    padding: 0 1;
}
"""

    def __init__(
        self,
        *entries: "str | tuple[str, str]",
        **kwargs,
    ) -> None:
        super().__init__("", **kwargs)
        self._entries = entries
        self._colors: SkinColors | None = None

    def on_mount(self) -> None:
        try:
            self._colors = SkinColors.from_app(self.app)
        except Exception:
            _log.debug("BodyFooter.on_mount: SkinColors.from_app failed", exc_info=True)
            self._colors = SkinColors.default()
        self.refresh()

    def render(self) -> "object":
        colors = self._colors if self._colors is not None else SkinColors.default()
        sep = f" {glyph('·')} "
        t = Text()
        for i, entry in enumerate(self._entries):
            if i:
                t.append(sep, style=Style(color=colors.separator_dim))
            if isinstance(entry, tuple):
                key, label = entry
                t.append(f"[{key}]", style=Style(color=colors.muted, bold=True))
                t.append(f" {label}", style=Style(color=colors.muted))
            else:
                t.append(entry, style=Style(color=colors.muted))
        return t


# ---------------------------------------------------------------------------
# build_parse_failure — body for parse-error states
# ---------------------------------------------------------------------------

def build_parse_failure(
    text: str,
    err: Exception,
    *,
    colors: "SkinColors | None" = None,
) -> "object":
    """Return a Rich Text renderable for a parse-failure body."""
    error_color = (colors.error if colors else None) or "#E06C75"
    t = Text()
    for line in text.splitlines():
        t.append(line, style=Style(dim=True))
        t.append("\n")
    t.append(f"Parse error: {err}", style=Style(color=error_color))
    return t
