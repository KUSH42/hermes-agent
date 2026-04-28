"""Color resolution utilities for the drawbraille animation overlay.

No Textual dependency — only stdlib + optional rich.color.Color.
"""
from __future__ import annotations


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """'#rrggbb' → (r, g, b) integers."""
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return r, g, b


def _hue_rotate(hex_color: str, delta: float) -> str:
    """Rotate the hue of '#rrggbb' by delta turns (0..1). Preserves lightness/saturation."""
    import colorsys
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except Exception:  # invalid hex input — return original string as-is
        return hex_color
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    h = (h + delta) % 1.0
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(
        int(nr * 255), int(ng * 255), int(nb * 255)
    )


def _expand_short_hex(h: str) -> str:
    """#abc → #aabbcc."""
    h = h.lstrip("#")
    return f"#{h[0]*2}{h[1]*2}{h[2]*2}"


def _rich_to_hex(value: str) -> str:
    try:
        from rich.color import Color as RichColor
        triplet = RichColor.parse(value).get_truecolor()
        return f"#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}"
    except Exception:  # rich colour parse failed — fall back to default cyan
        return "#00d7ff"


def _resolve_color(value: str, app: object, dim: float = 1.0) -> str:
    """Resolve TCSS var ref, named color, or hex → '#rrggbb' string.

    'auto' maps to '$accent' (resolved via CSS vars).
    dim ∈ [0,1] multiplies each RGB channel — used for fade-out.
    """
    if value == "auto":
        value = "$accent"
    if value.startswith("$"):
        var_name = value[1:]
        try:
            css_vars: dict[str, str] = app.get_css_variables()  # type: ignore[attr-defined]
            raw = css_vars.get(var_name, "")
            if raw and raw.startswith("#") and len(raw) in (4, 7):
                resolved_hex = raw if len(raw) == 7 else _expand_short_hex(raw)
            elif raw:
                resolved_hex = _rich_to_hex(raw)
            else:
                resolved_hex = "#00d7ff"
        except Exception:  # app.get_css_variables() unavailable (e.g. test env) — use default
            resolved_hex = "#00d7ff"
    else:
        resolved_hex = _rich_to_hex(value)

    if dim < 1.0:
        r, g, b = _hex_to_rgb(resolved_hex)
        r, g, b = int(r * dim), int(g * dim), int(b * dim)
        return f"#{r:02x}{g:02x}{b:02x}"
    return resolved_hex
