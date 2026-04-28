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
            rs.chips or rs.actions or rs.artifacts
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
            except Exception:  # noqa: bare-except
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
        except Exception:  # noqa: bare-except
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
            header._header_args = dict(args or {})
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
                # Prefer _renderer_output_raw (untruncated, set in close_streaming_tool_block)
                # over _all_plain, which caps each line at _LINE_BYTE_CAP (2000 B).
                # Single-blob results (web search JSON) become one truncated line in
                # _all_plain → invalid JSON → classifier falls back to TEXT → no swap.
                _untrunc = getattr(block, "_renderer_output_raw", None)
                if _untrunc:
                    output_raw = _untrunc
                else:
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

    def _emit_diff_stat_for_renderer(self, renderer: "Any") -> None:
        """PG-3 / SC-1: iterate renderer.diff_lines and post per-line DiffStatUpdate.

        Renderer purity (concept §renderer-purity rule 5) requires that build()
        not post messages. The panel owns the bus; it calls this after build_widget().
        """
        try:
            from hermes_cli.tui.tool_group import ToolGroup as _TG
            app = getattr(self, "app", None)  # type: ignore[attr-defined]
            if app is None:
                return
            for line in renderer.diff_lines:
                if line.startswith("+") and not line.startswith("+++"):
                    app.post_message(_TG.DiffStatUpdate(add=1, del_=0))
                elif line.startswith("-") and not line.startswith("---"):
                    app.post_message(_TG.DiffStatUpdate(add=0, del_=1))
        except Exception:
            _log.debug("_emit_diff_stat_for_renderer failed", exc_info=True)

    def _swap_renderer(
        self,
        new_renderer_cls: type,
        payload: "ToolPayload",
        cls_result: "ClassificationResult",
    ) -> None:
        if self._body_pane is None:  # type: ignore[attr-defined]
            # compose() hasn't run yet — defer until on_mount().
            self._pending_renderer_swap = (new_renderer_cls, payload, cls_result)  # type: ignore[attr-defined]
            _log.debug("_swap_renderer deferred (body_pane not yet mounted)")
            return
        renderer = new_renderer_cls(payload, cls_result, app=self.app)  # type: ignore[attr-defined]
        # Update BodyPane renderer FIRST so apply_density() (fired later by the resolver
        # on tier-change) uses real content instead of the initial empty renderer.
        self._body_pane._renderer = renderer  # type: ignore[attr-defined]
        try:
            new_widget = renderer.build_widget()
        except Exception:
            _log.exception("renderer.build_widget() failed; keeping original body")
            return
        if hasattr(renderer, "diff_lines"):
            self._emit_diff_stat_for_renderer(renderer)
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
        except Exception:  # remove_class may fail on partially initialized widget; swap continues
            pass
        try:
            from hermes_cli.tui.tool_payload import ResultKind
            from hermes_cli.tui.tool_category import ToolCategory
            from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer
            from hermes_cli.tui.tool_panel.density import DensityTier
            from hermes_cli.tui.services.tools import ToolCallState

            view = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
            override = view.user_kind_override if view is not None else None

            # KO-3-A: only honor TEXT/EMPTY/SHELL early-returns when no override.
            if override is None:
                if result.kind in (ResultKind.TEXT, ResultKind.EMPTY):
                    return
                if self._category == ToolCategory.SHELL:  # type: ignore[attr-defined]
                    return

            phase = view.state if view is not None else ToolCallState.COMPLETING
            density = view.density if view is not None else DensityTier.DEFAULT

            renderer_cls = pick_renderer(
                result, payload,
                phase=phase, density=density,
                user_kind_override=override,
            )
            # When override is set and pick_renderer returns Fallback, that IS
            # the user's choice — swap to it. When override is None and
            # pick_renderer returns Fallback, fall back to existing "no swap"
            # behavior so the default plain body stays.
            if override is None and renderer_cls is FallbackRenderer:
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
        except Exception:  # noqa: bare-except
            pass

    # ------------------------------------------------------------------
    # Auto-collapse
    # ------------------------------------------------------------------

    def _apply_complete_auto_collapse(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        from hermes_cli.tui.tool_panel.density import DensityInputs, DensityTier
        from hermes_cli.tui.services.tools import ToolCallState

        # Only run after completion; no-op during live streaming.
        if self._result_summary_v4 is None:  # type: ignore[attr-defined]
            return

        threshold = _CATEGORY_DEFAULTS[self._category].default_collapsed_lines  # type: ignore[attr-defined]
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            spec = _spec_for(self._tool_name or "")  # type: ignore[attr-defined]
            if spec.primary_result == "diff":
                threshold = 20
        except Exception:
            _log.debug("spec_for failed for %r", self._tool_name, exc_info=True)  # type: ignore[attr-defined]

        user_scrolled_up = False
        try:
            from textual.css.query import NoMatches
            output = self.app.query_one("#output-panel")  # type: ignore[attr-defined]
            if getattr(output, "_user_scrolled_up", False):
                user_scrolled_up = True
        except Exception:  # noqa: bare-except
            pass

        has_focus = self.has_focus or bool(list(self.query("*:focus")))  # type: ignore[attr-defined]
        if has_focus:
            self._should_auto_collapse = True  # type: ignore[attr-defined]
            return

        _vs = self._view_state or self._lookup_view_state()  # type: ignore[attr-defined]
        phase = _vs.state if _vs is not None else ToolCallState.DONE
        _vs_kind = getattr(_vs, "kind", None) if _vs is not None else None
        kind = _vs_kind.kind if _vs_kind is not None else None

        inputs = DensityInputs(
            phase=phase,
            is_error=bool(self._result_summary_v4.is_error),  # type: ignore[attr-defined]
            has_focus=False,  # focus check done above
            user_scrolled_up=user_scrolled_up,
            user_override=self._user_collapse_override,  # type: ignore[attr-defined]
            user_override_tier=self._user_override_tier,  # type: ignore[attr-defined]
            body_line_count=self._body_line_count(),
            threshold=threshold,
            row_budget=None,
            kind=kind,
            parent_clamp=self._parent_clamp_tier,  # type: ignore[attr-defined]
            is_streaming=(phase in (ToolCallState.STARTED, ToolCallState.STREAMING)),
        )
        prev_tier = self._resolver.tier  # type: ignore[attr-defined]
        self._resolver.resolve(inputs)  # type: ignore[attr-defined]

        # Flash only on auto-collapse transitions, not on user-driven resolves.
        if (not self._user_collapse_override  # type: ignore[attr-defined]
                and self._resolver.tier == DensityTier.COMPACT  # type: ignore[attr-defined]
                and prev_tier != DensityTier.COMPACT):
            line_count = self._body_line_count()
            if self._saved_visible_start is None and self._block is not None:  # type: ignore[attr-defined]
                visible_cap = int(getattr(self._block, "_visible_cap", 200) or 200)  # type: ignore[attr-defined]
                self._saved_visible_start = max(0, line_count - visible_cap)  # type: ignore[attr-defined]
            self._flash_header(f"▾ auto-collapsed ({line_count} lines)", tone="success")  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Main completion entry point
    # ------------------------------------------------------------------

    def set_result_summary(self, summary: "ResultSummaryV4") -> None:
        self._result_summary_v4 = summary  # type: ignore[attr-defined]
        self._completed_at = time.monotonic()  # type: ignore[attr-defined]

        final_state = "error" if summary.is_error else "ok"
        if summary.is_error:
            self.add_class("tool-panel--error")  # type: ignore[attr-defined]
            self.remove_class("--completed")  # type: ignore[attr-defined]
            # Eager uncollapse — resolver (_apply_complete_auto_collapse) is never called for
            # error completions (_post_complete_tidy returns early). This write is the sole owner.
            self.collapsed = False  # type: ignore[attr-defined]
        else:
            self.remove_class("tool-panel--error")  # type: ignore[attr-defined]
            self.add_class("--completed")  # type: ignore[attr-defined]
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
                except KeyError:
                    _log.debug(
                        "tool-header channel missing for 'done' flash on panel id=%r — "
                        "decorative; if seen post-fix this is an adoption re-registration desync",
                        self.id,  # type: ignore[attr-defined]
                    )
                except Exception:
                    _log.exception(
                        "tool-header 'done' flash failed on panel id=%r",
                        self.id,  # type: ignore[attr-defined]
                    )

        self._update_kind_from_classifier(line_count)

        if self._footer_pane is not None:  # type: ignore[attr-defined]
            self._footer_pane.update_summary_v4(summary, promoted_chip_texts=frozenset())  # type: ignore[attr-defined]

        # ER-1: body owns stderr evidence — propagate stderr_tail to ToolBodyContainer
        body = getattr(self._block, "_body", None)  # type: ignore[attr-defined]
        if body is not None and hasattr(body, "set_stderr_tail"):
            body.set_stderr_tail(summary.stderr_tail or None)

        if getattr(self, '_footer_pane', None) is not None:
            show = self._has_footer_content()
            self._footer_pane.styles.display = "block" if show else "none"  # type: ignore[attr-defined]

        self.post_message(self.__class__.Completed())  # type: ignore[attr-defined]

        self._schedule_age_ticks()

        import os as _os
        if _os.environ.get("HERMES_DETERMINISTIC"):
            self._post_complete_tidy(summary)
        else:
            try:
                self.add_class("--completing")  # type: ignore[attr-defined]
            except AttributeError:  # noqa: bare-except
                pass
            self.call_after_refresh(self._post_complete_tidy, summary)  # type: ignore[attr-defined]

    def set_result_summary_v4(self, summary: "ResultSummaryV4") -> None:
        self.set_result_summary(summary)

    def _post_complete_tidy(self, summary: "ResultSummaryV4") -> None:
        try:
            self.remove_class("--completing")  # type: ignore[attr-defined]
        except AttributeError:  # noqa: bare-except
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
            self._footer_pane._refresh_visibility()  # type: ignore[attr-defined]
