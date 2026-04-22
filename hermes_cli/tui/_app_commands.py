"""_CommandsMixin — TUI slash commands, animation control, undo/retry for HermesApp."""
from __future__ import annotations

import asyncio
import queue
import re
import time as _time
from typing import Any

from textual import work
from textual.css.query import NoMatches

from hermes_cli.tui.state import UndoOverlayState


class _CommandsMixin:
    """TUI command dispatch, animation config, and undo/retry/rollback sequences.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def _handle_tui_command(self, text: str) -> bool:
        """Intercept TUI-specific slash commands before agent sees them.

        Returns True if handled here; False to forward to agent.
        """
        stripped = text.strip()
        if stripped == "/undo":
            self._initiate_undo()
            return True
        if stripped == "/retry":
            self._initiate_retry()
            return True
        if re.match(r"^/rollback(?:\s+\d+)?$", stripped):
            self._initiate_rollback(stripped)
            return True
        if stripped == "/density":
            self.action_toggle_density()  # type: ignore[attr-defined]
            return True
        if stripped == "/density auto-mini":
            self.action_enable_auto_mini()  # type: ignore[attr-defined]
            return True
        if stripped in ("/density full", "/density compact"):
            # Disable auto-mini when switching to an explicit density level
            self._disable_auto_mini()  # type: ignore[attr-defined]
            if stripped == "/density full":
                self.compact = False  # type: ignore[attr-defined]
                self._compact_manual = None  # type: ignore[attr-defined]
                self._flash_hint("Full density", 1.5)  # type: ignore[attr-defined]
            else:
                self.compact = True  # type: ignore[attr-defined]
                self._compact_manual = True  # type: ignore[attr-defined]
                self._flash_hint("Compact ON", 1.5)  # type: ignore[attr-defined]
            return True
        if stripped.startswith("/anim"):
            self._handle_anim_command(stripped)
            return True
        if stripped == "/workspace":
            self.action_toggle_workspace()  # type: ignore[attr-defined]
            return True
        if stripped == "/sessions":
            self.action_open_sessions()  # type: ignore[attr-defined]
            return True
        if stripped == "/tools":
            self._open_tools_overlay()
            return True

        # --- Overlay commands ---
        from hermes_cli.tui.overlays import (
            CommandsOverlay, HelpOverlay, ModelPickerOverlay,
            ReasoningPickerOverlay, SkinPickerOverlay, UsageOverlay,
            VerbosePickerOverlay, YoloConfirmOverlay,
        )

        if stripped == "/help":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                self.query_one(HelpOverlay).show_overlay()  # type: ignore[attr-defined]
            except NoMatches:
                pass
            return True

        if stripped == "/usage":
            agent = getattr(self.cli, "agent", None)  # type: ignore[attr-defined]
            if agent is None:
                self._flash_hint("⚠  No active agent — send a message first", 2.0)  # type: ignore[attr-defined]
                return True
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(UsageOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(agent)
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        if stripped == "/commands":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                self.query_one(CommandsOverlay).show_overlay()  # type: ignore[attr-defined]
            except NoMatches:
                pass
            return True

        if stripped == "/model":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(ModelPickerOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(self.cli)  # type: ignore[attr-defined]
                overlay.add_class("--visible")
                overlay.query_one("#mpo-list").focus()
            except NoMatches:
                pass
            return True

        if stripped == "/verbose":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(VerbosePickerOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(self.cli)  # type: ignore[attr-defined]
                overlay.add_class("--visible")
                overlay.query_one("#vpo-list").focus()
            except NoMatches:
                pass
            return True

        if stripped == "/yolo":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(YoloConfirmOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(self.cli)  # type: ignore[attr-defined]
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        if stripped == "/reasoning":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(ReasoningPickerOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(self.cli)  # type: ignore[attr-defined]
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        if stripped == "/skin":
            self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
            try:
                overlay = self.query_one(SkinPickerOverlay)  # type: ignore[attr-defined]
                overlay.refresh_data(self.cli)  # type: ignore[attr-defined]
                overlay.add_class("--visible")
                overlay.query_one("#spo-list").focus()
            except NoMatches:
                pass
            return True

        # --- Flash + animation commands ---

        if stripped == "/clear":
            if not self._clear_animation_in_progress:  # type: ignore[attr-defined]
                self._clear_animation_in_progress = True  # type: ignore[attr-defined]
                self._handle_clear_tui()
            return True

        cmd_parts = stripped.split()
        if cmd_parts and cmd_parts[0] == "/schedule":
            if len(cmd_parts) < 2:
                self._flash_hint(
                    "ℹ  Tell the agent what to schedule, e.g. /schedule check logs every hour",
                    3.0,
                )  # type: ignore[attr-defined]
                return True          # consumed; do NOT forward empty command
            self._flash_hint("📅  Scheduling request sent to agent…", 2.0)  # type: ignore[attr-defined]
            return False             # forward full "/schedule <text>" to agent

        if cmd_parts and cmd_parts[0] == "/new":
            self._flash_hint("✨  New session started", 2.0)  # type: ignore[attr-defined]
            return False

        if cmd_parts and cmd_parts[0] == "/title":
            if len(cmd_parts) > 1:
                self._flash_hint(f"✓  Title: {' '.join(cmd_parts[1:])}", 2.5)  # type: ignore[attr-defined]
            else:
                self._flash_hint("⚠  Usage: /title <name>", 2.0)  # type: ignore[attr-defined]
            return False

        if cmd_parts and cmd_parts[0] == "/stop":
            self._flash_hint("⏹  Stopping processes…", 1.5)  # type: ignore[attr-defined]
            return False

        if re.match(r"^/[\w-]+", stripped):
            cmd_name = stripped.lstrip("/").split()[0]
            try:
                from hermes_cli.commands import resolve_command as _resolve_command
                in_registry = _resolve_command(cmd_name) is not None
            except Exception:
                in_registry = False
            if not in_registry:
                self._flash_hint("⚠  Unknown command — try /help for all commands", 2.0)  # type: ignore[attr-defined]

        return False

    @work(thread=False, group="clear")
    async def _handle_clear_tui(self) -> None:
        """Fade out MessagePanels, then delegate clear to CLI."""
        from hermes_cli.tui.widgets import MessagePanel, OutputPanel
        try:
            panels = list(self.query(MessagePanel))  # type: ignore[attr-defined]
            for p in panels:
                p.styles.animate("opacity", value=0.0, duration=0.3)
            await asyncio.sleep(0.35)
            self.cli.new_session(silent=True)  # type: ignore[attr-defined]
            if hasattr(self.cli, "_push_tui_status"):  # type: ignore[attr-defined]
                self.cli._push_tui_status()  # type: ignore[attr-defined]
            try:
                op = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                op.remove_children()
                from textual.widgets import Static as _Static
                op.mount(_Static(
                    "[dim]New session started — type a message to begin[/dim]",
                    classes="--empty-state-hint",
                ))
            except NoMatches:
                pass
            self._flash_hint("✨  Fresh start!", 2.0)  # type: ignore[attr-defined]
        finally:
            self._clear_animation_in_progress = False  # type: ignore[attr-defined]

    def _has_rollback_checkpoint(self) -> bool:
        """Return True if the agent has a filesystem checkpoint available."""
        try:
            return bool(getattr(self.cli.agent, "has_checkpoint", lambda: False)())  # type: ignore[attr-defined]
        except Exception:
            return False

    def _open_tools_overlay(self) -> None:
        """Push ToolsScreen showing the current turn's tool call timeline."""
        from hermes_cli.config import read_raw_config
        if not read_raw_config().get("display", {}).get("tools_overlay", True):
            self._flash_hint("⚠  /tools disabled in config", 2.0)  # type: ignore[attr-defined]
            return
        self._dismiss_all_info_overlays()  # type: ignore[attr-defined]
        snapshot = self.current_turn_tool_calls()  # type: ignore[attr-defined]
        if not snapshot:
            self._flash_hint("⚠  No tool calls in this turn", 2.0)  # type: ignore[attr-defined]
            return
        from hermes_cli.tui.tools_overlay import ToolsScreen
        self.push_screen(ToolsScreen(snapshot))  # type: ignore[attr-defined]

    def _open_anim_config(self) -> None:
        """Push the AnimConfigPanel modal screen."""
        from hermes_cli.tui.drawille_overlay import AnimConfigPanel as _ACP
        self.push_screen(_ACP())  # type: ignore[attr-defined]

    def _persist_anim_config(self, cfg_dict: dict) -> None:
        """Persist animation config dict to YAML config file."""
        try:
            from hermes_cli.config import read_raw_config, save_config, _set_nested, get_config_path
            import logging as _logging
            config_path = get_config_path()
            if not config_path.exists():
                _logging.getLogger(__name__).warning("Config path does not exist: %s", config_path)
                return
            cfg = read_raw_config()
            _set_nested(cfg, "display.drawille_overlay", cfg_dict)
            save_config(cfg)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("Failed to persist anim config: %s", exc)

    def _update_anim_hint(self) -> None:
        """Update _anim_hint reactive based on overlay visibility."""
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
            ov = self.query_one(_DO)  # type: ignore[attr-defined]
            cfg = ov._cfg
            if ov.has_class("-visible") and cfg is not None and cfg.animation == "sdf_morph":
                self._anim_hint = f"sdf: {ov.contextual_text}"  # type: ignore[attr-defined]
            else:
                self._anim_hint = ""  # type: ignore[attr-defined]
        except Exception:
            self._anim_hint = ""  # type: ignore[attr-defined]

    def _handle_anim_command(self, stripped: str) -> None:
        """Handle /anim subcommands."""
        from hermes_cli.tui.drawille_overlay import (
            DrawilleOverlay as _DO, AnimConfigPanel as _ACP,
            _ENGINES, _overlay_config, AnimGalleryOverlay as _AGA,
        )
        rest = stripped[len("/anim"):].strip()
        args = rest.split() if rest else []

        if not args:
            self._flash_hint(  # type: ignore[attr-defined]
                "/anim [on|off|toggle|config|list|speed <fps>|ambient <name>|"
                "color <#hex>|gradient [on|off|#c1 #c2]|hue [speed|off]|size <small|medium|large|fill>|preset <name>|sdf <text>]",
                5.0,
            )
            return

        sub = args[0].lower()

        if sub == "config":
            self._open_anim_config()
            return

        if sub == "on":
            self._anim_force = "on"  # type: ignore[attr-defined]
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                cfg = _overlay_config()
                cfg.enabled = True
                ov.show(cfg)
            except Exception:
                pass
            return

        if sub == "off":
            self._anim_force = "off"  # type: ignore[attr-defined]
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                cfg = _overlay_config()
                ov.hide(cfg)
            except Exception:
                pass
            return

        if sub == "toggle":
            if self._anim_force is None:  # type: ignore[attr-defined]
                self._anim_force = "on"  # type: ignore[attr-defined]
            elif self._anim_force == "on":  # type: ignore[attr-defined]
                self._anim_force = "off"  # type: ignore[attr-defined]
            else:
                self._anim_force = None  # type: ignore[attr-defined]
            self._drawille_show_hide(getattr(self, "agent_running", False))  # type: ignore[attr-defined]
            return

        if sub == "list":
            keys = list(_ENGINES.keys()) + ["sdf_morph"]
            try:
                from hermes_cli.tui.widgets import OutputPanel
                panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                msg = panel.current_message or panel.new_message()
                from rich.text import Text as _Text
                msg._log.write(_Text("Animations: " + ", ".join(keys)))
            except Exception:
                self._flash_hint(", ".join(keys), 5.0)  # type: ignore[attr-defined]
            return

        if sub == "sdf":
            sdf_text = " ".join(args[1:]) if len(args) > 1 else ""
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                cfg = _overlay_config()
                cfg.enabled = True
                cfg.animation = "sdf_morph"
                if sdf_text:
                    cfg.sdf_text = sdf_text
                ov.animation = "sdf_morph"
                ov.show(cfg)

                def _revert_sdf() -> None:
                    ov.animation = _overlay_config().animation
                    self._drawille_show_hide(getattr(self, "agent_running", False))  # type: ignore[attr-defined]

                self.set_timer(10.0, _revert_sdf)  # type: ignore[attr-defined]
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
                self._flash_hint(f"Presets: {', '.join(list(_PRESETS) + ['off'])}", 4.0)  # type: ignore[attr-defined]
                return
            if preset_name == "off":
                self._persist_anim_config({"enabled": False})
                return
            preset_dict = _PRESETS.get(preset_name)
            if preset_dict is None:
                self._flash_hint(f"Unknown preset — try: {', '.join(_PRESETS)}", 2.5)  # type: ignore[attr-defined]
                return
            current_cfg = _oc()
            merged = {**_dc.asdict(current_cfg), **preset_dict}
            self._persist_anim_config(merged)
            try:
                ov = self.query_one(DrawilleOverlay)  # type: ignore[attr-defined]
                ov._do_hide()
                ov.show(_oc())
            except NoMatches:
                pass
            return

        # B2: /anim speed <fps>
        if sub == "speed":
            try:
                fps = max(5, min(60, int(args[1])))
            except (IndexError, ValueError):
                self._flash_hint("Usage: /anim speed <5-60>", 2.0)  # type: ignore[attr-defined]
                return
            self._persist_anim_config({"fps": fps})
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                ov.fps = fps
            except Exception:
                pass
            self._flash_hint(f"Animation FPS → {fps}", 2.0)  # type: ignore[attr-defined]
            return

        # B3: /anim ambient <name>
        if sub == "ambient":
            ambient_sub = args[1].lower() if len(args) > 1 else ""
            if not ambient_sub:
                self._flash_hint("Usage: /anim ambient <engine>", 2.0)  # type: ignore[attr-defined]
                return
            clean_a = "".join(c for c in ambient_sub if c.isalpha())
            matched_a = next((k for k in list(_ENGINES.keys()) if clean_a in k.replace("_", "")), None)
            if matched_a is None:
                self._flash_hint(f"⚠  Unknown engine: {ambient_sub}", 2.0)  # type: ignore[attr-defined]
                return
            self._persist_anim_config({"ambient_engine": matched_a, "ambient_enabled": True})
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                if ov._visibility_state == "ambient":
                    ov._current_engine_instance = _ENGINES[matched_a]()
            except Exception:
                pass
            self._flash_hint(f"Ambient → {matched_a}", 2.0)  # type: ignore[attr-defined]
            return

        # D3: /anim color <hex>
        if sub == "color":
            hex_val = args[1].lstrip("#").lower() if len(args) > 1 else ""
            if len(hex_val) != 6 or not all(c in "0123456789abcdef" for c in hex_val):
                self._flash_hint("Usage: /anim color <#rrggbb>", 2.0)  # type: ignore[attr-defined]
                return
            color = f"#{hex_val}"
            self._persist_anim_config({"color": color})
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                ov.color = color
            except Exception:
                pass
            self._flash_hint(f"Color → {color}", 2.0)  # type: ignore[attr-defined]
            return

        # D3: /anim gradient [on|off|<color1> [color2]]
        if sub == "gradient":
            sub2 = args[1].lower() if len(args) > 1 else ""
            if sub2 == "off":
                self._persist_anim_config({"gradient": False})
                try:
                    self.query_one(_DO).gradient = False  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._flash_hint("Gradient off", 1.5)  # type: ignore[attr-defined]
                return

            def _validate_hex(raw: str) -> "str | None":
                h = raw.lstrip("#").lower()
                return f"#{h}" if (len(h) == 6 and all(c in "0123456789abcdef" for c in h)) else None

            if sub2 in ("on", "") or sub2.startswith("#"):
                updates: dict = {"gradient": True}
                if sub2.startswith("#"):
                    color1 = _validate_hex(sub2)
                    if color1 is None:
                        self._flash_hint("Color must be 6-char hex e.g. #ff0000", 2.0)  # type: ignore[attr-defined]
                        return
                    updates["color"] = color1
                if len(args) > 2 and args[2].startswith("#"):
                    color2 = _validate_hex(args[2])
                    if color2 is None:
                        self._flash_hint("Color2 must be 6-char hex e.g. #0000ff", 2.0)  # type: ignore[attr-defined]
                        return
                    updates["color_secondary"] = color2
                self._persist_anim_config(updates)
                try:
                    ov = self.query_one(_DO)  # type: ignore[attr-defined]
                    ov.gradient = True
                    if "color" in updates:
                        ov.color = updates["color"]
                    if "color_secondary" in updates:
                        ov.color_b = updates["color_secondary"]
                except Exception:
                    pass
                self._flash_hint("Gradient on", 1.5)  # type: ignore[attr-defined]
                return
            self._flash_hint("Usage: /anim gradient [on|off|#color1 #color2]", 2.5)  # type: ignore[attr-defined]
            return

        # D3: /anim hue [<speed>|off]
        if sub == "hue":
            val_str = args[1].lower() if len(args) > 1 else ""
            if val_str in ("off", "0"):
                hue_speed = 0.0
            else:
                try:
                    hue_speed = max(0.0, min(5.0, float(val_str or "0.3")))
                except ValueError:
                    self._flash_hint("Usage: /anim hue <0-5 | off>", 2.0)  # type: ignore[attr-defined]
                    return
            self._persist_anim_config({"hue_shift_speed": hue_speed})
            try:
                self.query_one(_DO).hue_shift_speed = hue_speed  # type: ignore[attr-defined]
            except Exception:
                pass
            label = "off" if hue_speed == 0.0 else f"{hue_speed:.2f}"
            self._flash_hint(f"Hue shift → {label}", 1.5)  # type: ignore[attr-defined]
            return

        # D4: /anim size <small|medium|large|fill>
        if sub == "size":
            valid = ["small", "medium", "large", "fill"]
            sz = args[1].lower() if len(args) > 1 else ""
            if sz not in valid:
                self._flash_hint(f"Usage: /anim size {' | '.join(valid)}", 2.0)  # type: ignore[attr-defined]
                return
            self._persist_anim_config({"size": sz})
            try:
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                ov.size_name = sz
            except Exception:
                pass
            self._flash_hint(f"Size → {sz}", 1.5)  # type: ignore[attr-defined]
            return

        all_keys = list(_ENGINES.keys())
        clean = "".join(c for c in sub if c.isalpha()).lower()
        matched = None
        for k in all_keys:
            if clean in k.replace("_", ""):
                matched = k
                break
        if matched is None:
            self._flash_hint(f"⚠  Unknown animation: {sub}", 2.0)  # type: ignore[attr-defined]
            return

        try:
            ov = self.query_one(_DO)  # type: ignore[attr-defined]
            ov.animation = matched
            cfg = _overlay_config()
            cfg.enabled = True
            cfg.animation = matched
            ov.show(cfg)

            # B1: optional preview duration
            try:
                preview_dur = float(args[1]) if len(args) > 1 else 4.0
                preview_dur = max(1.0, min(120.0, preview_dur))
            except ValueError:
                preview_dur = 4.0

            def _revert_engine() -> None:
                self._drawille_show_hide(getattr(self, "agent_running", False))  # type: ignore[attr-defined]

            self.set_timer(preview_dur, _revert_engine)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _try_auto_title(self) -> None:
        """Derive a session title from the first user message and save it (once per session)."""
        db = getattr(self, "_session_db", None) or getattr(getattr(self, "cli", None), "_session_db", None)
        session_id = getattr(getattr(self, "cli", None), "session_id", None)
        if not db or not session_id:
            return
        history = getattr(getattr(self, "cli", None), "conversation_history", None) or []
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

        _app = self
        _db, _sid, _title = db, session_id, title

        def _save_title_fn() -> None:
            try:
                updated = _db.set_title_if_unset(_sid, _title)
                if updated:
                    _app.call_from_thread(setattr, _app, "session_label", _title)  # type: ignore[attr-defined]
            except Exception:
                pass

        try:
            self.run_worker(_save_title_fn, thread=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._auto_title_done = True  # type: ignore[attr-defined]

    def _toggle_drawille_overlay(self) -> None:
        """Ctrl+Shift+A: dismiss overlay if visible, else show it."""
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, DrawilleOverlayCfg, _overlay_config
        try:
            overlay = self.query_one("#drawille-overlay", _DO)  # type: ignore[attr-defined]
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

    def action_open_anim_config(self) -> None:
        self._toggle_drawille_overlay()

    # --- Undo / Retry / Rollback (SPEC-C) ---

    def _initiate_undo(self) -> None:
        from hermes_cli.tui.widgets import MessagePanel
        if self._undo_in_progress:  # type: ignore[attr-defined]
            self._flash_hint("⚠  Undo in progress", 1.5)  # type: ignore[attr-defined]
            return
        if self.agent_running:  # type: ignore[attr-defined]
            self._flash_hint("⚠  Cannot undo while agent is running", 2.0)  # type: ignore[attr-defined]
            return
        panels = list(self.query(MessagePanel))  # type: ignore[attr-defined]
        if not panels:
            self._flash_hint("⚠  Nothing to undo", 1.5)  # type: ignore[attr-defined]
            return
        last_panel = panels[-1]
        user_text = getattr(last_panel, "_user_text", "")
        state = UndoOverlayState(
            deadline=_time.monotonic() + 10,
            response_queue=queue.Queue(),
            user_text=user_text[:80] + "…" if len(user_text) > 80 else user_text,
            has_checkpoint=self._has_rollback_checkpoint(),
        )
        self._pending_undo_panel = last_panel  # type: ignore[attr-defined]
        self._pending_rollback_n = 0  # type: ignore[attr-defined]
        self.undo_state = state  # type: ignore[attr-defined]

    @work(thread=False)
    async def _run_undo_sequence(self, panel: Any) -> None:
        try:
            self._undo_in_progress = True  # type: ignore[attr-defined]
            panel.styles.opacity = 0.3
            await asyncio.sleep(0.4)
            try:
                await asyncio.to_thread(self.cli.agent.undo)  # type: ignore[attr-defined]
            except (AttributeError, NotImplementedError):
                self._flash_hint("⚠  Undo not supported by agent", 2.0)  # type: ignore[attr-defined]
                panel.styles.opacity = 1.0
                return
            panel.remove()
            user_text = getattr(panel, "_user_text", "")
            if user_text:
                try:
                    from hermes_cli.tui.input_widget import HermesInput
                    hi = self.query_one(HermesInput)  # type: ignore[attr-defined]
                    hi.value = user_text
                    hi.cursor_position = len(user_text)
                except NoMatches:
                    pass
            self._flash_hint("↩  Undo done", 2.0)  # type: ignore[attr-defined]
        finally:
            self._undo_in_progress = False  # type: ignore[attr-defined]

    def _initiate_retry(self) -> None:
        from hermes_cli.tui.widgets import MessagePanel
        if self.agent_running:  # type: ignore[attr-defined]
            self._flash_hint("⚠  Cannot retry while agent is running", 2.0)  # type: ignore[attr-defined]
            return
        panels = list(self.query(MessagePanel))  # type: ignore[attr-defined]
        if not panels:
            self._flash_hint("⚠  Nothing to retry", 1.5)  # type: ignore[attr-defined]
            return
        last_user_text = getattr(panels[-1], "_user_text", "")
        if not last_user_text:
            self._flash_hint("⚠  No user message to retry", 1.5)  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            hi = self.query_one(HermesInput)  # type: ignore[attr-defined]
            hi.value = last_user_text
            hi.cursor_position = len(last_user_text)
            hi.action_submit()
        except NoMatches:
            pass

    def _initiate_rollback(self, text: str) -> None:
        m = re.match(r"^/rollback(?:\s+(\d+))?$", text.strip())
        if not m:
            self._flash_hint("⚠  Usage: /rollback [N]", 2.0)  # type: ignore[attr-defined]
            return
        n = int(m.group(1)) if m.group(1) else 0
        state = UndoOverlayState(
            deadline=_time.monotonic() + 15,
            response_queue=queue.Queue(),
            user_text=f"Filesystem rollback (checkpoint {n})",
            has_checkpoint=True,
        )
        self._pending_undo_panel = None  # type: ignore[attr-defined]
        self._pending_rollback_n = n  # type: ignore[attr-defined]
        self.undo_state = state  # type: ignore[attr-defined]

    @work(thread=False)
    async def _run_rollback_sequence(self, n: int) -> None:
        try:
            await asyncio.to_thread(self.cli.agent.rollback, n)  # type: ignore[attr-defined]
            self._flash_hint("↩  Rollback done", 2.0)  # type: ignore[attr-defined]
        except (AttributeError, NotImplementedError):
            self._flash_hint("⚠  Rollback not supported by agent", 2.0)  # type: ignore[attr-defined]
