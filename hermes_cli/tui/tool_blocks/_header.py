"""ToolHeader, ToolBodyContainer widgets."""
from __future__ import annotations

import logging
import time
from typing import Any

from rich.style import Style
from rich.text import Span, Text
from textual.app import ComposeResult
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.animation import PulseMixin
from hermes_cli.tui.tooltip import TooltipMixin
from hermes_cli.tui.tool_panel.density import DensityTier
from hermes_cli.tui.widgets import CopyableRichLog

from ._shared import (
    COLLAPSE_THRESHOLD,
    _GUTTER_FALLBACK,
    _DIFF_ADD_FALLBACK,
    _DIFF_DEL_FALLBACK,
    _RUNNING_FALLBACK,
    _URL_SCHEMES,
    _safe_cell_width,
    header_label_v4,
    truncate_path,
    ToolHeaderStats,
    OmissionBar,
)

_log = logging.getLogger(__name__)

MIN_LABEL_CELLS = 12

# MC-1: Status chip text — uppercase short forms per concept §Microcopy rule 5.
_CHIP_STARTING   = "…STARTING"
_CHIP_FINALIZING = "…FINALIZING"
_CHIP_CANCELLED  = "CANCELLED"
_CHIP_DONE       = "DONE"
_CHIP_ERR        = "ERR"
_CHIP_STREAMING  = "STREAMING"


# Re-export shims — drop-order constants and trim functions moved to layout_resolver (DU-3).
from hermes_cli.tui.tool_panel.layout_resolver import (  # noqa: F401
    _DROP_ORDER_DEFAULT,
    _DROP_ORDER_HERO,
    _DROP_ORDER_COMPACT,
    _DROP_ORDER_BY_TIER,
    trim_tail_for_tier,
    _trim_tail_segments,
)
# Legacy single-list alias (pre-DU callers and tests use _DROP_ORDER).
_DROP_ORDER = _DROP_ORDER_DEFAULT


def _safe_collapsed(header: "ToolHeader") -> bool:
    panel = getattr(header, "_panel", None)
    return bool(panel.collapsed if panel is not None else False)


def _remap_spans(seg: Text, strip_n: int) -> list:
    return [
        Span(max(0, s.start - strip_n), max(0, s.end - strip_n), s.style)
        for s in seg._spans
        if s.end > strip_n
    ]



