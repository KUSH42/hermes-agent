"""_ToolPanelActionsMixin — all keyboard action handlers for ToolPanel."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.message import Message

from hermes_cli.tui.io_boundary import safe_open_url, safe_edit_cmd

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_payload import ResultKind


class EditToolArgsRequested(Message):
    """ER-5: emitted when the user requests to re-edit a failed tool's arguments."""

    def __init__(self, tool_call_id: "str | None") -> None:
        super().__init__()
        self.tool_call_id = tool_call_id


# HF-B: re-show toggle hint after this many seconds of unfocus
TOGGLE_HINT_RESHOW_SECONDS = 300

# DC-1: concept §Block-level keys H5 — full 4-tier cycle.
# Tuple is populated lazily on first use to avoid import-time circular deps.
_DENSITY_CYCLE: "tuple | None" = None


def _density_cycle() -> "tuple":
    global _DENSITY_CYCLE
    if _DENSITY_CYCLE is None:
        from hermes_cli.tui.tool_panel.density import DensityTier
        _DENSITY_CYCLE = (
            DensityTier.DEFAULT,
            DensityTier.COMPACT,
            DensityTier.TRACE,
            DensityTier.HERO,
        )
    return _DENSITY_CYCLE


# DC-3: concept §H5 threshold — HERO requires at least this many body rows.
_HERO_MIN_BODY_ROWS: int = 5

_APP_BG_FALLBACK: str = "#1e1e2e"  # used when app-bg / background CSS vars are missing


def _is_hero_row_legal(body_lines: int) -> bool:
    return body_lines >= _HERO_MIN_BODY_ROWS


def _next_legal_tier_static(
    start: "object",
    direction: int,
    body_lines: int,
) -> "object":
    """Skip HERO if row-budget forbids it; return nearest legal tier.

    direction: +1 = forward, -1 = reverse.
    Returns start if no legal tier found (all cycled without a legal candidate).
    Caller is responsible for the post-resolve pressure flash.
    """
    from hermes_cli.tui.tool_panel.density import DensityTier
    cycle = _density_cycle()
    try:
        idx = cycle.index(start)  # type: ignore[arg-type]
    except ValueError:
        return DensityTier.DEFAULT
    for _ in range(len(cycle)):
        idx = (idx + direction) % len(cycle)
        candidate = cycle[idx]
        if candidate != DensityTier.HERO or _is_hero_row_legal(body_lines):
            return candidate
        # HERO row-budget forbidden: skip and continue
    return start


