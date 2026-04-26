"""_ToolPanelActionsMixin — all keyboard action handlers for ToolPanel."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_cli.tui.io_boundary import safe_open_url, safe_edit_cmd

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_payload import ResultKind


# HF-B: re-show toggle hint after this many seconds of unfocus
TOGGLE_HINT_RESHOW_SECONDS = 300


class _ToolPanelActionsMixin:
    """Keyboard action handlers and their private helpers."""

    @staticmethod
    def _next_tier_in_cycle(current: "object") -> "object":
        from hermes_cli.tui.tool_panel.density import DensityTier
        cycle = (DensityTier.DEFAULT, DensityTier.COMPACT, DensityTier.HERO)
        try:
            idx = cycle.index(current)  # type: ignore[arg-type]
        except ValueError:
            # TRACE or any future tier outside the cycle: reset to DEFAULT.
            return DensityTier.DEFAULT
        return cycle[(idx + 1) % len(cycle)]

    def action_toggle_collapse(self) -> None:
        block = getattr(self, "_block", None)
        tail = getattr(block, "_tail", None) if block is not None else None
        if tail is not None and tail.has_class("--visible"):
            tail.remove_class("--visible")
            if hasattr(tail, "dismiss"):
                tail.dismiss()
            return
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        requested_tier = self._next_tier_in_cycle(self._resolver.tier)  # type: ignore[attr-defined]
        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = requested_tier  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        inputs = DensityInputs(
            phase=phase,
            is_error=bool(
                getattr(self._result_summary_v4, "is_error", False)  # type: ignore[attr-defined]
                if self._result_summary_v4 else False  # type: ignore[attr-defined]
            ),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=requested_tier,  # type: ignore[arg-type]
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,  # irrelevant; override wins
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        if requested_tier == DensityTier.HERO and self._resolver.tier != DensityTier.HERO:  # type: ignore[attr-defined]
            self._flash_header("hero unavailable", tone="warning")

    def action_density_trace(self) -> None:
        """Force TRACE tier — show everything, no row clamp."""
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = DensityTier.TRACE  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        inputs = DensityInputs(
            phase=phase,
            is_error=bool(
                getattr(self._result_summary_v4, "is_error", False)  # type: ignore[attr-defined]
                if self._result_summary_v4 else False  # type: ignore[attr-defined]
            ),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=DensityTier.TRACE,
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,  # irrelevant; override wins
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        if self._resolver.tier != DensityTier.TRACE:  # type: ignore[attr-defined]
            if inputs.is_error:
                self._flash_header("trace unavailable — block errored", tone="warning")
                self._user_collapse_override = False  # type: ignore[attr-defined]
                self._user_override_tier = None  # type: ignore[attr-defined]
            elif inputs.phase in (ToolCallState.STREAMING, ToolCallState.STARTED):
                self._flash_header("trace pending — block still streaming", tone="warning")
                # Flags stay set; post-completion resolve will promote to TRACE.
            else:
                self._flash_header("trace unavailable", tone="warning")
                self._user_collapse_override = False  # type: ignore[attr-defined]
                self._user_override_tier = None  # type: ignore[attr-defined]

    def action_density_cycle(self) -> None:
        """Cycle density DEFAULT → COMPACT → HERO → DEFAULT via explicit D key."""
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        requested = self._next_tier_in_cycle(self._resolver.tier)  # type: ignore[attr-defined]
        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = requested  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        inputs = DensityInputs(
            phase=phase,
            is_error=self._is_error(),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=requested,  # type: ignore[arg-type]
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        if self._resolver.tier != requested:  # type: ignore[attr-defined]
            # Resolver rejected the target tier (e.g. HERO ineligible for short output)
            self._flash_header(
                f"{requested.value} → {self._resolver.tier.value}",  # type: ignore[attr-defined]
                tone="warning",
            )
        else:
            self._flash_header(f"density: {self._resolver.tier.value}")  # type: ignore[attr-defined]

    def action_open_primary(self) -> None:
        import os
        import shlex
        header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
        if header is not None and getattr(header, "_path_clickable", False) and header._full_path:
            self._flash_header("opening…")  # flash before the blocking call
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                self.app._open_path_action(header, header._full_path, opener, False)  # type: ignore[attr-defined]
            except Exception:
                self._flash_header("open failed", tone="error")
            return
        paths = self._result_paths_for_action()
        if not paths:
            return
        target = paths[0]
        is_url = "://" in target
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if editor and not is_url:
            safe_edit_cmd(
                self,
                shlex.split(editor),
                target,
                on_exit=lambda: self._flash_header("closed"),
                on_error=lambda exc: (
                    self._flash_header(
                        f"editor failed: {getattr(exc, 'reason', str(exc))}",
                        tone="error",
                    )
                    if self.is_mounted else None  # type: ignore[attr-defined]
                ),
            )
        else:
            self._flash_header("opening…")
            safe_open_url(
                self,
                target if is_url else Path(target).resolve().as_uri(),
                on_error=lambda exc: (
                    self._flash_header(f"could not open: {exc}", tone="error")
                    if self.is_mounted else None  # type: ignore[attr-defined]
                ),
            )

    def _result_paths_for_action(self) -> list[str]:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        paths: list[str] = []
        if rs is not None:
            for artifact in (rs.artifacts or ()):
                if artifact.kind in ("file", "url"):
                    paths.append(artifact.path_or_url)
        if not paths:
            paths = list(self._result_paths)  # type: ignore[attr-defined]
        return paths

    def _flash_header(self, msg: str, tone: str = "success") -> None:
        from hermes_cli.tui.services.feedback import NORMAL
        try:
            self.app.feedback.flash(  # type: ignore[attr-defined]
                f"tool-header::{self.id}",  # type: ignore[attr-defined]
                msg,
                duration=1.2,
                tone=tone,
                priority=NORMAL,
            )
        except Exception:
            pass

    def action_copy_body(self) -> None:
        text = self.copy_content()  # type: ignore[attr-defined]
        if not text:
            self._flash_header("body: nothing to copy", tone="warning")
            return
        self.app._copy_text_with_hint(text)  # type: ignore[attr-defined]
        from hermes_cli.tui.streaming_microcopy import _human_size
        size = len(text.encode("utf-8"))
        size_suffix = f" ({_human_size(size)})" if size >= 1024 else ""
        self._flash_header(f"copied text{size_suffix}")

    def action_open_url(self) -> None:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        url: str | None = None
        if rs is not None:
            for action in (rs.actions or ()):
                if action.kind == "open_url" and action.payload:
                    url = action.payload
                    break
            if not url:
                for artifact in (rs.artifacts or ()):
                    if artifact.kind == "url":
                        url = artifact.path_or_url
                        break
        if not url:
            self._flash_header("no URL in result", tone="warning")
            return
        self._flash_header("opening…")
        safe_open_url(
            self,
            url,
            on_error=lambda exc: (
                self._flash_header(f"open failed: {exc}", tone="error")
                if self.is_mounted else None  # type: ignore[attr-defined]
            ),
        )

    def action_edit_cmd(self) -> None:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        payload: str | None = None
        if rs is not None:
            for action in (rs.actions or ()):
                if action.kind == "edit_cmd" and action.payload:
                    payload = action.payload
                    break
        if not payload:
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)  # type: ignore[attr-defined]
            existing = inp.text.strip() if hasattr(inp, "text") else ""
            if existing:
                try:
                    inp._save_to_history(existing)
                except Exception:
                    pass
            inp.value = payload
            inp.focus()
            self._flash_header("edit cmd")
        except Exception:
            self._flash_header("edit unavailable")

    def action_copy_err(self) -> None:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        if rs is None:
            return
        payload = rs.stderr_tail
        if not payload:
            for action in (rs.actions or ()):
                if action.kind == "copy_err" and action.payload:
                    payload = action.payload
                    break
        if not payload:
            self._flash_header("stderr: nothing to copy", tone="warning")
            return
        self.app._copy_text_with_hint(payload)  # type: ignore[attr-defined]
        self._flash_header("copied stderr")

    def action_copy_paths(self) -> None:
        paths = self._result_paths_for_action()
        if not paths:
            self._flash_header("paths: nothing to copy", tone="warning")
            return
        self.app._copy_text_with_hint("\n".join(paths))  # type: ignore[attr-defined]
        self._flash_header(f"copied paths ({len(paths)})")

    def action_retry(self) -> None:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        if rs is None or not rs.is_error:
            self._flash_header("no error")
            return
        try:
            self.app._svc_commands.initiate_retry()  # type: ignore[attr-defined]
            self._flash_header("retrying…")
        except Exception:
            self._flash_header("retry failed")

    def action_copy_invocation(self) -> None:
        terminal_width = getattr(self.app, "size", None)  # type: ignore[attr-defined]
        terminal_width = terminal_width.width if terminal_width else 80
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            spec = spec_for(self._tool_name or "")  # type: ignore[attr-defined]
            is_shell = spec.category == ToolCategory.SHELL
            cat_name = spec.category.value
        except Exception:
            is_shell = False
            cat_name = "tool"
        label = self._tool_name or "tool"  # type: ignore[attr-defined]
        if is_shell:
            block = self._block  # type: ignore[attr-defined]
            cmd = ""
            if block is not None:
                args = getattr(block, "_header", None)
                args = getattr(args, "_header_args", {}) if args else {}
                cmd = str(args.get("command") or args.get("cmd") or "")
            header_line = f"{label} (shell)  $  {cmd}"
        else:
            primary_label = self._tool_name or "tool"  # type: ignore[attr-defined]
            block = self._block  # type: ignore[attr-defined]
            if block is not None:
                _hdr = getattr(block, "_header", None)
                if _hdr is not None:
                    primary_label = _hdr._label or primary_label
            header_line = f"{label} ({cat_name})    {primary_label}"
        sep_len = min(40, terminal_width - 4)
        separator = "─" * sep_len
        body = self.copy_content()  # type: ignore[attr-defined]
        text = "\n".join([header_line, separator, body])
        self.app._copy_text_with_hint(text)  # type: ignore[attr-defined]
        self._flash_header("copied invocation")

    def action_copy_ansi(self) -> None:
        import io
        from rich.console import Console
        terminal_width = getattr(self.app, "size", None)  # type: ignore[attr-defined]
        terminal_width = terminal_width.width if terminal_width else 80
        block = self._block  # type: ignore[attr-defined]
        if block is None:
            return
        all_rich = getattr(block, "_all_rich", None)
        if all_rich is None:
            try:
                from hermes_cli.tui.widgets import CopyableRichLog
                rl = block._body.query_one(CopyableRichLog)
                all_rich = getattr(rl, "_all_rich", None)
            except Exception:
                pass
        if not all_rich:
            self.action_copy_body()
            return
        buf = io.StringIO()
        console = Console(force_terminal=True, width=terminal_width, file=buf, highlight=False)
        for t in all_rich:
            console.print(t, highlight=False)
        ansi_text = buf.getvalue()
        self.app._copy_text_with_hint(ansi_text)  # type: ignore[attr-defined]
        from hermes_cli.tui.streaming_microcopy import _human_size
        size = len(ansi_text.encode("utf-8"))
        size_suffix = f" ({_human_size(size)})" if size >= 1024 else ""
        self._flash_header(f"copied ANSI{size_suffix}")

    def action_copy_html(self) -> None:
        from rich.console import Console
        terminal_width = getattr(self.app, "size", None)  # type: ignore[attr-defined]
        terminal_width = terminal_width.width if terminal_width else 80
        block = self._block  # type: ignore[attr-defined]
        if block is None:
            return
        all_rich = getattr(block, "_all_rich", None)
        if all_rich is None:
            try:
                from hermes_cli.tui.widgets import CopyableRichLog
                rl = block._body.query_one(CopyableRichLog)
                all_rich = getattr(rl, "_all_rich", None)
            except Exception:
                pass
        if not all_rich:
            self._flash_header("HTML: nothing to copy", tone="warning")
            return
        console = Console(record=True, width=terminal_width)
        for t in all_rich:
            console.print(t, highlight=False)
        html = console.export_html(inline_styles=True)
        try:
            css = self.app.get_css_variables()  # type: ignore[attr-defined]
            bg_hex = css.get("app-bg") or css.get("background") or "#1e1e2e"
        except Exception:
            bg_hex = "#1e1e2e"
        html = html.replace('<pre style="', f'<pre style="background:{bg_hex}; ', 1)
        self.app._copy_text_with_hint(html)  # type: ignore[attr-defined]
        from hermes_cli.tui.streaming_microcopy import _human_size as _hs
        _html_size = len(html.encode("utf-8"))
        _size_suffix = f" ({_hs(_html_size)})" if _html_size >= 1024 else ""
        try:
            from hermes_cli.tui.clipboard_cache import write_html as _write_html
            cache_path = _write_html(html)
            self._flash_header(f"copied HTML{_size_suffix}  (saved {cache_path})")
        except Exception:
            self._flash_header(f"copied HTML{_size_suffix}")

    def action_copy_urls(self) -> None:
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        if rs is None:
            return
        urls = [a.path_or_url for a in rs.artifacts if a.kind == "url"]
        if not urls:
            self._flash_header("URLs: nothing to copy", tone="warning")
            return
        self.app._copy_text_with_hint("\n".join(urls))  # type: ignore[attr-defined]
        self._flash_header(f"copied URLs ({len(urls)})")

    def action_copy_full_path(self) -> None:
        header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
        if header is None:
            return
        path = getattr(header, "_full_path", None)
        if not path:
            self._flash_header("path: nothing to copy", tone="warning")
            return
        self.app._copy_text_with_hint(path)  # type: ignore[attr-defined]
        self._flash_header("copied path")

    def action_dismiss_error_banner(self) -> None:
        try:
            if self._footer_pane is not None:  # type: ignore[attr-defined]
                self._footer_pane._remediation_row.update("")  # type: ignore[attr-defined]
                self._footer_pane._remediation_row.remove_class("footer-remediation--error")  # type: ignore[attr-defined]
                self._footer_pane.remove_class("has-remediation")  # type: ignore[attr-defined]
        except Exception:
            pass

    def action_show_context_menu(self) -> None:
        header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
        if header is None:
            return
        try:
            header._show_context_menu_at_center()
        except Exception:
            pass

    def action_scroll_body_down(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            log.scroll_down(animate=False)
        except Exception:
            pass

    def action_scroll_body_up(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            log.scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_body_page_down(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            page = max(5, (self.size.height or 20) // 2)  # type: ignore[attr-defined]
            for _ in range(page):
                log.scroll_down(animate=False)
        except Exception:
            pass

    def action_scroll_body_page_up(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            page = max(5, (self.size.height or 20) // 2)  # type: ignore[attr-defined]
            for _ in range(page):
                log.scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_body_top(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            log.scroll_home(animate=False)
        except Exception:
            pass

    def action_scroll_body_bottom(self) -> None:
        if self.collapsed:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)  # type: ignore[attr-defined]
            log.scroll_end(animate=False)
        except Exception:
            pass

    def action_show_help(self) -> None:
        from hermes_cli.tui.overlays import ToolPanelHelpOverlay
        from textual.css.query import NoMatches
        try:
            overlay = self.app.query_one(ToolPanelHelpOverlay)  # type: ignore[attr-defined]
        except NoMatches:
            # overlay not yet mounted; action is a no-op before TUI is fully composed
            return
        is_opening = not overlay.has_class("--visible")
        if is_opening:
            overlay.add_class("--visible")
            # Only mark categories discovered when actually opening, not closing
            from . import _completion as _comp_mod
            from hermes_cli.tui.tool_category import ToolCategory
            for _cat in ToolCategory:
                _comp_mod._DISCOVERY_SHOWN_CATEGORIES.add(_cat)
        else:
            overlay.remove_class("--visible")

    def on_focus(self) -> None:
        import time as _time
        self._maybe_show_discovery_hint()  # type: ignore[attr-defined]
        self._refresh_collapsed_strip()  # type: ignore[attr-defined]
        now = _time.monotonic()
        last_shown = getattr(self, "_toggle_hint_shown_at", 0.0)
        if now - last_shown < TOGGLE_HINT_RESHOW_SECONDS:
            return
        block = getattr(self, "_block", None)
        if block is not None:
            header = getattr(block, "_header", None)
            if not getattr(header, "_has_affordances", False):
                return
        self._toggle_hint_shown_at = now  # type: ignore[attr-defined]
        self._flash_header("(Enter) toggle", tone="accent")

    def on_blur(self) -> None:
        self._refresh_collapsed_strip()  # type: ignore[attr-defined]

    def _is_error(self) -> bool:
        """True when the panel is in a completed error state (non-zero exit code)."""
        rs = getattr(self, "_result_summary_v4", None)  # type: ignore[attr-defined]
        return rs is not None and rs.exit_code not in (None, 0)

    def _refresh_hint_row(self) -> None:
        """Recompute hint row content from the dynamic builder."""
        hint_row = getattr(self, "_hint_row", None)  # type: ignore[attr-defined]
        if hint_row is None:
            return
        show = getattr(self, "has_focus", False) or self.has_class("--has-affordances")  # type: ignore[attr-defined]
        if show:
            hint_row.update(self._build_hint_text())
            hint_row.add_class("--has-hint")
        else:
            hint_row.update("")
            hint_row.remove_class("--has-hint")

    def watch_has_focus(self, value: bool) -> None:
        if self._hint_row is None:  # type: ignore[attr-defined]
            return
        self._hint_visible = value  # type: ignore[attr-defined]
        self._refresh_hint_row()
        if value:
            try:
                block = self._block  # type: ignore[attr-defined]
                if block is not None and getattr(block._header, "_path_clickable", False):
                    self.post_message(self.__class__.PathFocused(self))  # type: ignore[attr-defined]
            except Exception:
                pass

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        self._last_resize_w = width  # type: ignore[attr-defined]
        always_visible = self.has_class("--has-affordances")  # type: ignore[attr-defined]
        if (self._hint_visible or always_visible) and self._hint_row is not None:  # type: ignore[attr-defined]
            self._hint_row.update(self._build_hint_text())  # type: ignore[attr-defined]

    def _visible_footer_action_kinds(self) -> "set[str]":
        """Return the set of action kind names currently visible as chips in the footer."""
        fp = getattr(self, "_footer_pane", None)
        if fp is None or fp.styles.display == "none":
            return set()
        try:
            return {
                getattr(b, "name", "") for b in fp._action_row.query(".--action-chip")
            } - {""}
        except Exception:
            # Best-effort DOM query during layout; partial DOM is expected at startup
            return set()

    def _build_hint_text(self) -> "Any":
        """Render hint row as a width-aware list of capability-bound keys.

        Order: primary (always shown) → contextual (visible when capable) →
        discovery (rotating tip + F1). Truncator pins F1 and primary; drops
        contextual right-to-left with explicit '+N more' marker (see _truncate_hints).
        """
        from rich.text import Text  # noqa: F401 (used by _render_hints return type)

        _mounted = getattr(self, "is_mounted", True)
        _size = getattr(self, "size", None)
        if not _mounted or _size is None:
            width = 80
        else:
            width = _size.width or 80

        primary, contextual = self._collect_hints()
        return self._render_hints(primary, contextual, width)

    def _collect_hints(self) -> "tuple[list[tuple[str, str]], list[tuple[str, str]]]":
        """Compute (primary, contextual) hint pairs from current panel state."""
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        block = self._block  # type: ignore[attr-defined]
        streaming = (
            block is not None
            and hasattr(block, "_completed")
            and not block._completed
        )
        is_error = self._is_error()
        is_collapsed = bool(getattr(self, "collapsed", False))  # type: ignore[attr-defined]

        # PRIMARY — always shown, max 2 entries.
        primary: list[tuple[str, str]] = []
        if streaming:
            primary.append(("Enter", "follow"))
            primary.append(("f",     "tail"))
        elif is_collapsed:
            # "expand" (not "toggle") so the label is unambiguous about direction
            primary.append(("Enter", "expand"))
            primary.append(("y",     "copy"))
        elif is_error:
            # Replaces old ("x", "dismiss"): retry is the primary recovery action.
            primary.append(("Enter", "toggle"))
            primary.append(("r",     "retry"))
        else:
            primary.append(("Enter", "toggle"))
            primary.append(("y",     "copy"))

        # CONTEXTUAL — capability-gated, dedup against visible footer chips.
        visible = self._visible_footer_action_kinds()
        contextual: list[tuple[str, str]] = []

        # Body / pagination
        if self._get_omission_bar() is not None:
            contextual.append(("+", "more"))
            contextual.append(("*", "all"))

        # Recovery (skip when footer already shows the chip)
        if rs is not None:
            has_stderr = bool(rs.stderr_tail) or any(
                a.kind == "copy_err" and a.payload for a in (rs.actions or ())
            )
            if has_stderr and "copy_err" not in visible:
                contextual.append(("e", "stderr"))
            # Skip retry in contextual when it already appears in the primary bucket (error state)
            if is_error and "retry" not in visible and not streaming and ("r", "retry") not in primary:
                contextual.append(("r", "retry"))

        # Artifacts
        if rs is not None:
            if self._result_paths_for_action() and "open_first" not in visible:
                contextual.append(("o", "open"))
            if any(a.kind == "url" for a in (rs.artifacts or ())):
                contextual.append(("u", "urls"))
            if any(a.kind == "edit_cmd" and a.payload for a in (rs.actions or ())):
                contextual.append(("E", "edit"))

        # Mode / kind — post-streaming, non-error only (ML-2 / ML-3)
        if not streaming and not is_error and rs is not None:
            _view = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
            _current_kind = getattr(_view, "user_kind_override", None) if _view else None
            _next_label = self._next_kind_label(_current_kind)
            contextual.append(("t", f"as {_next_label}"))
            if _current_kind is not None:
                contextual.append(("T", "auto"))  # revert hint when override active

        # Power copy variants — available when there's a result body
        if rs is not None and not streaming:
            contextual.append(("I", "copy cmd"))

        # Density TRACE — diagnostic; surface only post-completion
        if rs is not None and not streaming and not is_collapsed:
            contextual.append(("alt+t", "trace"))

        # Density cycle — explicit D key; surface post-completion (H-4)
        if rs is not None and not streaming and not is_collapsed:
            contextual.append(("D", "density"))

        return primary, contextual

    def _render_hints(
        self,
        primary: "list[tuple[str, str]]",
        contextual: "list[tuple[str, str]]",
        width: int,
    ) -> "Any":
        """Render the hint row: primary · contextual · +N more · F1 help [tip]."""
        from rich.text import Text
        from hermes_cli.tui.body_renderers._grammar import (
            GLYPH_META_SEP, glyph as _glyph, chip as _chip,
        )
        from rich.cells import cell_len as _cell_len

        sep = f" {_glyph(GLYPH_META_SEP)} "
        sep_w = _cell_len(sep)
        _HINT_ROW_MARGIN = 4  # Reserve space for gaps between primary/contextual/F1 regions

        primary_t = Text()
        for i, (k, l) in enumerate(primary[:2]):
            if i > 0:
                primary_t.append(sep, style="dim")
            primary_t.append_text(_chip(k, l, bracketed=False))

        # F1 always rendered as the trailing pinned slot
        f1_t = Text()
        f1_t.append("F1", style="bold dim")
        f1_t.append(" help", style="dim")

        # Truncate contextual to fit budget (F1 and primary are reserved)
        rendered_contextual, dropped_count = self._truncate_hints(
            contextual,
            budget=max(0, width - primary_t.cell_len - f1_t.cell_len - 2 * sep_w - _HINT_ROW_MARGIN),
        )

        out = Text()
        out.append_text(primary_t)
        if rendered_contextual.cell_len > 0:
            out.append(sep, style="dim")
            out.append_text(rendered_contextual)
        if dropped_count > 0:
            out.append(sep, style="dim")
            out.append(f"+{dropped_count} more", style="dim italic")
        out.append(sep, style="dim")
        out.append_text(f1_t)

        # Rotating power-key tip — wide widths only, post-streaming, non-error.
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        streaming = (
            self._block is not None  # type: ignore[attr-defined]
            and hasattr(self._block, "_completed")  # type: ignore[attr-defined]
            and not self._block._completed  # type: ignore[attr-defined]
        )
        if width >= 80 and rs is not None and not streaming and not rs.is_error:
            from hermes_cli.tui.services import tool_tips
            tip_key, tip_label = tool_tips.current_tip()
            out.append("  ", style="dim")
            out.append(tip_key, style="bold dim italic")
            out.append(f" {tip_label}", style="dim italic")

        return out

    def _truncate_hints(
        self,
        contextual: "list[tuple[str, str]]",
        budget: int,
    ) -> "tuple[Any, int]":
        """Return (rendered_text, dropped_count). Drops right-to-left to fit budget."""
        from rich.text import Text
        from hermes_cli.tui.body_renderers._grammar import (
            GLYPH_META_SEP, glyph as _glyph, chip as _chip,
        )
        from rich.cells import cell_len as _cell_len

        sep = f" {_glyph(GLYPH_META_SEP)} "
        sep_w = _cell_len(sep)

        fitted: list[tuple[str, str]] = []
        used = 0
        for k, l in contextual:
            chip_w = _cell_len(k) + 1 + _cell_len(l)
            next_w = used + (sep_w if fitted else 0) + chip_w
            if next_w > budget:
                break
            fitted.append((k, l))
            used = next_w

        out = Text()
        for i, (k, l) in enumerate(fitted):
            if i > 0:
                out.append(sep, style="dim")
            out.append_text(_chip(k, l, bracketed=False))

        dropped = len(contextual) - len(fitted)
        return out, dropped

    def _get_omission_bar(self) -> "Any | None":
        try:
            from hermes_cli.tui.tool_blocks import OmissionBar as _OB
            block = self._block  # type: ignore[attr-defined]
            bar = getattr(block, "_omission_bar_bottom", None)
            if isinstance(bar, _OB) and getattr(block, "_omission_bar_bottom_mounted", False):
                return bar
        except Exception:
            pass
        return None

    def action_expand_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            from hermes_cli.tui.tool_blocks import _PAGE_SIZE
            bar._parent_block.rerender_window(
                bar._visible_start,
                min(bar._total, bar._visible_end + _PAGE_SIZE),
            )

    def action_collapse_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is None:
            return
        from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
        new_start = max(0, bar._visible_start - _PAGE_SIZE)
        new_end = max(_VISIBLE_CAP, bar._visible_end - _PAGE_SIZE)
        if new_start == bar._visible_start and new_end == bar._visible_end:
            self._flash_header("at minimum")
            return
        bar._parent_block.rerender_window(new_start, new_end)

    def action_expand_all_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            bar._parent_block.rerender_window(bar._visible_start, bar._total)

    def action_toggle_tail_follow(self) -> None:
        block = self._block  # type: ignore[attr-defined]
        if not hasattr(block, '_follow_tail'):
            return
        if getattr(block, "_completed", False) is True:
            self._flash_header("tail-follow N/A", tone="warning")
            return
        block._follow_tail = not block._follow_tail
        state = "on" if block._follow_tail else "off"
        self._flash_header(f"tail: {state}")

    def action_copy_output(self) -> None:
        text = self.copy_content()  # type: ignore[attr-defined]
        if text:
            try:
                import pyperclip
                pyperclip.copy(text)
                self.app.notify("Copied output", timeout=1.5)  # type: ignore[attr-defined]
            except Exception:
                self.app.notify("Copy failed — use mouse select", timeout=3)  # type: ignore[attr-defined]

    def action_copy_input(self) -> None:
        text = self._format_arg_summary()  # type: ignore[attr-defined]
        if text:
            try:
                import pyperclip
                pyperclip.copy(text)
                self.app.notify("Copied input", timeout=1.5)  # type: ignore[attr-defined]
            except Exception:
                self.app.notify("Copy failed", timeout=3)  # type: ignore[attr-defined]

    def action_rerun(self) -> None:
        try:
            from hermes_cli.tui.messages import ToolRerunRequested
            self.post_message(ToolRerunRequested(panel=self))  # type: ignore[attr-defined]
            header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
            if header is not None:
                header.flash_success()
        except Exception:
            self.app.notify("Rerun not available", timeout=2)  # type: ignore[attr-defined]

    def action_omission_expand(self) -> None:
        try:
            from hermes_cli.tui.tool_blocks import OmissionBar
            bar = next(iter(self.query(OmissionBar)), None)  # type: ignore[attr-defined]
            if bar is not None:
                bar._do_expand_one()
        except Exception:
            pass

    def action_omission_collapse(self) -> None:
        try:
            from hermes_cli.tui.tool_blocks import OmissionBar
            bar = next(iter(self.query(OmissionBar)), None)  # type: ignore[attr-defined]
            if bar is not None:
                bar._do_collapse_one()
        except Exception:
            pass

    def force_renderer(self, kind: "ResultKind | None") -> None:
        """Set the user KIND override on this panel's view-state and re-render.

        KO-4: writes view.user_kind_override (single source of truth). Legacy
        self._forced_renderer_kind slot is gone. Passing kind=None clears the
        override (cycle returns to classifier verdict).
        """
        try:
            from hermes_cli.tui.body_renderers import pick_renderer
            from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult, ResultKind
            from hermes_cli.tui.tool_panel.density import DensityTier
            from hermes_cli.tui.services.tools import ToolCallState

            view = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
            if view is not None:
                view.user_kind_override = kind

            output_raw = self.copy_content()  # type: ignore[attr-defined]
            payload = ToolPayload(
                tool_name=self._tool_name,  # type: ignore[attr-defined]
                category=self._category,    # type: ignore[attr-defined]
                args=self._tool_args or {}, # type: ignore[attr-defined]
                input_display=None,
                output_raw=output_raw,
                line_count=self._body_line_count(),  # type: ignore[attr-defined]
            )
            if kind is not None:
                cls_result = ClassificationResult(kind=kind, confidence=1.0)
                # KO-C: annotate user-forced renders so renderers can disclose them
                object.__setattr__(cls_result, "_user_forced", True)
            else:
                stamped = view.kind if view is not None else None
                cls_result = stamped or ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

            phase = view.state if view is not None else ToolCallState.DONE
            density = view.density if view is not None else DensityTier.DEFAULT

            renderer_cls = pick_renderer(
                cls_result, payload,
                phase=phase, density=density,
                user_kind_override=kind,
            )
            # force_renderer is the ACTIVE entry point; replay the swap even
            # when the result is FallbackRenderer so a "clear override" cycle
            # produces an observable mount.
            self._swap_renderer(renderer_cls, payload, cls_result)  # type: ignore[attr-defined]
        except Exception:
            _log.exception("force_renderer failed for kind=%s", kind)

    def action_cycle_kind(self) -> None:
        """KO-4: cycle user KIND override on focused, post-streaming block."""
        # KO-D: 150 ms debounce — rapid presses on slow terminals cause flicker
        now = time.monotonic()
        last = getattr(self, "_cycle_kind_last_fired", 0.0)
        if now - last < 0.15:
            return
        self._cycle_kind_last_fired: float = now

        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.services.tools import ToolCallState

        # KO-B: TEXT intentionally absent — pick_renderer routes both None (auto)
        # and TEXT (override) to FallbackRenderer for typical payloads, so the
        # two stops produce identical output.  Every stop in this cycle is visually
        # distinct.
        cycle: tuple["ResultKind | None", ...] = (
            None,
            ResultKind.CODE,
            ResultKind.JSON,
            ResultKind.DIFF,
            ResultKind.TABLE,
            ResultKind.LOG,
            ResultKind.SEARCH,
        )

        view = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        if view is None:
            self._flash_header("no block focused", tone="warning")
            return
        _RENDERABLE = {
            ToolCallState.COMPLETING,
            ToolCallState.DONE,
            ToolCallState.ERROR,
            ToolCallState.CANCELLED,
        }
        # KO-A: flash on every no-op path instead of silently returning
        if view.state not in _RENDERABLE:
            if view.state in (ToolCallState.STREAMING, ToolCallState.STARTED):
                self._flash_header("render-as: wait for completion", tone="warning")
            else:
                self._flash_header(
                    f"render-as N/A (state={view.state.value})", tone="warning"
                )
            return

        current = view.user_kind_override
        try:
            idx = cycle.index(current)
        except ValueError:
            _log.debug("user_kind_override=%r not in cycle; snapping to None", current)
            idx = -1
        next_kind = cycle[(idx + 1) % len(cycle)]

        self.force_renderer(next_kind)  # type: ignore[attr-defined]
        label = next_kind.value if next_kind is not None else "auto"
        self._flash_header(f"render as: {label}", tone="accent")

    # ML-3: canonical cycle order (mirrors action_cycle_kind — keep in sync)
    _KIND_CYCLE: "tuple[Any, ...]" = ()  # populated lazily after ResultKind import

    @staticmethod
    def _next_kind_label(current: "Any") -> str:
        """Return the lowercase label of the kind `t` would advance to."""
        from hermes_cli.tui.tool_payload import ResultKind as _RK
        cycle = (
            None,
            _RK.CODE,
            _RK.JSON,
            _RK.DIFF,
            _RK.TABLE,
            _RK.LOG,
            _RK.SEARCH,
        )
        try:
            idx = cycle.index(current)
        except ValueError:
            idx = -1
        nxt = cycle[(idx + 1) % len(cycle)]
        return nxt.value.lower() if nxt is not None else "auto"

    def action_kind_revert(self) -> None:
        """ML-2: clear user_kind_override and flash confirmation."""
        view = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        if view is None:
            self._flash_header("no block focused", tone="warning")
            return
        if view.user_kind_override is None:
            self._flash_header("render as: no override", tone="warning")
            return
        view.user_kind_override = None
        self.force_renderer(None)  # type: ignore[attr-defined]
        self._flash_header("render as: auto", tone="accent")

    def on_tool_header_clicked(self, event: "object") -> None:
        getattr(event, "stop", lambda: None)()
        self.collapsed = not self.collapsed  # type: ignore[attr-defined]