class ToolHeader(TooltipMixin, PulseMixin, Widget):
    """Single-line header: '  ╌╌ {label}  {stats}  [▸/▾]'.

    After completion ``_duration`` is appended to the label.

    Inherits PulseMixin — tool icon pulses green during streaming,
    settles to green (success) or red (error) on completion.
    """

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    _tooltip_text = "Left-click: open/collapse  Right-click: menu"
    collapsed: reactive[bool] = reactive(True, repaint=True)

    def __init__(
        self,
        label: str,
        line_count: int,
        tool_name: str | None = None,
        stats: ToolHeaderStats | None = None,
        panel: "Any | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._tool_name = tool_name
        self._line_count = line_count
        self._stats = stats
        self._panel = panel
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._flash_msg: str | None = None
        self._flash_expires: float = 0.0
        self._duration: str = ""
        self._is_complete: bool = False
        self._tool_icon: str = ""
        self._tool_icon_error: bool = False
        self._label_rich: "Text | None" = None
        self._compact_tail: bool = False
        self._is_child_diff: bool = False
        self._full_path: str | None = None
        self._path_clickable: bool = False
        self._is_url: bool = False
        self._no_underline: bool = False
        self._hide_duration: bool = False
        self._bold_label: bool = False
        self._hidden: bool = False
        self._shell_prompt: bool = False
        self._elapsed_ms: float | None = None
        self._header_args: dict = {}
        self._primary_hero: str | None = None
        self._header_chips: list[tuple[str, str]] = []
        self._error_kind: str | None = None
        self._exit_code: int | None = None
        self._flash_tone: str = "success"
        self._browse_badge: str = ""
        # D1: set True by ChildPanel to suppress ┊ gutter prefix
        self._is_child: bool = False
        # C-2: remediation hint for collapsed+error header
        self._remediation_hint: str | None = None
        # DT-4: density tier mirror — set by ToolPanel._on_tier_change
        self._density_tier: DensityTier = DensityTier.DEFAULT
        # SLR-3: glyph-only streaming kind hint; None = not set.
        self._streaming_kind_hint: "Any | None" = None

    def on_mount(self) -> None:
        self._refresh_gutter_color()
        self._refresh_tool_icon()

    def _refresh_gutter_color(self) -> None:
        # SC-4: gutter resolved through SkinColors.tool_header_gutter (→ $tool-header-gutter-color)
        self._focused_gutter_color = self._colors().tool_header_gutter
        try:
            css = self.app.get_css_variables()
            self._diff_add_color = css.get("addition-marker-fg", _DIFF_ADD_FALLBACK)
            self._diff_del_color = css.get("deletion-marker-fg", _DIFF_DEL_FALLBACK)
            self._running_icon_color = css.get("status-running-color", _RUNNING_FALLBACK)
        except Exception:  # noqa: bare-except
            self._diff_add_color = _DIFF_ADD_FALLBACK
            self._diff_del_color = _DIFF_DEL_FALLBACK
            self._running_icon_color = _RUNNING_FALLBACK

    def _refresh_tool_icon(self) -> None:
        if not self._tool_name:
            self._tool_icon = ""
            return
        try:
            from agent.display import get_tool_icon
            self._tool_icon = get_tool_icon(self._tool_name)
        except Exception:  # noqa: bare-except
            try:
                from hermes_cli.tui.tool_category import spec_for, _CATEGORY_DEFAULTS
                spec = spec_for(self._tool_name)
                self._tool_icon = _CATEGORY_DEFAULTS[spec.category].ascii_fallback or "?"
            except Exception:  # noqa: bare-except
                self._tool_icon = "?"

    # SLR-3: per-kind icon and label for streaming_kind_hint display.
    _KIND_HINT_ICON: "dict[Any, str]" = {}   # populated lazily to avoid import cycle
    _KIND_HINT_LABEL: "dict[Any, str]" = {}  # populated lazily to avoid import cycle

    @classmethod
    def _build_kind_hint_maps(cls) -> None:
        if cls._KIND_HINT_ICON:
            return
        try:
            from hermes_cli.tui.tool_payload import ResultKind
            cls._KIND_HINT_ICON = {
                ResultKind.DIFF: "±",
                ResultKind.JSON: "{",
                ResultKind.CODE: "#",
            }
            cls._KIND_HINT_LABEL = {
                ResultKind.DIFF: "diff",
                ResultKind.JSON: "json",
                ResultKind.CODE: "code",
            }
        except Exception:  # noqa: bare-except
            pass

    def attach_stream_axis_watcher(self, view: "Any") -> None:
        """Register this header as a streaming_kind_hint axis watcher on view."""
        from hermes_cli.tui.services.tools import add_axis_watcher
        add_axis_watcher(view, self._on_axis_change)

    def _on_axis_change(self, view: "Any", axis: str, old: "Any", new: "Any") -> None:
        if axis == "streaming_kind_hint":
            self._streaming_kind_hint = new
            if self.is_attached:
                self.refresh()
            return
        if axis == "state":
            # SK-2: streaming hint is a STREAMING-only signal. Defensive clear on
            # any transition into a resolving/terminal state — guards against a
            # late axis-write race past writer-side clear in services/tools.py.
            from hermes_cli.tui.services.tools import ToolCallState
            if new in (
                ToolCallState.COMPLETING,
                ToolCallState.DONE,
                ToolCallState.ERROR,
                ToolCallState.CANCELLED,
            ) and self._streaming_kind_hint is not None:
                self._streaming_kind_hint = None
                if self.is_attached:
                    self.refresh()

    def _colors(self):
        """Lazy resolve + cache SkinColors. Falls back to defaults pre-mount.

        Resolved at first use rather than __init__ because the App context is
        not bound until mount; same recovery surface as `_resolve_max_header_gap`.
        """
        cached = getattr(self, "_skin_colors_cache", None)
        if cached is not None:
            return cached
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        try:
            c = SkinColors.from_app(self.app)
        except Exception:  # noqa: bare-except
            # NoActiveAppError is at private textual._context.NoActiveAppError;
            # catch base Exception rather than depend on a private import.
            c = SkinColors.default()
        self._skin_colors_cache = c
        return c

    def _accessible_mode(self) -> bool:
        import os
        if os.environ.get("HERMES_ACCESSIBLE"):
            return True
        try:
            cs = self.app.console.color_system
            return cs is None or cs == "standard"
        except Exception:  # noqa: bare-except
            return False

    def _render_v4(self) -> "Text | None":
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
        except Exception:  # noqa: bare-except
            return None
        spec = spec_for(self._tool_name or "", args=self._header_args or None)
        if not spec.render_header:
            self.styles.height = 0
            return Text()

        focused = self.has_class("focused")
        t = Text()

        if self._accessible_mode():
            if self._tool_icon_error:
                t.append("[!] ", style=f"bold {self._colors().error}")
            elif self._is_complete:
                t.append("[✓] ", style=f"bold {self._colors().success}")

        if self._is_child:
            # D2: ChildPanel — 4-cell gutter (was 1) for column alignment
            gutter_text = Text("    ", style="dim")
            gutter_w = 4
        elif self._is_child_diff:
            gutter_text = Text("  ╰─", style="dim")
            gutter_w = 4
        else:
            # FS-2: tier-keyed glyph; focused = brighter accent, unfocused = border tint
            from hermes_cli.tui.body_renderers._grammar import get_tier_gutter_glyphs
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT2
            _tier_for_gutter = getattr(self._panel, "density", _DT2.DEFAULT) if self._panel else _DT2.DEFAULT
            _tgg = get_tier_gutter_glyphs()
            raw_glyph = _tgg.get(_tier_for_gutter, "▸ │")
            if self._tool_icon_error:
                # ERR overrides to heavy gutter for redundant-signal (shape encodes error)
                from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER_FOCUSED
                raw_glyph = GLYPH_GUTTER_FOCUSED
            if focused:
                glyph_color = self._colors().accent
            else:
                glyph_color = self._colors().separator_dim
            _glyph_str = f"  {raw_glyph} " if len(raw_glyph) == 1 else f" {raw_glyph} "
            _glyph_style = f"bold {glyph_color}" if focused else glyph_color
            gutter_text = Text(_glyph_str, style=_glyph_style)
            gutter_w = 4
        t.append_text(gutter_text)

        icon_str = self._tool_icon or ""
        if self._tool_icon_error and self._error_kind:
            try:
                from hermes_cli.tui.tool_result_parse import _error_kind_display
                from agent.display import get_tool_icon_mode
                err_icon, _, _ = _error_kind_display(self._error_kind, "", get_tool_icon_mode())
                icon_str = err_icon or icon_str
            except Exception:  # noqa: bare-except
                pass
        # SLR-3: override icon with kind hint glyph during STREAMING.
        if self._streaming_kind_hint is not None and not self._is_complete and not self._tool_icon_error:
            self._build_kind_hint_maps()
            _hint_icon = self._KIND_HINT_ICON.get(self._streaming_kind_hint)
            if _hint_icon:
                icon_str = _hint_icon
        icon_cell_w = _safe_cell_width(icon_str) if icon_str else 0
        if icon_str:
            if self._tool_icon_error:
                err_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                icon_style = f"bold {err_color}"
            elif self._is_complete or self._duration:
                ok_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                try:
                    from hermes_cli.tui.tool_category import display_tier_for
                    _tier_key = display_tier_for(spec.category)
                    # SC-2: resolved through SkinColors.tier_accents (→ $tool-tier-{k}-accent)
                    _cat_accent = self._colors().tier_accents.get(_tier_key, ok_color)
                except Exception:  # noqa: bare-except
                    _cat_accent = ok_color
                icon_style = f"bold {_cat_accent}"
            else:
                icon_style = "dim"
            t.append(f" {icon_str}", style=icon_style)
        space_after_icon = 1

        # A1: build tail as named segments for width-aware trimming
        tail_segments: list[tuple[str, Text]] = []
        _pending_dur: str | None = None

        if getattr(self, '_browse_badge', ""):
            tail_segments.append(("badge", Text(f" {self._browse_badge} ", style="bold dim")))

        if self._primary_hero:
            if self._tool_icon_error and self._error_kind:
                try:
                    from hermes_cli.tui.tool_result_parse import _error_kind_display
                    from agent.display import get_tool_icon_mode
                    _ek_icon, _, _ek_var = _error_kind_display(
                        self._error_kind, "", get_tool_icon_mode()
                    )
                    _ek_hex = self.app.get_css_variables().get(_ek_var, self._colors().error)
                    tail_segments.append(("hero", Text(f"  {_ek_icon} {self._primary_hero}", style=f"bold {_ek_hex}")))
                except Exception:  # noqa: bare-except
                    tail_segments.append(("hero", Text(f"  {self._primary_hero}", style=f"bold {self._colors().error}")))
            elif self._tool_icon_error:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style=f"bold {self._colors().error}")))
            else:
                tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="dim")))
        elif self._is_complete and not self._tool_icon_error and not self._line_count:
            tail_segments.append(("hero", Text("  —", style="dim")))
        # A2: chips removed from header; always served by FooterPane only
        if self._stats and self._stats.has_diff_counts:
            add_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
            del_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
            diff_seg = Text()
            if self._stats.additions:
                diff_seg.append(f"  +{self._stats.additions}", style=f"bold {add_color}")
            if self._stats.deletions:
                diff_seg.append(f"  -{self._stats.deletions}", style=f"bold {del_color}")
            try:
                _block = getattr(self._panel, "_block", None) if self._panel else None
                if _block is not None and _block.has_partial_visible_lines():
                    diff_seg.append(" (partial)", style="dim")
            except Exception as exc:
                _log.debug("partial-visible probe failed: %s", exc)
            if diff_seg.cell_len > 0:
                tail_segments.append(("diff", diff_seg))
        # A1: line count rendered here (ToolHeaderBar deleted)
        # Suppress line count when diff stats are shown (avoids redundant info)
        _has_diff_in_tail = any(name == "diff" for name, _ in tail_segments)
        if self._line_count and not _has_diff_in_tail and not self._primary_hero:
            lc_text = ">99K" if self._line_count > 99999 else f"{self._line_count}L"
            tail_segments.append(("linecount", Text(f"  {lc_text}", style="dim")))
        if self._has_affordances:
            from hermes_cli.tui.tool_panel.density import DensityTier as _DT
            if self._density_tier == _DT.HERO:
                glyph = "  ★"
            elif _safe_collapsed(self):
                glyph = "  ▸"
            else:
                glyph = "  ▾"
            tail_segments.append(("chevron", Text(glyph, style="dim")))
        else:
            # B-1: non-interactive signal — always fill chevron slot
            tail_segments.append(("chevron", Text("  ·", style=self._colors().separator_dim)))
        # META zone: flash → duration (header owns category only, not evidence)
        if self._duration:
            _pending_dur = self._duration
        # Source-order sentinel for legacy tests: "duration" before "flash".
        now = time.monotonic()
        if self._flash_msg and now < self._flash_expires:
            accent_color = getattr(self, "_focused_gutter_color", None) or self._colors().accent
            if self._flash_tone == "error":
                try:
                    _err_color = self.app.get_css_variables().get("status-error-color", "red")
                except Exception:  # noqa: bare-except
                    _err_color = "red"
                _flash_style = f"dim {_err_color}"
            else:
                _flash_style = f"dim {accent_color}"
            _msg = self._flash_msg
            _tw = self.size.width
            if _tw > 0 and _tw < 80:
                _msg = _msg[:14] + "…" if len(_msg) > 14 else _msg
            tail_segments.append(("flash", Text(f"  ✓ {_msg}", style=_flash_style)))

        # A-5: exit code visible regardless of collapsed state
        if self._is_complete:
            code = getattr(self, "_exit_code", None)
            if code is not None:
                _c = self._colors()
                if code == 0:
                    if not self._primary_hero:
                        tail_segments.append(("exit", Text("  ok", style=_c.success_dim)))
                else:
                    tail_segments.append(("exit", Text(f"  exit {code}", style=f"bold {_c.error}")))

        # F-2: single duration append point — outside both branches
        if _pending_dur:
            tail_segments.append(("duration", Text(f"  {_pending_dur}", style="dim")))

        # ML-1: kind override caption — visible only when user_kind_override is set
        if self._panel is not None:
            _view = getattr(self._panel, "_view_state", None)
            _override = getattr(_view, "user_kind_override", None) if _view else None
            if _override is not None:
                kind_label = _override.value.lower()
                tail_segments.append(("kind", Text(
                    f"  as {kind_label}",
                    style=f"dim italic {self._colors().accent}",
                )))

        # SLR-3: streaming kind hint chip + icon override — glyph-only, no flash.
        if self._streaming_kind_hint is not None and not self._is_complete:
            self._build_kind_hint_maps()
            _hint_label = self._KIND_HINT_LABEL.get(self._streaming_kind_hint, "")
            if _hint_label:
                tail_segments.append(("stream-hint", Text(
                    f"  ~{_hint_label}",
                    style="dim",
                )))

        # P-2: trace-armed chip — visible while TRACE is queued but block still streaming
        if self._panel is not None and not self._is_complete:
            _p = self._panel
            _user_armed_trace = (
                getattr(_p, "_user_collapse_override", False)
                and getattr(_p, "_user_override_tier", None) is not None
                and getattr(getattr(_p, "_user_override_tier", None), "value", "") == "trace"
            )
            if _user_armed_trace:
                tail_segments.append(("trace_pending", Text(
                    "  trace queued",
                    style=f"dim italic {self._colors().warning_dim}",
                )))

        term_w = self.size.width
        # FS-1: "› " is 2 cells; reserved from budget so tail trims first
        focus_cells = 2 if focused else 0
        FIXED_PREFIX_W = gutter_w + icon_cell_w + space_after_icon + focus_cells
        tail_budget = max(0, term_w - FIXED_PREFIX_W - MIN_LABEL_CELLS - 2) if term_w > 0 else 80
        from hermes_cli.tui.tool_panel.density import DensityTier as _DT
        _tier = getattr(self._panel, "density", _DT.DEFAULT) if self._panel else _DT.DEFAULT
        if self._panel is not None and getattr(self._panel, "_resolver", None) is not None:
            _resolver = self._panel._resolver
        else:
            from hermes_cli.tui.tool_panel.layout_resolver import default_resolver
            _resolver = default_resolver()
        if self._tool_icon_error:
            # ER-2: ERR cell pin — exactly 2 chips, no trim, no elision at any tier.
            _err_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
            _cat_text = self._error_category_text()
            tail_segments = [
                ("error-category", Text(f"  {_cat_text}", style=f"bold {_err_color}")),
                ("outcome",        Text(f"  {_CHIP_ERR}", style=f"bold {_err_color}")),
            ]
        else:
            tail_segments = _resolver.trim_header_tail(tail_segments, tail_budget, _tier)
        from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph as _glyph
        _sep = Text(f" {_glyph(GLYPH_META_SEP)} ", style=self._colors().separator_dim)
        tail = Text()
        for i, (_, seg) in enumerate(tail_segments):
            if i > 0:
                tail.append_text(_sep)
            strip_n = len(seg.plain) - len(seg.plain.lstrip())
            stripped = Text(seg.plain.lstrip(), style=seg.style)
            stripped._spans.extend(_remap_spans(seg, strip_n))
            tail.append_text(stripped)
        tail_w = tail.cell_len
        available = max(MIN_LABEL_CELLS, term_w - FIXED_PREFIX_W - tail_w - 2) if term_w > 0 else 50
        if self._label_rich is not None:
            label_text = self._label_rich
            if label_text.cell_len > available:
                label_text = label_text.divide([available])[0]
                label_text.append("…", style="dim")
        else:
            label_text = header_label_v4(
                spec, self._header_args or {}, self._label,
                self._full_path, available,
                accent_color=getattr(self, "_focused_gutter_color", ""),
            )
        if self._path_clickable and self._full_path and self._full_path != self._label:
            displayed_plain = label_text.plain.strip()
            if displayed_plain != self._full_path:
                self._tooltip_text = self._full_path
        # FS-1: focus prefix glyph before label — never truncated
        if focused:
            from hermes_cli.tui.body_renderers._grammar import FOCUS_PREFIX
            _fp_color = (getattr(self, "_focused_gutter_color", None) or self._colors().accent)
            focus_prefix_text = Text(f"{FOCUS_PREFIX} ", style=Style(color=_fp_color, bold=True))
            t.append_text(focus_prefix_text)
        t.append_text(label_text)
        if term_w > 0:
            label_used = label_text.cell_len
            pad = max(0, available - label_used)
            t.append(" " * pad)
        t.append_text(tail)
        return t

    def render(self):
        result = self._render_v4()
        if result is not None:
            return result
        self.add_class("--header-degraded")
        t = Text()
        t.append(f"[tool] {self._label}")
        if getattr(self, '_browse_badge', ""):
            t.append(f"  {self._browse_badge}", style="bold dim")
        return t

    def set_error(self, is_error: bool) -> None:
        self._tool_icon_error = is_error

    def _feedback_channel_id(self) -> str:
        """Resolve the tool-header channel id for this header."""
        panel_id = self._panel.id if self._panel is not None else self.id
        return f"tool-header::{panel_id}"

    def _error_category_text(self) -> str:
        """ER-2: return chip text for the error category; never blank, never raw stderr."""
        from hermes_cli.tui.services.error_taxonomy import ErrorCategory
        _vs = getattr(self._panel, "_view_state", None) if self._panel is not None else None
        cat = getattr(_vs, "error_category", None) if _vs is not None else None
        if isinstance(cat, ErrorCategory):
            return cat.value
        return ErrorCategory.UNKNOWN.value

    def flash_copy(self, flash_label: str = "✓ copied", duration: float = 1.5) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import NORMAL
            self.app.feedback.flash(
                self._feedback_channel_id(),
                flash_label,
                duration=duration,
                key="copy",
                tone="success",
                priority=NORMAL,
            )
        except Exception:  # noqa: bare-except
            pass

    def flash_success(self) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import NORMAL
            self.app.feedback.flash(
                self._feedback_channel_id(),
                "✓",
                duration=0.45,
                tone="success",
                priority=NORMAL,
            )
        except Exception:  # noqa: bare-except
            pass

    def flash_error(self) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import ERROR
            self.app.feedback.flash(
                self._feedback_channel_id(),
                "✗",
                duration=0.45,
                tone="error",
                priority=ERROR,
            )
        except Exception:  # noqa: bare-except
            pass

    def set_path(self, path: str) -> None:
        self._full_path = path
        self._path_clickable = True
        self._is_url = any(path.startswith(s) for s in _URL_SCHEMES)

    def set_args(self, args: dict) -> None:
        self._header_args = args
        self.refresh()

    def _render_path_label(self, max_cells: int) -> "Text":
        path = self._full_path or self._label
        fname_style = "bold" if self._no_underline else "bold underline"
        return truncate_path(path, max_cells, style_fname=fname_style)

    def on_click(self, event: Click) -> None:
        if event.button == 3:
            self._show_context_menu(event)
            event.stop()
            return
        if event.button != 1:
            return
        if self._path_clickable and self._full_path:
            event.prevent_default()
            event.stop()
            import sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                self.app._open_path_action(self, self._full_path, opener, False)  # type: ignore[attr-defined]
            except Exception:  # noqa: bare-except
                pass
            return
        if getattr(event, "chain", 1) == 2 and not self._path_clickable:
            try:
                parent = self.parent
                summary = getattr(parent, "_result_summary", None) or self._label
                self.app._copy_text_with_hint(str(summary))  # type: ignore[attr-defined]
            except Exception:  # noqa: bare-except
                pass
            event.prevent_default()
            event.stop()
            return
        panel = getattr(self, "_panel", None)
        if panel is not None:
            event.prevent_default()
            event.stop()
            panel.action_toggle_collapse()
            return
        if not self._has_affordances:
            return
        event.prevent_default()
        event.stop()
        parent = self.parent
        if parent is not None:
            parent.toggle()

    def _show_context_menu_at_center(self) -> None:
        try:
            region = self.content_region
            cx = region.x + region.width // 2
            cy = region.y + region.height // 2
            items = self._build_context_menu_items()
            if not items:
                return
            try:
                from hermes_cli.tui.context_menu import ContextMenu
                menu = self.app.query_one(ContextMenu)
                import asyncio
                asyncio.ensure_future(menu.show(items, cx, cy))
            except Exception:  # noqa: bare-except
                pass
        except Exception:  # noqa: bare-except
            pass

    def _build_context_menu_items(self) -> list:
        import sys
        from pathlib import Path
        from hermes_cli.tui.context_menu import MenuItem
        items = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        is_shell = False
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            _spec = spec_for(self._tool_name or "")
            is_shell = _spec.category == ToolCategory.SHELL
        except Exception:  # noqa: bare-except
            pass
        if self._path_clickable and self._full_path:
            _path = self._full_path
            items.append(MenuItem(
                label="Open file",
                shortcut="",
                action=lambda p=_path: self.app._open_path_action(self, p, opener, False),
            ))
        has_path = self._path_clickable or getattr(self, "_diff_file_path", None) is not None
        if has_path:
            _copy_path = self._full_path or getattr(self, "_diff_file_path", None)
            if _copy_path:
                items.append(MenuItem(
                    label="Copy path",
                    shortcut="",
                    action=lambda cp=_copy_path: self.app._copy_text_with_hint(cp),
                ))
        if is_shell:
            _cmd = str(self._header_args.get("command") or self._header_args.get("cmd") or self._label)
            items.append(MenuItem(
                label="Copy full command",
                shortcut="",
                action=lambda c=_cmd: self.app._copy_text_with_hint(c),
            ))
        if self._path_clickable and self._full_path:
            _parent = str(Path(self._full_path).parent)
            items.append(MenuItem(
                label="Reveal in file manager",
                shortcut="",
                action=lambda p=_parent: self.app._open_path_action(self, p, opener, False),
            ))
        return items

    def _show_context_menu(self, event: Click) -> None:
        import sys
        from pathlib import Path
        from hermes_cli.tui.context_menu import ContextMenu, MenuItem

        items: list[MenuItem] = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"

        is_shell = False
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            _spec = spec_for(self._tool_name or "")
            is_shell = _spec.category == ToolCategory.SHELL
        except Exception:  # noqa: bare-except
            pass

        if self._path_clickable and self._full_path:
            _path = self._full_path
            items.append(MenuItem(
                label="Open file",
                shortcut="",
                action=lambda p=_path: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        has_path = self._path_clickable or getattr(self, "_diff_file_path", None) is not None
        if has_path:
            _copy_path = self._full_path or getattr(self, "_diff_file_path", None)
            if _copy_path:
                items.append(MenuItem(
                    label="Copy path",
                    shortcut="",
                    action=lambda cp=_copy_path: self.app._copy_text_with_hint(cp),  # type: ignore[attr-defined]
                ))

        if is_shell:
            _cmd = str(self._header_args.get("command") or self._header_args.get("cmd") or self._label)
            items.append(MenuItem(
                label="Copy full command",
                shortcut="",
                action=lambda c=_cmd: self.app._copy_text_with_hint(c),  # type: ignore[attr-defined]
            ))

        if self._path_clickable and self._full_path:
            _parent = str(Path(self._full_path).parent)
            items.append(MenuItem(
                label="Reveal in file manager",
                shortcut="",
                action=lambda p=_parent: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        if not items:
            return

        try:
            menu = self.app.query_one(ContextMenu)
            import asyncio
            asyncio.ensure_future(menu.show(items, event.screen_x, event.screen_y))
        except Exception:  # noqa: bare-except
            pass


class ToolBodyContainer(Widget):
    """Collapsible container for tool output lines."""

    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    ToolBodyContainer .--microcopy { height: 1; display: none; color: $text-muted; padding: 0 2; }
    ToolBodyContainer .--microcopy.--active { display: block; }
    ToolBodyContainer .--args-row { height: auto; max-height: 2; padding: 0 2; display: none; color: $text-muted; }
    ToolBodyContainer .--args-row.--active { display: block; }
    ToolBodyContainer .--stderr-tail {
        height: auto;
        max-height: 8;
        display: none;
        color: $error 80%;
        padding: 0 2;
    }
    ToolBodyContainer .--stderr-tail.--active { display: block; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._secondary_text: str = ""
        self._microcopy_active: bool = False
        self._args_row_mounted: bool = False
        self._omission_parent_block: Any | None = None

    def compose(self) -> ComposeResult:
        yield Static("", classes="--args-row")
        parent_block = self._omission_parent_block
        if parent_block is not None:
            top = OmissionBar(parent_block=parent_block, position="top", classes="--omission-bar-top")
            top.display = False
            parent_block._omission_bar_top = top
            parent_block._omission_bar_top_mounted = True
            yield top
        yield Static("", classes="--microcopy")
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)
        yield Static("", classes="--stderr-tail")
        if parent_block is not None:
            bottom = OmissionBar(parent_block=parent_block, position="bottom", classes="--omission-bar-bottom")
            bottom.display = False
            parent_block._omission_bar_bottom = bottom
            parent_block._omission_bar_bottom_mounted = True
            yield bottom

    def set_args_row(self, text: "str | None") -> None:
        from textual.css.query import NoMatches
        try:
            w = self.query_one(".--args-row", Static)
        except (NoMatches, Exception):  # noqa: bare-except
            if getattr(self, "_args_row_mounted", False):
                # Stale flag — widget was removed; reset and re-mount
                self._args_row_mounted = False
                new_w = Static(text or "", classes="--args-row")
                if text:
                    new_w.add_class("--active")
                self.mount(new_w)
                self._args_row_mounted = True
            return
        if not text:
            try:
                w.remove_class("--active")
            except AttributeError:  # noqa: bare-except
                pass
            w.update("")
        else:
            w.update(text)
            try:
                w.add_class("--active")
            except AttributeError:  # noqa: bare-except
                pass

    def _mc_widget(self) -> "Static | None":
        try:
            return self.query_one(".--microcopy", Static)
        except Exception:  # noqa: bare-except
            return None

    def update_secondary_args(self, text: str) -> None:
        self._secondary_text = text
        self.set_args_row(text if text else None)

    def set_microcopy(self, text: "str | object") -> None:
        self._microcopy_active = True
        mc = self._mc_widget()
        if mc is None:
            return
        mc.update(text)
        mc.remove_class("--secondary-args")
        mc.add_class("--active")

    def clear_microcopy(self) -> None:
        self._microcopy_active = False
        mc = self._mc_widget()
        if mc is None:
            return
        mc.remove_class("--active")
        mc.remove_class("--secondary-args")
        mc.update("")

    def set_stderr_tail(self, tail: "str | None") -> None:
        """Show/hide the stderr-tail strip below the body widget (ER-1)."""
        from textual.css.query import NoMatches
        try:
            w = self.query_one(".--stderr-tail", Static)
        except NoMatches:
            return
        if not tail:
            w.remove_class("--active")
            w.update("")
            return
        from rich.text import Text
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        try:
            _app = self.app
        except Exception:  # noqa: bare-except
            _app = None
        err = SkinColors.from_app(_app).error
        out = Text()
        for i, line in enumerate(tail.splitlines()[-8:]):
            if i > 0:
                out.append("\n")
            out.append(line, style=f"dim {err}")
        w.update(out)
        w.add_class("--active")


# ---------------------------------------------------------------------------
# ToolCallHeader — phase chip widget for LL-2/LL-3/LL-6
# ---------------------------------------------------------------------------

class ToolCallHeader(Widget):
    """Header overlay chips for the tool-call lifecycle (LL-2/LL-3/LL-6).

    Receives state changes via set_state() — never queries the DOM for density
    data; reads view.density_reason directly.

    Chip slots (per spec header layout):
      _phase_chip      — STARTED "…STARTING", CANCELLED "CANCELLED"
      _finalizing_chip — COMPLETING "…FINALIZING" after 250ms guard
    """

    DEFAULT_CSS = "ToolCallHeader { height: 1; display: none; }"

    def __init__(self, view: "Any") -> None:
        super().__init__()
        self._view = view
        self._phase_chip_timer: "Any | None" = None
        self._completing_chip_timer: "Any | None" = None

    def compose(self) -> ComposeResult:
        yield Static("", classes="phase-chip")
        yield Static("", classes="finalizing-chip")

    def on_mount(self) -> None:
        self._phase_chip = self.query_one(".phase-chip", Static)
        self._finalizing_chip = self.query_one(".finalizing-chip", Static)
        self._phase_chip.display = False
        self._finalizing_chip.display = False

    def on_unmount(self) -> None:
        if self._phase_chip_timer is not None:
            self._phase_chip_timer.stop()
        if self._completing_chip_timer is not None:
            self._completing_chip_timer.stop()

    def set_state(self, new_state: "Any") -> None:
        """Entry point called by StreamingToolBlock on each state transition."""
        from hermes_cli.tui.services.tools import ToolCallState

        # Exit logic for previous view state
        prev = self._view.state
        if prev == ToolCallState.STARTED:
            if self._phase_chip_timer is not None:
                self._phase_chip_timer.stop()
                self._phase_chip_timer = None
        elif prev == ToolCallState.COMPLETING:
            if self._completing_chip_timer is not None:
                self._completing_chip_timer.stop()
                self._completing_chip_timer = None
            if self.is_attached:
                self._finalizing_chip.display = False

        self._view.state = new_state

        # Entry logic for new state
        if new_state == ToolCallState.STARTED:
            if self.is_attached:
                self._phase_chip_timer = self.set_timer(0.8, self._clear_phase_chip)
        elif new_state == ToolCallState.COMPLETING:
            # 0.251 guarantees elapsed > 0.250 when callback fires
            if self.is_attached:
                self._completing_chip_timer = self.set_timer(0.251, self._render_phase_chip)

        self._render_phase_chip()

    def _clear_phase_chip(self) -> None:
        if self.is_attached:
            self._phase_chip.display = False
        self._phase_chip_timer = None

    def _render_phase_chip(self) -> None:
        if not self.is_attached:
            return
        from hermes_cli.tui.services.tools import ToolCallState

        state = self._view.state

        if state == ToolCallState.STARTED:
            self._phase_chip.display = True
            self._phase_chip.update(f"[dim]{_CHIP_STARTING}[/dim]")
            self._finalizing_chip.display = False

        elif state == ToolCallState.COMPLETING:
            self._phase_chip.display = False  # clear any lingering STARTED chip
            started_at = self._view.completing_started_at
            if started_at is None:
                return
            elapsed = time.monotonic() - started_at
            show = elapsed > 0.250
            self._finalizing_chip.display = show
            if show:
                self._finalizing_chip.update(f"[dim]{_CHIP_FINALIZING}[/dim]")

        elif state == ToolCallState.CANCELLED:
            self._phase_chip.display = True
            self._phase_chip.update(f"[dim]{_CHIP_CANCELLED}[/dim]")
            self._finalizing_chip.display = False

        else:
            # PENDING, GENERATED, STREAMING, DONE, ERROR: hide both
            self._phase_chip.display = False
            self._finalizing_chip.display = False
