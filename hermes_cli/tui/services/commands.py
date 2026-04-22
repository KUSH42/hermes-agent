"""Slash command dispatch, undo/rollback, anim commands service extracted from _app_commands.py."""
from __future__ import annotations

import asyncio
import queue
import re
import time as _time
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches

from hermes_cli.tui.state import UndoOverlayState

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

from .base import AppService


class CommandsService(AppService):
    """
    Slash command dispatch, animation config, and undo/retry/rollback sequences.
    Migrated from _CommandsMixin in _app_commands.py.

    Methods:
      handle_tui_command      — was _handle_tui_command
      handle_clear_tui        — was _handle_clear_tui (async, called via @work adapter)
      has_rollback_checkpoint — was _has_rollback_checkpoint
      open_tools_overlay      — was _open_tools_overlay
      handle_layout_command   — was _handle_layout_command
      open_anim_config        — was _open_anim_config
      persist_anim_config     — was _persist_anim_config
      update_anim_hint        — was _update_anim_hint
      handle_anim_command     — was _handle_anim_command
      try_auto_title          — was _try_auto_title
      toggle_drawille_overlay — was _toggle_drawille_overlay
      initiate_undo           — was _initiate_undo
      run_undo_sequence       — was _run_undo_sequence (async, called via @work adapter)
      initiate_retry          — was _initiate_retry
      initiate_rollback       — was _initiate_rollback
      run_rollback_sequence   — was _run_rollback_sequence (async, called via @work adapter)
    """

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)

    def handle_tui_command(self, text: str) -> bool:
        """Intercept TUI-specific slash commands before agent sees them.

        Returns True if handled here; False to forward to agent.
        """
        app = self.app
        stripped = text.strip()
        if stripped == "/undo":
            self.initiate_undo()
            return True
        if stripped == "/retry":
            self.initiate_retry()
            return True
        if re.match(r"^/rollback(?:\s+\d+)?$", stripped):
            self.initiate_rollback(stripped)
            return True
        if stripped == "/density":
            app.action_toggle_density()
            return True
        if stripped == "/density auto-mini":
            app.action_enable_auto_mini()
            return True
        if stripped in ("/density full", "/density compact"):
            app._disable_auto_mini()
            if stripped == "/density full":
                app.compact = False
                app._compact_manual = None
                app._flash_hint("Full density", 1.5)
            else:
                app.compact = True
                app._compact_manual = True
                app._flash_hint("Compact ON", 1.5)
            return True
        if stripped.startswith("/anim"):
            self.handle_anim_command(stripped)
            return True
        if stripped == "/workspace":
            app.action_toggle_workspace()
            return True
        if stripped == "/sessions":
            app.action_open_sessions()
            return True
        if stripped == "/tools":
            self.open_tools_overlay()
            return True

        if stripped.startswith("/layout"):
            args = stripped[len("/layout"):].strip()
            self.handle_layout_command(args)
            return True

        # --- Overlay commands ---
        from hermes_cli.tui.overlays import (
            CommandsOverlay, ConfigOverlay, HelpOverlay, UsageOverlay,
        )

        if stripped == "/help":
            app._dismiss_all_info_overlays()
            try:
                app.query_one(HelpOverlay).show_overlay()
            except NoMatches:
                pass
            return True

        if stripped == "/usage":
            agent = getattr(app.cli, "agent", None)
            if agent is None:
                app._flash_hint("⚠  No active agent — send a message first", 2.0)
                return True
            app._dismiss_all_info_overlays()
            try:
                overlay = app.query_one(UsageOverlay)
                overlay.refresh_data(agent)
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        if stripped == "/commands":
            app._dismiss_all_info_overlays()
            try:
                app.query_one(CommandsOverlay).show_overlay()
            except NoMatches:
                pass
            return True

        _TAB_FOR_CMD = {
            "/model":     "model",
            "/verbose":   "verbose",
            "/yolo":      "yolo",
            "/reasoning": "reasoning",
            "/skin":      "skin",
        }
        if stripped in _TAB_FOR_CMD:
            app._dismiss_all_info_overlays()
            try:
                overlay = app.query_one(ConfigOverlay)
                overlay.show_overlay(tab=_TAB_FOR_CMD[stripped])
                overlay.refresh_data(app.cli)
            except NoMatches:
                pass
            return True

        # --- Flash + animation commands ---

        if stripped == "/clear":
            if not app._clear_animation_in_progress:
                app._clear_animation_in_progress = True
                app._handle_clear_tui()
            return True

        cmd_parts = stripped.split()
        if cmd_parts and cmd_parts[0] == "/schedule":
            if len(cmd_parts) < 2:
                app._flash_hint(
                    "ℹ  Tell the agent what to schedule, e.g. /schedule check logs every hour",
                    3.0,
                )
                return True
            app._flash_hint("📅  Scheduling request sent to agent…", 2.0)
            return False

        if cmd_parts and cmd_parts[0] == "/new":
            app._flash_hint("✨  New session started", 2.0)
            return False

        if cmd_parts and cmd_parts[0] == "/title":
            if len(cmd_parts) > 1:
                app._flash_hint(f"✓  Title: {' '.join(cmd_parts[1:])}", 2.5)
            else:
                app._flash_hint("⚠  Usage: /title <name>", 2.0)
            return False

        if cmd_parts and cmd_parts[0] == "/stop":
            app._flash_hint("⏹  Stopping processes…", 1.5)
            return False

        if re.match(r"^/[\w-]+", stripped):
            cmd_name = stripped.lstrip("/").split()[0]
            try:
                from hermes_cli.commands import resolve_command as _resolve_command
                in_registry = _resolve_command(cmd_name) is not None
            except Exception:
                in_registry = False
            if not in_registry:
                app._flash_hint("⚠  Unknown command — try /help for all commands", 2.0)

        return False

    async def handle_clear_tui(self) -> None:
        """Async body for /clear fade-out animation + session reset.

        The @work adapter on the mixin keeps group='clear' and thread=False.
        """
        app = self.app
        from hermes_cli.tui.widgets import MessagePanel, OutputPanel
        try:
            panels = list(app.query(MessagePanel))
            for p in panels:
                p.styles.animate("opacity", value=0.0, duration=0.3)
            await asyncio.sleep(0.35)
            app.cli.new_session(silent=True)
            if hasattr(app.cli, "_push_tui_status"):
                app.cli._push_tui_status()
            try:
                op = app.query_one(OutputPanel)
                op.remove_children()
                from textual.widgets import Static as _Static
                op.mount(_Static(
                    "[dim]New session started — type a message to begin[/dim]",
                    classes="--empty-state-hint",
                ))
            except NoMatches:
                pass
            app._flash_hint("✨  Fresh start!", 2.0)
        finally:
            app._clear_animation_in_progress = False

    def has_rollback_checkpoint(self) -> bool:
        """Return True if the agent has a filesystem checkpoint available."""
        try:
            return bool(getattr(self.app.cli.agent, "has_checkpoint", lambda: False)())
        except Exception:
            return False

    def open_tools_overlay(self) -> None:
        """Push ToolsScreen showing the current turn's tool call timeline."""
        app = self.app
        from hermes_cli.config import read_raw_config
        if not read_raw_config().get("display", {}).get("tools_overlay", True):
            app._flash_hint("⚠  /tools disabled in config", 2.0)
            return
        app._dismiss_all_info_overlays()
        snapshot = app.current_turn_tool_calls()
        if not snapshot:
            app._flash_hint("⚠  No tool calls in this turn", 2.0)
            return
        from hermes_cli.tui.tools_overlay import ToolsScreen
        app.push_screen(ToolsScreen(snapshot))

    def handle_layout_command(self, args: str) -> None:
        """Handle /layout subcommands."""
        app = self.app
        if not args:
            current = getattr(app, "_display_layout", "v1")
            app._flash_hint(f"Current layout: {current}. Use /layout v1 or /layout v2.", 3.0)
            return

        kv = dict(re.findall(r'(\w+)=(\d+)', args))

        handled_kv = False
        if "left" in kv:
            w = max(16, int(kv["left"]))
            if getattr(app, "_pane_manager", None):
                app._pane_manager.set_left_w(w)
                if app._pane_manager.enabled:
                    app._pane_manager._apply_layout(app)
            app._flash_hint(f"Left pane width → {w}", 2.0)
            handled_kv = True

        if "right" in kv:
            w = max(16, int(kv["right"]))
            if getattr(app, "_pane_manager", None):
                app._pane_manager.set_right_w(w)
                if app._pane_manager.enabled:
                    app._pane_manager._apply_layout(app)
            app._flash_hint(f"Right pane width → {w}", 2.0)
            handled_kv = True

        if handled_kv:
            return

        if args in ("v1", "v2"):
            try:
                from hermes_cli.config import read_raw_config, save_config
                cfg = read_raw_config()
                if "display" not in cfg:
                    cfg["display"] = {}
                cfg["display"]["layout"] = args
                save_config(cfg)
            except Exception:
                pass
            app._flash_hint(f"Layout set to {args}. Restart to apply.", 4.0)
            return

        app._flash_hint("Usage: /layout v1|v2  or  /layout left=N right=M", 3.0)

    def open_anim_config(self) -> None:
        """Show the pre-mounted AnimConfigPanel overlay."""
        from hermes_cli.tui.drawille_overlay import AnimConfigPanel as _ACP
        try:
            self.app.query_one(_ACP).show()
        except Exception:
            pass

    def persist_anim_config(self, cfg_dict: dict) -> None:
        """Merge partial animation config dict into YAML config file."""
        try:
            from hermes_cli.config import read_raw_config, save_config, get_config_path
            import logging as _logging
            config_path = get_config_path()
            if not config_path.exists():
                _logging.getLogger(__name__).warning("Config path does not exist: %s", config_path)
                return
            cfg = read_raw_config()
            existing = cfg.setdefault("display", {}).setdefault("drawille_overlay", {})
            existing.update(cfg_dict)
            save_config(cfg)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("Failed to persist anim config: %s", exc)

    def update_anim_hint(self) -> None:
        """Update _anim_hint reactive based on overlay visibility."""
        app = self.app
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
            ov = app.query_one(_DO)
            cfg = ov._cfg
            if ov.has_class("-visible") and cfg is not None and cfg.animation == "sdf_morph":
                app._anim_hint = f"sdf: {ov.contextual_text}"
            else:
                app._anim_hint = ""
        except Exception:
            app._anim_hint = ""

    def handle_anim_command(self, stripped: str) -> None:
        """Handle /anim subcommands."""
        app = self.app
        from hermes_cli.tui.drawille_overlay import (
            DrawilleOverlay as _DO, AnimConfigPanel as _ACP,
            _ENGINES, _overlay_config, AnimGalleryOverlay as _AGA,
        )
        rest = stripped[len("/anim"):].strip()
        args = rest.split() if rest else []

        if not args:
            app._flash_hint(
                "/anim [on|off|toggle|config|list|speed <fps>|ambient <name>|"
                "color <#hex>|gradient [on|off|#c1 #c2]|hue [speed|off]|size <small|medium|large|fill>|preset <name>|sdf <text>]",
                5.0,
            )
            return

        sub = args[0].lower()

        if sub == "config":
            self.open_anim_config()
            return

        if sub == "on":
            app._anim_force = "on"
            try:
                ov = app.query_one(_DO)
                cfg = _overlay_config()
                cfg.enabled = True
                ov.show(cfg)
            except Exception:
                pass
            return

        if sub == "off":
            app._anim_force = "off"
            try:
                ov = app.query_one(_DO)
                cfg = _overlay_config()
                ov.hide(cfg)
            except Exception:
                pass
            return

        if sub == "toggle":
            if app._anim_force is None:
                app._anim_force = "on"
            elif app._anim_force == "on":
                app._anim_force = "off"
            else:
                app._anim_force = None
            app._drawille_show_hide(getattr(app, "agent_running", False))
            return

        if sub == "list":
            keys = list(_ENGINES.keys()) + ["sdf_morph"]
            try:
                from hermes_cli.tui.widgets import OutputPanel
                panel = app.query_one(OutputPanel)
                msg = panel.current_message or panel.new_message()
                from rich.text import Text as _Text
                msg._log.write(_Text("Animations: " + ", ".join(keys)))
            except Exception:
                app._flash_hint(", ".join(keys), 5.0)
            return

        if sub == "sdf":
            sdf_text = " ".join(args[1:]) if len(args) > 1 else ""
            try:
                ov = app.query_one(_DO)
                cfg = _overlay_config()
                cfg.enabled = True
                cfg.animation = "sdf_morph"
                if sdf_text:
                    cfg.sdf_text = sdf_text
                ov.animation = "sdf_morph"
                ov.show(cfg)

                def _revert_sdf() -> None:
                    ov.animation = _overlay_config().animation
                    app._drawille_show_hide(getattr(app, "agent_running", False))

                app.set_timer(10.0, _revert_sdf)
            except Exception:
                pass
            return

        if sub == "preset":
            from hermes_cli.tui.drawille_overlay import (
                DrawilleOverlay, _overlay_config as _oc, _PRESETS,
            )
            import dataclasses as _dc
            preset_name = args[1].lower() if len(args) > 1 else ""
            if not preset_name:
                app._flash_hint(f"Presets: {', '.join(list(_PRESETS) + ['off'])}", 4.0)
                return
            if preset_name == "off":
                self.persist_anim_config({"enabled": False})
                return
            preset_dict = _PRESETS.get(preset_name)
            if preset_dict is None:
                app._flash_hint(f"Unknown preset — try: {', '.join(_PRESETS)}", 2.5)
                return
            current_cfg = _oc()
            merged = {**_dc.asdict(current_cfg), **preset_dict}
            self.persist_anim_config(merged)
            try:
                ov = app.query_one(DrawilleOverlay)
                ov._do_hide()
                ov.show(_oc())
            except NoMatches:
                pass
            return

        if sub == "speed":
            try:
                fps = max(5, min(60, int(args[1])))
            except (IndexError, ValueError):
                app._flash_hint("Usage: /anim speed <5-60>", 2.0)
                return
            self.persist_anim_config({"fps": fps})
            try:
                ov = app.query_one(_DO)
                ov.fps = fps
            except Exception:
                pass
            app._flash_hint(f"Animation FPS → {fps}", 2.0)
            return

        if sub == "ambient":
            ambient_sub = args[1].lower() if len(args) > 1 else ""
            if not ambient_sub:
                app._flash_hint("Usage: /anim ambient <engine>", 2.0)
                return
            clean_a = "".join(c for c in ambient_sub if c.isalpha())
            matched_a = next((k for k in list(_ENGINES.keys()) if clean_a in k.replace("_", "")), None)
            if matched_a is None:
                app._flash_hint(f"⚠  Unknown engine: {ambient_sub}", 2.0)
                return
            self.persist_anim_config({"ambient_engine": matched_a, "ambient_enabled": True})
            try:
                ov = app.query_one(_DO)
                if ov._visibility_state == "ambient":
                    ov._current_engine_instance = _ENGINES[matched_a]()
            except Exception:
                pass
            app._flash_hint(f"Ambient → {matched_a}", 2.0)
            return

        if sub == "color":
            hex_val = args[1].lstrip("#").lower() if len(args) > 1 else ""
            if len(hex_val) != 6 or not all(c in "0123456789abcdef" for c in hex_val):
                app._flash_hint("Usage: /anim color <#rrggbb>", 2.0)
                return
            color = f"#{hex_val}"
            self.persist_anim_config({"color": color})
            try:
                ov = app.query_one(_DO)
                ov.color = color
            except Exception:
                pass
            app._flash_hint(f"Color → {color}", 2.0)
            return

        if sub == "gradient":
            sub2 = args[1].lower() if len(args) > 1 else ""
            if sub2 == "off":
                self.persist_anim_config({"gradient": False})
                try:
                    app.query_one(_DO).gradient = False
                except Exception:
                    pass
                app._flash_hint("Gradient off", 1.5)
                return

            def _validate_hex(raw: str) -> "str | None":
                h = raw.lstrip("#").lower()
                return f"#{h}" if (len(h) == 6 and all(c in "0123456789abcdef" for c in h)) else None

            if sub2 in ("on", "") or sub2.startswith("#"):
                updates: dict = {"gradient": True}
                if sub2.startswith("#"):
                    color1 = _validate_hex(sub2)
                    if color1 is None:
                        app._flash_hint("Color must be 6-char hex e.g. #ff0000", 2.0)
                        return
                    updates["color"] = color1
                if len(args) > 2 and args[2].startswith("#"):
                    color2 = _validate_hex(args[2])
                    if color2 is None:
                        app._flash_hint("Color2 must be 6-char hex e.g. #0000ff", 2.0)
                        return
                    updates["color_secondary"] = color2
                self.persist_anim_config(updates)
                try:
                    ov = app.query_one(_DO)
                    ov.gradient = True
                    if "color" in updates:
                        ov.color = updates["color"]
                    if "color_secondary" in updates:
                        ov.color_b = updates["color_secondary"]
                except Exception:
                    pass
                app._flash_hint("Gradient on", 1.5)
                return
            app._flash_hint("Usage: /anim gradient [on|off|#color1 #color2]", 2.5)
            return

        if sub == "hue":
            val_str = args[1].lower() if len(args) > 1 else ""
            if val_str in ("off", "0"):
                hue_speed = 0.0
            else:
                try:
                    hue_speed = max(0.0, min(5.0, float(val_str or "0.3")))
                except ValueError:
                    app._flash_hint("Usage: /anim hue <0-5 | off>", 2.0)
                    return
            self.persist_anim_config({"hue_shift_speed": hue_speed})
            try:
                app.query_one(_DO).hue_shift_speed = hue_speed
            except Exception:
                pass
            label = "off" if hue_speed == 0.0 else f"{hue_speed:.2f}"
            app._flash_hint(f"Hue shift → {label}", 1.5)
            return

        if sub == "size":
            valid = ["small", "medium", "large", "fill"]
            sz = args[1].lower() if len(args) > 1 else ""
            if sz not in valid:
                app._flash_hint(f"Usage: /anim size {' | '.join(valid)}", 2.0)
                return
            self.persist_anim_config({"size": sz})
            try:
                ov = app.query_one(_DO)
                ov.size_name = sz
            except Exception:
                pass
            app._flash_hint(f"Size → {sz}", 1.5)
            return

        all_keys = list(_ENGINES.keys())
        clean = "".join(c for c in sub if c.isalpha()).lower()
        matched = None
        for k in all_keys:
            if clean in k.replace("_", ""):
                matched = k
                break
        if matched is None:
            app._flash_hint(f"⚠  Unknown animation: {sub}", 2.0)
            return

        try:
            ov = app.query_one(_DO)
            ov.animation = matched
            cfg = _overlay_config()
            cfg.enabled = True
            cfg.animation = matched
            ov.show(cfg)

            try:
                preview_dur = float(args[1]) if len(args) > 1 else 4.0
                preview_dur = max(1.0, min(120.0, preview_dur))
            except ValueError:
                preview_dur = 4.0

            def _revert_engine() -> None:
                app._drawille_show_hide(getattr(app, "agent_running", False))

            app.set_timer(preview_dur, _revert_engine)
        except Exception:
            pass

    def try_auto_title(self) -> None:
        """Derive a session title from the first user message and save it (once per session)."""
        app = self.app
        db = getattr(app, "_session_db", None) or getattr(getattr(app, "cli", None), "_session_db", None)
        session_id = getattr(getattr(app, "cli", None), "session_id", None)
        if not db or not session_id:
            return
        history = getattr(getattr(app, "cli", None), "conversation_history", None) or []
        if not history:
            return
        first_user = next((m for m in history if m.get("role") == "user"), None)
        if not first_user:
            return
        content = (first_user.get("content") or "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        first_line = (content or "").split("\n", 1)[0]
        first_line = first_line.lstrip("# ").strip()
        if not first_line:
            return
        title = (first_line[:48] + "…") if len(first_line) > 48 else first_line

        _db, _sid, _title = db, session_id, title

        def _save_title_fn() -> None:
            try:
                updated = _db.set_title_if_unset(_sid, _title)
                if updated:
                    app.call_from_thread(setattr, app, "session_label", _title)
            except Exception:
                pass

        try:
            app.run_worker(_save_title_fn, thread=True)
        except Exception:
            pass
        app._auto_title_done = True

    def toggle_drawille_overlay(self) -> None:
        """Ctrl+Shift+A: dismiss overlay if visible, else show it."""
        app = self.app
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, DrawilleOverlayCfg, _overlay_config
        try:
            overlay = app.query_one("#drawille-overlay", _DO)
        except Exception:
            return
        if overlay.has_class("-visible"):
            overlay.remove_class("-visible")
            overlay._stop_anim()
        else:
            try:
                cfg = _overlay_config()
                cfg.enabled = True
            except Exception:
                cfg = DrawilleOverlayCfg(enabled=True)
            overlay.show(cfg)

    # --- Undo / Retry / Rollback ---

    def initiate_undo(self) -> None:
        app = self.app
        from hermes_cli.tui.widgets import MessagePanel
        if app._undo_in_progress:
            app._flash_hint("⚠  Undo in progress", 1.5)
            return
        if app.agent_running:
            app._flash_hint("⚠  Cannot undo while agent is running", 2.0)
            return
        panels = list(app.query(MessagePanel))
        if not panels:
            app._flash_hint("⚠  Nothing to undo", 1.5)
            return
        last_panel = panels[-1]
        user_text = getattr(last_panel, "_user_text", "")
        state = UndoOverlayState(
            deadline=_time.monotonic() + 10,
            response_queue=queue.Queue(),
            user_text=user_text[:80] + "…" if len(user_text) > 80 else user_text,
            has_checkpoint=self.has_rollback_checkpoint(),
        )
        app._pending_undo_panel = last_panel
        app._pending_rollback_n = 0
        app.undo_state = state

    async def run_undo_sequence(self, panel: Any) -> None:
        """Async body for the undo animation + agent.undo() sequence.

        The @work(thread=False) adapter on the mixin wraps this.
        """
        app = self.app
        try:
            app._undo_in_progress = True
            panel.styles.opacity = 0.3
            await asyncio.sleep(0.4)
            try:
                await asyncio.to_thread(app.cli.agent.undo)
            except (AttributeError, NotImplementedError):
                app._flash_hint("⚠  Undo not supported by agent", 2.0)
                panel.styles.opacity = 1.0
                return
            panel.remove()
            user_text = getattr(panel, "_user_text", "")
            if user_text:
                try:
                    from hermes_cli.tui.input_widget import HermesInput
                    hi = app.query_one(HermesInput)
                    hi.value = user_text
                    hi.cursor_position = len(user_text)
                except NoMatches:
                    pass
            app._flash_hint("↩  Undo done", 2.0)
        finally:
            app._undo_in_progress = False

    def initiate_retry(self) -> None:
        app = self.app
        from hermes_cli.tui.widgets import MessagePanel
        if app.agent_running:
            app._flash_hint("⚠  Cannot retry while agent is running", 2.0)
            return
        panels = list(app.query(MessagePanel))
        if not panels:
            app._flash_hint("⚠  Nothing to retry", 1.5)
            return
        last_user_text = getattr(panels[-1], "_user_text", "")
        if not last_user_text:
            app._flash_hint("⚠  No user message to retry", 1.5)
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            hi = app.query_one(HermesInput)
            hi.value = last_user_text
            hi.cursor_position = len(last_user_text)
            hi.action_submit()
        except NoMatches:
            pass

    def initiate_rollback(self, text: str) -> None:
        app = self.app
        m = re.match(r"^/rollback(?:\s+(\d+))?$", text.strip())
        if not m:
            app._flash_hint("⚠  Usage: /rollback [N]", 2.0)
            return
        n = int(m.group(1)) if m.group(1) else 0
        state = UndoOverlayState(
            deadline=_time.monotonic() + 15,
            response_queue=queue.Queue(),
            user_text=f"Filesystem rollback (checkpoint {n})",
            has_checkpoint=True,
        )
        app._pending_undo_panel = None
        app._pending_rollback_n = n
        app.undo_state = state

    async def run_rollback_sequence(self, n: int) -> None:
        """Async body for the rollback sequence.

        The @work(thread=False) adapter on the mixin wraps this.
        """
        app = self.app
        try:
            await asyncio.to_thread(app.cli.agent.rollback, n)
            app._flash_hint("↩  Rollback done", 2.0)
        except (AttributeError, NotImplementedError):
            app._flash_hint("⚠  Rollback not supported by agent", 2.0)
