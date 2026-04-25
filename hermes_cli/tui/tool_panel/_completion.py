"""_ToolPanelCompletionMixin — completion path and body-line helpers."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload, ResultKind

# Per-category discovery set: fires once per distinct category per session.
_DISCOVERY_SHOWN_CATEGORIES: "set[object]" = set()


class _ToolPanelCompletionMixin:
    """Completion path: set_result_summary, auto-collapse, renderer swap."""

    # ------------------------------------------------------------------
    # Footer / body helpers
    # ------------------------------------------------------------------

    def _has_footer_content(self) -> bool:  # type: ignore[return]
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        if rs is None:
            return False
        return bool(
            rs.chips or rs.stderr_tail or rs.actions or rs.artifacts
            or (rs.exit_code not in (None, 0))
        )

    def _body_line_count(self) -> int:
        if self._block is None:  # type: ignore[attr-defined]
            return 0
        for attr in ("_total_received", "_content_line_count"):
            val = getattr(self._block, attr, None)  # type: ignore[attr-defined]
            if isinstance(val, int):
                return val
        for attr in ("_plain_lines", "_all_plain", "_content_lines"):
            lines = getattr(self._block, attr, None)  # type: ignore[attr-defined]
            if isinstance(lines, list):
                return len(lines)
        return 0

    def copy_content(self) -> str:
        if self._block is None:  # type: ignore[attr-defined]
            return ""
        fn = getattr(self._block, "copy_content", None)  # type: ignore[attr-defined]
        if fn is not None:
            try:
                return str(fn())
            except Exception:
                pass
        for attr in ("_all_plain", "_content_lines", "_plain_lines"):
            lines = getattr(self._block, attr, None)  # type: ignore[attr-defined]
            if isinstance(lines, list):
                return "\n".join(lines)
        return ""

    # ------------------------------------------------------------------
    # B1: Collapsed action strip
    # ------------------------------------------------------------------

    def _refresh_collapsed_strip(self) -> None:
        strip = getattr(self, "_collapsed_strip", None)
        if strip is None:
            return
        import os
        if os.environ.get("HERMES_DETERMINISTIC"):
            strip.remove_class("--visible")
            return
        if not self.collapsed:  # type: ignore[attr-defined]
            strip.remove_class("--visible")
            return
        if self._result_summary_v4 is None:  # type: ignore[attr-defined]
            strip.remove_class("--visible")
            return
        from ._footer import _get_collapsed_actions
        actions = _get_collapsed_actions(self._category)  # type: ignore[attr-defined]
        filtered = []
        for hotkey, label in actions:
            if hotkey == "r" and not getattr(self._result_summary_v4, "is_error", False):  # type: ignore[attr-defined]
                continue
            if hotkey == "e" and not getattr(self._result_summary_v4, "stderr_tail", ""):  # type: ignore[attr-defined]
                continue
            filtered.append((hotkey, label))
        if not filtered:
            strip.remove_class("--visible")
            return
        from rich.text import Text
        t = Text()
        for hotkey, label in filtered:
            t.append(f"[{hotkey}]", style="dim bold")
            t.append(f" {label}  ", style="dim")
        strip.update(t)
        strip.add_class("--visible")

    # ------------------------------------------------------------------
    # B9: Discovery hint
    # ------------------------------------------------------------------

    def _maybe_show_discovery_hint(self) -> None:
        global _DISCOVERY_SHOWN_CATEGORIES
        from hermes_cli.tui.constants import accessibility_mode
        cat = getattr(self, "_category", None)
        if cat in _DISCOVERY_SHOWN_CATEGORIES or self._discovery_shown or accessibility_mode():  # type: ignore[attr-defined]
            return
        if self._result_summary_v4 is None:  # type: ignore[attr-defined]
            return
        self._discovery_shown = True  # type: ignore[attr-defined]
        _DISCOVERY_SHOWN_CATEGORIES.add(cat)
        try:
            from hermes_cli.tui.services import feedback as _fb_mod
            self.app.feedback.flash(  # type: ignore[attr-defined]
                "hint-bar",
                "  [?] or F1 → tool keys",
                duration=3.0,
                priority=_fb_mod.LOW,
                key="tool-discovery",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Age ticks
    # ------------------------------------------------------------------

    def _schedule_age_ticks(self) -> None:
        for delay in (10.0, 60.0, 300.0):
            self.set_timer(delay, self._tick_age)  # type: ignore[attr-defined]

    def _tick_age(self) -> None:
        if not self.is_mounted:  # type: ignore[attr-defined]
            return
        completed_at = getattr(self, "_completed_at", None)
        if completed_at is None:
            return
        elapsed = int(time.monotonic() - completed_at)
        block = getattr(self, "_block", None)
        if block is None or not getattr(block, "is_mounted", False):
            return
        if hasattr(block, "set_age_microcopy"):
            from ._footer import _format_age
            block.set_age_microcopy(_format_age(elapsed))

    # ------------------------------------------------------------------
    # Tool args
    # ------------------------------------------------------------------

    def set_tool_args(self, args: dict | None) -> None:
        self._tool_args = args  # type: ignore[attr-defined]
        header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
        if header is not None:
            header.refresh()

    def _format_arg_summary(self) -> str:
        args = self._tool_args or {}  # type: ignore[attr-defined]
        if not args:
            return ""
        for key in ("command", "cmd", "shell_command", "path", "pattern", "query", "url"):
            val = args.get(key)
            if val is not None:
                return str(val)
        first = next(iter(args.values()), None)
        return str(first) if first is not None else ""

    # ------------------------------------------------------------------
    # Content classifier / renderer swap
    # ------------------------------------------------------------------

    def _update_kind_from_classifier(self, line_count: int) -> None:
        try:
            from hermes_cli.tui.content_classifier import classify_content
            from hermes_cli.tui.tool_payload import ToolPayload
            output_raw = ""
            block = self._block  # type: ignore[attr-defined]
            if block is not None:
                for attr in ("_all_plain", "_content_lines", "_plain_lines"):
                    lines = getattr(block, attr, None)
                    if isinstance(lines, list):
                        output_raw = "\n".join(lines)
                        break
            payload = ToolPayload(
                tool_name=self._tool_name,  # type: ignore[attr-defined]
                category=self._category,    # type: ignore[attr-defined]
                args=self._tool_args or {}, # type: ignore[attr-defined]
                input_display=None,
                output_raw=output_raw,
                line_count=line_count,
            )
            result = classify_content(payload)
            self._maybe_swap_renderer(result, payload)
        except Exception:
            _log.debug("Tool output classification failed", exc_info=True)

    def _swap_renderer(
        self,
        new_renderer_cls: type,
        payload: "ToolPayload",
        cls_result: "ClassificationResult",
    ) -> None:
        if self._body_pane is None:  # type: ignore[attr-defined]
            return
        renderer = new_renderer_cls(payload, cls_result, app=self.app)  # type: ignore[attr-defined]
        try:
            new_widget = renderer.build_widget()
        except Exception:
            _log.exception("renderer.build_widget() failed; keeping original body")
            return
        plain_text = renderer.copy_text() if hasattr(renderer, "copy_text") else payload.output_raw
        old_block = self._block  # type: ignore[attr-defined]
        if old_block is not None and hasattr(old_block, "replace_body_widget"):
            try:
                old_block.replace_body_widget(new_widget, plain_text=plain_text)
            except Exception:
                _log.exception("replace_body_widget() failed; keeping original body")
                return
            self._block = old_block  # type: ignore[attr-defined]
            self._body_pane._block = old_block  # type: ignore[attr-defined]
        else:
            # Fallback: no ToolBlock wrapper present — mount directly and update refs.
            self._body_pane.mount(new_widget)  # type: ignore[attr-defined]
            self._block = new_widget  # type: ignore[attr-defined]
            self._body_pane._block = new_widget  # type: ignore[attr-defined]

    def _maybe_swap_renderer(
        self,
        result: "ClassificationResult",
        payload: "ToolPayload",
    ) -> None:
        try:
            self.remove_class("--streaming")  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            from hermes_cli.tui.tool_payload import ResultKind
            from hermes_cli.tui.tool_category import ToolCategory
            from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer

            if result.kind in (ResultKind.TEXT, ResultKind.EMPTY):
                return
            if self._category == ToolCategory.SHELL:  # type: ignore[attr-defined]
                return
            renderer_cls = pick_renderer(result, payload)
            if renderer_cls is FallbackRenderer:
                return
            self._swap_renderer(renderer_cls, payload, result)
        except Exception:
            _log.debug("Tool body renderer swap failed", exc_info=True)

    def _maybe_activate_mini(self, summary: "ResultSummaryV4") -> None:
        try:
            cli = getattr(self.app, "cli", None)  # type: ignore[attr-defined]
            if cli is None:
                return
            cfg = getattr(cli, "_cfg", None) or {}
            display_cfg = cfg.get("display", {}) if isinstance(cfg, dict) else {}
            if not display_cfg.get("auto_mini_mode", False):
                return
            from hermes_cli.tui.tool_category import ToolCategory
            exit_code = getattr(summary, "exit_code", None)
            stderr_raw = getattr(summary, "stderr_tail", None) or ""
            line_count = self._body_line_count()
            if self._category != ToolCategory.SHELL:  # type: ignore[attr-defined]
                return
            if exit_code != 0:
                return
            if line_count > 3:
                return
            if stderr_raw:
                return
            self.add_class("--minified")  # type: ignore[attr-defined]
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auto-collapse
    # ------------------------------------------------------------------

    def _apply_complete_auto_collapse(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        if getattr(self, "_user_collapse_override", False):
            return
        if self.has_focus or bool(list(self.query("*:focus"))):  # type: ignore[attr-defined]
            self._should_auto_collapse = True  # type: ignore[attr-defined]
            return
        try:
            output = self.app.query_one("#output-panel")  # type: ignore[attr-defined]
            if getattr(output, "_user_scrolled_up", False):
                block = getattr(self, "_block", None)
                if block is not None:
                    vs = getattr(block, "_visible_start", 0)
                    vc = getattr(block, "_visible_count", 0)
                    total_lines = len(getattr(block, "_all_plain", []))
                    if total_lines > 0 and (vs + vc) < total_lines:
                        self._should_auto_collapse = True  # type: ignore[attr-defined]
                        return
        except Exception:
            pass
        self._should_auto_collapse = False  # type: ignore[attr-defined]
        rs = self._result_summary_v4  # type: ignore[attr-defined]
        total = self._body_line_count()
        threshold = _CATEGORY_DEFAULTS[self._category].default_collapsed_lines  # type: ignore[attr-defined]
        if rs is not None:
            try:
                from hermes_cli.tui.tool_category import spec_for as _spec_for
                spec = _spec_for(self._tool_name or "")  # type: ignore[attr-defined]
                if spec.primary_result == "diff":
                    threshold = 20
            except Exception:
                pass
        should_collapse = total > threshold
        if should_collapse:
            if self._saved_visible_start is None and self._block is not None:  # type: ignore[attr-defined]
                visible_cap = int(getattr(self._block, "_visible_cap", 200) or 200)  # type: ignore[attr-defined]
                self._saved_visible_start = max(0, total - visible_cap)  # type: ignore[attr-defined]
        self.collapsed = should_collapse  # type: ignore[attr-defined]
        self._auto_collapsed = should_collapse  # type: ignore[attr-defined]
        self._mirror_density_to_view_state()  # type: ignore[attr-defined]
        if should_collapse:
            self._flash_header(f"▾ auto-collapsed ({total} lines)", tone="success")  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Main completion entry point
    # ------------------------------------------------------------------

    def set_result_summary(self, summary: "ResultSummaryV4") -> None:
        self._result_summary_v4 = summary  # type: ignore[attr-defined]
        self._completed_at = time.monotonic()  # type: ignore[attr-defined]

        final_state = "error" if summary.is_error else "ok"
        if summary.is_error:
            self.add_class("tool-panel--error")  # type: ignore[attr-defined]
            self.collapsed = False  # type: ignore[attr-defined]
        else:
            self.remove_class("tool-panel--error")  # type: ignore[attr-defined]
        header = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
        line_count = self._body_line_count()
        if header is not None:
            header._is_complete = True
            header._tool_icon_error = summary.is_error
            if self._completed_at is not None:
                elapsed = self._completed_at - self._start_time  # type: ignore[attr-defined]
                header._duration = f"{elapsed:.1f}s"
            header._line_count = line_count
            header._has_affordances = line_count > 3
            if summary.primary is not None:
                header._primary_hero = summary.primary
            header._error_kind = summary.error_kind
            header._exit_code = getattr(summary, "exit_code", None)
            header._header_chips = []
            header.refresh()

        if not summary.is_error:
            block_microcopy_shown = getattr(self._block, "_microcopy_shown", True)  # type: ignore[attr-defined]
            if not block_microcopy_shown and header is not None:
                try:
                    self.app.feedback.flash(  # type: ignore[attr-defined]
                        f"tool-header::{self.id}",  # type: ignore[attr-defined]
                        "done",
                        duration=0.5,
                        tone="success",
                    )
                except Exception:
                    pass

        self._update_kind_from_classifier(line_count)

        if self._footer_pane is not None and summary.is_error and summary.error_kind is not None:  # type: ignore[attr-defined]
            try:
                _ICON_MAP = {
                    "timeout": "⏱",
                    "signal": "💀",
                    "auth": "🔒",
                    "exit": "✗",
                    "network": "🌐",
                }
                icon = _ICON_MAP.get(summary.error_kind, "✗")
                kind_label = summary.error_kind.replace("_", " ").title()
                remediation = next(
                    (c.remediation for c in (summary.chips or ()) if c.remediation),
                    None
                )
                if remediation:
                    remediation_text = f"{icon} {kind_label}  ·  {remediation}"
                else:
                    remediation_text = f"{icon} {kind_label}"
                from rich.text import Text as _RText
                rem_rich = _RText()
                rem_rich.append(remediation_text, style="bold red")
                self._footer_pane._remediation_row.update(rem_rich)  # type: ignore[attr-defined]
                self._footer_pane._remediation_row.add_class("footer-remediation--error")  # type: ignore[attr-defined]
                self._footer_pane.add_class("has-remediation")  # type: ignore[attr-defined]
            except Exception:
                pass

        if self._footer_pane is not None:  # type: ignore[attr-defined]
            self._footer_pane.update_summary_v4(summary, promoted_chip_texts=frozenset())  # type: ignore[attr-defined]

        if getattr(self, '_footer_pane', None) is not None:
            show = self._has_footer_content()
            self._footer_pane.styles.display = "block" if show else "none"  # type: ignore[attr-defined]

        self.post_message(self.__class__.Completed())  # type: ignore[attr-defined]

        self._schedule_age_ticks()

        if summary.is_error and summary.error_kind is not None:
            _remediation = next(
                (c.remediation for c in (summary.chips or ()) if c.remediation),
                None,
            )
            if _remediation:
                _short = _remediation.split(";")[0].split(".")[0].strip()
                self._header_remediation_hint = _short[:28] + ("…" if len(_short) > 28 else "")  # type: ignore[attr-defined]
            else:
                self._header_remediation_hint = None  # type: ignore[attr-defined]
            _hdr = getattr(self._block, "_header", None)  # type: ignore[attr-defined]
            if _hdr is not None:
                _hdr._remediation_hint = self._header_remediation_hint  # type: ignore[attr-defined]
        else:
            self._header_remediation_hint = None  # type: ignore[attr-defined]

        import os as _os
        if _os.environ.get("HERMES_DETERMINISTIC"):
            self._post_complete_tidy(summary)
        else:
            try:
                self.add_class("--completing")  # type: ignore[attr-defined]
            except AttributeError:
                pass
            self.call_after_refresh(self._post_complete_tidy, summary)  # type: ignore[attr-defined]

    def set_result_summary_v4(self, summary: "ResultSummaryV4") -> None:
        self.set_result_summary(summary)

    def _post_complete_tidy(self, summary: "ResultSummaryV4") -> None:
        try:
            self.remove_class("--completing")  # type: ignore[attr-defined]
        except AttributeError:
            pass

        if summary.is_error:
            self.collapsed = False  # type: ignore[attr-defined]
            return

        did_collapse = False
        if not getattr(self, "_user_collapse_override", False):
            before = self.collapsed  # type: ignore[attr-defined]
            self._apply_complete_auto_collapse()
            did_collapse = self.collapsed and not before  # type: ignore[attr-defined]

        self._maybe_activate_mini(summary)

        if self._footer_pane is not None:  # type: ignore[attr-defined]
            show = self._has_footer_content() and not self.collapsed  # type: ignore[attr-defined]
            self._footer_pane.styles.display = "block" if show else "none"  # type: ignore[attr-defined]
