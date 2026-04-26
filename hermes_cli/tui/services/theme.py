"""Skin application, flash_hint, copy_with_hint service extracted from _app_theme.py."""
from __future__ import annotations

import time as _time
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches

from .base import AppService
from hermes_cli.tui.io_boundary import safe_run

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

logger = logging.getLogger(__name__)

# NOTE: get_css_variables() is NOT migrated here. Textual calls it via
# super().get_css_variables() on App; it must remain on the mixin/App class.


class ThemeService(AppService):
    """
    Skin application, hint flash, clipboard copy helpers.
    Migrated from _ThemeMixin in _app_theme.py.

    Methods:
      apply_skin           — apply skin dict or Path
      _apply_override_dict — apply override dict live
      refresh_slash_commands
      get_selected_text    — selection helper (was _get_selected_text)
      populate_slash_commands  — was _populate_slash_commands
      flash_hint           — was _flash_hint
      set_status_error
      copy_text_with_hint  — was _copy_text_with_hint
    """

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        self._flash_timer = None
        self._error_clear_timer = None

    # --- Theme / skin system ---

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """Apply a skin as CSS variable overrides. Safe to call via call_from_thread."""
        from hermes_cli.tui.widgets import _hint_cache, StatusBar, StreamingCodeBlock
        from hermes_cli.tui.tool_blocks import ToolBlock
        app = self.app
        if isinstance(skin_vars, dict):
            app._theme_manager.load_dict(skin_vars)
        else:
            app._theme_manager.load([skin_vars])
        app._theme_manager.apply()
        _hint_cache.clear()
        try:
            sb = app.query_one(StatusBar)
            sb._idle_tips_cache = None
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.completion_list import VirtualCompletionList
            app.query_one(VirtualCompletionList).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Completion list theme refresh failed", exc_info=True)
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel
            app.query_one(PreviewPanel).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Preview panel theme refresh failed", exc_info=True)
        for block in app.query(ToolBlock):
            try:
                block.refresh_skin()
            except Exception:
                logger.debug("ToolBlock theme refresh failed", exc_info=True)
        css = app.get_css_variables()
        for block in app.query(StreamingCodeBlock):
            try:
                block.refresh_skin(css)
            except Exception:
                logger.debug("StreamingCodeBlock theme refresh failed", exc_info=True)
        from hermes_cli.tui.widgets.message_panel import MessagePanel, ReasoningPanel
        for mp in app.query(MessagePanel):
            if mp._response_engine is not None:
                try:
                    mp._response_engine.refresh_skin(css)
                except Exception:
                    logger.debug("ResponseFlowEngine skin refresh failed", exc_info=True)
        for rp in app.query(ReasoningPanel):
            if rp._reasoning_engine is not None:
                try:
                    rp._reasoning_engine.refresh_skin(css)
                except Exception:
                    logger.debug("ReasoningFlowEngine skin refresh failed", exc_info=True)

    def _apply_override_dict(self, overrides: "dict") -> None:
        """Apply an override dict live without reloading the skin from disk."""
        tm = getattr(self.app, "_theme_manager", None)
        if tm is None:
            return
        tm._apply_overrides(overrides)
        tm.apply()

    def refresh_slash_commands(self, extra: "list[str] | None" = None) -> None:
        """Update the slash command list after plugins are loaded."""
        self.populate_slash_commands()
        app = self.app
        if extra:
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = app.query_one(_HI)
                combined = sorted(set(inp._slash_commands) | {
                    n if n.startswith("/") else f"/{n}" for n in extra
                })
                inp.set_slash_commands(combined)
            except (NoMatches, Exception):
                pass
        try:
            from hermes_cli.tui.overlays import HelpOverlay as _HO
            app.query_one(_HO)._refresh_commands_cache()
        except (NoMatches, Exception):
            pass

    # --- Clipboard / selection helpers ---

    def get_selected_text(self) -> "str | None":
        """Return selected text from the screen, or None."""
        try:
            result = self.app.screen.get_selected_text()
            return result if result else None
        except Exception:
            return None

    # --- Slash command wiring ---

    def populate_slash_commands(self) -> None:
        """Feed the canonical command list from COMMAND_REGISTRY into HermesInput."""
        app = self.app
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.commands import COMMAND_REGISTRY, SUBCOMMANDS
            names: list[str] = []
            for cmd in COMMAND_REGISTRY:
                if cmd.gateway_only:
                    continue
                names.append(f"/{cmd.name}")
                for alias in getattr(cmd, "aliases", []):
                    names.append(f"/{alias}")
            descs: dict[str, str] = {}
            args_hints: dict[str, str] = {}
            keybind_hints: dict[str, str] = {}
            for cmd in COMMAND_REGISTRY:
                if cmd.gateway_only:
                    continue
                cmd_desc = getattr(cmd, "description", "") or ""
                cmd_args = getattr(cmd, "args_hint", "") or ""
                cmd_keybind = getattr(cmd, "keybind_hint", "") or ""
                descs[f"/{cmd.name}"] = cmd_desc
                args_hints[f"/{cmd.name}"] = cmd_args
                keybind_hints[f"/{cmd.name}"] = cmd_keybind
                for alias in getattr(cmd, "aliases", []):
                    descs[f"/{alias}"] = cmd_desc
                    args_hints[f"/{alias}"] = cmd_args
                    keybind_hints[f"/{alias}"] = cmd_keybind
            try:
                inp = app.query_one(_HI)
                inp.set_slash_commands(names)
                inp.set_slash_descriptions(descs)
                inp.set_slash_args_hints(args_hints)
                inp.set_slash_keybind_hints(keybind_hints)
                inp.set_slash_subcommands(dict(SUBCOMMANDS))
            except NoMatches:
                pass
        except Exception:
            pass

    # --- Skill wiring ---

    def populate_skills(self) -> None:
        """Scan installed skills and push SkillCandidate list to HermesInput + KNOWN_SKILLS."""
        app = self.app
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            inp = app.query_one(_HI)
        except NoMatches:
            # NoMatches is expected in headless/gateway mode where HermesInput
            # is not mounted. populate_skills is a no-op in that case.
            logger.debug("populate_skills: HermesInput not mounted, skipping")
            return
        try:
            from agent.skill_commands import get_skill_commands
            from hermes_cli.tui.types.skill_candidate import SkillCandidate
            from hermes_cli.tui._app_constants import refresh_known_skills
            skill_cmds = get_skill_commands()
            candidates = []
            for cmd_key, info in skill_cmds.items():
                bare_name = cmd_key.lstrip("/")
                try:
                    candidate = SkillCandidate.from_skill_info(bare_name, info)
                    candidates.append(candidate)
                except Exception:
                    logger.debug("populate_skills: failed to build candidate for %s", cmd_key, exc_info=True)
            inp.set_skills(candidates)
            refresh_known_skills(c.name for c in candidates)
        except Exception:
            logger.debug("populate_skills: failed", exc_info=True)

    # --- Copy/paste feedback ---

    def flash_hint(self, text: str, duration: float = 1.5) -> None:
        """Flash *text* in the HintBar for *duration* seconds, then restore."""
        self.app.feedback.flash("hint-bar", text, duration=duration)

    def set_status_error(self, msg: str, auto_clear_s: float = 0.0) -> None:
        """Persistent StatusBar error. Thread-safety: must be called from the event loop."""
        app = self.app
        app.status_error = msg
        flash_duration = auto_clear_s if 0 < auto_clear_s <= 2.5 else 2.5
        self.flash_hint(f"⚠ {msg}", flash_duration)
        if auto_clear_s > 0:
            app.set_timer(auto_clear_s, lambda: setattr(app, "status_error", ""))

    def copy_text_with_hint(self, text: str) -> None:
        """Copy text to clipboard with capability guard and hint flash."""
        app = self.app
        app._clipboard = text
        if not app._clipboard_available:
            if app._xclip_cmd:
                safe_run(
                    app,
                    app._xclip_cmd,
                    timeout=2,
                    input_bytes=text.encode(),
                    capture=False,
                    on_success=lambda o, e, rc: self.flash_hint(f"⎘  {len(text)} chars copied", 1.2),
                    on_error=lambda exc, e: self.set_status_error("copy failed", auto_clear_s=10.0),
                )
            else:
                self.set_status_error("no clipboard — install xclip or xsel", auto_clear_s=0)
            return
        app.copy_to_clipboard(text)
        self.flash_hint(f"⎘  {len(text)} chars copied", 1.2)
