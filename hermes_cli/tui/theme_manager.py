"""ThemeManager — centralised skin loader with Component Parts support.

Extends the flat ``skin_loader`` contract with:

1.  **Component Variable Layer** — a ``component_vars`` section in skin
    JSON/YAML maps logical UI-part names (e.g. ``cursor-color``,
    ``cursor-selection-bg``) to CSS color values.  These become Textual CSS
    variables consumed by ``hermes.tcss`` via ``$var-name`` references — the
    Textual Component Parts approach without any private-API hacking.

2.  **Fallback Chain** — ``load()`` accepts a list of paths.  Each is tried
    in order; the first successful load wins.  Lets users ship a personal skin
    with a bundled default as fallback::

        manager.load([Path("~/.config/hermes/my_skin.json"), BUNDLED_SKIN])

3.  **Hot Reload** — ``check_for_changes()`` polls the active skin file's
    ``mtime`` (no watchfiles dependency).  Call it from a ``set_interval``
    callback (``_tick_duration`` at 1 Hz) to auto-reload in < 2 s.

Skin file format (JSON or YAML)
--------------------------------
::

    # Standard semantic keys (existing skin_loader contract)
    fg:     "#E0E0E0"
    bg:     "#0F0F23"
    accent: "#7C3AED"

    # Raw Textual CSS variable overrides (wins on conflict)
    vars:
        primary: "#7C3AED"

    # Component-level UI-part variables  ← NEW in ThemeManager
    component_vars:
        cursor-color:        "#FFD700"    # input cursor glyph/block
        cursor-selection-bg: "#1E4080"    # text selection highlight
        cursor-placeholder:  "#666666"    # placeholder text colour

Integration with HermesApp
---------------------------
::

    def get_css_variables(self) -> dict[str, str]:
        base = super().get_css_variables()
        tm = getattr(self, "_theme_manager", None)
        return {**base, **(tm.css_variables if tm else {})}

    def apply_skin(self, skin_vars: dict | Path) -> None:
        if isinstance(skin_vars, dict):
            self._theme_manager.load_dict(skin_vars)
        else:
            self._theme_manager.load([skin_vars])
        self._theme_manager.apply()

Validation plan
---------------
Instrumentation (Textual Console)::

    TEXTUAL_LOG=1 python -m textual run --dev cli.py
    # Look for:  [THEME] loaded <path>
    # Look for:  [THEME] hot-reload triggered  (after editing skin on disk)
    # Look for:  [THEME] refresh_css failed     (bad skin — graceful)

Stress test::

    # Edit cursor-color in your skin file while the TUI is running.
    # Cursor colour must update within 2 s.  No frame drops expected:
    # refresh_css() is O(widgets) and does not remount anything.

Before/After::

    Before: cursor always renders #FFF8DC regardless of skin.
    After:  cursor respects skin component_vars.cursor-color.
            Switching between Neon/Nord/Monokai themes changes all component
            parts without any restart.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from textual import log

from hermes_cli.tui.skin_loader import SkinError, load_skin_full

if TYPE_CHECKING:
    from textual.app import App


# ---------------------------------------------------------------------------
# VarSpec + migration shim (RX3 §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VarSpec:
    """Canonical description of a component CSS variable.

    During RX3 migration, COMPONENT_VAR_DEFAULTS values may be either raw
    strings or VarSpec instances. Consumers MUST route through ``_default_of``
    to extract the hex default.
    """

    default: str
    description: str = ""
    since: str | None = None
    optional_in_skin: bool = False
    category: str = "misc"


def _default_of(x: "str | VarSpec") -> str:
    """Unwrap a COMPONENT_VAR_DEFAULTS value to its hex default.

    See RX3 spec §5.1 migration shim.
    """
    return x if isinstance(x, str) else x.default


def _defaults_as_strs() -> dict[str, str]:
    """Return COMPONENT_VAR_DEFAULTS with all values coerced to strings."""
    return {k: _default_of(v) for k, v in COMPONENT_VAR_DEFAULTS.items()}


# ---------------------------------------------------------------------------
# Validator (RX3 §8)
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class SkinValidationError(ValueError):
    """Raised when a skin file fails structural or type validation."""


def _validate_hex(path: str, value: Any) -> str:
    """Accept a hex color string; raise with a helpful error path on failure."""
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise SkinValidationError(
            f"{path}: expected #RRGGBB or #RRGGBBAA hex color, got {value!r}"
        )
    return value


def validate_skin_payload(
    payload: "dict[str, Any]",
    *,
    source: str = "<skin>",
    warn_missing: bool = True,
) -> None:
    """Validate a merged skin dict against COMPONENT_VAR_DEFAULTS.

    Raises ``SkinValidationError`` on structural or hex-format errors.
    Emits ``UserWarning`` for missing/unknown component_vars keys.

    ``source`` is prepended to error paths (e.g. ``"skin_overrides"``,
    ``"skins/matrix.yaml"``) so users can locate the offending edit.
    """
    if not isinstance(payload, dict):
        raise SkinValidationError(f"{source}: top level must be a mapping")

    cv = payload.get("component_vars", {})
    if not isinstance(cv, dict):
        raise SkinValidationError(
            f"{source}.component_vars: must be a mapping, got {type(cv).__name__}"
        )
    for name, value in cv.items():
        _validate_hex(f"{source}.component_vars.{name}", value)

    # vars block — also hex-valued when present
    vars_block = payload.get("vars", {})
    if not isinstance(vars_block, dict):
        raise SkinValidationError(
            f"{source}.vars: must be a mapping, got {type(vars_block).__name__}"
        )

    if warn_missing:
        known = set(COMPONENT_VAR_DEFAULTS.keys())
        present = {str(k) for k in cv.keys()}
        required = {
            k for k, v in COMPONENT_VAR_DEFAULTS.items()
            if not (isinstance(v, VarSpec) and v.optional_in_skin)
        }
        missing = required - present
        unknown = present - known
        if missing:
            warnings.warn(
                f"{source}: missing component_vars keys "
                f"(using defaults): {sorted(missing)}",
                UserWarning,
                stacklevel=2,
            )
        if unknown:
            warnings.warn(
                f"{source}: unknown component_vars keys "
                f"(ignored): {sorted(unknown)}",
                UserWarning,
                stacklevel=2,
            )


# ---------------------------------------------------------------------------
# Defaults — mirror the hardcoded values in hermes.tcss
# These ensure skin files that omit component_vars still render correctly.
# ---------------------------------------------------------------------------

COMPONENT_VAR_DEFAULTS: dict[str, str] = {
    # Global app background — used by HermesApp, chrome widgets, and response
    # content areas so everything renders at the same shade.  Users can override
    # in skin component_vars:  app-bg: "#0F0F0F"
    "app-bg":               "#1E1E1E",
    # HermesInput cursor glyph and block colour
    "cursor-color":         "#FFF8DC",
    # HermesInput text selection highlight
    "cursor-selection-bg":  "#3A5A8C",
    # HermesInput placeholder text
    "cursor-placeholder":   "#555555",
    # Ghost text color — used for inline ghost/suggestion text
    "ghost-text-color":     "#555555",
    # Chevron phase colours
    "chevron-base":         "#FFF8DC",
    "chevron-file":         "#FFBF00",
    "chevron-stream":       "#6EA8D4",
    "chevron-shell":        "#A8D46E",
    "chevron-done":         "#4CAF50",
    "chevron-error":        "#E06C75",
    # Fuzzy match highlight in autocomplete list
    "fuzzy-match-color":    "#FFD866",
    # Status / pulse indicators
    "status-running-color": "#FFBF00",
    "status-error-color":   "#ef5350",
    "status-warn-color":    "#FFA726",
    "status-context-color": "#5f87d7",
    # Running indicator high-color (StatusBar ● + shimmer)
    "running-indicator-hi-color": "#FFA726",
    # Running indicator dim-color (StatusBar ● pulse trough + shimmer base)
    "running-indicator-dim-color": "#6e6e6e",
    # FPS HUD background
    "fps-hud-bg":           "#1a1a2e",
    # User echo panel bullet color
    "user-echo-bullet-color": "#FFBF00",
    # Completion list empty-state background
    "completion-empty-bg":  "#2A2A2A",
    # TitledRule / PlainRule separator tones
    "rule-dim-color":       "#888888",
    "rule-bg-color":        "#1E1E1E",
    "rule-accent-color":    "#FFD700",
    "rule-accent-dim-color":"#B8860B",
    # TitledRule idle glyph — visible but dimmer than primary (#5f87d7) so
    # the pulse animation from idle→active is meaningful.
    # NOT in Textual's default theme vars; must be injected here so
    # _live_colors() get_css_variables() lookup succeeds at runtime.
    "primary-darken-3":     "#4a7aaa",
    # Brand glyph color — dedicated color for the ⟁/⚕ glyph in TitledRule.
    # Allows skins to give the brand glyph its own accent separate from
    # the title text and the idle/active pulse colors.
    "brand-glyph-color":    "#FFD700",
    # Scrollbar thumb color — ThemeManager overrides via component_vars.
    # Named "scrollbar" to match Textual's built-in CSS var.
    "scrollbar": "#5f87d7",
    # Drawille overlay braille canvas color (default: bright cyan)
    "drawille-canvas-color": "#00d7ff",
    # Panel border color — used by SourcesBar and other bordered panels
    "panel-border":       "#333333",
    # Footnote superscript marker color (in _render_footnote_section)
    "footnote-ref-color": "#888888",
    # MCP tool accent — purple; reserved for future _refresh_gutter_color wiring
    "tool-mcp-accent": "#9b59b6",
    # Vision tool accent — teal
    "tool-vision-accent": "#00bcd4",
    # Diff background colors — used by ToolBlock._diff_bg_colors()
    "diff-add-bg": "#1a3a1a",
    "diff-del-bg": "#3a1a1a",
    # Citation chip colors — used by SourcesBar
    "cite-chip-bg": "#1a2030",
    "cite-chip-fg": "#8899bb",
    # Browse mode visual markers — pip/badge colors per anchor type
    "browse-turn":  "#d4a017",
    "browse-code":  "#4caf50",
    "browse-tool":  "#2196f3",
    "browse-diff":  "#e040fb",
    "browse-media": "#00bcd4",
    # AssistantNameplate animation colors
    "nameplate-idle-color":    "#888888",
    "nameplate-active-color":  "#7b68ee",
    "nameplate-decrypt-color": "#00ff41",
    # Spinner shimmer colors — F1: skinnable so light-bg skins stay readable
    "spinner-shimmer-dim":  "#555555",
    "spinner-shimmer-peak": "#d8d8d8",
    # Second accent color — used for interactive key badges in HintBar
    "accent-interactive":   "#00bcd4",
    # PlanPanel (R1) — now-section foreground and pending-section foreground
    "plan-now-fg":          "#00bcd4",
    "plan-pending-fg":      "#777777",
    # Pane layout border colors — used by PaneContainer in v2 layout
    "pane-border":          "#333333",
    "pane-border-focused":  "#5f87d7",
    "pane-title-fg":        "#888888",
    "pane-divider":         "#2a2a2a",
    # MCP tool glyph color — referenced by tool_category.CategoryDefaults for MCP
    "tool-glyph-mcp":       "#9b59b6",
    # v4 error-kind classification colors (tool_result_parse._ERROR_DISPLAY)
    "error-timeout":        "#f59e0b",
    "error-critical":       "#ef4444",
    "error-auth":           "#eab308",
    "error-network":        "#f97316",
}


class ThemeManager:
    """Centralised theme manager with Component Parts support and hot reload.

    Parameters
    ----------
    app:
        The ``HermesApp`` instance.  Stored as a weak reference is not needed
        here — ``ThemeManager`` is owned by the app and lives and dies with it.
    """

    def __init__(self, app: "App") -> None:
        self._app = app
        # CSS vars from semantic/raw skin keys (fed to get_css_variables)
        self._css_vars: dict[str, str] = {}
        # Component-part vars (cursor-color, etc.) merged on top
        self._component_vars: dict[str, str] = _defaults_as_strs()
        # Hot-reload tracking
        self._source_path: Path | None = None
        self._source_mtime: float = 0.0
        self._watcher_thread: threading.Thread | None = None
        self._watcher_stop = threading.Event()
        self._watcher_interval_s: float = 1.0
        self._pending_reload_mtime: float = 0.0

    # ------------------------------------------------------------------
    # Public load API
    # ------------------------------------------------------------------

    def load(self, skin: "Path | list[Path]") -> bool:
        """Load from a path or a fallback chain.

        Tries each path in order; stops at the first success. Every load
        path runs through the RX3 validator and, if merged with
        ``display.skin_overrides``, validates the merged output so typos in
        config.yaml surface loud.

        Returns ``True`` if any skin loaded successfully, ``False`` if all
        paths failed (app keeps previous skin / defaults).
        """
        paths: list[Path] = [skin] if isinstance(skin, Path) else skin
        for p in paths:
            try:
                self._load_path(p)
                log(f"[THEME] loaded {p}")
                try:
                    from hermes_cli.config import read_skin_overrides
                    overrides = read_skin_overrides()
                    # Validate merged (skin ⊕ overrides) — §8.4
                    try:
                        validate_skin_payload(
                            {"component_vars": {**self._component_vars,
                                                **(overrides.get("component_vars") or {})},
                             "vars": overrides.get("vars", {})},
                            source="skin_overrides",
                            warn_missing=False,
                        )
                    except SkinValidationError:
                        raise
                    self._apply_overrides(overrides)
                except SkinValidationError:
                    raise
                except Exception:
                    pass
                return True
            except (SkinError, SkinValidationError, OSError) as exc:
                log.warning(f"[THEME] SKIN_LOAD_FAILED: {p}: {exc}")
                print(f"SKIN_LOAD_FAILED: {p}: {exc}", file=sys.stderr)
            except Exception as exc:
                log.warning(f"[THEME] unexpected error loading {p}: {exc}")
                print(f"SKIN_LOAD_FAILED: {p}: {exc}", file=sys.stderr)
        return False

    def load_with_fallback(
        self,
        configured: "Path | list[Path] | None" = None,
        *,
        bundled_default: "Path | None" = None,
    ) -> str:
        """3-step fallback chain per RX3 §11.4.

        Step 1: configured user skin(s). Step 2: bundled default.yaml.
        Step 3: emergency COMPONENT_VAR_DEFAULTS-only path (always succeeds).

        Returns the tag of the successful step: ``"configured"``,
        ``"default"``, or ``"emergency"``.
        """
        if configured is not None:
            try:
                ok = self.load(configured)
                if ok:
                    return "configured"
            except SkinValidationError as exc:
                log.warning(f"[THEME] SKIN_LOAD_FAILED: {exc}")
                print(f"SKIN_LOAD_FAILED: {exc}", file=sys.stderr)

        # Reset partial state before falling through
        self._css_vars = {}
        self._component_vars = _defaults_as_strs()

        if bundled_default is not None and bundled_default.exists():
            try:
                self._load_path(bundled_default)
                return "default"
            except Exception as exc:
                log.warning(f"[THEME] SKIN_DEFAULT_FAILED: {exc}")
                print(f"SKIN_DEFAULT_FAILED: {exc}", file=sys.stderr)
                self._css_vars = {}
                self._component_vars = _defaults_as_strs()

        # Emergency: bypass YAML entirely; merge skin_overrides onto defaults
        try:
            from hermes_cli.config import read_skin_overrides
            self._apply_overrides(read_skin_overrides())
        except Exception:
            pass
        print("SKIN_EMERGENCY_FALLBACK: using COMPONENT_VAR_DEFAULTS only", file=sys.stderr)
        log.warning("[THEME] SKIN_EMERGENCY_FALLBACK")
        return "emergency"

    def load_dict(self, skin_vars: "dict[str, Any]") -> None:
        """Load a pre-built variable dict (bypasses file parsing).

        Callers that pass a ``dict`` to ``HermesApp.apply_skin()`` take this
        path.  If the dict contains a ``"component_vars"`` key it is extracted
        and applied separately; all other keys are treated as CSS variable
        overrides.
        """
        # Shallow-copy so we don't mutate the caller's dict
        d = dict(skin_vars)
        raw_component = d.pop("component_vars", {})
        self._css_vars = {str(k): str(v) for k, v in d.items()}
        updated = _defaults_as_strs()
        if isinstance(raw_component, dict):
            updated.update({str(k): str(v) for k, v in raw_component.items()})
        self._component_vars = updated
        self._source_path = None  # dict loads cannot hot-reload

    def apply(self) -> None:
        """Push the loaded skin to the app via ``refresh_css()``."""
        try:
            self._app.refresh_css()
        except Exception as exc:
            log.warning(f"[THEME] refresh_css failed: {exc}")

    def start_hot_reload(self, poll_interval_s: float = 1.0) -> None:
        """Start background skin watcher.

        Polling the filesystem from the UI thread can stall Textual on slower
        filesystems. The watcher keeps the blocking ``stat()`` / file-read work
        off the event loop and only schedules the final ``refresh_css()`` back
        onto the app thread.
        """
        self._watcher_interval_s = max(0.1, float(poll_interval_s))
        thread = self._watcher_thread
        if thread is not None and thread.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name="hermes-theme-watcher",
            daemon=True,
        )
        self._watcher_thread.start()

    def stop_hot_reload(self) -> None:
        """Stop background skin watcher."""
        self._watcher_stop.set()
        thread = self._watcher_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.2, self._watcher_interval_s + 0.1))
        self._watcher_thread = None
        self._pending_reload_mtime = 0.0

    # ------------------------------------------------------------------
    # Hot reload (call from set_interval at ~1 Hz)
    # ------------------------------------------------------------------

    def check_for_changes(self) -> bool:
        """Poll source mtime; reload if changed.

        Returns ``True`` if a reload was triggered (``refresh_css()`` already
        called).  Returns ``False`` if no file is loaded or mtime unchanged.
        """
        if self._source_path is None:
            return False
        try:
            mtime = self._source_path.stat().st_mtime
        except OSError:
            return False
        if mtime <= self._source_mtime:
            return False
        # File changed on disk — reload
        try:
            self._load_path(self._source_path)
            log(f"[THEME] hot-reload triggered: {self._source_path}")
            self.apply()
            return True
        except Exception as exc:
            log.warning(f"[THEME] hot-reload failed: {exc}")
            return False

    def _watch_loop(self) -> None:
        """Background hot-reload poller.

        Does blocking filesystem work off-thread, then schedules final state
        update + ``refresh_css()`` onto Textual's event loop via
        ``call_from_thread``.
        """
        while not self._watcher_stop.wait(self._watcher_interval_s):
            path = self._source_path
            if path is None:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            baseline = max(self._source_mtime, self._pending_reload_mtime)
            if mtime <= baseline:
                continue
            try:
                css_vars, component_vars = load_skin_full(path)
            except Exception as exc:
                log.warning(f"[THEME] hot-reload failed: {exc}")
                continue
            self._pending_reload_mtime = mtime
            try:
                self._app.call_from_thread(
                    self._apply_hot_reload_payload,
                    path,
                    mtime,
                    css_vars,
                    component_vars,
                )
            except RuntimeError:
                return

    def _apply_hot_reload_payload(
        self,
        path: Path,
        mtime: float,
        css_vars: dict[str, str],
        component_vars: dict[str, str],
    ) -> None:
        """Apply background-loaded skin data on the app thread."""
        self._pending_reload_mtime = 0.0
        if self._source_path != path or mtime <= self._source_mtime:
            return
        updated_component = _defaults_as_strs()
        updated_component.update(component_vars)
        self._css_vars = css_vars
        self._component_vars = updated_component
        self._source_mtime = mtime
        log(f"[THEME] hot-reload triggered: {path}")
        self.apply()

    # ------------------------------------------------------------------
    # CSS variable output (consumed by HermesApp.get_css_variables)
    # ------------------------------------------------------------------

    @property
    def css_variables(self) -> dict[str, str]:
        """Merged CSS variable dict: semantic + raw + component parts.

        Precedence (highest → lowest):
            component_vars overrides  >  skin vars  >  Textual defaults
        """
        return {**self._css_vars, **self._component_vars}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_overrides(self, overrides: "dict[str, Any]") -> None:
        """Merge skin_overrides on top of currently loaded skin vars.

        Called at the end of ``load()`` only — NOT in ``load_dict()``.
        Dict-based loads are transient live previews; running overrides there
        would overwrite the preview value immediately.
        """
        self._css_vars.update(overrides.get("vars", {}))
        self._component_vars.update(overrides.get("component_vars", {}))

    def _load_path(self, path: Path) -> None:
        css_vars, component_vars = load_skin_full(path)
        # Validate against COMPONENT_VAR_DEFAULTS — §8.1
        validate_skin_payload(
            {"component_vars": component_vars, "vars": css_vars},
            source=str(path),
        )
        updated_component = _defaults_as_strs()
        updated_component.update(component_vars)
        self._css_vars = css_vars
        self._component_vars = updated_component
        self._source_path = path
        self._source_mtime = path.stat().st_mtime
