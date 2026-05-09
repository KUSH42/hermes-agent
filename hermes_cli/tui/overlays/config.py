"""ConfigOverlay — canonical picker fan-in for R3 consolidation.

Replaces VerbosePickerOverlay, ModelPickerOverlay, TabbedSkinOverlay,
ReasoningPickerOverlay, YoloConfirmOverlay with a single tabbed overlay.

Per spec §2.1 of 2026-04-22-tui-v2-R3-overlay-consolidation-spec.md:
- 6 top-level tabs: model / skin / syntax / reasoning / verbose / yolo
- ConfigOverlay owns overlay chrome; tab bodies are plain Widgets
- Pre-mounted; toggled via `--visible`; dismiss via Escape → focus HermesInput
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Checkbox, OptionList, Static
from textual.widgets.option_list import Option
from textual import work
from textual.worker import WorkerState as _WorkerState

_WORKER_DONE = {_WorkerState.SUCCESS, _WorkerState.ERROR, _WorkerState.CANCELLED}

from hermes_cli.tui.overlays._aliases import register_config_aliases
from hermes_cli.tui.overlays._legacy import (
    FIXTURE_CODE,
    _FIXTURE_BY_LANG,
    _cfg_read_raw_config,
    _cfg_save_config,
    _cfg_set_nested,
)
from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin

if TYPE_CHECKING:
    pass


# Tab roster — spec §2.1 table. Keys drive _AliasMeta.__instancecheck__.
_TABS: list[tuple[str, str, str]] = [
    # (tab_key, hotkey, label)
    ("model",     "1", "Model"),
    ("skin",      "2", "Skin"),
    ("syntax",    "3", "Syntax"),
    ("reasoning", "4", "Reasoning"),
    ("verbose",   "5", "Verbose"),
    ("yolo",      "6", "YOLO"),
]

_TAB_KEYS: list[str] = [t[0] for t in _TABS]
_REASONING_LEVELS: list[str] = ["none", "low", "minimal", "medium", "high", "xhigh"]
_VERBOSE_CHOICES: list[tuple[str, str]] = [
    ("off",     "off      — no streaming tool output"),
    ("new",     "new      — stream output for new tools only"),
    ("all",     "all      — stream all tool output"),
    ("verbose", "verbose  — stream + expanded collapse thresholds"),
]


class ConfigOverlay(ModalOverlayMixin, Widget):
    """Tabbed config overlay replacing 5 standalone picker overlays."""

    can_focus = True
    _push_modal_on_mount: bool = False  # permanent widget; push/pop managed in show_overlay/dismiss_overlay

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
    ConfigOverlay .co-provider-list { max-height: 6; }
    ConfigOverlay .co-row { height: auto; margin-bottom: 1; }
    ConfigOverlay .co-lbl { width: 18; color: $text-muted; }
    ConfigOverlay .co-btn { min-width: 8; height: 1; margin-right: 1; }
    ConfigOverlay .co-footer { color: $text-muted; margin-top: 1; }
    ConfigOverlay .co-subheader { color: $text-muted; margin-top: 1; }
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
        # Model tab state
        self._browsed_provider: str = ""  # provider currently selected in provider list
        self._provider_slugs: list[str] = []  # parallel list to co-provider-list options
        # Model catalog cache (populated by background prefetch worker)
        self._model_cache: dict[str, list[str] | list[dict]] = {}
        self._provider_list_cache: list[dict] | None = None
        self._model_prefetch_done: bool = False
        # Skin tab snapshot (for Esc revert)
        self._snap_css_vars: dict[str, str] = {}
        self._snap_component_vars: dict[str, str] = {}
        self._snap_skin_name: str = "hermes"
        self._current_skin: str = "hermes"
        self._current_syntax: str = "monokai"
        self._skin_names: list[str] = []
        self._syntax_schemes: list[str] = []
        self._last_cli: object = None  # stored for tab-switch refresh

    def compose(self) -> ComposeResult:
        yield Static("", id="co-tab-bar")

        # ── Tab: model ───────────────────────────────────────────────────
        with Vertical(id="co-body-model"):
            yield Static("  Model", classes="co-section-header")
            yield Static("Provider", classes="co-subheader")
            yield OptionList(id="co-provider-list", classes="co-list co-provider-list")
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

        # ── Tab: reasoning ───────────────────────────────────────────────
        with Vertical(id="co-body-reasoning"):
            yield Static("  Reasoning", classes="co-section-header")
            yield OptionList(id="co-rpo-list", classes="co-list")
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
        # Permanent widget: do NOT call ModalOverlayMixin.on_mount().
        # push_modal / --modal are managed per show_overlay() / dismiss_overlay() cycle.
        self.border_title = "Config"
        self._update_tab_bar()
        self._update_body_visibility()
        # Preload verbose options (static)
        try:
            ol = self.query_one("#co-verbose-list", OptionList)
            for value, label in _VERBOSE_CHOICES:
                ol.add_option(Option(f"  {label}", id=f"co-verbose-opt-{value}"))
        except NoMatches:
            pass  # widget not yet in DOM during deferred mount; options absent but non-fatal

    def on_unmount(self) -> None:
        # Permanent widget: never removed from DOM. ModalOverlayMixin.on_unmount must NOT
        # be called here — stack/focus cleanup is owned by dismiss_overlay(), not lifecycle hooks.
        pass

    # ── Visibility / tab switching ────────────────────────────────────────

    def show_overlay(self, tab: str = "model") -> None:
        """Open ConfigOverlay focused on the given tab."""
        if self.has_class("--visible"):
            return  # already open — don't double-push the modal stack
        if tab not in _TAB_KEYS:
            tab = "model"
        self.active_tab = tab
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # il-m1: register in arbiter stack
        except AttributeError:  # push_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("ConfigOverlay.show_overlay: app has no push_modal")
        self.add_class("--modal", "--visible")  # il-m1: owned by show_overlay (permanent widget override)
        self._refresh_active_tab()
        running = {w.name for w in self.workers if w.state not in _WORKER_DONE}
        if not self._model_prefetch_done and "model-catalog-prefetch" not in running:
            self._prefetch_all_providers()
        self.call_after_refresh(self._focus_active_tab)

    def hide_overlay(self) -> None:
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        """Permanent-widget dismiss: hide without removing from DOM."""
        self._model_prefetch_done = False  # allow re-run on next open
        target = self._restore_focus_to()  # capture focus target before any DOM/CSS mutation
        self._revert_skin_preview_if_any()
        self.remove_class("--visible", "--modal")  # il-m1: owned by dismiss_overlay (permanent override)
        try:
            self.app.pop_modal(self)  # il-m1: deregister from arbiter stack
        except AttributeError:  # pop_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("ConfigOverlay.dismiss_overlay: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("ConfigOverlay.dismiss_overlay: focus restore failed", exc_info=True)

    def refresh_data(self, cli: object) -> None:
        """Populate active tab from config/app state. Called by slash handlers."""
        self._last_cli = cli
        self._refresh_active_tab()

    def watch_active_tab(self, old: str, new: str) -> None:
        if not self.is_mounted:
            return
        self._update_tab_bar()
        self._update_body_visibility()
        if self.has_class("--visible"):
            self._refresh_active_tab()
            self._focus_active_tab()

    def _update_tab_bar(self) -> None:
        try:
            bar = self.query_one("#co-tab-bar", Static)
        except NoMatches:
            return  # not yet mounted; called speculatively before compose completes
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
            "model":     "#co-provider-list",
            "skin":      "#co-skin-list",
            "syntax":    "#co-syntax-list",
            "verbose":   "#co-verbose-list",
            "reasoning": "#co-rpo-list",
        }
        sel = focus_map.get(self.active_tab)
        if not sel:
            return
        try:
            self.query_one(sel).focus()
        except NoMatches:
            pass  # expected on first show_overlay before compose completes; focus silently skipped

    def _refresh_active_tab(self) -> None:
        """Refresh current tab's data. Safe to call with _last_cli=None."""
        tab = self.active_tab
        if tab == "model":
            self._refresh_model_tab(self._last_cli)
        elif tab == "skin":
            if not self._snap_css_vars:   # snapshot once per session when tm is available;
                self._take_skin_snapshot()  # when tm is None, dict stays empty and revert short-circuits
            self._refresh_skin_tab()
        elif tab == "syntax":
            if not self._snap_css_vars:   # same guard
                self._take_skin_snapshot()
            self._refresh_syntax_tab()
        elif tab == "reasoning":
            self._refresh_reasoning_tab()
        elif tab == "verbose":
            self._refresh_verbose_tab()
        elif tab == "yolo":
            self._refresh_yolo_tab()

    # ── Bindings ──────────────────────────────────────────────────────────

    def dismiss(self) -> None:
        """Public close helper — delegates to action_dismiss."""
        self.action_dismiss()

    def action_dismiss(self) -> None:
        self.dismiss_overlay()

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
        model_section = cfg.get("model", {})
        configured_models = cfg.get("models", {})
        config_provider = model_section.get("provider", "openrouter") or "openrouter"
        current = (
            model_section.get("default")
            or getattr(getattr(cli, "agent", None), "model", None)
            or getattr(cli, "model", None)
            or "unknown"
        )
        self._browsed_provider = config_provider
        self._populate_provider_list(config_provider)
        configured_model_ids = list(configured_models) if isinstance(configured_models, dict) else []
        self._populate_model_list(config_provider, current, configured_model_ids)

    def _populate_provider_list(self, active_provider: str) -> None:
        try:
            from hermes_cli.models import list_available_providers, normalize_provider
        except Exception:
            _log.debug("_populate_provider_list: import failed", exc_info=True)
            return
        providers = self._provider_list_cache
        if providers is None:
            # Cache miss: prefetch not done yet — fall back to synchronous call.
            # This is intentional degraded behaviour on first open before the
            # prefetch worker finishes; subsequent opens hit the cache.
            try:
                providers = list_available_providers()
            except Exception:
                _log.warning("_populate_provider_list: list_available_providers() failed", exc_info=True)
                providers = []
        active_norm = normalize_provider(active_provider)
        # Ensure active provider appears even if not in list
        slugs = [p["id"] for p in providers]
        if active_norm not in slugs:
            providers.insert(0, {"id": active_norm, "label": active_provider, "authenticated": False})
        self._provider_slugs = [p["id"] for p in providers]
        try:
            ol = self.query_one("#co-provider-list", OptionList)
            ol.clear_options()
            for p in providers:
                pid = p["id"]
                label = p.get("label") or pid
                auth_mark = " ✓" if p.get("authenticated") else ""
                marker = "● " if pid == active_norm else "  "
                ol.add_option(Option(f"{marker}{label}{auth_mark}", id=f"co-provider-opt-{pid}"))
            if active_norm in self._provider_slugs:
                ol.highlighted = self._provider_slugs.index(active_norm)
        except NoMatches:
            pass

    def _populate_model_list(
        self,
        provider: str,
        current_model: str,
        configured_models: list[str] | None = None,
    ) -> None:
        models = list(configured_models or [])
        if not models:
            cached = self._model_cache.get(provider)
            if cached is not None:
                models = list(cached)
            else:
                # Cache miss: show placeholder and kick off targeted fetch
                models = ["⟳ loading…"]
                worker_name = f"model-catalog-fetch-{provider}"
                if worker_name not in {w.name for w in self.workers if w.state not in _WORKER_DONE}:
                    _p, _m = provider, current_model
                    self.run_worker(
                        lambda: self._fetch_provider_models(_p, _m),
                        name=worker_name,
                        thread=True,
                    )
        if current_model and current_model not in models:
            models.insert(0, current_model)
        try:
            self.query_one("#co-model-current", Static).update(f"Current:  {current_model}")
        except NoMatches:
            pass
        try:
            ol = self.query_one("#co-model-list", OptionList)
            ol.clear_options()
            for m in models:
                marker = "● " if m == current_model else "  "
                ol.add_option(Option(f"{marker}{m}", id=f"co-model-opt-{m}"))
            if current_model in models:
                ol.highlighted = models.index(current_model)
        except NoMatches:
            pass

    # ── Background model catalog workers ─────────────────────────────────

    @work(thread=True, name="model-catalog-prefetch")
    def _prefetch_all_providers(self) -> None:
        from hermes_cli.models import list_available_providers, provider_model_ids

        try:
            providers = list_available_providers()
        except Exception:
            _log.warning("_prefetch_all_providers: list_available_providers failed", exc_info=True)
            return  # _model_prefetch_done stays False; next open will retry
        self._provider_list_cache = providers
        for p in providers:
            slug = p["id"]
            if slug in self._model_cache:
                continue
            try:
                ids = list(provider_model_ids(slug, force_refresh=False))
            except Exception:
                _log.warning("_prefetch_all_providers: provider_model_ids(%r) failed", slug, exc_info=True)
                continue  # Don't cache failure; targeted fetch will retry on highlight
            self._model_cache[slug] = ids
        self._model_prefetch_done = True  # set even if some providers failed; partial cache is valid

    def _fetch_provider_models(self, provider: str, current_model: str) -> None:
        # MUST be called via run_worker(thread=True) — not directly
        from hermes_cli.models import provider_model_ids

        try:
            ids = list(provider_model_ids(provider, force_refresh=False))
        except Exception:
            _log.warning("_fetch_provider_models(%r) failed", provider, exc_info=True)
            return  # Don't cache failure; next highlight will retry via targeted fetch
        self._model_cache[provider] = ids
        # Repopulate only if provider is still the one being browsed
        if self._browsed_provider == provider:
            self.app.call_from_thread(self._populate_model_list, provider, current_model)

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
        try:
            ol = self.query_one("#co-rpo-list", OptionList)
            ol.clear_options()
            for lvl in _REASONING_LEVELS:
                marker = "● " if lvl == self._reasoning_current_level else "  "
                ol.add_option(Option(f"{marker}{lvl}", id=f"co-rpo-opt-{lvl}"))
            if self._reasoning_current_level in _REASONING_LEVELS:
                ol.highlighted = _REASONING_LEVELS.index(self._reasoning_current_level)
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
            _log.warning("Failed to persist YOLO mode change", exc_info=True)
        _os.environ["HERMES_YOLO_MODE"] = "1" if enable else ""
        try:
            self.app.yolo_mode = enable  # type: ignore[attr-defined]
        except Exception:
            _log.debug("Failed to set app.yolo_mode reactive", exc_info=True)
        try:
            msg = "⚡  YOLO mode enabled" if enable else "  YOLO mode disabled"
            self.app._flash_hint(msg, 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass  # flash hint is best-effort UI decoration; action already applied
        self.dismiss_overlay()

    # ── Skin tab (+ snapshot) ─────────────────────────────────────────────

    def _take_skin_snapshot(self) -> None:
        cfg = _cfg_read_raw_config()
        self._snap_skin_name = cfg.get("display", {}).get("skin", "hermes")
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
            names = [self._current_skin or "hermes"]
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
            pass  # skin tab widgets not yet in DOM; refresh will retry on next show_overlay

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
        self._render_syntax_fixture(self._current_syntax)

    def _syntax_fixture_content(self) -> tuple[str, str]:
        active = getattr(self.app, "status_active_file", "") or ""
        ext = Path(active).suffix.lstrip(".").lower() if active else ""
        ext_to_lang = {
            "py": "python", "js": "javascript", "ts": "typescript",
            "go": "go", "rs": "rust", "rb": "ruby", "sh": "bash",
            "java": "java", "cpp": "cpp", "c": "c", "md": "markdown",
        }
        lang = ext_to_lang.get(ext, "python")
        return lang, _FIXTURE_BY_LANG.get(lang, FIXTURE_CODE)

    def _render_syntax_fixture(self, theme: str) -> None:
        try:
            css = self.app.get_css_variables()
            background = css.get("app-bg", "#1e1e1e")
        except Exception:
            _log.debug("ConfigOverlay syntax fixture CSS lookup failed", exc_info=True)
            background = "#1e1e1e"
        try:
            lang, fixture = self._syntax_fixture_content()
            self.query_one("#co-syntax-fixture", Static).update(
                Syntax(
                    fixture,
                    lexer=lang,
                    theme=theme,
                    line_numbers=False,
                    word_wrap=False,
                    indent_guides=False,
                    background_color=background,
                )
            )
        except Exception:
            _log.debug("ConfigOverlay syntax fixture render failed", exc_info=True)
            try:
                _lang, fixture = self._syntax_fixture_content()
                self.query_one("#co-syntax-fixture", Static).update(fixture)
            except NoMatches:
                pass
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
            _log.warning("_revert_skin_preview_if_any: CSS restore failed", exc_info=True)

    def _preview_syntax_theme(self, theme: str) -> None:
        try:
            tm = getattr(self.app, "_theme_manager", None)
        except Exception:
            tm = None
        if tm is not None and hasattr(tm, "_css_vars"):
            try:
                tm._css_vars["preview-syntax-theme"] = theme
                if hasattr(tm, "refresh_css"):
                    tm.refresh_css()
            except Exception:
                _log.debug("syntax preview refresh_css(%r) failed", theme, exc_info=True)
        self._render_syntax_fixture(theme)

    # ── Event wiring ──────────────────────────────────────────────────────

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Preview skin/syntax/provider on highlight WITHOUT committing to disk."""
        opt_id = getattr(event.option, "id", None) or ""
        if event.option_list.id == "co-provider-list":
            if not opt_id.startswith("co-provider-opt-"):
                return
            slug = opt_id[len("co-provider-opt-"):]
            if slug == self._browsed_provider:
                return
            self._browsed_provider = slug
            cfg = _cfg_read_raw_config()
            current = cfg.get("model", {}).get("default", "")
            self._populate_model_list(slug, current)
            event.stop()
            return
        if event.option_list.id == "co-skin-list":
            if not opt_id.startswith("co-skin-opt-"):
                return
            name = opt_id[len("co-skin-opt-"):]
            try:
                app_dict = getattr(self.app, "__dict__", {})
                apply_named_skin = app_dict.get("apply_named_skin")
                if callable(apply_named_skin):
                    apply_named_skin(name)
                else:
                    tm = getattr(self.app, "_theme_manager", None)
                    if tm is None or not hasattr(tm, "load_skin"):
                        return
                    tm.load_skin(name)
            except Exception:
                _log.debug("skin preview load_skin(%r) failed", name, exc_info=True)
            event.stop()
            return
        if event.option_list.id == "co-syntax-list":
            if not opt_id.startswith("co-syntax-opt-"):
                return
            self._preview_syntax_theme(opt_id[len("co-syntax-opt-"):])
            event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("co-provider-opt-"):
            # Provider Enter → commit _browsed_provider + move focus to model list
            slug = opt_id[len("co-provider-opt-"):]
            self._browsed_provider = slug
            try:
                self.query_one("#co-model-list", OptionList).focus()
            except NoMatches:
                pass
            return
        if opt_id.startswith("co-model-opt-"):
            self._confirm_model(opt_id[len("co-model-opt-"):])
        elif opt_id.startswith("co-verbose-opt-"):
            self._confirm_verbose(opt_id[len("co-verbose-opt-"):])
        elif opt_id.startswith("co-skin-opt-"):
            self._confirm_skin(opt_id[len("co-skin-opt-"):])
        elif opt_id.startswith("co-syntax-opt-"):
            self._confirm_syntax(opt_id[len("co-syntax-opt-"):])
        elif opt_id.startswith("co-rpo-opt-"):
            lvl = opt_id[len("co-rpo-opt-"):]
            if lvl in _REASONING_LEVELS:
                self._apply_reasoning_level(lvl)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid == "co-yolo-enable":
            self._set_yolo(True)
        elif bid == "co-yolo-disable":
            self._set_yolo(False)
        elif bid == "co-yolo-cancel":
            self.dismiss_overlay()

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
            _log.warning("on_checkbox_changed: config write failed for %r", cb_id, exc_info=True)

    # ── Confirm handlers ──────────────────────────────────────────────────

    def _confirm_model(self, value: str) -> None:
        cfg = _cfg_read_raw_config()
        config_provider = cfg.get("model", {}).get("provider", "openrouter") or "openrouter"
        browsed = getattr(self, "_browsed_provider", "") or config_provider
        try:
            from hermes_cli.models import normalize_provider
            provider_changed = normalize_provider(browsed) != normalize_provider(config_provider)
        except Exception:
            provider_changed = browsed != config_provider
        cmd_args = f"{value} --provider {browsed} --global" if provider_changed else f"{value} --global"
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            try:
                inp.save_draft_stash()
            except Exception:
                pass  # draft stash is best-effort; model switch proceeds regardless
            inp.value = f"/model {cmd_args}"
            inp.action_submit()
        except Exception:
            _log.warning("Failed to apply model selection %r (provider=%r)", value, browsed, exc_info=True)
        label = f"{browsed}:{value}" if provider_changed else value
        try:
            self.app._flash_hint(f"  Model → {label}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass  # flash hint is best-effort UI decoration; action already applied
        self.dismiss_overlay()

    def _confirm_verbose(self, value: str) -> None:
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.tool_progress", value)
            _cfg_save_config(cfg)
        except Exception:
            _log.warning("Failed to persist verbose setting %r", value, exc_info=True)
        try:
            self.app._flash_hint(f"  Tool progress → {value}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass  # flash hint is best-effort UI decoration; action already applied
        self.dismiss_overlay()

    def _confirm_skin(self, name: str) -> None:
        self._current_skin = name
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.skin", name)
            _cfg_save_config(cfg)
        except Exception:
            _log.warning("Failed to persist skin selection %r", name, exc_info=True)
        try:
            apply_named_skin = getattr(self.app, "apply_named_skin", None)
            if callable(apply_named_skin):
                apply_named_skin(name)
            else:
                tm = getattr(self.app, "_theme_manager", None)
                if tm is not None and hasattr(tm, "load_skin"):
                    tm.load_skin(name)
        except Exception:
            _log.warning("Failed to apply skin selection %r", name, exc_info=True)
        # Fresh snapshot so Esc from now on reverts to the newly persisted skin
        try:
            self._take_skin_snapshot()
        except Exception:
            _log.debug("_confirm_skin: snapshot refresh failed for %r", name, exc_info=True)
        try:
            self.query_one("#co-skin-current", Static).update(f"Current: {name}")
        except NoMatches:
            pass
        try:
            self.app._flash_hint(f"  Skin → {name}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass  # flash hint is best-effort UI decoration; action already applied

    def _confirm_syntax(self, value: str) -> None:
        self._current_syntax = value
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.skin_overrides.vars.preview-syntax-theme", value)
            _cfg_save_config(cfg)
        except Exception:
            _log.warning("Failed to persist syntax theme %r", value, exc_info=True)
        try:
            self._preview_syntax_theme(value)
        except Exception:
            _log.warning("Failed to apply syntax theme %r", value, exc_info=True)
        try:
            self._take_skin_snapshot()
        except Exception:
            _log.debug("_confirm_syntax: snapshot refresh failed for %r", value, exc_info=True)
        try:
            self.query_one("#co-syntax-current", Static).update(f"Current: {value}")
        except NoMatches:
            pass  # syntax tab may not be visible; label update is best-effort display
        try:
            self.app._flash_hint(f"  Syntax → {value}", 2.0)  # type: ignore[attr-defined]
        except Exception:
            pass  # flash hint is best-effort UI decoration; action already applied

    def _apply_reasoning_level(self, level: str) -> None:
        self._reasoning_current_level = level
        self._update_reasoning_highlights()
        self._inject_reasoning_command(level)

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
            _log.warning("_inject_reasoning_command: command injection failed for %r", level, exc_info=True)
        self.dismiss_overlay()


# Register aliases into ConfigOverlay's CSS type names so `query_one(Alias)`
# resolves to the canonical instance (§5 of spec).
register_config_aliases(ConfigOverlay)


__all__ = ["ConfigOverlay"]
