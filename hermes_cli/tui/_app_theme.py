"""_ThemeMixin — skin/theme, slash commands, hint flash, clipboard for HermesApp."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from textual.css.query import NoMatches

logger = logging.getLogger(__name__)


class _ThemeMixin:
    """Skin/theme application, slash command wiring, hint flash, copy helpers.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    NOTE: Most logic has moved to ThemeService (_svc_theme).
    Methods here are 1-line adapters preserved for backward compatibility.
    Remove in Phase 3.
    """

    # --- Theme / skin system ---

    def get_css_variables(self) -> dict[str, str]:
        """Merge ThemeManager overrides into Textual's CSS variable resolution.

        NOTE: This method MUST remain on the mixin/App — Textual calls it via
        super().get_css_variables() and it cannot be moved to a service.
        """
        base = super().get_css_variables()  # type: ignore[misc]
        tm = getattr(self, "_theme_manager", None)
        if tm is not None:
            overrides = tm.css_variables
        else:
            from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
            overrides = COMPONENT_VAR_DEFAULTS
        return {**base, **overrides}

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.apply_skin(skin_vars)  # type: ignore[attr-defined]

    def _apply_override_dict(self, overrides: "dict") -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme._apply_override_dict(overrides)  # type: ignore[attr-defined]

    def refresh_slash_commands(self, extra: "list[str] | None" = None) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.refresh_slash_commands(extra)  # type: ignore[attr-defined]

    # --- Clipboard / selection helpers ---

    def _get_selected_text(self) -> "str | None":
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.get_selected_text()  # type: ignore[attr-defined]

    # --- Slash command wiring ---

    def _populate_slash_commands(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.populate_slash_commands()  # type: ignore[attr-defined]

    # --- Copy/paste feedback ---

    def _flash_hint(self, text: str, duration: float = 1.5) -> None:
        """Flash *text* in the HintBar for *duration* seconds, then restore.

        Routes through FeedbackService (RX1 Phase B).
        """
        from hermes_cli.tui.services.feedback import NORMAL
        self.feedback.flash(  # type: ignore[attr-defined]
            "hint-bar",
            text,
            duration=duration,
            priority=NORMAL,
            key="hint",
        )

    def set_status_error(self, msg: str, auto_clear_s: float = 0.0) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.set_status_error(msg, auto_clear_s)  # type: ignore[attr-defined]

    def _copy_text_with_hint(self, text: str) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_theme.copy_text_with_hint(text)  # type: ignore[attr-defined]
