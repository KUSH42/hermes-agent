"""Textual widgets for the Hermes TUI.

All widgets follow these conventions (from the migration spec):
- Widget.render() returns Text objects, never plain str (plain str = literal, no markup)
- RichLog.write() has no markup kwarg — set markup= at construction
- query_one() raises NoMatches — use _safe_widget_call during teardown
- self.size.width is 0 during compose() — don't use for layout math
- set_interval callbacks must be def, not async def (unless they contain await)
- Reactive mutable defaults use factory form: reactive(list) not reactive([])

This module is now a re-export shim: the actual implementations live in:
  - widget_utils.py   — pure utility functions
  - renderers.py      — CopyableRichLog, CopyableBlock, CodeBlockFooter,
                        LiveLineWidget, StreamingCodeBlock, _fade_rule,
                        TitledRule, PlainRule
  - message_panel.py  — MessagePanel, ThinkingWidget, _EchoBullet,
                        UserMessagePanel, ReasoningPanel
  - status_bar.py     — HintBar, StatusBar, AnimatedCounter,
                        VoiceStatusBar, ImageBar, AttachmentChip (+ hint helpers)
  - overlays.py       — TurnCandidate, TurnResultItem, KeymapOverlay,
                        HistorySearchOverlay (+ search helpers)

Split sub-modules (all re-exported here):
  - output_panel.py   — ScrollState, OutputPanel, OutputPanelScrollBadge
  - fps_counter.py    — FPSCounter
  - tte_widget.py     — TTEWidget
  - startup_banner.py — StartupBannerWidget
  - nameplate.py      — AssistantNameplate, _NPChar, _NPState, _NPIdleBeat
  - _events.py        — STARTUP_BANNER_READY, OUTPUT_PANEL_WIDTH_READY, STARTUP_TTE_SKIP
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (backward-compat shim)
# ---------------------------------------------------------------------------

from .utils import (  # noqa: F401
    _ANSI_RE,
    _ANSI_SEQ_RE,
    _PRENUMBERED_LINE_RE,
    _animate_counters_enabled,
    _apply_span_style,
    _boost_layout_caches,
    _cursor_blink_enabled,
    _format_compact_tokens,
    _format_elapsed_compact,
    _fps_hud_enabled,
    _prewrap_code_line,
    _pulse_enabled,
    _safe_widget_call,
    _skin_branding,
    _skin_color,
    _strip_ansi,
    _typewriter_burst_threshold,
    _typewriter_cursor_enabled,
    _typewriter_delay_s,
    _typewriter_enabled,
)

from .renderers import (  # noqa: F401
    CopyableBlock,
    CopyableRichLog,
    LiveLineWidget,
    PlainRule,
    TitledRule,
    _CopyBtn,
    _fade_rule,
)

from .code_blocks import (  # noqa: F401
    CodeBlockFooter,
    StreamingCodeBlock,
)

from .inline_media import (  # noqa: F401
    ChipPlan,
    InlineImage,
    InlineImageBar,
    InlineThumbnail,
    OverflowChip,
    _layout_chips,
    _render_attachment_thumb,
    _size_str_for_path,
    _size_suffix,
)

from .prose import (  # noqa: F401
    InlineProseLog,
    MathBlockWidget,
)

from .message_panel import (  # noqa: F401
    MessagePanel,
    ReasoningPanel,
    UserMessagePanel,
    _EchoBullet,
)

from .thinking import ThinkingWidget  # noqa: F401


def _clear_thinking_reserve(tw: "ThinkingWidget") -> None:
    """D-4 helper: safely call clear_reserve() on a ThinkingWidget."""
    try:
        tw.clear_reserve()
    except Exception:
        # best-effort UI update; widget may not be mounted
        pass


from .status_bar import (  # noqa: F401
    AnimatedCounter,
    AttachmentChip,
    HintBar,
    ImageBar,
    KindOverrideChanged,
    KindOverrideChip,
    StatusBar,
    VoiceStatusBar,
    _BAR_EMPTY,
    _BAR_FILLED,
    _BAR_WIDTH,
    _SEP,
    _STREAMING_PROMOTE_PRIORITY,
    _build_hints,
    _build_streaming_hint,
    _clear_hint_cache,
    _hint_cache,
    _hint_to_text,
    _hints_for,
    # HB2-L2: KEY_* constants and HINT_MAX_PRIMARY exported for test imports
    KEY_ENTER,
    KEY_TAB,
    KEY_SPACE,
    KEY_ESC,
    KEY_UP,
    KEY_DOWN,
    KEY_CTRL_C,
    KEY_CTRL_F,
    KEY_CTRL_SHIFT_H,
    KEY_CTRL_J,
    KEY_CTRL_Z,
    HINT_MAX_PRIMARY,
)

from .overlays import (  # noqa: F401
    HistorySearchOverlay,
    KeymapOverlay,
    TurnCandidate,
    TurnResultItem,
    _CrossSessionResult,
    _ModeBar,
    _SearchResult,
    _TurnEntry,
    _build_cross_session_label,
    _build_result_label,
    _escape_markup,
    _extract_snippet,
    _highlight_spans,
    _substring_search,
    _turn_result_label,
)

from .media import (  # noqa: F401
    InlineMediaWidget,
    SeekBar,
)

# R3 Phase B: interrupt widget classes are aliases routing to InterruptOverlay.
from hermes_cli.tui.perf import measure  # noqa: E402
from hermes_cli.tui.overlays._aliases import (  # noqa: F401,E402
    ApprovalWidget,
    ClarifyWidget,
    MergeConfirmOverlay,
    NewSessionOverlay,
    SecretWidget,
    SudoWidget,
    UndoConfirmOverlay,
)

from .status_bar import SourcesBar, _extract_domain, _truncate  # noqa: F401



def _stream_effect_cfg() -> dict:
    """Read stream-effect config from hermes config.yaml + active skin."""
    try:
        from hermes_cli.config import read_raw_config
        raw = read_raw_config()
    except Exception:
        # config dict read failed; use empty defaults
        raw = {}
    terminal_cfg = raw.get("terminal", {}) if isinstance(raw, dict) else {}
    se_cfg = terminal_cfg.get("stream_effect", {}) if isinstance(terminal_cfg, dict) else {}
    if isinstance(se_cfg, str):
        effect_name = se_cfg
        se_cfg = {}
    else:
        effect_name = se_cfg.get("enabled", "none") if isinstance(se_cfg, dict) else "none"
    # Skin overrides — read from display.skin path in config, then theme_manager
    skin_path = None
    try:
        display_cfg = raw.get("display", {}) if isinstance(raw, dict) else {}
        skin_path = display_cfg.get("skin") if isinstance(display_cfg, dict) else None
    except Exception:
        # widget refresh failed pre-mount; skip silently
        pass
    if not skin_path:
        try:
            from hermes_cli.tui.theme_manager import _active_skin_path
            skin_path = _active_skin_path()
        except Exception:
            # CSS variable lookup unavailable; use default value
            pass
    skin_se_cfg: dict = {}
    if skin_path:
        try:
            import yaml
            skin = yaml.safe_load(open(skin_path)) or {}  # allow-sync-io: skin init, one-shot at startup
            se_skin = skin.get("stream_effect")
            if isinstance(se_skin, str):
                effect_name = se_skin
            elif isinstance(se_skin, dict):
                effect_name = se_skin.get("enabled", effect_name)
                skin_se_cfg = {k: v for k, v in se_skin.items() if k != "enabled"}
        except Exception:
            # reactive set failed before mount; skip gracefully
            pass
    merged_se_cfg = {**se_cfg, **skin_se_cfg} if isinstance(se_cfg, dict) else skin_se_cfg
    result: dict = {
        "stream_effect": effect_name,
        "stream_effect_length": int(merged_se_cfg.get("length", 16)),
        "stream_effect_settle_frames": int(merged_se_cfg.get("settle_frames", 6)),
        "stream_effect_scramble_frames": int(merged_se_cfg.get("scramble_frames", 14)),
    }
    if "cascade_ticks" in merged_se_cfg:
        result["stream_effect_cascade_ticks"] = int(merged_se_cfg["cascade_ticks"])
    return result


if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports from the newly split sub-modules
# ---------------------------------------------------------------------------

from ._events import (  # noqa: F401
    OUTPUT_PANEL_WIDTH_READY,
    STARTUP_BANNER_READY,
    STARTUP_TTE_SKIP,
)

from .output_panel import (  # noqa: F401
    OutputPanel,
    OutputPanelScrollBadge,
    ScrollState,
    _clear_thinking_reserve,
)

from .fps_counter import FPSCounter  # noqa: F401

from .tte_widget import TTEWidget  # noqa: F401

from .startup_banner import StartupBannerWidget  # noqa: F401

from .nameplate import (  # noqa: F401
    AssistantNameplate,
    _NPChar,
    _NPIdleBeat,
    _NPState,
    _lerp_hex,
    _NP_ACTIVE_COLOR,
    _NP_DECRYPT_COLOR,
    _NP_DIM_COLOR,
    _NP_ERROR_COLOR,
    _NP_IDLE_COLOR,
    _NP_POOL,
)

