"""HermesApp — Textual App subclass for the Hermes TUI.

Replaces the prompt_toolkit Application with a reactive, CSS-themed Textual
app. Thread → App communication uses two mechanisms:

A. ``call_from_thread(fn, *args)`` for scalar reactive mutations.
B. Bounded ``asyncio.Queue`` for high-throughput streaming output.

Module-level ``_hermes_app`` reference is set in ``cli.py:run()`` and cleared
in its ``finally`` block — replaces all ``hasattr(self, "_app")`` guards.
"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import enum
import logging
import math
import platform
import queue
import re
import threading

from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS as _KNOWN_SLASH_COMMANDS

# File-touching tool names — used by watch_spinner_label to extract active file
_FILE_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "create_file",
    "view", "str_replace_editor", "patch",
})

_SHELL_TOOLS: frozenset[str] = frozenset({
    "bash", "run_command", "execute_command", "shell", "run_bash",
})

_PATH_EXTRACT_RE = re.compile(
    r'["\']?(/[\w./\-]+|[\w./\-]+\.[\w]{1,6})["\']?'
)


def _looks_like_slash_command(text: str) -> bool:
    """Return True if text looks like a slash command, not a file path."""
    if not text or not text.startswith("/"):
        return False
    first_word = text.split()[0]
    return "/" not in first_word[1:]


import time as _time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static, TextArea
from textual import events, work

from hermes_cli.file_drop import classify_dropped_file, format_link_token
from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
    UndoOverlayState,
)
from hermes_cli.tui.widgets import (
    ApprovalWidget,
    ClarifyWidget,
    CopyableRichLog,
    FPSCounter,
    HistorySearchOverlay,
    HintBar,
    KeymapOverlay,
    ImageBar,
    InlineImageBar,
    LiveLineWidget,
    MessagePanel,
    OutputPanel,
    PlainRule,
    ReasoningPanel,
    SecretWidget,
    StartupBannerWidget,
    StatusBar,
    StreamingCodeBlock,
    SudoWidget,
    TTEWidget,
    ThinkingWidget,
    TitledRule,
    UndoConfirmOverlay,
    UserMessagePanel,
    VoiceStatusBar,
    AssistantNameplate,
    _fps_hud_enabled,
    _safe_widget_call,
)

from hermes_cli.tui.overlays import (
    CommandsOverlay,
    HelpOverlay,
    ModelOverlay,
    ModelPickerOverlay,
    ReasoningPickerOverlay,
    SessionOverlay,
    SkinPickerOverlay,
    UsageOverlay,
    VerbosePickerOverlay,
    WorkspaceOverlay,
    YoloConfirmOverlay,
    _SessionResumedBanner,
)
from hermes_cli.tui.session_widgets import (
    MergeConfirmOverlay,
    NewSessionOverlay,
    SessionBar,
    _SessionNotification,
)
from hermes_cli.tui.workspace_tracker import (
    GitPoller,
    GitSnapshot,
    WorkspaceTracker,
    WorkspaceUpdated,
    analyze_complexity,
)
from hermes_cli.tool_icons import get_display_name
from hermes_cli.tui.tool_category import (
    MCPServerInfo,
    ToolSpec,
    register_mcp_server,
    register_tool,
)
from hermes_cli.tui.constants import ICON_COPY
from hermes_cli.tui.animation import AnimationClock, shimmer_text
from hermes_cli.tui.perf import (
    EventLoopLatencyProbe,
    FrameRateProbe,
    SuspicionDetector,
    WorkerWatcher,
)
from hermes_cli.tui.theme_manager import ThemeManager
from wcwidth import wcswidth

try:
    import drawille as _drawille
except ImportError:
    _drawille = None

if TYPE_CHECKING:
    from hermes_cli.tui.input_widget import HermesInput
    from hermes_cli.tui.path_search import Candidate, PathCandidate
    from hermes_cli.tui.tool_blocks import ToolHeader
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

logger = logging.getLogger(__name__)

import os as _os_mod

from hermes_cli.tui._app_utils import (
    _CPYTHON_FAST_PATH,
    _HELIX_DELAY_S,
    _HELIX_FRAME_COUNT,
    _HELIX_MIN_CELLS,
    _animations_enabled_check,
    _log_lag,
    _run_effect_sync,
)
from hermes_cli.tui._app_io import _AppIOMixin
from hermes_cli.tui._app_spinner import _SpinnerMixin
from hermes_cli.tui._app_tool_rendering import _ToolRenderingMixin
from hermes_cli.tui._app_browse import _BrowseMixin
from hermes_cli.tui._app_context_menu import _ContextMenuMixin
from hermes_cli.tui._app_sessions import _SessionsMixin
from hermes_cli.tui._app_theme import _ThemeMixin
from hermes_cli.tui._app_commands import _CommandsMixin
from hermes_cli.tui._app_watchers import _WatchersMixin
from hermes_cli.tui._app_key_handler import _KeyHandlerMixin
from hermes_cli.tui._browse_types import (
    BrowseAnchor,
    BrowseAnchorType,
    _BROWSE_TYPE_GLYPH,
    _is_in_reasoning,
)

# CSS file path — relative to this module
_CSS_PATH = Path(__file__).parent / "hermes.tcss"


class _HermesScreen(Screen):
    """Custom Screen that prevents focus stealing on right-click.

    Textual's default Screen._forward_event calls set_focus() on ANY
    MouseDown, including right-click (button=3).  This steals focus from
    the input bar and loses text selection before the context menu appears.
    Override: skip the focus change for right-click.
    """

    def _forward_event(self, event: events.Event) -> None:
        if (
            isinstance(event, events.MouseDown)
            and getattr(event, "button", None) == 3
            and not self.app.mouse_captured
        ):
            # Right-click: forward the event but skip Textual's focus-on-click.
            # Reproduce the non-focus parts of Screen._forward_event.
            if event.is_forwarded:
                return
            event._set_forwarded()
            try:
                widget, region = self.get_widget_at(event.x, event.y)
            except Exception:
                return
            event.style = self.get_style_at(event.screen_x, event.screen_y)
            if widget.loading:
                return
            if widget is self:
                event._set_forwarded()
                self.post_message(event)
            else:
                widget._forward_event(event._apply_offset(-region.x, -region.y))
            return
        super()._forward_event(event)


# ---------------------------------------------------------------------------
# MCP event messages (v4 sub-spec A §3)
# ---------------------------------------------------------------------------

from textual.message import Message as _TxtMessage


class MCPServerRegistered(_TxtMessage):
    """Posted when an MCP server connects and registers its tool list.

    Consumed by HermesApp._on_mcp_server_registered to update the tool registry.
    """
    def __init__(
        self,
        server: str,
        icon_nf: str | None,
        icon_ascii: str,
        tools: tuple[dict, ...],
    ) -> None:
        super().__init__()
        self.server = server
        self.icon_nf = icon_nf
        self.icon_ascii = icon_ascii
        self.tools: tuple[dict, ...] = tools


class MCPServerDisconnected(_TxtMessage):
    """Posted when an MCP server disconnects. Specs stay registered."""
    def __init__(self, server: str) -> None:
        super().__init__()
        self.server = server


# ---------------------------------------------------------------------------


# BrowseAnchorType, BrowseAnchor, _BROWSE_TYPE_GLYPH, _is_in_reasoning
# moved to _browse_types.py — imported above


class HermesApp(_AppIOMixin, _SpinnerMixin, _ToolRenderingMixin, _BrowseMixin, _ContextMenuMixin, _SessionsMixin, _ThemeMixin, _CommandsMixin, _WatchersMixin, _KeyHandlerMixin, App):
    """Main Textual application for the Hermes Agent TUI.

    Holds all reactive state that drives widget updates. The agent thread
    (and other background threads) mutate these reactives via
    ``call_from_thread``, and Textual's watch system handles re-rendering.
    """

    CSS_PATH = "hermes.tcss"

    # Layer declaration — required before any widget uses ``layer: overlay``
    # in CSS.  Draw order: default → overlay.
    LAYERS = ("default", "overlay")

    def get_default_screen(self) -> Screen:
        """Use custom Screen that prevents focus stealing on right-click."""
        return _HermesScreen(id="_default")

    BINDINGS = [
        Binding("ctrl+f", "open_history_search", "History search", show=False, priority=True),
        Binding("f1", "show_help", "Keyboard shortcuts", show=False),
        Binding("f2", "show_usage", "Usage stats", show=False),  # C5: usage overlay shortcut
        Binding("f8", "toggle_fps_hud", "FPS HUD", show=False),
        Binding("alt+up",   "jump_turn_prev", "Previous turn", show=False),
        Binding("alt+down", "jump_turn_next", "Next turn",     show=False),
        Binding("ctrl+shift+a", "open_anim_config", "Animation config", show=False, priority=True),
        Binding("ctrl+b", "open_anim_config", show=False, priority=True),
        Binding("ctrl+shift+h", "open_sessions", show=False),
        Binding("ctrl+w+n", "new_worktree_session", show=False),
        Binding("o", "focus_output", "Output", show=False),
        Binding("i", "focus_input_from_output", "Input", show=False),
        Binding("ctrl+alt+up",   "jump_subagent_prev", "Prev agent", show=False),
        Binding("ctrl+alt+down", "jump_subagent_next", "Next agent", show=False),
    ]

    _CHEVRON_PHASE_CLASSES: frozenset[str] = frozenset({
        "--phase-file", "--phase-stream", "--phase-shell",
        "--phase-done", "--phase-error",
    })

    # --- Reactive state (replaces flag + _invalidate() pattern) ---
    agent_running: reactive[bool] = reactive(False)
    command_running: reactive[bool] = reactive(False)
    voice_mode: reactive[bool] = reactive(False)
    voice_recording: reactive[bool] = reactive(False)

    # Overlay states — typed dataclasses, not raw dicts
    clarify_state: reactive[ChoiceOverlayState | None] = reactive(None)
    approval_state: reactive[ChoiceOverlayState | None] = reactive(None)
    sudo_state: reactive[SecretOverlayState | None] = reactive(None)
    secret_state: reactive[SecretOverlayState | None] = reactive(None)
    undo_state: reactive[UndoOverlayState | None] = reactive(None)

    # Status bar data — display-only, read directly by StatusBar (no watcher needed)
    status_model: reactive[str] = reactive("")
    status_context_tokens: reactive[int] = reactive(0)
    status_context_max: reactive[int] = reactive(0)

    # Compaction state — display-only (status_compaction_progress has a watcher; enabled does not)
    status_compaction_progress: reactive[float] = reactive(0.0)  # 0.0–1.0
    status_compaction_enabled: reactive[bool] = reactive(True)  # display-only

    # Tok/s throughput (last turn) — display-only
    status_tok_s: reactive[float] = reactive(0.0)

    # Browse mode — keyboard-driven navigation through ToolBlock widgets
    browse_mode: reactive[bool] = reactive(False)
    browse_index: reactive[int] = reactive(0)
    # Memoized count of mounted ToolHeaders — display-only, read by StatusBar.render()
    _browse_total: reactive[int] = reactive(0)
    # Unified anchor list hint shown in StatusBar during []/{}/ Alt+↑↓ navigation — display-only
    _browse_hint: reactive[str] = reactive("")

    # Completion overlay hint shown in StatusBar while overlay is visible — display-only
    _completion_hint: reactive[str] = reactive("")

    # Animation force state — overrides trigger-based show/hide logic
    # None = normal; "on" = always show; "off" = always hide
    _anim_force: "str | None" = None

    # Compact layout — True = density-compact CSS class active
    compact: reactive[bool] = reactive(False)
    _compact_manual: "bool | None" = None  # None = auto; True/False = user override

    # Animation hint for StatusBar — display-only
    _anim_hint: reactive[str] = reactive("")

    # Active tool name — set/cleared by _on_tool_start/_on_tool_complete (C1)
    _active_tool_name: str = ""

    # Detail level of currently focused ToolPanel in browse mode — display-only
    browse_detail_level: reactive[int] = reactive(0)


    # Output dropped flag — display-only; shown in StatusBar until next successful write
    status_output_dropped: reactive[bool] = reactive(False)

    # D5: count of currently-streaming tool blocks (shows badge in StatusBar)
    _streaming_tool_count: reactive[int] = reactive(0, repaint=False)

    # Image attachments — reactive(list) uses factory form to avoid shared mutable default
    attached_images: reactive[list] = reactive(list)

    # Spinner label — text shown beside the spinner frame (e.g. "Calling tool…")
    spinner_label: reactive[str] = reactive("")

    # Active file path — display-only; drives the 📄 breadcrumb in StatusBar
    status_active_file: reactive[str] = reactive("")

    # Persistent error message shown in StatusBar until cleared.
    # repaint=False: StatusBar registers its own watch() in on_mount.
    status_error: reactive[str] = reactive("", repaint=False)

    # Highlighted completion candidate — drives PreviewPanel via watch_highlighted_candidate.
    # Uses reactive(None) (no type param) to avoid import cycle at class-definition time.
    highlighted_candidate: reactive = reactive(None)

    # FPS HUD visibility — toggled via Ctrl+\ or display.fps_hud config
    fps_hud_visible: reactive[bool] = reactive(False)

    # Context-window % meter (Feature A)
    context_pct: reactive[float] = reactive(0.0, repaint=False)

    # Yolo mode — mirrors HERMES_YOLO_MODE env var; toggled at runtime via /yolo
    yolo_mode: reactive[bool] = reactive(False, repaint=False)

    # Current session label — display-only; shown in StatusBar chip
    session_label: reactive[str] = reactive("")

    # hint_text is NOT on HermesApp — HintBar.hint is the single source of truth.

    def __init__(
        self,
        cli: Any,
        startup_fn=None,
        clipboard_available: bool = True,
        xclip_cmd: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.cli = cli
        self._startup_fn = startup_fn
        self._clipboard_available: bool = clipboard_available
        self._xclip_cmd: list[str] | None = xclip_cmd

        # Bounded queue: prevents unbounded memory growth when agent produces
        # faster than UI renders. 4096 chunks ≈ ~1MB of text at ~256 bytes/chunk.
        self._output_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4096)
        self._spinner_idx = 0
        self._shimmer_tick = 0  # monotonic; never wraps — decoupled from spinner frame count
        self._cached_input_area = None  # cached DOM ref — avoids per-tick query_one
        self._cached_spinner_overlay = None  # cached DOM ref — avoids per-tick query_one
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # ThemeManager handles skin loading, component vars, and hot reload.
        # Must be constructed after super().__init__() so App internals exist.
        self._theme_manager = ThemeManager(self)
        # Diagnostic probes — initialised in on_mount once the event loop runs.
        self._worker_watcher: WorkerWatcher | None = None
        self._event_loop_probe: EventLoopLatencyProbe | None = None
        self._frame_probe: FrameRateProbe | None = None
        self._spinner_perf_alarm: SuspicionDetector | None = None
        self._duration_perf_alarm: SuspicionDetector | None = None
        self._workspace_poll_perf_alarm: SuspicionDetector | None = None
        self._workspace_apply_perf_alarm: SuspicionDetector | None = None
        self._fps_hud_update_every: int = 1  # refined in on_mount once MAX_FPS is known

        # Spinner frames — read from module-level _COMMAND_SPINNER_FRAMES in cli.py
        self._spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self._helix_frame_cache: dict[int, tuple[str, ...]] = {}

        # Elapsed time for the current tool call — reset whenever spinner_label changes
        self._tool_start_time: float = 0.0

        # Whether to use HermesInput (step 5) or interim TextArea
        self._use_hermes_input = True
        # Lines scrolled per mouse wheel tick — overridden from config in cli.py
        self._scroll_lines: int = 3
        # C4: path search ignore set — None means use walker's built-in default
        self._path_search_ignore: "frozenset[str] | None" = None

        # Browse-mode visit counter — first 3 visits show full hint, then compact
        self._browse_uses: int = 0
        # Unified anchor list for []/{}/ Alt+↑↓ navigation
        self._browse_anchors: list[BrowseAnchor] = []
        self._browse_cursor: int = 0
        # Browse mode visual markers config (wired from cli.py)
        self._browse_markers_enabled: bool = True
        self._browse_reasoning_markers: bool = True
        self._browse_minimap_default: bool = False
        self._browse_streaming_flash: bool = True
        self._browse_turn_boundary_always: bool = True
        self._browse_minimap: bool = False
        # Widgets that have a _browse_badge set — tracked for cleanup
        self._browse_badge_widgets: list = []

        # Active StreamingToolBlocks keyed by tool_call_id
        self._active_streaming_blocks: dict[str, Any] = {}
        # P7 — per-turn tool call tracking for /tools overlay
        self._turn_tool_calls: dict[str, Any] = {}
        self._agent_stack: list[str] = []
        self._turn_start_monotonic: float | None = None
        self._response_metrics_active: bool = False
        self._response_wall_start_time: float | None = None
        self._response_segment_start_time: float | None = None
        self._response_token_window: collections.deque[tuple[float, int]] = collections.deque()

        # Undo/retry state
        self._undo_in_progress: bool = False
        self._last_user_input: str = ""
        # Panel/args to act on when undo/rollback overlay is confirmed
        self._pending_undo_panel: "MessagePanel | None" = None
        self._pending_rollback_n: int = 0
        # Animation feature flag — checked by all shimmer/pulse paths
        self._animations_enabled: bool = _animations_enabled_check()
        # F2: reduced-motion — disable shimmer/pulse; set from config or env var
        import os as _os
        self._reduced_motion: bool = bool(_os.environ.get("HERMES_REDUCED_MOTION"))
        # Current hint phase — tracks what the user is doing
        self._hint_phase: str = "idle"
        # Timestamp until which _flash_hint has the hint bar reserved.
        # _tick_spinner must not overwrite before this expires.
        self._flash_hint_expires: float = 0.0
        # D3: timer handle for the current flash so we can cancel it on re-entry.
        self._flash_hint_timer: "object | None" = None
        # The hint text that was active before the current flash started.
        self._flash_hint_prior: str = ""
        # Compaction warning state — reset when progress returns to 0
        self._compaction_warned: bool = False
        # Clear animation guard — prevents re-entry while fade is running
        self._clear_animation_in_progress: bool = False
        # InlineImageBar enabled state — set from cli.py before app launch
        self._inline_image_bar_enabled: bool = True
        # Active media player count — enforces max_concurrent limit (event-loop only)
        self._active_media_count: int = 0
        # Auto-title: fire once per session on first turn completion
        self._auto_title_done: bool = False
        # Session DB reference (wired from cli.py if available)
        self._session_db: object = None
        # Parallel worktree sessions
        self._own_session_id: str = ""          # set from --worktree-session-id CLI arg
        self._session_mgr: "object | None" = None
        self._notify_listener: "object | None" = None
        self._sessions_poll_timer: "object | None" = None
        self._session_records_cache: list = []
        self._session_active_id: str = ""
        self._sessions_enabled_override: bool | None = None  # set by tests
        # P1-7: one-shot "press o to open file" hint when path is clickable
        self._path_open_hint_shown: bool = False
        # Workspace overlay state
        self._last_git_snapshot: GitSnapshot | None = None
        self._git_poll_h: object | None = None  # textual.timer.Timer
        self._workspace_hint_shown: bool = False
        self._workspace_tracker = None
        self._git_poller = None
        self._git_poll_in_flight: bool = False
        self._git_poll_retrigger: bool = False
        # Resize debounce — coalesces rapid resize events before app-level work
        self._pending_resize: "object | None" = None
        self._resize_timer: "object | None" = None  # textual Timer
        # Panel-ready gate: cli.py waits on this Event before starting chat() so
        # streaming only begins after the new MessagePanel and its engine are
        # mounted.  Eliminates the multi-line-chunk race where lines arrive on the
        # old panel before watch_agent_running(True) fires.
        self._panel_ready_event: "threading.Event | None" = None
        # F4: track last keypress time for desktop notify active-user gate
        self._last_keypress_time: float = 0.0

    # --- Compose ---

    def compose(self) -> ComposeResult:
        yield OutputPanel(id="output-panel")
        # TTEWidget uses layer: overlay + dock: top in its DEFAULT_CSS so it
        # floats over the banner area when active.  Banner content is already
        # in OutputPanel underneath; when effect ends the overlay hides and
        # the static caduceus is visible in-place.
        yield TTEWidget(id="tte-effect")
        with Vertical(id="overlay-layer"):
            yield ClarifyWidget(id="clarify")
            yield ApprovalWidget(id="approval")
            yield SudoWidget(id="sudo")
            yield SecretWidget(id="secret")
            yield UndoConfirmOverlay(id="undo-confirm")
        yield AssistantNameplate(
            id="nameplate",
            name=getattr(self, "_nameplate_name", "Hermes"),
            effects_enabled=getattr(self, "_nameplate_effects", True),
            idle_effect=getattr(self, "_nameplate_idle_effect", "shimmer"),
            morph_speed=getattr(self, "_nameplate_morph_speed", 1.0),
            glitch_enabled=getattr(self, "_nameplate_glitch", True),
        )
        yield HintBar(id="hint-bar")
        yield SessionBar(id="session-bar")
        yield _SessionNotification(id="session-notification")
        yield InlineImageBar(id="inline-image-bar")
        yield ImageBar(id="image-bar")
        yield TitledRule(id="input-rule", show_state=True)

        if self._use_hermes_input:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            from hermes_cli.tui.path_search import PathSearchProvider as _PSP
            # CompletionOverlay must be composed BEFORE HermesInput so it sits
            # directly above the input in the natural layout flow (no dock/offset).
            yield _CO(id="completion-overlay")
            yield HistorySearchOverlay(id="history-search")
            yield KeymapOverlay(id="keymap-help")
            yield HelpOverlay(id="help-overlay")
            yield UsageOverlay(id="usage-overlay")
            yield CommandsOverlay(id="commands-overlay")
            yield ModelOverlay(id="model-overlay")
            yield WorkspaceOverlay(id="workspace-overlay")
            yield SessionOverlay(id="session-overlay")
            yield NewSessionOverlay(id="new-session-overlay")
            yield MergeConfirmOverlay(id="merge-confirm-overlay")
            yield ModelPickerOverlay(id="model-picker-overlay")
            yield ReasoningPickerOverlay(id="reasoning-picker-overlay")
            yield SkinPickerOverlay(id="skin-picker-overlay")
            yield YoloConfirmOverlay(id="yolo-confirm-overlay")
            yield VerbosePickerOverlay(id="verbose-picker-overlay")
            # C1: pre-mount ToolPanelHelpOverlay at screen level so layer: overlay
            # resolves against Screen (not a child ToolPanel).
            from hermes_cli.tui.overlays import ToolPanelHelpOverlay as _TPHO
            yield _TPHO(id="tool-panel-help-overlay")
            with Horizontal(id="input-row"):
                yield Static("❯ ", id="input-chevron")
                yield _HI(id="input-area")
                yield Static("", id="spinner-overlay")
            # PathSearchProvider is invisible — position is irrelevant.
            yield _PSP(id="path-search-provider")
        else:
            yield TextArea(id="input-area")

        yield PlainRule(id="input-rule-bottom")
        yield VoiceStatusBar(id="voice-status")
        yield StatusBar(id="status-bar")
        # Drawille animation overlay — before FPSCounter so FPS HUD stays above.
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
        yield _DO(id="drawille-overlay")
        # FPS HUD — overlay layer, docked top; display:none by default.
        # Must be before ContextMenu so ContextMenu stays topmost in overlay layer.
        yield FPSCounter(id="fps-counter")
        # ContextMenu must be last so it renders above all other widgets
        # within the overlay layer (DOM order = paint order within a layer).
        from hermes_cli.tui.context_menu import ContextMenu as _CM
        yield _CM(id="context-menu")

    # --- Lifecycle ---

    def on_mount(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._worker_watcher = WorkerWatcher(self)
        self._event_loop_probe = EventLoopLatencyProbe()
        self._spinner_perf_alarm = SuspicionDetector(
            "spinner-tick",
            budget_ms=16.0,
            severe_ms=50.0,
            burst_window=5,
            burst_count=2,
            streak_count=2,
            cooldown_s=10.0,
        )
        self._duration_perf_alarm = SuspicionDetector(
            "duration-tick",
            budget_ms=16.0,
            severe_ms=50.0,
            burst_window=5,
            burst_count=2,
            streak_count=2,
            cooldown_s=10.0,
        )
        self._workspace_poll_perf_alarm = SuspicionDetector(
            "workspace-git-poll",
            budget_ms=250.0,
            severe_ms=1500.0,
            burst_window=4,
            burst_count=2,
            streak_count=2,
            cooldown_s=20.0,
        )
        self._workspace_apply_perf_alarm = SuspicionDetector(
            "workspace-apply",
            budget_ms=16.0,
            severe_ms=80.0,
            burst_window=5,
            burst_count=2,
            streak_count=2,
            cooldown_s=10.0,
        )
        self._theme_manager.start_hot_reload()
        from textual import constants as _tc
        _frame_interval = 1.0 / _tc.MAX_FPS  # matches Screen._update_timer cadence
        # window=MAX_FPS → 1 s of rolling history; log every MAX_FPS ticks → 1 log/s
        self._frame_probe = FrameRateProbe(window=_tc.MAX_FPS, log_every=_tc.MAX_FPS)
        self._fps_hud_update_every = max(1, _tc.MAX_FPS // 4)  # update display at ~4 Hz
        self._consume_output()  # starts the @work consumer
        self._anim_clock = AnimationClock()
        self._anim_clock_h = self.set_interval(1 / 15, self._anim_clock.tick)
        self._spinner_h = self.set_interval(0.14, self._tick_spinner)  # ~7Hz — smooth enough, 30% less event-loop pressure vs 10Hz
        self._fps_h = self.set_interval(_frame_interval, self._tick_fps)
        self._duration_h = self.set_interval(1.0, self._tick_duration)
        # Restore FPS HUD state from config (runtime toggle overrides this)
        if _fps_hud_enabled():
            self.fps_hud_visible = True
        # Focus the input bar so the user can type immediately
        try:
            self.query_one("#input-area").focus()
        except NoMatches:
            pass
        if not self._clipboard_available and not self._xclip_cmd:
            try:
                self.query_one("#status-clipboard-warning").add_class("--active")
            except NoMatches:
                pass
        if self._startup_fn is not None:
            threading.Thread(target=self._startup_fn, daemon=True).start()
        import os as _os
        if _os.environ.get("HERMES_DENSITY", "").lower() == "compact":
            self._compact_manual = True
            self.compact = True  # triggers watch_compact → adds "density-compact"
        if _os.environ.get("HERMES_REDUCED_MOTION", "").lower() in ("1", "true", "yes"):
            self.add_class("reduced-motion")
        # Wire slash commands from COMMAND_REGISTRY into the autocomplete engine
        if self._use_hermes_input:
            self._populate_slash_commands()
        # Initialize hint bar to idle phase — shows key-badge hints immediately
        self._set_hint_phase("idle")
        # Apply InlineImageBar enabled state from config
        try:
            self.query_one(InlineImageBar)._enabled = self._inline_image_bar_enabled
        except NoMatches:
            pass
        # Initialize workspace tracker in background thread (subprocess call)
        self._init_workspace_tracker()
        # Apply --no-turn-boundary class if config disables turn boundary rule
        if not self._browse_turn_boundary_always:
            self.add_class("--no-turn-boundary")
        # Yolo mode: sync reactive with env var state at startup
        import os as _os2
        self.yolo_mode = _os2.environ.get("HERMES_YOLO_MODE") == "1"
        # Desktop notify: track turn start time
        self._turn_start_time: float = 0.0
        self._last_assistant_text: str = ""
        # Initialize parallel worktree sessions (feature-gated)
        self._init_sessions()

    _RESIZE_DEBOUNCE_S: float = 0.06  # 60 ms

    def on_resize(self, event: "events.Resize") -> None:
        """Debounce rapid resize events; flush once idle for 60 ms."""
        self._pending_resize = event
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(self._RESIZE_DEBOUNCE_S, self._flush_resize)

    def _maybe_reload_emoji(self, event: "events.Resize") -> None:
        """Re-normalize emoji images when the terminal cell pixel size changes."""
        registry = getattr(self, "_emoji_registry", None)
        if registry is None or registry.is_empty():
            return
        try:
            from hermes_cli.tui.emoji_registry import _cell_px
            cpw, cph = _cell_px()
        except Exception:
            return
        cur = getattr(self, "_emoji_cell_px", None)
        if cur == (cpw, cph):
            return
        self._emoji_cell_px = (cpw, cph)
        self.run_worker(lambda: registry.reload_normalized(cpw, cph), thread=True)

    def _flush_resize(self) -> None:
        """Run app-level resize work after the debounce window expires."""
        event = self._pending_resize
        if event is None:
            return
        self._pending_resize = None
        self._resize_timer = None
        self._maybe_reload_emoji(event)
        try:
            w = event.size.width  # type: ignore[union-attr]
            h = event.size.height  # type: ignore[union-attr]
        except AttributeError:
            return
        self._apply_min_size_overlay(w, h)
        # Auto compact-mode detection (debounced here, not in watch_size)
        if self._compact_manual is None:
            should = w <= 120 or h <= 30
            if self.compact != should:
                self.compact = should
        # Hard floor: w < 30 forces compact regardless of manual override
        if w < 30 and not self.compact:
            self.compact = True

    def _apply_min_size_overlay(self, w: int, h: int) -> None:
        """Mount or dismiss the MinSizeBackdrop based on current terminal dimensions."""
        if not self.screen_stack:
            return
        from hermes_cli.tui.min_size_overlay import MinSizeBackdrop
        from hermes_cli.tui.resize_utils import THRESHOLD_ULTRA_NARROW, THRESHOLD_MIN_HEIGHT
        from textual.app import ScreenStackError
        too_small = w < THRESHOLD_ULTRA_NARROW or h < THRESHOLD_MIN_HEIGHT
        try:
            existing = self.screen.query("MinSizeBackdrop")
        except ScreenStackError:
            return
        if too_small and not existing:
            self.screen.mount(MinSizeBackdrop(w, h))
        elif too_small and existing:
            existing.first(MinSizeBackdrop).update_size(w, h)
        elif not too_small and existing:
            existing.first(MinSizeBackdrop).remove()

    def on_unmount(self) -> None:
        """Stop background helpers tied to app lifetime."""
        self._theme_manager.stop_hot_reload()
        for _attr in ("_anim_clock_h", "_spinner_h", "_fps_h", "_duration_h",
                      "_sessions_poll_timer", "_git_poll_h", "_resize_timer"):
            _h = getattr(self, _attr, None)
            if _h is not None:
                try:
                    _h.stop()
                except Exception:
                    pass
        # Safety-net: stop any lingering media players
        try:
            from hermes_cli.tui.widgets import InlineMediaWidget as _IMW
            for _w in self.query(_IMW):
                try:
                    if _w._poller:
                        _w._poller.stop()
                    if _w._ctrl:
                        _w._ctrl.stop()
                except Exception:
                    pass
        except Exception:
            pass
        # Safety-net delete-all: removes any TGP placements that leaked (e.g. crash path)
        try:
            import sys as _sys
            from hermes_cli.tui.kitty_graphics import get_caps, GraphicsCap, _get_renderer
            if get_caps() == GraphicsCap.TGP:
                _sys.stdout.write(_get_renderer().delete_all_sequence())
                _sys.stdout.flush()
        except Exception:
            pass

    # --- Workspace tracker ---

    @work(thread=True)
    def _init_workspace_tracker(self) -> None:
        """Resolve repo root in a worker thread, then set tracker on event loop."""
        import os as _os
        import subprocess as _sp
        try:
            root = _sp.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=_sp.DEVNULL,
                timeout=5,
            ).decode().strip()
            is_git_repo = True
        except Exception:
            root = _os.getcwd()
            is_git_repo = False
        tracker = WorkspaceTracker(root, is_git_repo=is_git_repo)
        poller = GitPoller(root, is_git_repo=is_git_repo)
        self.call_from_thread(self._set_workspace_tracker, tracker, poller)

    def _set_workspace_tracker(self, tracker: WorkspaceTracker, poller: GitPoller) -> None:
        self._workspace_tracker = tracker
        self._git_poller = poller
        if not poller.is_git_repo:
            self._last_git_snapshot = GitSnapshot(
                branch="",
                dirty_count=0,
                entries=[],
                staged_count=0,
                untracked_count=0,
                modified_count=0,
                deleted_count=0,
                renamed_count=0,
                conflicted_count=0,
                is_git_repo=False,
            )

    def _trigger_git_poll(self) -> None:
        poller = getattr(self, "_git_poller", None)
        if poller is None or not getattr(poller, "is_git_repo", False):
            return
        if self._git_poll_in_flight:
            self._git_poll_retrigger = True
            return
        self._git_poll_in_flight = True
        self._run_git_poll()

    @work(thread=True, group="git-poll")
    def _run_git_poll(self) -> None:
        import time as _t
        poller = getattr(self, "_git_poller", None)
        if poller is None:
            return
        _t0 = _t.perf_counter()
        snapshot = poller.poll()
        elapsed_ms = (_t.perf_counter() - _t0) * 1000.0
        self.post_message(WorkspaceUpdated(snapshot, poll_elapsed_ms=elapsed_ms))

    def _workspace_polling_desired(self) -> bool:
        poller = getattr(self, "_git_poller", None)
        if poller is None or not getattr(poller, "is_git_repo", False):
            return False
        overlay_visible = False
        try:
            overlay_visible = self.query_one(WorkspaceOverlay).has_class("--visible")
        except NoMatches:
            pass
        return overlay_visible or bool(self.agent_running)

    def _sync_workspace_polling_state(self) -> None:
        desired = self._workspace_polling_desired()
        if desired:
            if self._git_poll_h is None:
                self._git_poll_h = self.set_interval(5.0, self._trigger_git_poll)
        else:
            if self._git_poll_h is not None:
                self._git_poll_h.stop()
                self._git_poll_h = None

    @work(thread=True, group="complexity")
    def _analyze_complexity(self, path: str) -> None:
        tracker = getattr(self, "_workspace_tracker", None)
        if tracker is None:
            return
        warning = analyze_complexity(path)
        self.call_from_thread(tracker.set_complexity, path, warning)
        self.call_from_thread(self._refresh_workspace_overlay)

    def _refresh_workspace_overlay(self) -> None:
        """Refresh WorkspaceOverlay content if visible. Must run on event loop."""
        tracker = getattr(self, "_workspace_tracker", None)
        if tracker is None:
            return
        try:
            ov = self.query_one(WorkspaceOverlay)
            if ov.has_class("--visible"):
                ov.refresh_data(tracker, self._last_git_snapshot)
        except NoMatches:
            pass

    def on_workspace_updated(self, event: WorkspaceUpdated) -> None:
        import time as _t

        self._git_poll_in_flight = False
        self._last_git_snapshot = event.snapshot
        tracker = getattr(self, "_workspace_tracker", None)
        if tracker is None:
            return
        if event.poll_elapsed_ms is not None and self._workspace_poll_perf_alarm is not None:
            self._workspace_poll_perf_alarm.observe(
                event.poll_elapsed_ms,
                detail=f"entries={len(event.snapshot.entries)}",
            )
        _t0 = _t.perf_counter()
        tracker.apply_snapshot(event.snapshot)
        try:
            ov = self.query_one(WorkspaceOverlay)
            if ov.has_class("--visible"):
                ov.refresh_data(tracker, event.snapshot)
        except NoMatches:
            pass
        apply_ms = (_t.perf_counter() - _t0) * 1000.0
        if self._workspace_apply_perf_alarm is not None:
            self._workspace_apply_perf_alarm.observe(
                apply_ms,
                detail=f"entries={len(event.snapshot.entries)} overlay_visible={ov.has_class('--visible') if 'ov' in locals() else False}",
            )
        if not self._workspace_hint_shown and tracker.entries():
            self._workspace_hint_shown = True
            self._flash_hint("w  workspace changes", 3.0)
        if self._git_poll_retrigger and self._workspace_polling_desired():
            self._git_poll_retrigger = False
            self._trigger_git_poll()
        else:
            self._git_poll_retrigger = False

    # ---------------------------------------------------------------------------
    # MCP registry handlers (v4 P1 — sub-spec B §5.3)
    # ---------------------------------------------------------------------------

    def on_mcp_server_registered(self, msg: MCPServerRegistered) -> None:
        """Consume MCPServerRegistered: update tool registry."""
        kw: dict = {"icon_ascii": msg.icon_ascii}
        if msg.icon_nf:
            kw["icon_nf"] = msg.icon_nf
        try:
            register_mcp_server(msg.server, **kw)
        except ValueError:
            logger.warning("register_mcp_server failed for %r", msg.server)
            return
        for tool_meta in msg.tools:
            try:
                register_tool(
                    ToolSpec.from_mcp_meta(tool_meta, server=msg.server),
                    overwrite=True,
                )
            except Exception:
                logger.debug("Failed to register MCP tool %r from %r", tool_meta.get("name"), msg.server)

    def on_mcp_server_disconnected(self, msg: MCPServerDisconnected) -> None:
        """Consume MCPServerDisconnected: specs stay — panels may still be on screen."""
        pass  # deliberate no-op; MCPServerRegistry entry stays for in-flight renders

    def action_toggle_workspace(self) -> None:
        try:
            ov = self.query_one(WorkspaceOverlay)
        except NoMatches:
            return
        if ov.has_class("--visible"):
            ov.action_dismiss()
        else:
            self._dismiss_all_info_overlays()
            tracker = getattr(self, "_workspace_tracker", None)
            if tracker is not None:
                ov.refresh_data(tracker, self._last_git_snapshot)
            ov.show_overlay()
            self._sync_workspace_polling_state()
            self._trigger_git_poll()

    def action_dismiss_all_error_banners(self) -> None:
        """E5: query all .error-banner widgets in the screen and remove each."""
        try:
            banners = list(self.screen.query(".error-banner"))
            for banner in banners:
                try:
                    banner.remove()
                except Exception:
                    pass
        except Exception:
            pass

    # --- InlineImageBar handlers ---

    def on_image_mounted(self, event: Any) -> None:
        """Bubble from StreamingToolBlock.ImageMounted → add thumbnail to InlineImageBar."""
        try:
            self.query_one(InlineImageBar).add_image(event.path)
        except NoMatches:
            pass

    async def on_inline_image_bar_thumbnail_clicked(self, event: Any) -> None:
        """Scroll OutputPanel to the InlineImage matching the clicked thumbnail."""
        from hermes_cli.tui.widgets import InlineImage
        for widget in self.query(InlineImage):
            if getattr(widget, "_src_path", "") == event.path:
                try:
                    self.query_one(OutputPanel).scroll_to_widget(widget, animate=True)
                except NoMatches:
                    pass
                break

    def _mount_inline_media_widget(self, kind: str, url: str) -> None:
        """Mount InlineMediaWidget in output panel. Event-loop only."""
        from hermes_cli.tui.media_player import _inline_media_config
        from hermes_cli.tui.widgets import InlineMediaWidget
        cfg = _inline_media_config()
        if not cfg.enabled:
            return
        try:
            from hermes_cli.tui.tool_blocks import ToolPendingLine
            output = self.query_one(OutputPanel)
            widget = InlineMediaWidget(url=url, kind=kind)
            try:
                tool_pending = output.query_one(ToolPendingLine)
                output.mount(widget, before=tool_pending)
            except NoMatches:
                output.mount(widget)
        except Exception:
            pass

    # IO methods extracted → _app_io.py

    # Spinner + hint bar methods extracted → _app_spinner.py

    # --- User message echo ---

    def echo_user_message(self, text: str, images: int = 0) -> None:
        """Mount a UserMessagePanel showing the user's submitted message.

        Called from the agent thread via ``call_from_thread`` before
        ``agent_running`` is set to True (which creates the new MessagePanel).
        """
        try:
            panel = self.query_one(OutputPanel)
            # D4: remove empty-state hint (if present from /clear) before mounting user message
            for hint in panel.query(".--empty-state-hint"):
                try:
                    hint.remove()
                except Exception:
                    pass
            ump = UserMessagePanel(text, images=images)
            panel.mount(ump, before=panel.query_one(ThinkingWidget))
            # Always scroll to show the user's own message regardless of scroll
            # position — the user just submitted, they expect to see the exchange.
            # Re-engage auto-scroll for the upcoming assistant response.
            panel._user_scrolled_up = False
            self.call_after_refresh(panel.scroll_end, animate=False)
        except NoMatches:
            pass

    def _resolve_user_emoji(self, text: str, panel: "UserMessagePanel") -> None:
        """Mount custom emoji images for :name: tokens found in the user's message.

        Runs on the event-loop thread (called directly from echo_user_message).
        """
        # User echo is a lightweight transcript row, not rich response prose.
        # Mounting image widgets into it after first paint can perturb turn
        # layout and visually corrupt adjacent status lines. Keep raw :name:
        # text in the echo panel; custom emoji remain enabled in assistant
        # responses where the richer layout path is designed for it.
        return
        from hermes_cli.tui.response_flow import _EMOJI_RE
        from hermes_cli.tui.kitty_graphics import get_caps, GraphicsCap
        registry = getattr(self, "_emoji_registry", None)
        if registry is None or not getattr(self, "_emoji_images_enabled", True):
            return
        cap = get_caps()
        use_images = cap in (GraphicsCap.TGP, GraphicsCap.SIXEL)
        seen: set[str] = set()
        for m in _EMOJI_RE.finditer(text):
            name = m.group(1).lower()
            if name in seen:
                continue
            entry = registry.get(name)
            if entry is None:
                continue
            seen.add(name)
            try:
                if entry.n_frames > 1 and use_images and entry.pil_image is not None:
                    from hermes_cli.tui.emoji_registry import get_animated_emoji_widget_class
                    cls = get_animated_emoji_widget_class()
                    panel.mount(cls(entry))
                elif use_images and entry.pil_image is not None:
                    from hermes_cli.tui.widgets import InlineImage
                    img = InlineImage(max_rows=entry.cell_height)
                    img.image = entry.pil_image
                    panel.mount(img)
            except Exception:
                pass

    # Hint phase + drawille methods extracted → _app_spinner.py

    def watch_yolo_mode(self, old: bool, value: bool) -> None:
        """Update #input-chevron CSS class to reflect yolo state."""
        try:
            chevron = self.query_one("#input-chevron", Static)
            if value:
                chevron.add_class("--yolo-active")
            else:
                chevron.remove_class("--yolo-active")
        except Exception:
            pass
        # E5: flash confirmation — skip initial reactive fire (old == value at init)
        if old == value:
            return
        msg = "YOLO mode ON — auto-approving all tool calls" if value else "YOLO mode OFF"
        self._flash_hint(msg, 2.0)

    def watch_agent_running(self, value: bool) -> None:
        self._drawille_show_hide(value)
        if value:
            # Signal thinking when agent starts
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.query_one(_DO).signal("thinking")
            except Exception:
                pass
            self._update_anim_hint()
            self._dismiss_all_info_overlays()
            self._response_metrics_active = False
            self._response_wall_start_time = None
            self._response_segment_start_time = None
            self._response_token_window.clear()
            self._set_chevron_phase("--phase-stream")
            self._set_hint_phase("stream")
            # P7: reset per-turn tool call list for fresh turn
            self._turn_tool_calls = {}
            self._agent_stack = []
            self._turn_start_monotonic = None
            self._current_turn_tool_count = 0  # A6: reset first-in-turn counter
            # Track turn start for desktop notify
            self._turn_start_time = _time.monotonic()
            try:
                self.query_one(OutputPanel).reset_turn_capture()
            except NoMatches:
                pass
            self._sync_workspace_polling_state()
            # OSC progress bar
            self._osc_progress_update(True)
        else:
            # Signal complete when agent stops
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.query_one(_DO).signal("complete")
            except Exception:
                pass
            self._update_anim_hint()
            self._sync_workspace_polling_state()
            try:
                chevron = self.query_one("#input-chevron", Static)
                if not chevron.has_class("--phase-error"):
                    self._set_chevron_phase("--phase-done")
                    self.set_timer(0.4, lambda: self._set_chevron_phase(""))
            except NoMatches:
                pass
            # Safety net: flush live buffer + stop all per-turn timers.
            # flush_output() is never called from cli.py so the None sentinel
            # that drives flush_live() via _consume_output never arrives.
            # flush_live() handles: (1) ThinkingWidget.deactivate(),
            # (2) LiveLineWidget.flush() → stops blink timer + resets
            #     _blink_visible, (3) commits any partial _buf to MessagePanel.
            try:
                output = self.query_one(OutputPanel)
                output.flush_live()
                # Evict old turns at idle to prevent compositor cache thrash
                # (Textual LRU maxsize=16 can't cope with 300+ children).
                output.evict_old_turns()
            except NoMatches:
                pass
            # D1: clear output-dropped flag on agent stop so StatusBar backpressure
            # indicator doesn't persist into the next idle period.
            self.status_output_dropped = False
            # Clear stale spinner/file breadcrumb — cli.py resets _spinner_text
            # locally but never pushes spinner_label="" to the app, so the last
            # tool label persists into turn 2 and StatusBar shows a stale file path.
            self.spinner_label = ""
            self.status_active_file = ""
            self._response_metrics_active = False
            self._response_wall_start_time = None
            self._response_segment_start_time = None
            self._response_token_window.clear()
            # Clear the tracking dict for blocks left open from an interrupted turn
            # (agent stopped without calling close_streaming_tool_block).
            # Leaked refs prevent GC; stale entries corrupt the next turn's diff
            # connector logic.  DOM nodes stay visible so users see partial output.
            self._active_streaming_blocks.clear()
            # Clear file-tool block ref so next turn's diff won't inherit connector
            try:
                msg = self.query_one(OutputPanel).current_message
                if msg is not None:
                    msg._last_file_tool_block = None
            except NoMatches:
                pass
            # Clear any gen blocks left open from interrupted turns
            pending = getattr(self.cli, "_pending_gen_queue", None)
            if pending:
                for block in pending:
                    try:
                        block.remove()
                    except Exception:
                        pass
                pending.clear()
            # v2 heat injection: signal turn complete
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay
                ov = self.query_one(DrawilleOverlay)
                ov.signal("complete")
            except Exception:
                pass
            # Rebuild unified browse anchor list now that all blocks are mounted
            if self.browse_mode:
                self._rebuild_browse_anchors()
            # OSC progress bar: clear
            self._osc_progress_update(False)
            # Desktop notification
            self._maybe_notify()
            # Auto-title: derive session title from first user message (once per session)
            if not self._auto_title_done:
                self._try_auto_title()
            # Live-refresh history search index if overlay is open
            try:
                hs = self.query_one(HistorySearchOverlay)
                if hs.has_class("--visible"):
                    hs.post_message(HistorySearchOverlay.TurnCompleted())
            except NoMatches:
                pass

        # --- nameplate ---
        try:
            np = self.query_one("#nameplate", AssistantNameplate)
            if value:
                np.transition_to_active(label=self.spinner_label or "● thinking")
            else:
                np.transition_to_idle()
        except NoMatches:
            pass

        # --- undo safety guard ---
        if value and self.undo_state is not None:
            # Agent started while undo overlay was open — auto-cancel for safety
            self.undo_state = None
            self._pending_undo_panel = None
            self._flash_hint("⚠  Agent started, undo cancelled", 2.0)

        try:
            widget = self.query_one("#input-area")
            # Input stays enabled when agent is running — user can submit
            # to interrupt + send new message.  Only overlays disable input.
            if not value:
                if hasattr(widget, "spinner_text"):
                    widget.spinner_text = ""
                # Restore input visibility (safety guard) and clear spinner placeholder
                widget.display = True
                if hasattr(widget, "placeholder"):
                    # A1: restore idle placeholder, not blank string.
                    # Show error hint in placeholder when status_error is set
                    # so the error state is visible even at short terminal heights
                    # where HintBar may be hidden.
                    if self.status_error:
                        err_snippet = self.status_error[:60]
                        widget.placeholder = f"Error: {err_snippet}…  (Esc to clear)"
                    else:
                        widget.placeholder = getattr(widget, "_idle_placeholder", "")
                try:
                    self.query_one("#spinner-overlay", Static).display = False
                except NoMatches:
                    pass
                # Clear the HintBar spinner when the agent stops.
                # E3: respect _flash_hint_expires — don't clear a timed flash.
                if _time.monotonic() >= self._flash_hint_expires:
                    try:
                        self.query_one(HintBar).hint = ""
                    except NoMatches:
                        pass
                # GAP-17: restore focus so the user can type immediately without clicking
                self.call_after_refresh(widget.focus)
        except NoMatches:
            pass
        # New turn starting — create a new MessagePanel with the last user input
        if value:
            try:
                output = self.query_one(OutputPanel)
                # Migrate any setext/table lookahead content buffered in the
                # previous panel's engine to the new panel.
                #
                # Race: the agent starts streaming before watch_agent_running(True)
                # fires on the event loop.  The first response line (e.g. "Wake up
                # Neo") may arrive via _commit_lines() while current_message is
                # still the old (startup/previous-turn) panel, causing it to be
                # held in that panel's _block_buf._pending.  When new_message()
                # creates the new panel, the old panel is never flushed again →
                # content disappears.
                #
                # Fix: steal _pending from the old engine and re-process it
                # through the new engine after new_message(), so the content
                # lands in the correct panel rather than being flushed to the
                # wrong one or lost.
                prev_msg = output.current_message
                stolen_pending: str | None = None
                stolen_partial: str | None = None
                if prev_msg is not None:
                    prev_engine = getattr(prev_msg, "_response_engine", None)
                    if prev_engine is not None:
                        try:
                            p = prev_engine._block_buf._pending
                            if p:  # non-None and non-empty string
                                prev_engine._block_buf._pending = None
                                stolen_pending = p
                            elif p is not None:
                                # empty string sentinel — just clear it
                                prev_engine._block_buf._pending = None
                        except Exception:
                            pass
                        try:
                            # Also steal any partial chunk (no \n yet) buffered by feed()
                            frag = prev_engine._partial
                            if frag:
                                prev_engine._partial = ""
                                stolen_partial = frag
                        except Exception:
                            pass
                new_msg = output.new_message(user_text=self._last_user_input)
                # Engine isn't ready yet (on_mount fires next cycle); use
                # _carry_pending/_carry_partial so on_mount processes them once engine exists.
                if stolen_pending and new_msg is not None:
                    new_msg._carry_pending = stolen_pending
                if stolen_partial and new_msg is not None:
                    new_msg._carry_partial = stolen_partial
            except NoMatches:
                pass
        # Recompute hint phase when agent stops
        if not value:
            self._set_hint_phase(self._compute_hint_phase())

    def _osc_progress_update(self, running: bool) -> None:
        """Emit OSC 9;4 sequence when config flag is set."""
        try:
            from hermes_cli.tui.osc_progress import osc_progress_start, osc_progress_end
            cfg = getattr(self.cli, "_cfg", {}) if self.cli else {}
            if (cfg.get("display", {}) if isinstance(cfg, dict) else {}).get("osc_progress", True):
                if running:
                    osc_progress_start()
                else:
                    osc_progress_end()
        except Exception:
            pass

    def _maybe_notify(self) -> None:
        """Fire desktop notification when turn exceeds threshold."""
        try:
            cfg = getattr(self.cli, "_cfg", {}) if self.cli else {}
            display = (cfg.get("display", {}) if isinstance(cfg, dict) else {})
            if not display.get("desktop_notify", False):
                return
            import time as _time2
            elapsed = _time2.monotonic() - getattr(self, "_turn_start_time", 0.0)
            min_s = float(display.get("notify_min_seconds", 10.0))
            if elapsed < min_s:
                return
            # F4: skip notification when user is actively watching the TUI
            # (last keypress < 5 s ago means they are present)
            since_key = _time2.monotonic() - getattr(self, "_last_keypress_time", 0.0)
            if since_key < 5.0:
                return
            from hermes_cli.tui.desktop_notify import notify as _notify
            body = (getattr(self, "_last_assistant_text", "") or "").strip()
            if body:
                body = body.splitlines()[0][:120]
            else:
                body = "Task complete"
            _notify(
                "Hermes",
                body,
                sound=bool(display.get("notify_sound", False)),
                sound_name=str(display.get("notify_sound_name", "Glass")),
            )
        except Exception:
            pass

    def _refresh_live_response_metrics(self) -> None:
        """Refresh current message header while a streamed response is active."""
        if not self._response_metrics_active:
            return
        try:
            output = self.query_one(OutputPanel)
        except NoMatches:
            return
        msg = output.current_message
        if msg is None:
            return
        wall_start = self._response_wall_start_time
        if wall_start is None:
            return
        now = _time.monotonic()
        elapsed = max(0.0, now - wall_start)
        window_s = 2.0
        while self._response_token_window and now - self._response_token_window[0][0] > window_s:
            self._response_token_window.popleft()
        live_tok_s = 0.0
        if self._response_token_window:
            token_sum = sum(tokens for _, tokens in self._response_token_window)
            # Floor span at 0.2s to prevent initial spike from tiny windows
            span = max(now - self._response_token_window[0][0], 0.2)
            live_tok_s = token_sum / span
        msg.set_response_metrics(tok_s=live_tok_s, elapsed_s=elapsed, streaming=True)

    def mark_response_stream_started(self) -> None:
        """Start live response timing for current assistant turn."""
        if not self._response_metrics_active:
            self._response_metrics_active = True
            self._response_wall_start_time = _time.monotonic()
            self._response_token_window.clear()
        if self._response_segment_start_time is None:
            self._response_segment_start_time = _time.monotonic()
        self._refresh_live_response_metrics()

    def mark_response_stream_delta(self, text: str) -> None:
        """Record streamed response text for rolling live tok/s."""
        if self._response_segment_start_time is None or not text:
            return
        from agent.model_metadata import estimate_tokens_rough
        est_tokens = estimate_tokens_rough(text)
        if est_tokens <= 0:
            return
        self._response_token_window.append((_time.monotonic(), est_tokens))
        # v2 heat injection: bump heat on each streaming token chunk
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            ov = self.query_one(DrawilleOverlay)
            ov.signal("token")
        except Exception:
            pass
        self._refresh_live_response_metrics()

    def pause_response_stream(self) -> None:
        """Pause live message timing while agent waits on tool execution."""
        self._response_segment_start_time = None
        # Don't clear token_window — preserves recent tok/s for display

    def finalize_response_metrics(self, tok_s: float, elapsed_s: float) -> None:
        """Freeze tok/s + elapsed on current assistant message header."""
        self.pause_response_stream()
        self._response_metrics_active = False
        self._response_wall_start_time = None
        self._response_token_window.clear()
        try:
            output = self.query_one(OutputPanel)
        except NoMatches:
            return
        msg = output.current_message
        if msg is None:
            return
        msg.set_response_metrics(tok_s=tok_s, elapsed_s=elapsed_s, streaming=False)

    def watch_spinner_label(self, value: str) -> None:
        """Reset per-tool elapsed timer and extract active file path."""
        self._tool_start_time = _time.monotonic() if value else 0.0
        if value and isinstance(value, str):
            # Labels are already prefix-stripped by _build_hint_text.
            # Split on "(" (args form) and " · " (elapsed-time form) to isolate tool name.
            tool_name = value.split("(")[0].split(" · ")[0].strip()
            if tool_name in _FILE_TOOLS:
                m = _PATH_EXTRACT_RE.search(value)
                self.status_active_file = m.group(1) if m else ""
                self._set_chevron_phase("--phase-file")
                self._set_hint_phase("file")
            elif tool_name in _SHELL_TOOLS:
                self.status_active_file = ""
                self._set_chevron_phase("--phase-shell")
                self._set_hint_phase("stream")
            else:
                self.status_active_file = ""
                self._set_chevron_phase("--phase-stream")
                self._set_hint_phase("stream")
        else:
            self.status_active_file = ""
            if self.agent_running:
                self._set_chevron_phase("--phase-stream")
        # nameplate: glitch + label update on non-empty spinner_label
        if value:
            try:
                np = self.query_one("#nameplate", AssistantNameplate)
                np.glitch()
                np.set_active_label(f"▸ {value[:16]}")
            except NoMatches:
                pass

    @property
    def choice_overlay_active(self) -> bool:
        """True when an interactive choice overlay (clarify/approval) is up.

        Used by HermesInput._update_autocomplete to suppress completion while
        the user is answering an approval prompt.
        """
        return self.clarify_state is not None or self.approval_state is not None

    def _hide_completion_overlay_if_present(self) -> None:
        """Hide the completion overlay when a choice overlay activates."""
        try:
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            self.query_one(_CO).remove_class("--visible")
        except NoMatches:
            pass

    def action_open_history_search(self) -> None:
        """Open (or close) the history search overlay."""
        from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
        try:
            if self.query_one(_CO).has_class("--visible"):
                return
        except NoMatches:
            pass
        try:
            hs = self.query_one(HistorySearchOverlay)
            if hs.has_class("--visible"):
                hs.action_dismiss()
            else:
                hs.open_search()
        except NoMatches:
            pass

    def action_show_help(self) -> None:
        """Toggle the keyboard-shortcut reference overlay."""
        try:
            overlay = self.query_one(KeymapOverlay)
            if overlay.has_class("--visible"):
                overlay.remove_class("--visible")
            else:
                overlay.add_class("--visible")
        except NoMatches:
            pass

    def show_model_switch_result(self, new_model: str) -> None:
        """C3: Flash confirmation when model switch completes. Call via call_from_thread."""
        self._flash_hint(f"Model: {new_model}", 2.0)

    def action_show_usage(self) -> None:
        """C5: Show the usage/cost overlay (F2 key)."""
        self._dismiss_all_info_overlays()
        try:
            ov = self.query_one(UsageOverlay)
            agent = getattr(self.cli, "agent", None) if self.cli else None
            if agent is None:
                agent = self.cli
            if agent is not None:
                ov.refresh_data(agent)
            ov.add_class("--visible")
        except NoMatches:
            pass

    def action_jump_turn_prev(self) -> None:
        """Jump to the previous TURN_START anchor. No-op while agent is running."""
        if self.agent_running:
            self._flash_hint("Navigation paused while agent is running", 1.5)
            return
        self._jump_anchor(-1, BrowseAnchorType.TURN_START)


    def action_jump_turn_next(self) -> None:
        """Jump to the next TURN_START anchor. No-op while agent is running."""
        if self.agent_running:
            self._flash_hint("Navigation paused while agent is running", 1.5)
            return
        self._jump_anchor(+1, BrowseAnchorType.TURN_START)


    def action_focus_output(self) -> None:
        """o: move focus to OutputPanel."""
        try:
            self.query_one(OutputPanel).focus()
        except Exception:
            pass

    def action_focus_input_from_output(self) -> None:
        """i: move focus back to HermesInput from output area."""
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.query_one(HermesInput).focus()
        except Exception:
            pass

    def action_toggle_density(self) -> None:
        """Toggle compact / normal density mode."""
        if self._compact_manual is None or not self.compact:
            self._compact_manual = True
            self.compact = True
            self._flash_hint("Compact ON  (/density to toggle)", 1.5)
        else:
            self._compact_manual = None  # restore auto
            w, h = self.size.width, self.size.height
            self.compact = w <= 120 or h <= 30
            self._flash_hint("Compact auto", 1.5)

    def _dismiss_floating_panels(self) -> None:
        """Dismiss HistorySearchOverlay and KeymapOverlay (P0-B stacking).

        Called whenever an agent-triggered overlay becomes active so that the
        reference/navigation panels do not compete for screen space.
        """
        try:
            hs = self.query_one(HistorySearchOverlay)
            if hs.has_class("--visible"):
                hs.action_dismiss()
        except NoMatches:
            pass
        try:
            ko = self.query_one(KeymapOverlay)
            if ko.has_class("--visible"):
                ko.remove_class("--visible")
        except NoMatches:
            pass

    def handle_session_resume(self, session_id: str, session_title: str, turn_count: int) -> None:
        """Clear OutputPanel and show resumed-session banner. Event-loop only."""
        try:
            panel = self.query_one(OutputPanel)
        except NoMatches:
            return
        panel.remove_children()
        banner = _SessionResumedBanner(session_title or session_id[-8:], turn_count)
        panel.mount(banner)
        self.session_label = session_title or session_id[-8:]
        self._auto_title_done = False
        # D3: reset browse anchor state so old indices do not point to removed widgets
        self._browse_anchors = []
        self._browse_cursor = 0
        self._browse_total = 0
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

        # --- Input/size/compaction/voice/image/file-drop watchers: in _app_watchers.py ---

        # --- Reasoning panel helpers (called via call_from_thread) ---

    # --- Tool rendering: in _app_tool_rendering.py ---


    # --- Browse mode: in _app_browse.py ---

        # --- Theme / skin system ---

    # --- Theme/skin/slash/flash: in _app_theme.py ---

    # --- Context menu + clipboard: in _app_context_menu.py ---

    
    # --- TUI commands + anim + undo/retry: in _app_commands.py ---

    # --- Key handler + input submission: in _app_key_handler.py ---
