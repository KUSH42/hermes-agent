"""_ThemeMixin — skin/theme, slash commands, hint flash, clipboard for HermesApp."""
from __future__ import annotations

import time as _time
import logging
from pathlib import Path
from typing import Any

from textual.css.query import NoMatches

logger = logging.getLogger(__name__)


class _ThemeMixin:
    """Skin/theme application, slash command wiring, hint flash, copy helpers.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    # --- Theme / skin system ---

    def get_css_variables(self) -> dict[str, str]:
        """Merge ThemeManager overrides into Textual's CSS variable resolution."""
        base = super().get_css_variables()  # type: ignore[misc]
        tm = getattr(self, "_theme_manager", None)
        if tm is not None:
            overrides = tm.css_variables
        else:
            from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
            overrides = COMPONENT_VAR_DEFAULTS
        return {**base, **overrides}

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """Apply a skin as CSS variable overrides. Safe to call via call_from_thread."""
        from hermes_cli.tui.widgets import _hint_cache, StatusBar, StreamingCodeBlock
        from hermes_cli.tui.tool_blocks import ToolBlock
        if isinstance(skin_vars, dict):
            self._theme_manager.load_dict(skin_vars)  # type: ignore[attr-defined]
        else:
            self._theme_manager.load([skin_vars])  # type: ignore[attr-defined]
        self._theme_manager.apply()  # type: ignore[attr-defined]
        _hint_cache.clear()
        try:
            sb = self.query_one(StatusBar)  # type: ignore[attr-defined]
            sb._idle_tips_cache = None
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.completion_list import VirtualCompletionList
            self.query_one(VirtualCompletionList).refresh_theme()  # type: ignore[attr-defined]
        except NoMatches:
            pass
        except Exception:
            logger.debug("Completion list theme refresh failed", exc_info=True)
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel
            self.query_one(PreviewPanel).refresh_theme()  # type: ignore[attr-defined]
        except NoMatches:
            pass
        except Exception:
            logger.debug("Preview panel theme refresh failed", exc_info=True)
        for block in self.query(ToolBlock):  # type: ignore[attr-defined]
            try:
                block.refresh_skin()
            except Exception:
                logger.debug("ToolBlock theme refresh failed", exc_info=True)
        for block in self.query(StreamingCodeBlock):  # type: ignore[attr-defined]
            try:
                block.refresh_skin(self.get_css_variables())
            except Exception:
                logger.debug("StreamingCodeBlock theme refresh failed", exc_info=True)

    def refresh_slash_commands(self, extra: "list[str] | None" = None) -> None:
        """Update the slash command list after plugins are loaded."""
        self._populate_slash_commands()
        if extra:
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)  # type: ignore[attr-defined]
                combined = sorted(set(inp._slash_commands) | {
                    n if n.startswith("/") else f"/{n}" for n in extra
                })
                inp.set_slash_commands(combined)
            except (NoMatches, Exception):
                pass
        try:
            from hermes_cli.tui.overlays import HelpOverlay as _HO
            self.query_one(_HO)._refresh_commands_cache()  # type: ignore[attr-defined]
        except (NoMatches, Exception):
            pass

    # --- Clipboard / selection helpers ---

    def _get_selected_text(self) -> "str | None":
        """Return selected text from the screen, or None."""
        try:
            result = self.screen.get_selected_text()  # type: ignore[attr-defined]
            return result if result else None
        except Exception:
            return None

    # --- Slash command wiring ---

    def _populate_slash_commands(self) -> None:
        """Feed the canonical command list from COMMAND_REGISTRY into HermesInput."""
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
                inp = self.query_one(_HI)  # type: ignore[attr-defined]
                inp.set_slash_commands(names)
                inp.set_slash_descriptions(descs)
                inp.set_slash_args_hints(args_hints)
                inp.set_slash_keybind_hints(keybind_hints)
                inp.set_slash_subcommands(dict(SUBCOMMANDS))
            except NoMatches:
                pass
        except Exception:
            pass

    # --- Copy/paste feedback ---

    def _flash_hint(self, text: str, duration: float = 1.5) -> None:
        """Flash *text* in the HintBar for *duration* seconds, then restore."""
        from hermes_cli.tui.widgets import HintBar
        try:
            bar = self.query_one(HintBar)  # type: ignore[attr-defined]
            if self._flash_hint_timer is not None:  # type: ignore[attr-defined]
                try:
                    self._flash_hint_timer.stop()  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._flash_hint_timer = None  # type: ignore[attr-defined]
                prior = self._flash_hint_prior  # type: ignore[attr-defined]
            else:
                prior = bar.hint
                self._flash_hint_prior = prior  # type: ignore[attr-defined]
            bar.hint = text
            self._flash_hint_expires = _time.monotonic() + duration  # type: ignore[attr-defined]

            def _restore() -> None:
                self._flash_hint_timer = None  # type: ignore[attr-defined]
                self._flash_hint_prior = ""  # type: ignore[attr-defined]
                try:
                    setattr(bar, "hint", prior)
                except Exception:
                    pass

            self._flash_hint_timer = self.set_timer(duration, _restore)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def set_status_error(self, msg: str, auto_clear_s: float = 0.0) -> None:
        """Persistent StatusBar error. Thread-safety: must be called from the event loop."""
        self.status_error = msg  # type: ignore[attr-defined]
        flash_duration = auto_clear_s if 0 < auto_clear_s <= 2.5 else 2.5
        self._flash_hint(f"⚠ {msg}", flash_duration)
        if auto_clear_s > 0:
            self.set_timer(auto_clear_s, lambda: setattr(self, "status_error", ""))  # type: ignore[attr-defined]

    def _copy_text_with_hint(self, text: str) -> None:
        """Copy text to clipboard with capability guard and hint flash."""
        self._clipboard = text  # type: ignore[attr-defined]
        if not self._clipboard_available:  # type: ignore[attr-defined]
            if self._xclip_cmd:  # type: ignore[attr-defined]
                try:
                    import subprocess
                    subprocess.run(
                        self._xclip_cmd,  # type: ignore[attr-defined]
                        input=text.encode(),
                        check=True,
                        timeout=2,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._flash_hint(f"⎘  {len(text)} chars copied", 1.2)
                except Exception:
                    self.set_status_error("copy failed", auto_clear_s=10.0)
            else:
                self.set_status_error("no clipboard — install xclip or xsel", auto_clear_s=0)
            return
        self.copy_to_clipboard(text)  # type: ignore[attr-defined]
        self._flash_hint(f"⎘  {len(text)} chars copied", 1.2)
