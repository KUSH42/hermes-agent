"""AnimConfigPanel, AnimGalleryOverlay, _GalleryPreview — config/gallery widgets.

Extracted from drawbraille_overlay.py (Phase 1 split).
These widgets depend on drawbraille_overlay at runtime (query_one, _cfg_from_mapping,
etc.), so they import from it at runtime (not TYPE_CHECKING only).

Circular import note: drawbraille_overlay re-exports AnimConfigPanel etc. at the
*bottom* of the file, after all names (DrawbrailleOverlay, DrawbrailleOverlayCfg,
module constants) are defined. This file imports from drawbraille_overlay at module
load time, but that import executes after Python has already finished processing
drawbraille_overlay's top-level code (because the re-export trigger at the bottom
means drawbraille_overlay is fully initialized before Python processes the
circular-import resolution). Safe as long as the re-export block stays at the bottom.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

# Runtime imports — needed for query_one(), isinstance(), and direct function calls.
# Note: _overlay_config is NOT imported here at module level; callers use
# hermes_cli.tui.drawbraille_overlay._overlay_config lazily so that test patches
# on that name propagate correctly.
from hermes_cli.tui.drawbraille_overlay import (
    DrawbrailleOverlay,
    DrawbrailleOverlayCfg,
    _cfg_from_mapping,
    _ENGINES,
    _ENGINE_META,
    _PHASE_CATEGORIES,
    _PRESETS,
)
from hermes_cli.tui.anim_engines import AnimParams


# ── Panel field descriptor ────────────────────────────────────────────────────

@dataclass
class _PanelField:
    name: str
    label: str
    kind: str               # "cycle" | "int" | "float" | "toggle" | "color"
    value: object           # current value
    choices: list | None = None   # for cycle fields
    min_val: float = 1
    max_val: float = 15
    step: float = 0.05      # used by "float" kind; ignored for other kinds


# ── ANIMATION_KEYS ─────────────────────────────────────────────────────────────
# Must be defined BEFORE AnimConfigPanel class body (used in _build_fields).

ANIMATION_KEYS: list[str] = list(_ENGINES.keys()) + ["sdf_morph"]


# ── Panel config helpers ──────────────────────────────────────────────────────

_PANEL_CONFIG_KEYS: dict[str, str] = {
    "enabled": "enabled",
    "animation": "animation",
    "trigger": "trigger",
    "fps": "fps",
    "position": "position",
    "size_name": "size",
    "color": "color",
    "gradient": "gradient",
    "color_b": "color_secondary",
    "hue_shift_speed": "hue_shift_speed",
    "dim_bg": "dim_background",
    "show_border": "show_border",
    "vertical": "vertical",
    "ambient_enabled": "ambient_enabled",
    "ambient_engine": "ambient_engine",
    "ambient_heat": "ambient_heat",
    "ambient_alpha": "ambient_alpha",
    "carousel": "carousel",
    "carousel_interval_s": "carousel_interval_s",
    "blend_mode": "blend_mode",
    "layer_b": "layer_b",
    "trail_decay": "trail_decay",
    "particle_count": "particle_count",
    "symmetry": "symmetry",
    "attractor_type": "attractor_type",
    "life_seed": "life_seed",
    "depth_cues": "depth_cues",
}


def _panel_updates(fields: list[_PanelField]) -> dict:
    updates: dict = {}
    for f in fields:
        key = _PANEL_CONFIG_KEYS.get(f.name)
        if key is None:
            continue
        value = f.value
        if key in {"enabled", "gradient", "dim_background", "show_border", "vertical",
                   "ambient_enabled", "carousel", "depth_cues"}:
            value = bool(value)
        elif key in {"fps", "particle_count", "symmetry"}:
            value = int(value)
        elif key in {"hue_shift_speed", "ambient_heat", "ambient_alpha",
                     "carousel_interval_s", "trail_decay"}:
            value = float(value)
        elif key in {"animation", "trigger", "position", "size", "color",
                     "color_secondary", "ambient_engine", "blend_mode", "layer_b",
                     "attractor_type", "life_seed"}:
            value = str(value)
        updates[key] = value
    return updates


def _current_panel_cfg(fields: list[_PanelField]) -> DrawbrailleOverlayCfg:
    """Build a DrawbrailleOverlayCfg from current panel fields.

    Starts from the current full config so preview/live changes preserve
    advanced keys that the compact panel does not expose.

    NOTE: _overlay_config() is imported lazily via module ref so that test
    patches on hermes_cli.tui.drawbraille_overlay._overlay_config propagate.
    """
    from dataclasses import replace
    import hermes_cli.tui.drawbraille_overlay as _dbo
    base = _dbo._overlay_config()
    return replace(base, **_panel_updates(fields))


def _fields_to_dict(fields: list[_PanelField]) -> dict:
    """Convert panel fields to a full config dict, preserving hidden keys."""
    from dataclasses import asdict
    import hermes_cli.tui.drawbraille_overlay as _dbo
    data = asdict(_dbo._overlay_config())
    data.update(_panel_updates(fields))
    if data.get("multi_color") is None:
        data["multi_color"] = []
    return data


# ── AnimConfigPanel ───────────────────────────────────────────────────────────

class AnimConfigPanel(Widget):
    """Non-modal config overlay for the drawbraille animation.

    Pre-mounted in app compose. Toggled via ``--visible`` class.
    Opened by ``/anim config`` slash command or ``ctrl+shift+a``.
    Dismissed by ``Escape``.
    """

    COMPONENT_CLASSES = {
        "anim-config-panel--field",
        "anim-config-panel--focused",
        "anim-config-panel--button",
    }

    DEFAULT_CSS = """
    AnimConfigPanel {
        layer: overlay;
        align: center middle;
        display: none;
        width: 74;
        height: auto;
        max-height: 30;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    AnimConfigPanel.--visible { display: block; }
    AnimConfigPanel > VerticalScroll {
        width: 1fr;
        height: auto;
        max-height: 24;
    }
    """

    BINDINGS = [
        Binding("escape",     "dismiss",       "Close",         show=False, priority=True),
        Binding("tab",        "next_field",    "Next field",    show=False),
        Binding("shift+tab",  "prev_field",    "Prev field",    show=False),
        Binding("left",       "cycle_left",    "Prev value",    show=False),
        Binding("right",      "cycle_right",   "Next value",    show=False),
        Binding("up",         "inc_value",     "Increase",      show=False),
        Binding("down",       "dec_value",     "Decrease",      show=False),
        Binding("space",      "toggle_value",  "Toggle",        show=False),
        Binding("enter",      "activate",      "Activate",      show=False),
    ]

    can_focus = True

    _focus_idx: int = 0
    _preview_timer: "Timer | None" = None
    _color_editing: bool = False

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._fields: list[_PanelField] = []
        self._build_fields()

    def show(self) -> None:
        """Show the panel and refresh fields from current config."""
        self._build_fields()
        self._refresh_body()
        self.add_class("--visible")
        self.focus()

    def _build_fields(self, cfg: DrawbrailleOverlayCfg | None = None) -> None:
        import hermes_cli.tui.drawbraille_overlay as _dbo
        cfg = cfg or _dbo._overlay_config()
        layer_b_choices = [""] + [k for k in ANIMATION_KEYS if k != "sdf_morph"]
        self._fields = [
            # ── Core ──────────────────────────────────────────────────────
            _PanelField("enabled",    "Enabled",   "toggle", cfg.enabled),
            _PanelField("animation",  "Animation", "cycle",  cfg.animation,
                        choices=ANIMATION_KEYS),
            _PanelField("fps",        "FPS",       "int",    cfg.fps,
                        min_val=1, max_val=60),
            _PanelField("size_name",  "Size",      "cycle",  cfg.size,
                        choices=["small", "medium", "large", "fill"]),
            _PanelField("position",   "Position",  "cycle",  cfg.position,
                        choices=["center", "top-right", "bottom-right", "bottom-left", "top-left",
                                 "top-center", "bottom-center", "mid-right", "mid-left",
                                 "rail-right", "rail-left", "custom"]),
            _PanelField("trigger",    "Trigger",   "cycle",  cfg.trigger,
                        choices=["agent_running", "command_running", "always"]),
            # ── Color ─────────────────────────────────────────────────────
            _PanelField("color",      "Color",     "color",  cfg.color),
            _PanelField("gradient",   "Gradient",  "toggle", cfg.gradient),
            _PanelField("color_b",    "Color B",   "color",  cfg.color_secondary),
            _PanelField("hue_shift_speed", "Hue shift",  "float",  cfg.hue_shift_speed,
                        min_val=0.0, max_val=2.0, step=0.05),
            # ── Display ───────────────────────────────────────────────────
            _PanelField("show_border","Border",    "toggle", cfg.show_border),
            _PanelField("dim_bg",     "Dim BG",    "toggle", cfg.dim_background),
            _PanelField("vertical",   "Vertical",  "toggle", cfg.vertical),
            # ── Ambient idle (Phase D) ─────────────────────────────────────
            _PanelField("ambient_enabled", "Ambient",      "toggle", cfg.ambient_enabled),
            _PanelField("ambient_engine",  "Amb engine",   "cycle",  cfg.ambient_engine,
                        choices=["perlin_flow", "neural_pulse", "wave_collapse", "boids", "dna"]),
            _PanelField("ambient_heat",    "Amb heat",     "float",  cfg.ambient_heat,
                        min_val=0.0, max_val=1.0, step=0.02),
            _PanelField("ambient_alpha",   "Amb alpha",    "float",  cfg.ambient_alpha,
                        min_val=0.05, max_val=1.0, step=0.05),
            # ── Carousel ──────────────────────────────────────────────────
            _PanelField("carousel",           "Carousel",   "toggle", cfg.carousel),
            _PanelField("carousel_interval_s","Carsl intv", "float",  cfg.carousel_interval_s,
                        min_val=2.0, max_val=60.0, step=1.0),
            # ── v2 compositing ────────────────────────────────────────────
            _PanelField("blend_mode",     "Blend",       "cycle",  cfg.blend_mode,
                        choices=["overlay", "additive", "xor", "dissolve"]),
            _PanelField("layer_b",        "Layer B",     "cycle",  cfg.layer_b,
                        choices=layer_b_choices),
            _PanelField("trail_decay",    "Trail",       "float",  cfg.trail_decay,
                        min_val=0.0, max_val=0.98, step=0.05),
            _PanelField("particle_count", "Particles",   "int",    cfg.particle_count,
                        min_val=10, max_val=200),
            _PanelField("symmetry",       "Symmetry",    "int",    cfg.symmetry,
                        min_val=1, max_val=12),
            _PanelField("attractor_type", "Attractor",   "cycle",  cfg.attractor_type,
                        choices=["lorenz", "rossler", "thomas"]),
            _PanelField("life_seed",      "Life seed",   "cycle",  cfg.life_seed,
                        choices=["gosper", "acorn", "puffer", "random"]),
            _PanelField("depth_cues",     "Depth cues",  "toggle", cfg.depth_cues),
        ]
        self._focus_idx = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self._build_text(), id="anim-config-body")

    def on_mount(self) -> None:
        pass

    def _get_overlay(self) -> "DrawbrailleOverlay | None":
        try:
            return self.app.query_one(DrawbrailleOverlay)
        except (NoMatches, Exception):
            return None

    # ── rendering ──────────────────────────────────────────────────────────

    def _build_text(self) -> Text:
        lines: list[str] = []
        lines.append("─ Animation Config ─")
        row: list[str] = []
        for i, f in enumerate(self._fields):
            focused = i == self._focus_idx
            val_str = self._format_field_value(f)
            bracket_l = "["
            bracket_r = "]"
            cell = f"  {f.label} {bracket_l}{val_str}{bracket_r}"
            if focused:
                row.append(f"\x1b[7m{cell}\x1b[0m")
            else:
                row.append(cell)
            if len(row) == 2:
                lines.append("  ".join(row))
                row = []
            # E1: show engine description below animation field
            if f.name == "animation" and focused:
                desc = _ENGINE_META.get(str(f.value), {}).get("desc", "")
                if desc:
                    lines.append("")  # flush the current row first
                    row = []
                    lines.append(f"     \x1b[2m{desc}\x1b[0m")
        if row:
            lines.append(row[0])
        lines.append("")
        lines.append("  [P] Preview  [S] Save  [R] Reset  Esc close")
        return Text.from_ansi("\n".join(lines))

    def _refresh_body(self) -> None:
        """Update the Static child with current field state."""
        try:
            self.query_one("#anim-config-body", Static).update(self._build_text())
        except (NoMatches, Exception):
            pass

    def _format_field_value(self, f: _PanelField) -> str:
        if f.kind == "cycle":
            if f.name == "animation":
                key = str(f.value)
                cat = _ENGINE_META.get(key, {}).get("category", "")
                badge = f"[{cat[:3].upper()}] " if cat else ""
                return (badge + key)[:18]
            return str(f.value)[:16]
        elif f.kind == "int":
            return str(f.value)
        elif f.kind == "float":
            return f"{float(f.value):.2f}"
        elif f.kind == "toggle":
            return "on" if f.value else "off"
        else:  # color
            return str(f.value)[:12]

    # ── key actions ────────────────────────────────────────────────────────

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def on_blur(self, event: object) -> None:
        """Trap focus: while visible, never let focus escape the panel."""
        if not self.has_class("--visible"):
            return
        try:
            from hermes_cli.tui.overlays.interrupt import InterruptOverlay as _IO
            io = self.app.query_one(_IO)
            if io.has_class("--visible"):
                return
        except Exception:
            pass
        try:
            self.call_after_refresh(self.focus)
        except Exception:
            pass

    def action_next_field(self) -> None:
        self._focus_idx = (self._focus_idx + 1) % len(self._fields)
        self._refresh_body()

    def action_prev_field(self) -> None:
        self._focus_idx = (self._focus_idx - 1) % len(self._fields)
        self._refresh_body()

    def action_cycle_right(self) -> None:
        self._cycle(+1)

    def action_cycle_left(self) -> None:
        self._cycle(-1)

    def action_inc_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = min(int(f.max_val), int(f.value) + 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) + f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()

    def action_dec_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "int":
            f.value = max(int(f.min_val), int(f.value) - 1)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()
        elif f.kind == "float":
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) - f.step)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()

    def action_toggle_value(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self._refresh_body()

    def action_activate(self) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "toggle":
            f.value = not f.value
            self._push_to_overlay(f)
            self._refresh_body()
        elif f.kind == "cycle":
            self._cycle(+1)
        elif f.kind == "color":
            self._cycle_color(f, +1)

    def on_key(self, event: object) -> None:
        """Handle P/S/R shortcuts."""
        key = getattr(event, "key", "")
        if key == "p":
            self._do_preview()
        elif key == "s":
            self._do_save()
        elif key == "r":
            self._do_reset()

    def _cycle(self, direction: int) -> None:
        f = self._fields[self._focus_idx]
        if f.kind == "float":
            delta = f.step * direction
            f.value = round(max(float(f.min_val), min(float(f.max_val), float(f.value) + delta)), 6)  # type: ignore[assignment]
            self._push_to_overlay(f)
            self._refresh_body()
            return
        if f.kind == "color":
            self._cycle_color(f, direction)
            return
        if f.kind != "cycle" or not f.choices:
            return
        idx = (f.choices.index(str(f.value)) + direction) % len(f.choices)
        f.value = f.choices[idx]
        self._push_to_overlay(f)
        self._refresh_body()

    def _cycle_color(self, f: _PanelField, direction: int) -> None:
        palette = [
            "auto",
            "$accent",
            "$primary",
            "#00d7ff",
            "#00ff41",
            "#ff00aa",
            "#ffb454",
            "#ffffff",
        ]
        current = str(f.value)
        if current not in palette:
            palette = [current] + palette
            idx = 0
        else:
            idx = palette.index(current)
        f.value = palette[(idx + direction) % len(palette)]
        self._push_to_overlay(f)
        self._refresh_body()

    def _push_to_overlay(self, f: _PanelField) -> None:
        """Apply field change to DrawbrailleOverlay reactive immediately."""
        ov = self._get_overlay()
        if ov is None:
            return
        attr_map = {
            "enabled":       None,    # not a reactive; applied via show()/hide()
            "animation":     "animation",
            "fps":           "fps",
            "size_name":     "size_name",
            "position":      "position",
            "color":         "color",
            "gradient":      "gradient",
            "color_b":       "color_b",
            "hue_shift_speed": "hue_shift_speed",
            "trigger":       None,    # not a reactive on overlay
            "show_border":   "show_border",
            "dim_bg":        "dim_bg",
            "vertical":      "vertical",
            # ambient — not reactives; applied via _cfg on show()
            "ambient_enabled": None,
            "ambient_engine":  None,
            "ambient_heat":    None,
            "ambient_alpha":   None,
            # carousel — not reactives; applied via show()
            "carousel":           None,
            "carousel_interval_s": None,
            # v2 attrs
            "blend_mode":    "blend_mode",
            "layer_b":       "layer_b",
            "trail_decay":   "trail_decay",
            "particle_count": "particle_count",
            "symmetry":      "symmetry",
            "attractor_type": "attractor_type",
            "life_seed":     "life_seed",
            "depth_cues":    "depth_cues",
        }
        attr = attr_map.get(f.name)
        if attr is not None:
            setattr(ov, attr, f.value)
        if f.name in {
            "enabled",
            "trigger",
            "ambient_enabled",
            "ambient_engine",
            "ambient_heat",
            "ambient_alpha",
            "carousel",
            "carousel_interval_s",
        }:
            cfg = _current_panel_cfg(self._fields)
            if cfg.enabled and (cfg.trigger == "always" or ov.has_class("-visible")):
                ov.show(cfg)
            elif not cfg.enabled:
                ov.hide(cfg)

    # ── preview / save / reset ─────────────────────────────────────────────

    def _do_preview(self) -> None:
        ov = self._get_overlay()
        if ov is None:
            return
        cfg = _current_panel_cfg(self._fields)
        cfg.enabled = True
        ov.show(cfg)
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = self.set_timer(3.0, self._end_preview)

    def _end_preview(self) -> None:
        self._preview_timer = None
        try:
            if not self.app.agent_running:   # type: ignore[attr-defined]
                import hermes_cli.tui.drawbraille_overlay as _dbo
                ov = self._get_overlay()
                if ov is not None:
                    ov.hide(_dbo._overlay_config())
        except Exception:
            pass

    def _do_save(self) -> None:
        self._push_to_overlay_all()
        try:
            vals = _fields_to_dict(self._fields)
            try:
                self.app._svc_commands.persist_anim_config(vals)  # type: ignore[attr-defined]
            except Exception:
                # Fallback: direct write
                from hermes_cli.config import read_raw_config, save_config, _set_nested
                cfg = read_raw_config()
                _set_nested(cfg, "display.drawbraille_overlay", vals)
                save_config(cfg)
            try:
                from hermes_cli.tui.widgets import HintBar
                self.app.query_one(HintBar).hint = "✓ Saved to config"  # type: ignore[attr-defined]
                self.app.set_timer(2.0, lambda: None)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                ov = self._get_overlay()
                if ov is not None:
                    cfg = _current_panel_cfg(self._fields)
                    if cfg.enabled and cfg.trigger == "always":
                        ov.show(cfg)
                    elif not cfg.enabled:
                        ov.hide(cfg)
            except Exception:
                pass
        except Exception as exc:
            try:
                self.app.set_status_error(f"save failed: {exc}", auto_clear_s=5.0)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _push_to_overlay_all(self) -> None:
        """Apply all field changes to DrawbrailleOverlay."""
        for f in self._fields:
            self._push_to_overlay(f)

    def _do_reset(self) -> None:
        from dataclasses import replace
        from hermes_cli.config import DEFAULT_CONFIG
        d = DEFAULT_CONFIG["display"]["drawbraille_overlay"]  # type: ignore[index]
        cfg = _cfg_from_mapping(d)
        self._build_fields(cfg)
        ov = self._get_overlay()
        if ov is not None:
            ov.show(replace(cfg, enabled=True))
        self._refresh_body()


# ── _GalleryPreview ───────────────────────────────────────────────────────────

class _GalleryPreview(Widget):
    """Live engine preview widget for AnimGalleryOverlay and AnimConfigPanel."""

    DEFAULT_CSS = """
    _GalleryPreview {
        width: 20;
        height: 6;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._engine_key: str = ""
        self._engine: object | None = None
        self._preview_timer: "Timer | None" = None

    def set_engine(self, key: str) -> None:
        """Switch to a new engine. Creates a fresh instance."""
        self._engine_key = key
        if key == "sdf_morph":
            # SDF requires baking — use neural_pulse as stand-in
            self._engine = _ENGINES["neural_pulse"]()
        elif key in _ENGINES:
            self._engine = _ENGINES[key]()
            if hasattr(self._engine, "on_mount"):
                try:
                    self._engine.on_mount(self)  # type: ignore[arg-type]
                except Exception:
                    pass
        else:
            self._engine = None
        self.refresh()

    def _preview_tick(self) -> None:
        if self._engine is None:
            return
        try:
            params = AnimParams(width=40, height=24, heat=0.5)
            frame = self._engine.next_frame(params)
            params.t += params.dt
            self.update(frame)
        except Exception:
            pass

    def on_mount(self) -> None:
        self._engine = None
        self._preview_timer = self.set_interval(0.5, self._preview_tick)


# ── AnimGalleryOverlay ────────────────────────────────────────────────────────

class AnimGalleryOverlay(Widget):
    """Non-modal gallery overlay for browsing and selecting animation engines (B2)."""

    DEFAULT_CSS = """
    AnimGalleryOverlay {
        layer: overlay;
        align: center middle;
        display: none;
        width: 74;
        height: auto;
        max-height: 28;
        background: $surface;
        border: round $accent;
        padding: 0 1;
    }
    AnimGalleryOverlay.--visible { display: block; }
    AnimGalleryOverlay > Vertical {
        width: 1fr;
        height: auto;
        max-height: 24;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss",     "Close",   show=False, priority=True),
        Binding("enter",  "select",      "Select",  show=False),
        Binding("space",  "select",      "Select",  show=False),
        Binding("up",     "prev_item",   "Prev",    show=False),
        Binding("down",   "next_item",   "Next",    show=False),
        Binding("p",      "preview",     "Preview", show=False),
        Binding("s",      "open_config", "Config",  show=False),
    ]

    can_focus = True

    _focus_idx: int = 0

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._engine_list: list[str] = list(_ENGINES.keys()) + ["sdf_morph"]
        self._focus_idx = 0

    def show(self) -> None:
        """Show the gallery and focus it."""
        self._focus_idx = 0
        self.add_class("--visible")
        self._refresh_list()
        self._update_preview()
        self.focus()

    def compose(self) -> "ComposeResult":
        with Vertical():
            yield Static("", id="gallery-list")
            yield _GalleryPreview(id="gallery-preview")

    def on_mount(self) -> None:
        self._refresh_list()
        self._update_preview()

    def _refresh_list(self) -> None:
        lines: list[str] = []
        lines.append("─ Animation Gallery ─")
        for i, key in enumerate(self._engine_list):
            meta = _ENGINE_META.get(key, {})
            cat = meta.get("category", "")
            badge = f"[{cat[:3].upper()}]" if cat else "   "
            marker = ">" if i == self._focus_idx else " "
            lines.append(f"  {marker} {key:<22} {badge}")
        lines.append("")
        lines.append("  ↑↓ navigate · Enter select · P preview · Esc close")
        try:
            self.query_one("#gallery-list", Static).update("\n".join(lines))
        except (NoMatches, Exception):
            pass

    def _update_preview(self) -> None:
        try:
            key = self._engine_list[self._focus_idx]
            self.query_one(_GalleryPreview).set_engine(key)
        except (NoMatches, IndexError, Exception):
            pass

    def action_prev_item(self) -> None:
        self._focus_idx = (self._focus_idx - 1) % len(self._engine_list)
        self._refresh_list()
        self._update_preview()

    def action_next_item(self) -> None:
        self._focus_idx = (self._focus_idx + 1) % len(self._engine_list)
        self._refresh_list()
        self._update_preview()

    def action_select(self) -> None:
        try:
            key = self._engine_list[self._focus_idx]
            try:
                ov = self.app.query_one(DrawbrailleOverlay)
                ov.animation = key
            except (NoMatches, Exception):
                pass
            try:
                import hermes_cli.tui.drawbraille_overlay as _dbo
                cfg = _dbo._overlay_config()
                cfg.animation = key
            except Exception:
                pass
        except IndexError:
            pass
        self.action_dismiss()

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def action_preview(self) -> None:
        """Force-show overlay with selected engine for 5s."""
        try:
            import hermes_cli.tui.drawbraille_overlay as _dbo
            key = self._engine_list[self._focus_idx]
            ov = self.app.query_one(DrawbrailleOverlay)
            cfg = _dbo._overlay_config()
            cfg.enabled = True
            cfg.animation = key
            ov.animation = key
            ov.show(cfg)
            self.app.set_timer(5.0, lambda: None)  # type: ignore[attr-defined]
        except (NoMatches, Exception):
            pass

    def action_open_config(self) -> None:
        self.remove_class("--visible")
        try:
            self.app.query_one(AnimConfigPanel).show()
        except (NoMatches, Exception):
            pass
