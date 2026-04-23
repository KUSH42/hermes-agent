"""ConfigOverlay — canonical picker fan-in for R3 consolidation.

Replaces VerbosePickerOverlay, ModelPickerOverlay, TabbedSkinOverlay,
ReasoningPickerOverlay, YoloConfirmOverlay with a single tabbed overlay.

Per spec §2.1 of 2026-04-22-tui-v2-R3-overlay-consolidation-spec.md:
- 7 top-level tabs: model / skin / syntax / options / reasoning / verbose / yolo
- Tabs 2/3/4 carry what was TabbedSkinOverlay's 3 internal tabs, flattened
- ConfigOverlay owns overlay chrome; tab bodies are plain Widgets
- Pre-mounted; toggled via `--visible`; dismiss via Escape → focus HermesInput
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Checkbox, OptionList, Static
from textual.widgets.option_list import Option

from hermes_cli.tui.overlays._aliases import register_config_aliases
from hermes_cli.tui.overlays._legacy import (
    FIXTURE_CODE,
    _cfg_read_raw_config,
    _cfg_save_config,
    _cfg_set_nested,
    _dismiss_overlay_and_focus_input,
)

if TYPE_CHECKING:
    pass


# Tab roster — spec §2.1 table. Keys drive _AliasMeta.__instancecheck__.
_TABS: list[tuple[str, str, str]] = [
    # (tab_key, hotkey, label)
    ("model",     "1", "Model"),
    ("skin",      "2", "Skin"),
    ("syntax",    "3", "Syntax"),
    ("options",   "4", "Options"),
    ("reasoning", "5", "Reasoning"),
    ("verbose",   "6", "Verbose"),
    ("yolo",      "7", "YOLO"),
]

_TAB_KEYS: list[str] = [t[0] for t in _TABS]
_REASONING_LEVELS: list[str] = ["none", "low", "minimal", "medium", "high", "xhigh"]
_VERBOSE_CHOICES: list[tuple[str, str]] = [
    ("off",     "off      — no streaming tool output"),
    ("new",     "new      — stream output for new tools only"),
    ("all",     "all      — stream all tool output"),
    ("verbose", "verbose  — stream + expanded collapse thresholds"),
]


class ConfigOverlay(Widget):
    """Tabbed config overlay replacing 5 standalone picker overlays."""

    can_focus = True

    DEFAULT_CSS = """
    ConfigOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 30;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    ConfigOverlay.--visible { display: block; }
    ConfigOverlay > #co-tab-bar { color: $accent; margin-bottom: 1; }
    ConfigOverlay .co-section-header { color: $accent; }
    ConfigOverlay .co-current { color: $text-muted; }
    ConfigOverlay .co-list { height: auto; max-height: 14; }
    ConfigOverlay .co-row { height: auto; margin-bottom: 1; }
    ConfigOverlay .co-lbl { width: 18; color: $text-muted; }
    ConfigOverlay .co-btn { min-width: 8; height: 1; margin-right: 1; }
    ConfigOverlay .co-footer { color: $text-muted; margin-top: 1; }
    ConfigOverlay .co-fixture { margin-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("tab", "next_tab", priority=True),
        Binding("shift+tab", "prev_tab", priority=True),
        *[Binding(t[1], f"goto_tab('{t[0]}')", priority=True) for t in _TABS],
    ]

    active_tab: reactive[str] = reactive("model", always_update=True)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        # YOLO tab state
        self._yolo_previous_mode: str = "manual"
        # Reasoning tab state
        self._reasoning_current_level: str = "medium"
        # Skin tab snapshot (for Esc revert)
        self._snap_css_vars: dict[str, str] = {}
        self._snap_component_vars: dict[str, str] = {}
        self._snap_skin_name: str = "default"
        self._current_skin: str = "default"
        self._current_syntax: str = "monokai"
        self._skin_names: list[str] = []
        self._syntax_schemes: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="co-tab-bar")

        # ── Tab: model ───────────────────────────────────────────────────
        with Vertical(id="co-body-model"):
            yield Static("  Model", classes="co-section-header")
            yield Static("", id="co-model-current", classes="co-current")
            yield OptionList(id="co-model-list", classes="co-list")

        # ── Tab: skin ────────────────────────────────────────────────────
        with Vertical(id="co-body-skin"):
            yield Static("  Skin", classes="co-section-header")
            yield Static("", id="co-skin-current", classes="co-current")
            yield OptionList(id="co-skin-list", classes="co-list")

        # ── Tab: syntax ──────────────────────────────────────────────────
        with Vertical(id="co-body-syntax"):
            yield Static("  Syntax theme", classes="co-section-header")
            yield Static("", id="co-syntax-current", classes="co-current")
            yield OptionList(id="co-syntax-list", classes="co-list")
            yield Static("", id="co-syntax-fixture", classes="co-fixture")

        # ── Tab: options ─────────────────────────────────────────────────
        with Vertical(id="co-body-options"):
            yield Static("  Options", classes="co-section-header")
            with Horizontal(classes="co-row"):
                yield Static("  Bold keywords  ", classes="co-lbl")
                yield Button("✓ On", id="co-bold-on", classes="co-btn")
                yield Button("  Off", id="co-bold-off", classes="co-btn")
            with Horizontal(classes="co-row"):
                yield Static("  Cursor colour  ", classes="co-lbl")
                yield Button("cream", id="co-cur-cream", classes="co-btn")
                yield Button("cyan",  id="co-cur-cyan",  classes="co-btn")
                yield Button("pink",  id="co-cur-pink",  classes="co-btn")
                yield Button("amber", id="co-cur-amber", classes="co-btn")
            with Horizontal(classes="co-row"):
                yield Static("  Anim colour    ", classes="co-lbl")
                yield Button("cyan",  id="co-anim-cyan",  classes="co-btn")
                yield Button("pink",  id="co-anim-pink",  classes="co-btn")
                yield Button("green", id="co-anim-green", classes="co-btn")
                yield Button("amber", id="co-anim-amber", classes="co-btn")
            with Horizontal(classes="co-row"):
                yield Static("  Spinner        ", classes="co-lbl")
                yield Button("dots",  id="co-spin-dots",  classes="co-btn")
                yield Button("pulse", id="co-spin-pulse", classes="co-btn")
                yield Button("moon",  id="co-spin-moon",  classes="co-btn")
                yield Button("grow",  id="co-spin-grow",  classes="co-btn")
            yield Static("  Enter=apply  Esc=close", classes="co-footer")

        # ── Tab: reasoning ───────────────────────────────────────────────
        with Vertical(id="co-body-reasoning"):
            yield Static("  Reasoning", classes="co-section-header")
            with Horizontal(id="co-rpo-levels", classes="co-row"):
                for lvl in _REASONING_LEVELS:
                    variant = "primary" if lvl == self._reasoning_current_level else "default"
                    yield Button(lvl, id=f"co-rpo-{lvl}", variant=variant, classes="co-btn")
            with Horizontal(id="co-rpo-toggles", classes="co-row"):
                yield Checkbox("Show panel", id="co-rpo-show", value=False)
                yield Checkbox("Rich mode",  id="co-rpo-rich", value=True)
            yield Static(
                "[dim]Select a level to set reasoning effort. Esc to close.[/dim]",
                classes="co-footer",
            )

        # ── Tab: verbose ─────────────────────────────────────────────────
        with Vertical(id="co-body-verbose"):
            yield Static("  Tool progress", classes="co-section-header")
            yield OptionList(id="co-verbose-list", classes="co-list")

        # ── Tab: yolo ────────────────────────────────────────────────────
        with Vertical(id="co-body-yolo"):
            yield Static("  YOLO mode", classes="co-section-header")
            yield Static(
                "All tool approval prompts will be skipped.\n"
                "Tools run without confirmation.",
                classes="co-current",
            )
            with Horizontal(classes="co-row"):
                yield Button("Enable",  id="co-yolo-enable",  variant="warning", classes="co-btn")
                yield Button("Disable", id="co-yolo-disable", variant="success", classes="co-btn")
                yield Button("Cancel",  id="co-yolo-cancel",  variant="default", classes="co-btn")
            yield Static("[dim]Space · Esc close[/dim]", classes="co-footer")

    def on_mount(self) -> None:
        self.border_title = "Config"
        self._update_tab_bar()
        self._update_body_visibility()
        # Preload verbose options (static)
        try:
            ol = self.query_one("#co-verbose-list", OptionList)
            for value, label in _VERBOSE_CHOICES:
                ol.add_option(Option(f"  {label}", id=f"co-verbose-opt-{value}"))
        except NoMatches:
            pass

    # ── Visibility / tab switching ────────────────────────────────────────

    def show_overlay(self, tab: str = "model") -> None:
        """Open ConfigOverlay focused on the given tab."""
        if tab not in _TAB_KEYS:
            tab = "model"
        self.active_tab = tab
        self.add_class("--visible")

    def hide_overlay(self) -> None:
        self.remove_class("--visible")

    def refresh_data(self, cli: object) -> None:
        """Populate active tab from config/app state. Called by slash handlers."""
        tab = self.active_tab
        if tab == "model":
            self._refresh_model_tab(cli)
        elif tab == "skin":
            self._take_skin_snapshot()
            self._refresh_skin_tab()
        elif tab == "syntax":
            self._take_skin_snapshot()
            self._refresh_syntax_tab()
        elif tab == "options":
            self._take_skin_snapshot()
            # Options tab has no data to populate beyond button state
        elif tab == "reasoning":
            self._refresh_reasoning_tab()
        elif tab == "verbose":
            self._refresh_verbose_tab()
        elif tab == "yolo":
            self._refresh_yolo_tab()

    def watch_active_tab(self, old: str, new: str) -> None:
        if not self.is_mounted:
            return
        self._update_tab_bar()
        self._update_body_visibility()
        self._focus_active_tab()

    def _update_tab_bar(self) -> None:
        try:
            bar = self.query_one("#co-tab-bar", Static)
        except NoMatches:
            return
        parts = []
        for key, hotkey, label in _TABS:
            if key == self.active_tab:
                parts.append(f"[b on $primary 25%] {hotkey} {label} [/]")
            else:
                parts.append(f" [dim]{hotkey}[/] {label} ")
        bar.update("│".join(parts))

    def _update_body_visibility(self) -> None:
        for key in _TAB_KEYS:
            try:
                body = self.query_one(f"#co-body-{key}", Vertical)
            except NoMatches:
                continue
            body.display = (key == self.active_tab)

    def _focus_active_tab(self) -> None:
        focus_map = {
            "model":     "#co-model-list",
            "skin":      "#co-skin-list",
            "syntax":    "#co-syntax-list",
            "verbose":   "#co-verbose-list",
        }
        sel = focus_map.get(self.active_tab)
        if not sel:
            return
        try:
            self.query_one(sel).focus()
        except NoMatches:
            pass

    # ── Bindings ──────────────────────────────────────────────────────────

    def action_dismiss(self) -> None:
        self._revert_skin_preview_if_any()
        _dismiss_overlay_and_focus_input(self)

    def action_next_tab(self) -> None:
        i = _TAB_KEYS.index(self.active_tab)
        self.active_tab = _TAB_KEYS[(i + 1) % len(_TAB_KEYS)]

    def action_prev_tab(self) -> None:
        i = _TAB_KEYS.index(self.active_tab)
        self.active_tab = _TAB_KEYS[(i - 1) % len(_TAB_KEYS)]

    def action_goto_tab(self, tab_key: str) -> None:
        if tab_key in _TAB_KEYS:
            self.active_tab = tab_key

    # ── Model tab ─────────────────────────────────────────────────────────

    def _refresh_model_tab(self, cli: object) -> None:
        cfg = _cfg_read_raw_config()
        models = list(cfg.get("models", {}).keys())
        current = (
            getattr(getattr(cli, "agent", None), "model", None)
            or getattr(cli, "model", None)
            or "unknown"
        )
        if current and current not in models:
            models.insert(0, current)
        try:
            self.query_one("#co-model-current", Static).update(f"Current: {current}")
        except NoMatches:
            pass
        try:
            ol = self.query_one("#co-model-list", OptionList)
            ol.clear_options()
            for m in models:
                marker = "● " if m == current else "  "
                ol.add_option(Option(f"{marker}{m}", id=f"co-model-opt-{m}"))
            if current in models:
                ol.highlighted = models.index(current)
        except NoMatches:
            pass

    # ── Verbose tab ───────────────────────────────────────────────────────

    def _refresh_verbose_tab(self) -> None:
        cfg = _cfg_read_raw_config()
        current = cfg.get("display", {}).get("tool_progress", "all")
        try:
            ol = self.query_one("#co-verbose-list", OptionList)
            ol.clear_options()
            for value, label in _VERBOSE_CHOICES:
                marker = "● " if value == current else "  "
                ol.add_option(Option(f"{marker}{label}", id=f"co-verbose-opt-{value}"))
            values = [v for v, _ in _VERBOSE_CHOICES]
            if current in values:
                ol.highlighted = values.index(current)
        except NoMatches:
            pass

    # ── Reasoning tab ─────────────────────────────────────────────────────

    def _refresh_reasoning_tab(self) -> None:
        cfg = _cfg_read_raw_config()
        show = bool(cfg.get("display", {}).get("show_reasoning", False))
        rich = bool(cfg.get("display", {}).get("rich_reasoning", True))
        try:
            self.query_one("#co-rpo-show", Checkbox).value = show
        except NoMatches:
            pass
        try:
            self.query_one("#co-rpo-rich", Checkbox).value = rich
        except NoMatches:
            pass
        self._update_reasoning_highlights()

    def _update_reasoning_highlights(self) -> None:
        for lvl in _REASONING_LEVELS:
            try:
                btn = self.query_one(f"#co-rpo-{lvl}", Button)
                btn.variant = "primary" if lvl == self._reasoning_current_level else "default"
            except NoMatches:
                pass

    # ── YOLO tab ──────────────────────────────────────────────────────────

    def _refresh_yolo_tab(self) -> None:
        cfg = _cfg_read_raw_config()
        mode = cfg.get("approvals", {}).get("mode", "manual")
        is_active = (mode == "off")
        if not is_active:
            self._yolo_previous_mode = mode
        self.border_subtitle = "YOLO ACTIVE" if is_active else ""
        self.set_class(is_active, "--yolo-active")
        try:
            self.query_one("#co-yolo-enable", Button).display = not is_active
            self.query_one("#co-yolo-disable", Button).display = is_active
        except NoMatches:
            pass

    def _set_yolo(self, enable: bool) -> None:
        import os as _os
        try:
            cfg = _cfg_read_raw_config()
            if enable:
                _cfg_set_nested(cfg, "approvals.mode", "off")
            else:
                _cfg_set_nested(cfg, "approvals.mode", self._yolo_previous_mode)
            _cfg_save_config(cfg)
        except Exception:
            pass
        _os.environ["HERMES_YOLO_MODE"] = "1" if enable else ""
        try:
            self.app.yolo_mode = enable  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            msg = "⚡  YOLO mode enabled" if enable else "  YOLO mode disabled"
            self.app._flash_hint(msg, 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    # ── Skin tab (+ snapshot) ─────────────────────────────────────────────

    def _take_skin_snapshot(self) -> None:
        cfg = _cfg_read_raw_config()
        self._snap_skin_name = cfg.get("display", {}).get("skin", "default")
        self._current_skin = self._snap_skin_name
        tm = getattr(self.app, "_theme_manager", None)
        if tm is not None:
            self._snap_css_vars = dict(getattr(tm, "_css_vars", {}))
            self._snap_component_vars = dict(getattr(tm, "_component_vars", {}))
        # Best-effort: current syntax
        self._current_syntax = (
            cfg.get("display", {})
            .get("skin_overrides", {})
            .get("vars", {})
            .get("preview-syntax-theme", "monokai")
        )

    def _refresh_skin_tab(self) -> None:
        # Populate skin list from theme manager if available
        tm = getattr(self.app, "_theme_manager", None)
        names: list[str] = []
        if tm is not None and hasattr(tm, "list_skins"):
            try:
                names = list(tm.list_skins())
            except Exception:
                names = []
        if not names:
            names = [self._current_skin or "default"]
        self._skin_names = names
        try:
            self.query_one("#co-skin-current", Static).update(f"Current: {self._current_skin}")
        except NoMatches:
            pass
        try:
            ol = self.query_one("#co-skin-list", OptionList)
            ol.clear_options()
            for n in names:
                marker = "● " if n == self._current_skin else "  "
                ol.add_option(Option(f"{marker}{n}", id=f"co-skin-opt-{n}"))
            if self._current_skin in names:
                ol.highlighted = names.index(self._current_skin)
        except NoMatches:
            pass

    def _refresh_syntax_tab(self) -> None:
        # Static list of common syntax schemes; refined at runtime
        schemes = [
            "monokai", "dracula", "nord", "github-dark", "solarized-dark",
            "one-dark", "tokyo-night", "material",
        ]
        self._syntax_schemes = schemes
        try:
            self.query_one("#co-syntax-current", Static).update(
                f"Current: {self._current_syntax}"
            )
        except NoMatches:
            pass
        try:
            ol = self.query_one("#co-syntax-list", OptionList)
            ol.clear_options()
            for s in schemes:
                marker = "● " if s == self._current_syntax else "  "
                ol.add_option(Option(f"{marker}{s}", id=f"co-syntax-opt-{s}"))
            if self._current_syntax in schemes:
                ol.highlighted = schemes.index(self._current_syntax)
        except NoMatches:
            pass
        try:
            self.query_one("#co-syntax-fixture", Static).update(FIXTURE_CODE)
        except NoMatches:
            pass

    def _revert_skin_preview_if_any(self) -> None:
        """Restore open-time snapshot if user previewed but didn't persist."""
        tm = getattr(self.app, "_theme_manager", None)
        if tm is None or not self._snap_css_vars:
            return
        try:
            if hasattr(tm, "_css_vars"):
                tm._css_vars.clear()
                tm._css_vars.update(self._snap_css_vars)
            if hasattr(tm, "_component_vars"):
                tm._component_vars.clear()
                tm._component_vars.update(self._snap_component_vars)
            if hasattr(tm, "refresh_css"):
                tm.refresh_css()
        except Exception:
            pass

    # ── Event wiring ──────────────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("co-model-opt-"):
            self._confirm_model(opt_id[len("co-model-opt-"):])
        elif opt_id.startswith("co-verbose-opt-"):
            self._confirm_verbose(opt_id[len("co-verbose-opt-"):])
        elif opt_id.startswith("co-skin-opt-"):
            self._confirm_skin(opt_id[len("co-skin-opt-"):])
        elif opt_id.startswith("co-syntax-opt-"):
            self._confirm_syntax(opt_id[len("co-syntax-opt-"):])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid.startswith("co-rpo-") and bid not in ("co-rpo-show", "co-rpo-rich"):
            level = bid[len("co-rpo-"):]
            if level in _REASONING_LEVELS:
                self._reasoning_current_level = level
                self._update_reasoning_highlights()
                self._inject_reasoning_command(level)
        elif bid == "co-yolo-enable":
            self._set_yolo(True)
        elif bid == "co-yolo-disable":
            self._set_yolo(False)
        elif bid == "co-yolo-cancel":
            _dismiss_overlay_and_focus_input(self)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        cb_id = event.checkbox.id or ""
        value = event.value
        try:
            cfg = _cfg_read_raw_config()
            if cb_id == "co-rpo-show":
                _cfg_set_nested(cfg, "display.show_reasoning", value)
            elif cb_id == "co-rpo-rich":
                _cfg_set_nested(cfg, "display.rich_reasoning", value)
            else:
                return
            _cfg_save_config(cfg)
        except Exception:
            pass

    # ── Confirm handlers ──────────────────────────────────────────────────

    def _confirm_model(self, value: str) -> None:
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            try:
                inp.save_draft_stash()
            except Exception:
                pass
            inp.value = f"/model {value}"
            inp.action_submit()
        except Exception:
            pass
        try:
            self.app._flash_hint(f"  Model → {value}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def _confirm_verbose(self, value: str) -> None:
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.tool_progress", value)
            _cfg_save_config(cfg)
        except Exception:
            pass
        try:
            self.app._flash_hint(f"  Tool progress → {value}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def _confirm_skin(self, name: str) -> None:
        self._current_skin = name
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.skin", name)
            _cfg_save_config(cfg)
        except Exception:
            pass
        tm = getattr(self.app, "_theme_manager", None)
        if tm is not None and hasattr(tm, "load_skin"):
            try:
                tm.load_skin(name)
            except Exception:
                pass
        # Fresh snapshot so Esc from now on reverts to the newly persisted skin
        self._take_skin_snapshot()
        try:
            self.query_one("#co-skin-current", Static).update(f"Current: {name}")
        except NoMatches:
            pass
        try:
            self.app._flash_hint(f"  Skin → {name}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _confirm_syntax(self, value: str) -> None:
        self._current_syntax = value
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.skin_overrides.vars.preview-syntax-theme", value)
            _cfg_save_config(cfg)
        except Exception:
            pass
        try:
            self.query_one("#co-syntax-current", Static).update(f"Current: {value}")
        except NoMatches:
            pass
        try:
            self.app._flash_hint(f"  Syntax → {value}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _inject_reasoning_command(self, level: str) -> None:
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            try:
                inp.save_draft_stash()
            except Exception:
                pass
            inp.value = f"/reasoning {level}"
            inp.action_submit()
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)


# Register aliases into ConfigOverlay's CSS type names so `query_one(Alias)`
# resolves to the canonical instance (§5 of spec).
register_config_aliases(ConfigOverlay)


__all__ = ["ConfigOverlay"]