class _ToolPanelActionsMixin:
    """Keyboard action handlers and their private helpers."""

    @staticmethod
    def _next_tier_in_cycle(current: "object") -> "object":
        """Advance to the next tier in the forward density cycle.

        Cycle: DEFAULT → COMPACT → TRACE → HERO → DEFAULT (concept §H5).
        Any tier outside the cycle resets to DEFAULT.
        """
        from hermes_cli.tui.tool_panel.density import DensityTier
        cycle = _density_cycle()
        try:
            idx = cycle.index(current)  # type: ignore[arg-type]
        except ValueError:
            return DensityTier.DEFAULT
        return cycle[(idx + 1) % len(cycle)]

    @staticmethod
    def _prev_tier_in_cycle(current: "object") -> "object":
        """Retreat one step in the density cycle (reverse of _next_tier_in_cycle).

        Any tier outside the cycle resets to DEFAULT.
        """
        from hermes_cli.tui.tool_panel.density import DensityTier
        cycle = _density_cycle()
        try:
            idx = cycle.index(current)  # type: ignore[arg-type]
        except ValueError:
            return DensityTier.DEFAULT
        return cycle[(idx - 1) % len(cycle)]

    def action_toggle_collapse(self) -> None:
        # Dismiss a visible tail panel first; Enter has no density effect while tail is open.
        block = getattr(self, "_block", None)
        tail = getattr(block, "_tail", None) if block is not None else None
        if tail is not None and tail.has_class("--visible"):
            tail.remove_class("--visible")
            if hasattr(tail, "dismiss"):
                tail.dismiss()
            return
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        current = self._resolver.tier  # type: ignore[attr-defined]
        if current == DensityTier.COMPACT:
            target = DensityTier.DEFAULT
            flash_label = "expanded"
        else:
            # DEFAULT, HERO, TRACE all collapse to COMPACT.
            target = DensityTier.COMPACT
            flash_label = "collapsed"

        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = target  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        _size = getattr(self, "size", None)
        width = _size.width if _size is not None else 0
        inputs = DensityInputs(
            phase=phase,
            is_error=self._is_error(),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=target,  # type: ignore[arg-type]
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
            width=width,
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        self._flash_header(flash_label, tone="info")

    def _hero_rejection_reason(self, inp: "object") -> str:
        """Explain why a HERO tier request was downgraded."""
        from hermes_cli.tui.tool_panel.layout_resolver import _HERO_KINDS, _HERO_MAX_LINES
        _kind = getattr(inp, "kind", None)
        if _kind not in _HERO_KINDS:
            kind_name = _kind.value if _kind is not None else "unclassified"
            return f"kind {kind_name} not eligible"
        _body = getattr(inp, "body_line_count", 0)
        if _body == 0:
            return "no body content"
        if _body > _HERO_MAX_LINES:
            return f"body too long ({_body} > {_HERO_MAX_LINES})"
        _w = getattr(inp, "width", 0)
        _resolver = getattr(self, "_resolver", None)  # type: ignore[attr-defined]
        _hero_min = getattr(_resolver, "hero_min_width", 0) if _resolver is not None else 0
        if _w and _hero_min and _w < _hero_min:
            return f"terminal too narrow ({_w} < {_hero_min})"
        return "ineligible"

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
            width=self.size.width,  # type: ignore[attr-defined]
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
        """D key — advance density tier in cycle (concept §H5)."""
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        requested_tier = _next_legal_tier_static(
            self._resolver.tier, direction=+1,  # type: ignore[attr-defined]
            body_lines=self._body_line_count(),  # type: ignore[attr-defined]
        )
        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = requested_tier  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        _size = getattr(self, "size", None)
        width = _size.width if _size is not None else 0
        inputs = DensityInputs(
            phase=phase,
            is_error=self._is_error(),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=requested_tier,  # type: ignore[arg-type]
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
            width=width,
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        if requested_tier == DensityTier.HERO and self._resolver.tier != DensityTier.HERO:  # type: ignore[attr-defined]
            self._flash_header("hero mode unavailable", tone="warning")
        else:
            self._flash_header(self._resolver.tier.value, tone="info")  # type: ignore[attr-defined]

    def action_density_cycle_reverse(self) -> None:
        """Shift+D — reverse density tier in cycle (concept §H5)."""
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        requested_tier = _next_legal_tier_static(
            self._resolver.tier, direction=-1,  # type: ignore[attr-defined]
            body_lines=self._body_line_count(),  # type: ignore[attr-defined]
        )
        self._user_collapse_override = True  # type: ignore[attr-defined]
        self._user_override_tier = requested_tier  # type: ignore[attr-defined]
        self._auto_collapsed = False  # type: ignore[attr-defined]
        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None
        _size = getattr(self, "size", None)
        width = _size.width if _size is not None else 0
        inputs = DensityInputs(
            phase=phase,
            is_error=self._is_error(),
            has_focus=False,
            user_scrolled_up=False,
            user_override=True,
            user_override_tier=requested_tier,  # type: ignore[arg-type]
            body_line_count=self._body_line_count(),  # type: ignore[attr-defined]
            threshold=0,
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
            width=width,
        )
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]
        if requested_tier == DensityTier.HERO and self._resolver.tier != DensityTier.HERO:  # type: ignore[attr-defined]
            self._flash_header("hero mode unavailable", tone="warning")
        else:
            self._flash_header(self._resolver.tier.value, tone="info")  # type: ignore[attr-defined]

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

    def action_edit_args(self) -> None:
        """ER-5: emit EditToolArgsRequested so the orchestrator can pre-fill the prompt."""
        vs = getattr(self, "_view_state", None)  # type: ignore[attr-defined]
        tool_call_id = getattr(vs, "tool_call_id", None) if vs is not None else None
        self.post_message(EditToolArgsRequested(tool_call_id))  # type: ignore[attr-defined]
        self._flash_header("edit args…")

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
            bg_hex = css.get("app-bg") or css.get("background") or _APP_BG_FALLBACK
        except Exception as exc:
            _log.debug("app-bg css lookup failed: %s", exc)
            bg_hex = _APP_BG_FALLBACK
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

    def _available_width(self) -> int:
        """Return the content area width in terminal cells."""
        try:
            return self.content_region.width  # type: ignore[attr-defined]
        except Exception:
            return 80

    def _is_error(self) -> bool:
        """True when the panel is in a completed error state."""
        vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        return vs.is_error_for_ui if vs is not None else False

    def _refresh_hint_row(self) -> None:
        """Recompute and apply hint row content based on focus and affordances state."""
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

    def _collect_hints(
        self,
    ) -> "tuple[list[tuple[str, str]], list[tuple[str, str]]]":
        """H-2: Build (primary, contextual) hint lists from panel state.

        Returns two lists of (key, label) pairs. Primary hints are always shown;
        contextual hints are shown when space allows and deduplicated against
        visible footer chips.
        """
        rs = getattr(self, "_result_summary_v4", None)
        block = getattr(self, "_block", None)
        _block_streaming = (
            block is not None
            and hasattr(block, "_completed")
            and not block._completed
        )

        primary: list[tuple[str, str]] = []
        if _block_streaming:
            # Streaming: follow + tail are the two most important actions
            primary.append(("Enter", "follow"))
            primary.append(("f", "tail"))
        else:
            # Binary: COMPACT → "expand"; everything else → "collapse".
            enter_label = "expand" if getattr(self, "collapsed", False) else "collapse"
            primary.append(("Enter", enter_label))
            if self._is_error():
                primary.append(("r", "retry"))
            else:
                primary.append(("y", "copy"))

        # HF-A: consult visible footer chips to suppress duplicate hints
        visible_action_kinds = self._visible_footer_action_kinds()

        contextual: list[tuple[str, str]] = []
        bar = self._get_omission_bar()
        if bar is not None:
            contextual.append(("*", "all"))

        if rs is not None:
            has_copy_err = rs.stderr_tail or any(
                a.kind == "copy_err" and a.payload for a in (rs.actions or ())
            )
            # Recovery contract (ER-4): dedup against visible footer chips.
            if has_copy_err and "copy_err" not in visible_action_kinds:
                contextual.append(("e", "stderr"))
            if self._result_paths_for_action() and "open_first" not in visible_action_kinds:
                contextual.append(("o", "open"))
            has_urls = any(a.kind == "url" for a in (rs.artifacts or ()))
            if has_urls:
                contextual.append(("u", "urls"))
            has_edit = any(a.kind == "edit_cmd" and a.payload for a in (rs.actions or ()))
            if has_edit:
                contextual.append(("E", "edit"))
            # Only add retry in contextual if it's not already in primary (error case)
            if self._is_error() and "retry" not in visible_action_kinds and ("r", "retry") not in primary:
                contextual.insert(0, ("r", "retry"))
            # KO-4 / ML-3: Render-as cycle hint with next-kind preview.
            if not _block_streaming and not self._is_error():
                _view = (
                    getattr(self, "_view_state", None)
                    or (getattr(self, "_lookup_view_state", lambda: None))()
                )
                _current_kind = getattr(_view, "user_kind_override", None) if _view else None
                _next_kind_label = getattr(self, "_next_kind_label", None)
                if _next_kind_label is not None:
                    _next_label = _next_kind_label(_current_kind)
                    contextual.insert(0, ("t", f"as {_next_label}"))
                    if _current_kind is not None:
                        contextual.insert(1, ("T", "auto"))  # ML-2: revert hint when override active

        # DC-4: density cycle hints (D forward, Shift+D reverse) for complete blocks
        if not _block_streaming and not getattr(self, "collapsed", False):
            contextual.append(("D", "density-cycle"))
            contextual.append(("shift+d", "density-back"))

        return primary, contextual

    def _truncate_hints(
        self,
        chips: "list[tuple[str, str]]",
        budget: int,
    ) -> "tuple[Any, int]":
        """H-3: Fit as many chips as possible within ``budget`` terminal cells.

        Returns ``(Text, dropped_count)`` where dropped_count is the number of
        chips that did not fit.
        """
        from rich.text import Text
        t = Text()
        cell_used = 0
        fitted = 0
        for i, (key, label) in enumerate(chips):
            sep = "  " if i > 0 else ""
            chunk = f"{sep}{key} {label}"
            chunk_cells = len(chunk)  # ASCII keys/labels; len == cell width
            if cell_used + chunk_cells > budget and fitted > 0:
                break
            t.append(sep, style="dim")
            t.append(key, style="bold")
            t.append(f" {label}", style="dim")
            cell_used += chunk_cells
            fitted += 1
        return t, len(chips) - fitted

    def _render_hints(
        self,
        primary: "list[tuple[str, str]]",
        contextual: "list[tuple[str, str]]",
        width: int,
    ) -> "Any":
        """H-3: Render primary + contextual hints into a Rich Text.

        F1 is always appended regardless of width (P-6 / HF-C).
        """
        from rich.text import Text
        narrow = width < 50
        t = Text()

        # Primary (at most 2, always shown)
        for i, (key, label) in enumerate(primary[:2]):
            if i > 0:
                t.append("  ", style="dim")
            t.append(key, style="bold")
            t.append(f" {label}", style="dim")

        # Contextual (truncated to 2 at wide width, 0 at narrow)
        shown_contextual = contextual[:2] if not narrow else []
        n_dropped = len(contextual) - len(shown_contextual)
        if shown_contextual:
            ctx_text, ctx_dropped = self._truncate_hints(shown_contextual, width - t.cell_len - 2)
            n_dropped += ctx_dropped
            if ctx_text.plain:
                t.append("  ", style="dim")
                t.append_text(ctx_text)

        # P-7: +N more when contextual hints were truncated
        if n_dropped > 0:
            t.append("  ", style="dim")
            t.append(f"+{n_dropped}", style="bold dim")
            t.append(" more", style="dim")

        # HF-C / P-6: F1 always pinned regardless of terminal width
        t.append("  F1 ", style="bold dim")
        t.append("help", style="dim")

        return t

    def _build_hint_text(self) -> "Any":
        _mounted = getattr(self, "is_mounted", True)
        _size = getattr(self, "size", None)
        width = ((_size.width if _size is not None else 0) or 80) if _mounted else 80

        primary, contextual = self._collect_hints()
        t = self._render_hints(primary, contextual, width)

        # HF-G: append rotating power-key tip when wide and block is complete
        rs = getattr(self, "_result_summary_v4", None)
        block = getattr(self, "_block", None)
        _block_streaming = (
            block is not None
            and hasattr(block, "_completed")
            and not block._completed
        )
        narrow = width < 50
        if not narrow and rs is not None and not _block_streaming:
            from hermes_cli.tui.services import tool_tips
            tip_key, tip_label = tool_tips.current_tip()
            t.append("  ", style="dim")
            t.append(tip_key, style="bold dim italic")
            t.append(f" {tip_label}", style="dim italic")

        return t

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
