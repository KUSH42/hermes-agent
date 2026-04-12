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

from pathlib import Path
from typing import Any, TYPE_CHECKING

from textual import log

from hermes_cli.tui.skin_loader import SkinError, load_skin_full

if TYPE_CHECKING:
    from textual.app import App


# ---------------------------------------------------------------------------
# Defaults — mirror the hardcoded values in hermes.tcss
# These ensure skin files that omit component_vars still render correctly.
# ---------------------------------------------------------------------------

COMPONENT_VAR_DEFAULTS: dict[str, str] = {
    # HermesInput cursor glyph and block colour
    "cursor-color":         "#FFF8DC",
    # HermesInput text selection highlight
    "cursor-selection-bg":  "#3A5A8C",
    # HermesInput placeholder text
    "cursor-placeholder":   "#555555",
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
    # Completion list empty-state background
    "completion-empty-bg":  "#2A2000",
    # TitledRule / PlainRule separator tones
    "rule-dim-color":       "#555555",
    "rule-bg-color":        "#2A2A2A",
    "rule-accent-color":    "#FFD700",
    "rule-accent-dim-color":"#B8860B",
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
        self._component_vars: dict[str, str] = dict(COMPONENT_VAR_DEFAULTS)
        # Hot-reload tracking
        self._source_path: Path | None = None
        self._source_mtime: float = 0.0

    # ------------------------------------------------------------------
    # Public load API
    # ------------------------------------------------------------------

    def load(self, skin: "Path | list[Path]") -> bool:
        """Load from a path or a fallback chain.

        Tries each path in order; stops at the first success.

        Returns ``True`` if any skin loaded successfully, ``False`` if all
        paths failed (app keeps previous skin / defaults).
        """
        paths: list[Path] = [skin] if isinstance(skin, Path) else skin
        for p in paths:
            try:
                self._load_path(p)
                log(f"[THEME] loaded {p}")
                return True
            except (SkinError, OSError) as exc:
                log.warning(f"[THEME] could not load {p}: {exc}")
            except Exception as exc:
                log.warning(f"[THEME] unexpected error loading {p}: {exc}")
        return False

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
        updated = dict(COMPONENT_VAR_DEFAULTS)
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

    def _load_path(self, path: Path) -> None:
        css_vars, component_vars = load_skin_full(path)
        updated_component = dict(COMPONENT_VAR_DEFAULTS)
        updated_component.update(component_vars)
        self._css_vars = css_vars
        self._component_vars = updated_component
        self._source_path = path
        self._source_mtime = path.stat().st_mtime
