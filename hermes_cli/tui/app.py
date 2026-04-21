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

# Known TUI slash commands — unknown /cmd input shows a hint instead of routing to agent.
_KNOWN_SLASH_COMMANDS: frozenset[str] = frozenset([
    "/loop", "/schedule", "/anim", "/yolo", "/verbose",
    "/model", "/reasoning", "/skin", "/fast", "/easteregg",
    "/help", "/queue", "/btw", "/clear",
])

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


class HermesApp(_AppIOMixin, _SpinnerMixin, _ToolRenderingMixin, _BrowseMixin, _ContextMenuMixin, App):
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
        Binding("ctrl+g", "open_history_search", "History search", show=False, priority=True),
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

    # Status bar data
    status_model: reactive[str] = reactive("")
    status_context_tokens: reactive[int] = reactive(0)
    status_context_max: reactive[int] = reactive(0)

    # Compaction state
    status_compaction_progress: reactive[float] = reactive(0.0)  # 0.0–1.0
    status_compaction_enabled: reactive[bool] = reactive(True)

    # Tok/s throughput (last turn)
    status_tok_s: reactive[float] = reactive(0.0)

    # Browse mode — keyboard-driven navigation through ToolBlock widgets
    browse_mode: reactive[bool] = reactive(False)
    browse_index: reactive[int] = reactive(0)
    # Memoized count of mounted ToolHeaders — avoids O(n) DOM query in StatusBar.render()
    _browse_total: reactive[int] = reactive(0)
    # Unified anchor list hint shown in StatusBar during []/{}/ Alt+↑↓ navigation
    _browse_hint: reactive[str] = reactive("")

    # Completion overlay hint shown in StatusBar while overlay is visible (A3/C1)
    _completion_hint: reactive[str] = reactive("")

    # Animation force state — overrides trigger-based show/hide logic
    # None = normal; "on" = always show; "off" = always hide
    _anim_force: "str | None" = None

    # Animation hint for StatusBar (C3)
    _anim_hint: reactive[str] = reactive("")

    # Active tool name — set/cleared by _on_tool_start/_on_tool_complete (C1)
    _active_tool_name: str = ""

    # Detail level of currently focused ToolPanel in browse mode (for StatusBar badge)
    browse_detail_level: reactive[int] = reactive(0)


    # Output dropped flag — set when queue is full; shown in StatusBar until next successful write
    status_output_dropped: reactive[bool] = reactive(False)

    # D5: count of currently-streaming tool blocks (shows badge in StatusBar)
    _streaming_tool_count: reactive[int] = reactive(0, repaint=False)

    # Image attachments — reactive(list) uses factory form to avoid shared mutable default
    attached_images: reactive[list] = reactive(list)

    # Spinner label — text shown beside the spinner frame (e.g. "Calling tool…")
    spinner_label: reactive[str] = reactive("")

    # Active file path extracted from spinner_label when a file-touching tool runs.
    # Drives the 📄 breadcrumb in StatusBar. Empty string when no file is active.
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

    # Current session label — shown in StatusBar chip
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
        self._turn_tool_calls: list[dict] = []
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
            self.add_class("density-compact")
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
        for _attr in ("_anim_clock_h", "_spinner_h", "_fps_h", "_duration_h"):
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

    def watch_yolo_mode(self, value: bool) -> None:
        """Update #input-chevron CSS class to reflect yolo state."""
        try:
            chevron = self.query_one("#input-chevron", Static)
            if value:
                chevron.add_class("--yolo-active")
            else:
                chevron.remove_class("--yolo-active")
        except Exception:
            pass
        # E5: flash confirmation so the mode change is not silent
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
            self._turn_tool_calls = []
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
        if self.has_class("density-compact"):
            self.remove_class("density-compact")
            self._flash_hint("Density: normal", 1.0)
        else:
            self.add_class("density-compact")
            self._flash_hint("Density: compact", 1.0)

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

    @work(thread=True)
    def action_resume_session(self, session_id: str) -> None:
        """Resume a session by ID (runs in worker thread)."""
        cli = self.cli
        try:
            if hasattr(cli, "_handle_resume_command"):
                cli._handle_resume_command(f"/resume {session_id}")
                db = getattr(cli, "_session_db", None)
                session_meta: dict = {}
                if db is not None:
                    try:
                        session_meta = db.get_session(session_id) or {}
                    except Exception:
                        pass
                title = session_meta.get("title") or ""
                msgs = getattr(cli, "conversation_history", []) or []
                turn_count = len([m for m in msgs if m.get("role") in ("user", "assistant")])
                self.call_from_thread(
                    self.handle_session_resume, session_id, title, turn_count
                )
        except Exception:
            pass

    def action_open_sessions(self) -> None:
        """Open the session browser overlay."""
        self._dismiss_all_info_overlays()
        try:
            self.query_one(SessionOverlay).open_sessions()
        except NoMatches:
            pass

    # --- Parallel worktree sessions ---

    @property
    def _sessions_enabled(self) -> bool:
        """True when sessions.enabled is set in CLI config."""
        if self._sessions_enabled_override is not None:
            return self._sessions_enabled_override
        try:
            from hermes_cli.config import CLI_CONFIG
            return bool(CLI_CONFIG.get("sessions", {}).get("enabled", False))
        except Exception:
            return False

    @_sessions_enabled.setter
    def _sessions_enabled(self, value: bool) -> None:
        self._sessions_enabled_override = value

    def _init_sessions(self) -> None:
        """Initialize parallel session infrastructure (event-loop only)."""
        from hermes_cli.tui.session_manager import SessionManager, _NotifyListener
        cfg = getattr(self, "_sessions_cfg", {})
        if not cfg:
            # Read config from cli if available
            cli_cfg = getattr(getattr(self, "cli", None), "config", None) or {}
            cfg = cli_cfg.get("sessions", {}) if isinstance(cli_cfg, dict) else {}
        if not cfg.get("enabled", False):
            return
        self._sessions_enabled = True
        import os as _os
        session_dir = _os.path.expanduser(cfg.get("session_dir", "/tmp/hermes-sessions"))
        from pathlib import Path as _Path
        self._session_mgr = SessionManager(
            _Path(session_dir),
            max_sessions=int(cfg.get("max_sessions", 8)),
        )
        # Load initial session records
        self._session_records_cache = self._session_mgr.index.get_sessions()
        self._session_active_id = self._session_mgr.index.get_active_id()
        # Enable SessionBar
        try:
            bar = self.query_one(SessionBar)
            bar.add_class("--sessions-enabled")
            bar.update_sessions(
                self._session_records_cache,
                self._session_active_id,
                self._session_mgr._max_sessions,
            )
        except NoMatches:
            pass
        # Start notify listener if we have an own session ID
        if self._own_session_id:
            try:
                sock_path = str(
                    _Path(session_dir) / self._own_session_id / "notify.sock"
                )
                self._notify_listener = _NotifyListener(
                    sock_path, self._on_session_notify_event
                )
                self._notify_listener.start()
            except Exception:
                pass
        # Start 2s polling timer
        self._sessions_poll_timer = self.set_interval(2.0, self._poll_session_index)

    def _get_session_records(self) -> list:
        """Return cached session records. Event-loop safe."""
        return list(self._session_records_cache)

    def _get_active_session_id(self) -> str:
        """Return active session ID. Event-loop safe."""
        return self._session_active_id

    def _refresh_session_bar(self) -> None:
        """Rebuild SessionBar from current cache. Event-loop only."""
        if not self._sessions_enabled:
            return
        try:
            bar = self.query_one(SessionBar)
            max_s = self._session_mgr._max_sessions if self._session_mgr else 8
            bar.update_sessions(
                self._session_records_cache,
                self._session_active_id,
                max_s,
            )
        except NoMatches:
            pass

    def _poll_session_index(self) -> None:
        """Event-loop: re-read sessions.json every 2s and refresh bar on change."""
        if not self._session_mgr:
            return
        try:
            records = self._session_mgr.index.get_sessions()
            active_id = self._session_mgr.index.get_active_id()
            if records != self._session_records_cache or active_id != self._session_active_id:
                self._session_records_cache = records
                self._session_active_id = active_id
                self._refresh_session_bar()
        except Exception:
            pass

    def _refresh_session_records_from_index(self) -> None:
        """Re-read sessions.json and update bar. Event-loop only."""
        self._poll_session_index()

    def _open_new_session_overlay(self) -> None:
        """Show NewSessionOverlay. Event-loop only."""
        if not self._sessions_enabled:
            return
        self._dismiss_all_info_overlays()
        try:
            self.query_one(NewSessionOverlay).show_overlay()
        except NoMatches:
            pass

    def _flash_sessions_max(self) -> None:
        """Flash HintBar with max sessions message. Event-loop only."""
        self._flash_hint("Max sessions reached", duration=2.0)

    def action_new_worktree_session(self) -> None:
        """Ctrl+W N — open new session overlay."""
        if not self._sessions_enabled:
            return
        if len(self._session_records_cache) >= (
            self._session_mgr._max_sessions if self._session_mgr else 8
        ):
            self._flash_sessions_max()
            return
        self._open_new_session_overlay()

    def _switch_to_session_by_index(self, n: int) -> None:
        """Switch to session by 0-based index in session bar. Event-loop only."""
        if not self._sessions_enabled or not self._session_records_cache:
            return
        if 0 <= n < len(self._session_records_cache):
            rec = self._session_records_cache[n]
            target_id = getattr(rec, "id", None)
            if target_id and target_id != self._session_active_id:
                self._switch_to_session(target_id)

    def _switch_to_session(self, session_id: str) -> None:
        """Switch to a background session via os.execvp. Event-loop only."""
        import sys as _sys
        if session_id == self._session_active_id or not self._sessions_enabled:
            return
        # Write active_session_id to sessions.json before exec
        try:
            if self._session_mgr:
                self._session_mgr.index.update_active(session_id)
        except Exception:
            pass
        # Stop notify listener and poll timer (best-effort)
        if self._notify_listener:
            try:
                self._notify_listener.stop()
            except Exception:
                pass
        if self._sessions_poll_timer:
            try:
                self._sessions_poll_timer.stop()
            except Exception:
                pass
        # Exit Textual cleanly then exec into the target session
        def _do_exec() -> None:
            import os as _os
            _os.execvp(_sys.argv[0], [_sys.argv[0], "--worktree-session-id", session_id])

        self.exit(callback=_do_exec)

    def _on_session_notify_event(self, event: dict) -> None:
        """Called from _NotifyListener daemon thread — must use call_from_thread."""
        self.call_from_thread(self._handle_session_event, event)

    def _handle_session_event(self, event: dict) -> None:
        """Event-loop: route IPC notification to _SessionNotification widget."""
        try:
            notif = self.query_one(_SessionNotification)
            notif.push(event)
        except NoMatches:
            pass
        # Also refresh session records to pick up agent_running state change
        self._refresh_session_records_from_index()

    @work(thread=True)
    def _create_new_session(self, branch: str, base: str, overlay: object) -> None:
        """Worker: git worktree add + spawn headless process + register in index."""
        import subprocess as _sp
        import sys as _sys
        if not self._session_mgr:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), "Sessions not initialized."
            )
            return
        new_id = self._session_mgr.new_id()
        try:
            self._session_mgr.validate_socket_path(new_id)
        except ValueError as exc:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), str(exc)
            )
            return
        worktree_path = self._session_mgr.create_session_dir(new_id)
        # git worktree add
        base_ref = "HEAD" if base == "current" else "main"
        try:
            result = _sp.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch, base_ref],
                capture_output=True, text=True, check=True,
            )
        except _sp.CalledProcessError as exc:
            err = (exc.stderr or "").strip() or "git worktree add failed"
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), err
            )
            return
        # Spawn headless process
        try:
            _sp.Popen(
                [_sys.argv[0], "--headless", "--worktree-session-id", new_id],
                cwd=str(worktree_path),
                start_new_session=True,
            )
        except OSError as exc:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), f"Spawn failed: {exc}"
            )
            return
        # Poll state.json for PID
        rec = self._session_mgr.poll_state_until_pid(new_id, timeout=3.0)
        if rec is None:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), "Session failed to start."
            )
            # Cleanup
            try:
                _sp.run(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
            return
        # Register in sessions.json
        try:
            self._session_mgr.index.add_session(rec)
        except Exception:
            pass
        self.call_from_thread(self._on_session_created, new_id, overlay)

    def _on_session_created(self, new_id: str, overlay: object) -> None:
        """Event-loop: dismiss overlay and refresh session bar after create."""
        dismiss = getattr(overlay, "action_dismiss", None)
        if dismiss:
            dismiss()
        self._refresh_session_records_from_index()

    @work(thread=True)
    def _kill_session_prompt(self, session_id: str) -> None:
        """Worker: find record and kill the session process."""
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            self.call_from_thread(self._flash_hint, "Session not found.", 2.0)
            return
        try:
            if self._session_mgr:
                self._session_mgr.kill_session(rec)
            self._session_mgr.index.remove_session(session_id)
        except Exception:
            pass
        self.call_from_thread(self._refresh_session_records_from_index)

    @work(thread=True)
    def _do_kill_session(self, session_id: str) -> None:
        """Worker: kill session process and remove from index."""
        from pathlib import Path
        from hermes_cli.config import CLI_CONFIG
        from hermes_cli.tui.session_manager import SessionManager
        sessions_cfg = CLI_CONFIG.get("sessions", {})
        session_dir = Path(sessions_cfg.get("session_dir", "/tmp/hermes-sessions"))
        mgr = SessionManager(session_dir)
        for rec in mgr.index.get_sessions():
            if rec.id == session_id:
                mgr.kill_session(rec)
                mgr.index.remove_session(session_id)
                break
        self.call_from_thread(self._flash_hint, f"Session {session_id[:8]} killed", 1.5)

    @work(thread=True)
    def _open_merge_overlay(self, session_id: str) -> None:
        """Worker: fetch diff stat then show MergeConfirmOverlay."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            return
        branch = getattr(rec, "branch", "")
        try:
            result = _sp.run(
                ["git", "diff", "HEAD..." + branch, "--stat"],
                capture_output=True, text=True, timeout=10,
            )
            diff_stat = result.stdout.strip() or "(no diff)"
        except Exception:
            diff_stat = "(error fetching diff)"
        self.call_from_thread(self._show_merge_overlay, session_id, diff_stat)

    def _show_merge_overlay(self, session_id: str, diff_stat: str) -> None:
        """Event-loop: open MergeConfirmOverlay for the given session."""
        try:
            overlay = self.query_one(MergeConfirmOverlay)
            overlay.show_for(session_id, diff_stat)
        except NoMatches:
            pass

    @work(thread=True)
    def _run_merge(
        self,
        session_id: str,
        strategy: str,
        close_on_success: bool,
        overlay: object,
    ) -> None:
        """Worker: run git merge/squash/rebase for the session branch."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), "Session not found."
            )
            return
        branch = getattr(rec, "branch", "")
        if strategy == "squash":
            cmd = ["git", "merge", "--squash", branch]
        elif strategy == "rebase":
            cmd = ["git", "rebase", branch]
        else:
            cmd = ["git", "merge", branch]
        try:
            result = _sp.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "merge failed").strip()
                self.call_from_thread(
                    getattr(overlay, "_set_error", lambda m: None), err
                )
                return
        except Exception as exc:
            self.call_from_thread(
                getattr(overlay, "_set_error", lambda m: None), str(exc)
            )
            return
        if close_on_success:
            try:
                if self._session_mgr:
                    self._session_mgr.kill_session(rec)
                    import subprocess as _sp2
                    _sp2.run(
                        ["git", "worktree", "remove", "--force", getattr(rec, "worktree_path", "")],
                        capture_output=True, timeout=10,
                    )
                    self._session_mgr.index.remove_session(session_id)
            except Exception:
                pass
        self.call_from_thread(self._refresh_session_records_from_index)
        self.call_from_thread(getattr(overlay, "action_dismiss", lambda: None))

    @work(thread=True)
    def _reopen_orphan_session(self, session_id: str) -> None:
        """Worker: spawn new headless process in an orphan worktree."""
        import subprocess as _sp
        import sys as _sys
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        if rec is None:
            return
        worktree_path = getattr(rec, "worktree_path", "")
        try:
            _sp.Popen(
                [_sys.argv[0], "--headless", "--worktree-session-id", session_id],
                cwd=worktree_path,
                start_new_session=True,
            )
        except Exception:
            return
        new_rec = self._session_mgr.poll_state_until_pid(session_id, timeout=3.0) if self._session_mgr else None
        if new_rec:
            try:
                self._session_mgr.index.add_session(new_rec)
            except Exception:
                pass
        self.call_from_thread(self._refresh_session_records_from_index)

    @work(thread=True)
    def _delete_orphan_session(self, session_id: str) -> None:
        """Worker: remove worktree dir and session index entry."""
        import subprocess as _sp
        records = self._session_mgr.index.get_sessions() if self._session_mgr else []
        rec = next((r for r in records if getattr(r, "id", None) == session_id), None)
        worktree_path = getattr(rec, "worktree_path", "") if rec else ""
        if worktree_path:
            try:
                _sp.run(
                    ["git", "worktree", "remove", "--force", worktree_path],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
        try:
            if self._session_mgr:
                self._session_mgr.index.remove_session(session_id)
        except Exception:
            pass
        self.call_from_thread(self._refresh_session_records_from_index)

    def watch_clarify_state(self, value: ChoiceOverlayState | None) -> None:
        try:
            w = self.query_one(ClarifyWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
                self._dismiss_floating_panels()
                self.call_after_refresh(w.focus)
            else:
                if not self.agent_running and not self.command_running:
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_approval_state(self, value: ChoiceOverlayState | None) -> None:
        # Phase A3: signal waiting/thinking to drawille overlay
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            self.query_one(DrawilleOverlay).signal("waiting" if value is not None else "thinking")
        except Exception:
            pass
        try:
            w = self.query_one(ApprovalWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()
                self._dismiss_floating_panels()
                self.call_after_refresh(w.focus)
            else:
                if not self.agent_running and not self.command_running:
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_highlighted_candidate(self, c: Any) -> None:
        """Route highlighted candidate to PreviewPanel (PathCandidate only)."""
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel as _PP
            from hermes_cli.tui.path_search import PathCandidate as _PC
            panel = self.query_one(_PP)
            panel.candidate = c if isinstance(c, _PC) else None
        except NoMatches:
            pass
        # Toggle --no-preview class so CompletionOverlay hides preview when nothing highlighted
        try:
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            comp = self.query_one(_CO)
            if c is None:
                comp.add_class("--no-preview")
            else:
                comp.remove_class("--no-preview")
        except NoMatches:
            pass

    def watch_sudo_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SudoWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_secret_state(self, value: SecretOverlayState | None) -> None:
        try:
            w = self.query_one(SecretWidget)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())

    def watch_status_error(self, value: str) -> None:
        """Update TitledRule error state and hint phase when error changes."""
        try:
            self.query_one("#input-rule", TitledRule).set_error(bool(value))
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())
        # E1: auto-clear error after 10 s so stale indicators don't linger
        _timer = getattr(self, "_status_error_timer", None)
        if _timer is not None:
            try:
                _timer.stop()
            except Exception:
                pass
            self._status_error_timer = None
        if value:
            self._status_error_timer = self.set_timer(
                10.0, lambda v=value: self._auto_clear_status_error(v)
            )

    def _auto_clear_status_error(self, expected: str) -> None:
        """Clear status_error if it still matches *expected* (not replaced by newer error)."""
        self._status_error_timer = None
        if self.status_error == expected:
            self.status_error = ""

    def watch_undo_state(self, value: UndoOverlayState | None) -> None:
        try:
            w = self.query_one(UndoConfirmOverlay)
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()
                # P0-B: pause any active agent overlay countdown while undo confirm is open
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)
                        if aw.display:
                            aw.pause_countdown()
                    except NoMatches:
                        pass
            else:
                # P0-B: resume paused agent overlay countdowns when undo confirm dismisses
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)
                        if aw.display and getattr(aw, "_was_paused", False):
                            aw.resume_countdown()
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        # Disable input while overlay is open so printable keys (y/n) bubble
        # up to the app-level on_key handler instead of being typed into the field.
        try:
            inp = self.query_one("#input-area")
            if value is not None:
                inp.disabled = True
            elif not self.agent_running and not self.command_running:
                inp.disabled = False
        except NoMatches:
            pass
        # Clear pending panel ref when overlay is dismissed (including auto-cancel)
        if value is None:
            self._pending_undo_panel = None

    def on_text_area_changed(self, event: Any) -> None:
        """Update hint phase when HermesInput (TextArea-based) content changes."""
        if getattr(event, "text_area", None) is not None:
            inp = event.text_area
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")

    def on_input_changed(self, event: Any) -> None:
        """Update hint phase on input content change (typing phase detection)."""
        # Only react to the main input area, not overlay inputs
        if getattr(event, "input", None) is not None:
            inp = event.input
            if getattr(inp, "id", None) == "input-area":
                # Don't override if agent is running or overlays are active
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")

    def watch_size(self, size: Any) -> None:
        """Hide bottom-bar widgets when terminal is too short (height < 12)."""
        try:
            h = size.height
        except AttributeError:
            return
        try:
            plain_rule = self.query_one("#input-rule-bottom")
            plain_rule.display = h >= 8
        except NoMatches:
            pass
        try:
            image_bar = self.query_one(ImageBar)
            # Only hide if it was visible (has images)
            if h < 10:
                image_bar.styles.display = "none"
            elif image_bar._static_content:
                image_bar.styles.display = "block"
        except (NoMatches, AttributeError):
            pass
        try:
            hint_bar = self.query_one(HintBar)
            hint_bar.display = h >= 9
        except NoMatches:
            pass

    def watch_status_compaction_progress(self, value: float) -> None:
        if value == 0.0:
            # D2: reset context_pct so StatusBar doesn't show a stale % after compaction
            self.context_pct = 0.0
            # E4: reset both thresholds on progress return to 0
            self._compaction_warned = False
            self._compaction_warn_99: bool = getattr(self, "_compaction_warn_99", False)
            self._compaction_warn_99 = False
        try:
            self.query_one("#input-rule", TitledRule).progress = value
        except NoMatches:
            pass
        if value >= 0.9 and not self._compaction_warned:
            self._compaction_warned = True
            self._flash_hint("⚠  Context window 90% full — compaction imminent", 3.0)
        # E4: second escalated warning at 99%
        if value >= 0.99 and not getattr(self, "_compaction_warn_99", False):
            self._compaction_warn_99 = True
            self._flash_hint("⚠  Context 99% — send /compact or clear conversation", 5.0)

    def watch_voice_mode(self, value: bool) -> None:
        try:
            self.query_one(VoiceStatusBar).set_class(value, "active")
        except NoMatches:
            pass
        self._set_hint_phase("voice" if value else self._compute_hint_phase())

    def watch_voice_recording(self, value: bool) -> None:
        try:
            bar = self.query_one(VoiceStatusBar)
            if value:
                bar.update_status("● REC")
            elif self.voice_mode:
                bar.update_status("🎤 Voice mode")
        except NoMatches:
            pass

    def watch_attached_images(self, value: list) -> None:
        try:
            self.query_one(ImageBar).update_images(value)
        except NoMatches:
            pass

    def _append_attached_images(self, images: list[Path]) -> None:
        """Keep TUI image state and CLI submit payload in sync."""
        if not images:
            return
        current = list(self.attached_images)
        current.extend(images)
        self.attached_images = current
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.extend(images)

    def _clear_attached_images(self) -> None:
        self.attached_images = []
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.clear()

    def _insert_link_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        try:
            inp = self.query_one("#input-area")
        except NoMatches:
            return
        selection = getattr(inp, "selection", None)
        if hasattr(inp, "_location_to_flat") and selection is not None:
            # TextArea: convert (row,col) to flat ints for string slicing
            start = end = inp.cursor_pos
            if not selection.is_empty:
                start = inp._location_to_flat(selection.start)
                end   = inp._location_to_flat(selection.end)
        else:
            start = end = getattr(inp, "cursor_position", 0)
            if selection is not None and not selection.is_empty:
                start, end = selection.start, selection.end

        before = inp.value[:start]
        after  = inp.value[end:]
        prefix = "" if not before or before[-1].isspace() else " "
        suffix = "" if not after  or after[0].isspace()  else " "
        payload = prefix + " ".join(tokens) + suffix
        if selection is not None and not selection.is_empty:
            if hasattr(inp, "replace_flat"):
                inp.replace_flat(payload, start, end)
            elif hasattr(inp, "replace"):
                inp.replace(payload, start, end)
        else:
            inp.insert_text(payload)

    @staticmethod
    def _drop_path_display(path: Path, cwd: Path) -> str:
        """Format a dropped file path: relative if in cwd/child/parent, else absolute."""
        try:
            return path.relative_to(cwd).as_posix()
        except ValueError:
            pass
        # Check parent level with os.path.relpath
        try:
            rel = _os_mod.path.relpath(path, cwd)
        except ValueError:
            return path.as_posix()
        # Count leading ../ segments — allow single level (parent/sibling)
        depth = 0
        r = rel
        while r.startswith(".."):
            depth += 1
            r = r[3:] if len(r) > 2 else ""
        if depth <= 1:
            return rel.replace(_os_mod.sep, "/")
        return path.as_posix()

    def handle_file_drop(self, paths: list[Path]) -> None:
        """Route terminal drag-and-drop pasted paths into input bar."""
        try:
            self._handle_file_drop_inner(paths)
        except Exception:
            self._flash_hint("file drop failed — see log for details", 2.0)

    def _handle_file_drop_inner(self, paths: list[Path]) -> None:
        if any(getattr(self, attr) is not None for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")):
            self._flash_hint("file drop unavailable while prompt is open", 1.5)
            return

        cwd = self.get_working_directory()
        link_tokens: list[str] = []
        image_paths: list[Path] = []
        rejected: list[str] = []

        for path in paths:
            dropped = classify_dropped_file(path, cwd)
            if dropped.kind == "image":
                image_paths.append(path)
            elif dropped.kind in ("linkable_text", "directory"):
                link_tokens.append(format_link_token(path, cwd))
            elif dropped.kind == "unsupported_binary":
                rejected.append(dropped.reason or "unsupported file type")
            else:
                rejected.append(dropped.reason or dropped.kind)

        if image_paths:
            self._append_attached_images(image_paths)
        if link_tokens:
            self._insert_link_tokens(link_tokens)

        hint_parts: list[str] = []
        if link_tokens:
            noun = "file" if len(link_tokens) == 1 else "files"
            hint_parts.append(f"linked {len(link_tokens)} {noun}")
        if image_paths:
            noun = "image" if len(image_paths) == 1 else "images"
            hint_parts.append(f"attached {len(image_paths)} {noun}")
        if rejected:
            noun = "item" if len(rejected) == 1 else "items"
            hint_parts.append(f"dropped {len(rejected)} unsupported {noun}")

        if hint_parts:
            self._flash_hint(" · ".join(hint_parts), 1.2)

    # --- Reasoning panel helpers (called via call_from_thread) ---

    # --- Tool rendering: in _app_tool_rendering.py ---


    # --- Browse mode: in _app_browse.py ---

        # --- Theme / skin system ---

    def get_css_variables(self) -> dict[str, str]:
        """Merge ThemeManager overrides into Textual's CSS variable resolution.

        Confirmed stable: ``App.get_css_variables() -> dict[str, str]`` is
        unchanged from Textual 1.0 through 8.x.

        Variable precedence (highest → lowest):
            component_vars  >  skin vars  >  Textual defaults

        The component_vars layer enables full Component Parts theming without
        private-API hacks: ``hermes.tcss`` references ``$cursor-color`` etc.
        which ThemeManager injects here.
        """
        base = super().get_css_variables()
        # _theme_manager may not exist yet if called during super().__init__().
        # Fall back to COMPONENT_VAR_DEFAULTS so CSS vars resolve on first parse.
        tm = getattr(self, "_theme_manager", None)
        if tm is not None:
            overrides = tm.css_variables
        else:
            from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
            overrides = COMPONENT_VAR_DEFAULTS
        return {**base, **overrides}

    def apply_skin(self, skin_vars: "dict[str, str] | Path") -> None:
        """Apply a skin as CSS variable overrides.

        Accepts either a pre-built ``dict[str, str]`` of Textual CSS variable
        names, or a ``Path`` to a JSON/YAML skin file (processed via
        ``ThemeManager``).

        Skin files may include a ``component_vars`` section to theme cursor
        colour, selection colour, and other Component Part variables.

        Safe to call via ``call_from_thread``.
        """
        if isinstance(skin_vars, dict):
            self._theme_manager.load_dict(skin_vars)
        else:
            self._theme_manager.load([skin_vars])
        self._theme_manager.apply()
        # Invalidate hint cache on skin change so key-badge colors are rebuilt
        from hermes_cli.tui.widgets import _hint_cache
        _hint_cache.clear()
        # Invalidate StatusBar idle tips cache
        try:
            sb = self.query_one(StatusBar)
            sb._idle_tips_cache = None
        except NoMatches:
            pass
        try:
            from .completion_list import VirtualCompletionList
            self.query_one(VirtualCompletionList).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Completion list theme refresh failed", exc_info=True)
        try:
            from .preview_panel import PreviewPanel
            self.query_one(PreviewPanel).refresh_theme()
        except NoMatches:
            pass
        except Exception:
            logger.debug("Preview panel theme refresh failed", exc_info=True)
        from hermes_cli.tui.tool_blocks import ToolBlock
        for block in self.query(ToolBlock):
            try:
                block.refresh_skin()
            except Exception:
                logger.debug("ToolBlock theme refresh failed", exc_info=True)
        for block in self.query(StreamingCodeBlock):
            try:
                block.refresh_skin(self.get_css_variables())
            except Exception:
                logger.debug("StreamingCodeBlock theme refresh failed", exc_info=True)

    def refresh_slash_commands(self, extra: list[str] | None = None) -> None:
        """Update the slash command list after plugins are loaded.

        Call via ``call_from_thread`` if not on the event loop.

        Parameters
        ----------
        extra:
            Additional command names to append (e.g. plugin-registered commands
            that COMMAND_REGISTRY doesn't know about yet).
        """
        self._populate_slash_commands()
        if extra:
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                combined = sorted(set(inp._slash_commands) | {
                    n if n.startswith("/") else f"/{n}" for n in extra
                })
                inp.set_slash_commands(combined)
            except (NoMatches, Exception):
                pass
        # SC-08: notify HelpOverlay to refresh its cache after plugin registration
        try:
            from hermes_cli.tui.overlays import HelpOverlay as _HO
            self.query_one(_HO)._refresh_commands_cache()
        except (NoMatches, Exception):
            pass

    # --- Clipboard / selection helpers ---

    def _get_selected_text(self) -> str | None:
        """Return selected text from the screen, or None."""
        try:
            result = self.screen.get_selected_text()
            return result if result else None
        except Exception:
            return None

    # --- Slash command wiring ---

    def _populate_slash_commands(self) -> None:
        """Feed the canonical command list from COMMAND_REGISTRY into HermesInput.

        Called once on mount.  Safe to call again after plugin commands are added.
        Includes built-in commands, their aliases, and any registered skill commands.
        Excludes gateway_only commands (not actionable in TUI).
        """
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from hermes_cli.commands import COMMAND_REGISTRY, SUBCOMMANDS
            # Build full slash-name list: /name + /alias for each command
            # SC-10: exclude gateway_only commands (not actionable in TUI)
            names: list[str] = []
            for cmd in COMMAND_REGISTRY:
                if cmd.gateway_only:
                    continue
                names.append(f"/{cmd.name}")
                for alias in getattr(cmd, "aliases", []):
                    names.append(f"/{alias}")
            # B1: build descriptions dict for SlashDescPanel
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
                inp = self.query_one(_HI)
                inp.set_slash_commands(names)
                inp.set_slash_descriptions(descs)
                inp.set_slash_args_hints(args_hints)
                inp.set_slash_keybind_hints(keybind_hints)
                inp.set_slash_subcommands(dict(SUBCOMMANDS))
            except NoMatches:
                pass
        except Exception:
            pass  # Don't crash on import errors during init

    # --- Copy/paste feedback ---

    def _flash_hint(self, text: str, duration: float = 1.5) -> None:
        """Flash *text* in the HintBar for *duration* seconds, then restore.

        Reuses the existing ``HintBar.hint`` reactive — no new widgets.
        Safe to call from the event loop (e.g. from action lambdas).
        """
        try:
            bar = self.query_one(HintBar)
            # D3: cancel the previous flash timer before starting a new one.
            # Without this, rapid consecutive flashes each capture the *current*
            # bar.hint as `prior` — the second call captures the first flash's
            # text, so when the first timer fires it restores flash-1-text instead
            # of the original idle hint.  Cancelling ensures only one restore
            # callback is in flight and `prior` is captured once from idle state.
            if self._flash_hint_timer is not None:
                try:
                    self._flash_hint_timer.stop()
                except Exception:
                    pass
                self._flash_hint_timer = None
                # Restore to the pre-flash prior we saved on the *first* entry
                prior = self._flash_hint_prior
            else:
                # First flash: capture the real idle hint
                prior = bar.hint
                self._flash_hint_prior = prior
            bar.hint = text
            # Reserve the hint bar for the flash duration so _tick_spinner
            # does not overwrite the message before it expires.
            self._flash_hint_expires = _time.monotonic() + duration
            def _restore() -> None:
                self._flash_hint_timer = None
                self._flash_hint_prior = ""
                try:
                    setattr(bar, "hint", prior)
                except Exception:
                    pass
            self._flash_hint_timer = self.set_timer(duration, _restore)
        except NoMatches:
            pass

    def set_status_error(self, msg: str, auto_clear_s: float = 0.0) -> None:
        """Persistent StatusBar error. Also fires a flash hint for immediate visibility.

        Thread-safety: must be called from the event loop.
        auto_clear_s=0 → sticky until next set_status_error("") call.
        auto_clear_s>0 → auto-clears after that many seconds.
        """
        self.status_error = msg
        flash_duration = auto_clear_s if 0 < auto_clear_s <= 2.5 else 2.5
        self._flash_hint(f"⚠ {msg}", flash_duration)
        if auto_clear_s > 0:
            self.set_timer(auto_clear_s, lambda: setattr(self, "status_error", ""))

    def _copy_text_with_hint(self, text: str) -> None:
        """Copy text to clipboard with capability guard and hint flash."""
        # Keep Textual's local clipboard in sync even when we have to fall back
        # to external clipboard tools, so app-level paste actions still work.
        self._clipboard = text
        if not self._clipboard_available:
            if self._xclip_cmd:
                try:
                    import subprocess
                    subprocess.run(
                        self._xclip_cmd,
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
        self.copy_to_clipboard(text)
        self._flash_hint(f"⎘  {len(text)} chars copied", 1.2)

    # --- Context menu + clipboard: in _app_context_menu.py ---

    
    def _handle_tui_command(self, text: str) -> bool:
        """Intercept TUI-specific slash commands before agent sees them.

        Returns True if the command was handled here (do not forward to agent).
        Returns False if not a TUI command (forward to agent as normal).
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
        if stripped == "/compact":
            self.action_toggle_density()
            return True
        if stripped.startswith("/anim"):
            self._handle_anim_command(stripped)
            return True

        if stripped == "/workspace":
            self.action_toggle_workspace()
            return True

        if stripped == "/sessions":
            self.action_open_sessions()
            return True

        # SC-11: Disambiguation — bare "/tools" (no args) opens the TUI ToolsScreen overlay.
        # "/tools list", "/tools enable <name>", etc. have arguments and fall through to CLI,
        # which handles all /tools subcommands. The condition `stripped == "/tools"` ensures
        # we only intercept the no-arg form; any "/tools <subcmd>" form passes the equality
        # check false and falls through to the `return False` at the bottom.
        if stripped == "/tools":
            self._open_tools_overlay()
            return True

        # --- Overlay commands ---

        if stripped == "/help":
            self._dismiss_all_info_overlays()
            try:
                self.query_one(HelpOverlay).show_overlay()
            except NoMatches:
                pass
            return True

        if stripped == "/usage":
            agent = getattr(self.cli, "agent", None)
            if agent is None:
                self._flash_hint("⚠  No active agent — send a message first", 2.0)
                return True
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(UsageOverlay)
                overlay.refresh_data(agent)
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        if stripped == "/commands":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(CommandsOverlay)
                overlay._refresh_content()  # SC-38: always refresh on open for fresh data
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        # /model with NO args → show picker overlay; /model <name> → fall through to CLI
        if stripped == "/model":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(ModelPickerOverlay)
                overlay.refresh_data(self.cli)
                overlay.add_class("--visible")
                overlay.query_one("#mpo-list").focus()
            except NoMatches:
                pass
            return True

        # /verbose → always open picker overlay
        if stripped == "/verbose":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(VerbosePickerOverlay)
                overlay.refresh_data(self.cli)
                overlay.add_class("--visible")
                overlay.query_one("#vpo-list").focus()
            except NoMatches:
                pass
            return True

        # /yolo → always open confirmation overlay
        if stripped == "/yolo":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(YoloConfirmOverlay)
                overlay.refresh_data(self.cli)
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        # /reasoning bare → open picker; /reasoning <level|show|hide> → fall through to CLI
        if stripped == "/reasoning":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(ReasoningPickerOverlay)
                overlay.refresh_data(self.cli)
                overlay.add_class("--visible")
            except NoMatches:
                pass
            return True

        # /skin bare → open picker; /skin <name> → fall through to CLI
        if stripped == "/skin":
            self._dismiss_all_info_overlays()
            try:
                overlay = self.query_one(SkinPickerOverlay)
                overlay.refresh_data(self.cli)
                overlay.add_class("--visible")
                overlay.query_one("#spo-list").focus()
            except NoMatches:
                pass
            return True

        # --- Flash + animation commands ---

        if stripped == "/clear":
            if not self._clear_animation_in_progress:
                self._clear_animation_in_progress = True
                self._handle_clear_tui()
            return True

        cmd_parts = stripped.split()
        if cmd_parts and cmd_parts[0] == "/new":
            # Flash goes to HintWidget (bottom bar) — survives new_session() DOM reset
            self._flash_hint("✨  New session started", 2.0)
            return False  # forward to CLI for actual session creation

        if cmd_parts and cmd_parts[0] == "/title":
            if len(cmd_parts) > 1:
                self._flash_hint(f"✓  Title: {' '.join(cmd_parts[1:])}", 2.5)
            else:
                self._flash_hint("⚠  Usage: /title <name>", 2.0)
            return False  # forward to CLI for actual title set

        if cmd_parts and cmd_parts[0] == "/stop":
            self._flash_hint("⏹  Stopping processes…", 1.5)
            return False  # forward to CLI for actual stop

        # SC-12: Flash hint for bare unknown slash commands before forwarding to CLI.
        # Only fires for /word (with or without arguments) that is NOT in COMMAND_REGISTRY.
        # Commands in the registry that aren't TUI-handled (e.g. /verbose, /yolo, /profile)
        # fall through silently to the CLI agent — no false-positive flash.
        # Double-flash guard: the typing-time "Unknown command: /fragment" flash fires
        # while typing (from _show_slash_completions); this submit-time flash is
        # temporally disjoint (fires on Enter after the typing flash has expired).
        if re.match(r"^/[\w-]+", stripped):
            cmd_name = stripped.lstrip("/").split()[0]
            try:
                from hermes_cli.commands import resolve_command as _resolve_command
                in_registry = _resolve_command(cmd_name) is not None
            except Exception:
                in_registry = False
            if not in_registry:
                self._flash_hint("⚠  Unknown command — try /help for all commands", 2.0)

        return False

    @work(thread=False, group="clear")
    async def _handle_clear_tui(self) -> None:
        """Fade out MessagePanels, then delegate clear to CLI."""
        import asyncio as _asyncio
        try:
            panels = list(self.query(MessagePanel))
            for p in panels:
                p.styles.animate("opacity", value=0.0, duration=0.3)
            await _asyncio.sleep(0.35)
            self.cli.new_session(silent=True)
            if hasattr(self.cli, "_push_tui_status"):
                self.cli._push_tui_status()
            # D4: after clearing, show an empty-state hint so the panel isn't blank.
            try:
                op = self.query_one(OutputPanel)
                op.remove_children()
                from textual.widgets import Static as _Static
                op.mount(_Static(
                    "[dim]New session started — type a message to begin[/dim]",
                    classes="--empty-state-hint",
                ))
            except NoMatches:
                pass
            self._flash_hint("✨  Fresh start!", 2.0)
        finally:
            self._clear_animation_in_progress = False

    def _has_rollback_checkpoint(self) -> bool:
        """Return True if the agent has a filesystem checkpoint available."""
        try:
            return bool(getattr(self.cli.agent, "has_checkpoint", lambda: False)())
        except Exception:
            return False

    def _open_tools_overlay(self) -> None:
        """Push ToolsScreen showing the current turn's tool call timeline."""
        from hermes_cli.config import read_raw_config
        if not read_raw_config().get("display", {}).get("tools_overlay", True):
            self._flash_hint("⚠  /tools disabled in config", 2.0)
            return
        self._dismiss_all_info_overlays()
        snapshot = self.current_turn_tool_calls()
        if not snapshot:
            self._flash_hint("⚠  No tool calls in this turn", 2.0)
            return
        from hermes_cli.tui.tools_overlay import ToolsScreen
        self.push_screen(ToolsScreen(snapshot))

    def _open_anim_config(self) -> None:
        """Push the AnimConfigPanel modal screen."""
        from hermes_cli.tui.drawille_overlay import AnimConfigPanel as _ACP
        self.push_screen(_ACP())

    def _persist_anim_config(self, cfg_dict: dict) -> None:
        """Persist animation config dict to YAML config file (E5)."""
        try:
            from hermes_cli.config import read_raw_config, save_config, _set_nested, get_config_path
            config_path = get_config_path()
            if not config_path.exists():
                import logging as _logging
                _logging.getLogger(__name__).warning("Config path does not exist: %s", config_path)
                return
            cfg = read_raw_config()
            _set_nested(cfg, "display.drawille_overlay", cfg_dict)
            save_config(cfg)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("Failed to persist anim config: %s", exc)

    def _update_anim_hint(self) -> None:
        """Update _anim_hint reactive based on overlay visibility (C3)."""
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
            ov = self.query_one(_DO)
            cfg = ov._cfg
            if ov.has_class("-visible") and cfg is not None and cfg.animation == "sdf_morph":
                self._anim_hint = f"sdf: {ov.contextual_text}"
            else:
                self._anim_hint = ""
        except Exception:
            self._anim_hint = ""

    def _handle_anim_command(self, stripped: str) -> None:
        """Handle /anim subcommands (B1)."""
        from hermes_cli.tui.drawille_overlay import (
            DrawilleOverlay as _DO, AnimConfigPanel as _ACP,
            _ENGINES, _overlay_config, AnimGalleryOverlay as _AGA,
        )
        # Parse args after "/anim"
        rest = stripped[len("/anim"):].strip()
        args = rest.split() if rest else []

        if not args:
            # /anim → open gallery modal screen (B2)
            self.push_screen(_AGA())
            return

        sub = args[0].lower()

        if sub == "config":
            self._open_anim_config()
            return

        if sub == "on":
            self._anim_force = "on"
            try:
                ov = self.query_one(_DO)
                cfg = _overlay_config()
                cfg.enabled = True
                ov.show(cfg)
            except Exception:
                pass
            return

        if sub == "off":
            self._anim_force = "off"
            try:
                ov = self.query_one(_DO)
                cfg = _overlay_config()
                ov.hide(cfg)
            except Exception:
                pass
            return

        if sub == "toggle":
            if self._anim_force is None:
                self._anim_force = "on"
            elif self._anim_force == "on":
                self._anim_force = "off"
            else:
                self._anim_force = None
            self._drawille_show_hide(getattr(self, "agent_running", False))
            return

        if sub == "list":
            keys = list(_ENGINES.keys()) + ["sdf_morph"]
            try:
                from hermes_cli.tui.widgets import OutputPanel
                panel = self.query_one(OutputPanel)
                msg = panel.current_message or panel.new_message()
                from rich.text import Text as _Text
                msg._log.write(_Text("Animations: " + ", ".join(keys)))
            except Exception:
                self._flash_hint(", ".join(keys), 5.0)
            return

        if sub == "sdf":
            sdf_text = " ".join(args[1:]) if len(args) > 1 else ""
            try:
                ov = self.query_one(_DO)
                cfg = _overlay_config()
                cfg.enabled = True
                cfg.animation = "sdf_morph"
                if sdf_text:
                    cfg.sdf_text = sdf_text
                ov.animation = "sdf_morph"
                ov.show(cfg)
                # Force-show for 10s then revert
                def _revert_sdf():
                    ov.animation = _overlay_config().animation
                    self._drawille_show_hide(getattr(self, "agent_running", False))
                self.set_timer(10.0, _revert_sdf)
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
                self._flash_hint(f"Presets: {', '.join(list(_PRESETS) + ['off'])}", 4.0)
                return
            if preset_name == "off":
                self._persist_anim_config({"enabled": False})
                return
            preset_dict = _PRESETS.get(preset_name)
            if preset_dict is None:
                self._flash_hint(f"Unknown preset — try: {', '.join(_PRESETS)}", 2.5)
                return
            current_cfg = _oc()
            merged = {**_dc.asdict(current_cfg), **preset_dict}
            self._persist_anim_config(merged)
            try:
                ov = self.query_one(DrawilleOverlay)
                ov._do_hide()
                ov.show(_oc())
            except NoMatches:
                pass
            return

        # Fuzzy match engine name
        all_keys = list(_ENGINES.keys())
        clean = "".join(c for c in sub if c.isalpha()).lower()
        matched = None
        for k in all_keys:
            if clean in k.replace("_", ""):
                matched = k
                break
        if matched is None:
            self._flash_hint(f"⚠  Unknown animation: {sub}", 2.0)
            return

        try:
            ov = self.query_one(_DO)
            ov.animation = matched
            cfg = _overlay_config()
            cfg.enabled = True
            cfg.animation = matched
            ov.show(cfg)
            # Force-show for 4s then revert
            def _revert_engine():
                self._drawille_show_hide(getattr(self, "agent_running", False))
            self.set_timer(4.0, _revert_engine)
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
            # Multipart content: join text parts
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        first_line = (content or "").split("\n", 1)[0]
        # Strip markdown heading markers
        first_line = first_line.lstrip("# ").strip()
        if not first_line:
            return
        if len(first_line) > 48:
            title = first_line[:48] + "…"
        else:
            title = first_line
        # Save via worker so DB write doesn't block event loop
        @work(thread=True)
        def _save_title(self=self, db=db, session_id=session_id, title=title) -> None:
            try:
                updated = db.set_title_if_unset(session_id, title)
                if updated:
                    self.call_from_thread(setattr, self, "session_label", title)
            except Exception:
                pass
        _save_title()
        self._auto_title_done = True

    def _toggle_drawille_overlay(self) -> None:
        """Ctrl+Shift+A: dismiss overlay if visible, else show it."""
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, DrawilleOverlayCfg, _overlay_config
        try:
            overlay = self.query_one("#drawille-overlay", _DO)
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

    def _initiate_undo(self) -> None:
        if self._undo_in_progress:
            self._flash_hint("⚠  Undo in progress", 1.5)
            return
        if self.agent_running:
            self._flash_hint("⚠  Cannot undo while agent is running", 2.0)
            return
        panels = list(self.query(MessagePanel))
        if not panels:
            self._flash_hint("⚠  Nothing to undo", 1.5)
            return
        last_panel = panels[-1]
        user_text = getattr(last_panel, "_user_text", "")
        state = UndoOverlayState(
            deadline=_time.monotonic() + 10,
            response_queue=queue.Queue(),
            user_text=user_text[:80] + "…" if len(user_text) > 80 else user_text,
            has_checkpoint=self._has_rollback_checkpoint(),
        )
        self._pending_undo_panel = last_panel
        self._pending_rollback_n = 0
        self.undo_state = state

    @work(thread=False)
    async def _run_undo_sequence(self, panel: MessagePanel) -> None:
        try:
            self._undo_in_progress = True

            # Step 1: Opacity fade to signal impending removal
            panel.styles.opacity = 0.3
            await asyncio.sleep(0.4)  # wait for CSS transition (0.3s + margin)

            # Step 2: Call agent undo in a thread so event loop stays responsive
            try:
                await asyncio.to_thread(self.cli.agent.undo)
            except (AttributeError, NotImplementedError):
                self._flash_hint("⚠  Undo not supported by agent", 2.0)
                panel.styles.opacity = 1.0
                return

            # Step 3: Remove the MessagePanel from DOM (synchronous in Textual)
            panel.remove()

            # Step 4: Restore user message to HermesInput (if stored)
            user_text = getattr(panel, "_user_text", "")
            if user_text:
                try:
                    from hermes_cli.tui.input_widget import HermesInput
                    hi = self.query_one(HermesInput)
                    hi.value = user_text
                    hi.cursor_position = len(user_text)
                except NoMatches:
                    pass

            # Step 5: Feedback
            self._flash_hint("↩  Undo done", 2.0)
        finally:
            self._undo_in_progress = False

    def _initiate_retry(self) -> None:
        if self.agent_running:
            self._flash_hint("⚠  Cannot retry while agent is running", 2.0)
            return
        panels = list(self.query(MessagePanel))
        if not panels:
            self._flash_hint("⚠  Nothing to retry", 1.5)
            return
        last_user_text = getattr(panels[-1], "_user_text", "")
        if not last_user_text:
            self._flash_hint("⚠  No user message to retry", 1.5)
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            hi = self.query_one(HermesInput)
            hi.value = last_user_text
            hi.cursor_position = len(last_user_text)
            hi.action_submit()
        except NoMatches:
            pass

    def _initiate_rollback(self, text: str) -> None:
        m = re.match(r"^/rollback(?:\s+(\d+))?$", text.strip())
        if not m:
            self._flash_hint("⚠  Usage: /rollback [N]", 2.0)
            return
        n = int(m.group(1)) if m.group(1) else 0
        # Build a simple rollback state reusing UndoOverlayState
        state = UndoOverlayState(
            deadline=_time.monotonic() + 15,
            response_queue=queue.Queue(),
            user_text=f"Filesystem rollback (checkpoint {n})",
            has_checkpoint=True,
        )
        self._pending_undo_panel = None
        self._pending_rollback_n = n
        self.undo_state = state

    @work(thread=False)
    async def _run_rollback_sequence(self, n: int) -> None:
        try:
            await asyncio.to_thread(self.cli.agent.rollback, n)
            self._flash_hint("↩  Rollback done", 2.0)
        except (AttributeError, NotImplementedError):
            self._flash_hint("⚠  Rollback not supported by agent", 2.0)

    # --- Key bindings for overlays, copy, and interrupt ---

    def on_key(self, event: Any) -> None:
        """Global key handler for overlay navigation, copy, and interrupt.

        Keybinding split:
        - ctrl+c: copy selected text → cancel overlay → clear input → exit
        - ctrl+shift+c: dedicated agent interrupt (double-press = force exit)
        - escape: cancel overlay → interrupt agent
        """
        # F4: track last keypress time so _maybe_notify can skip notifying
        # when the user is actively watching the TUI.
        self._last_keypress_time = _time.monotonic()
        key = event.key

        # --- ctrl+p → path/file picker (@-completion) ---
        if key == "ctrl+p":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                inp.focus()
                inp.insert_text("@")
            except (NoMatches, Exception):
                pass
            event.prevent_default()
            return

        # --- Alt+1–9 → switch parallel session by index ---
        if key.startswith("alt+") and key[4:].isdigit() and len(key) == 5:
            n = int(key[4:]) - 1
            if n >= 0 and self._sessions_enabled:
                self._switch_to_session_by_index(n)
                event.prevent_default()
                return

        # --- undo overlay key dispatch ---
        if self.undo_state is not None:
            if event.key in ("y", "enter"):
                pending_panel = self._pending_undo_panel
                pending_n = self._pending_rollback_n
                self.undo_state = None
                self._pending_undo_panel = None
                if pending_panel is not None:
                    # Undo: run undo sequence directly (no thread/queue needed)
                    self._run_undo_sequence(pending_panel)
                else:
                    # Rollback
                    self._run_rollback_sequence(pending_n)
                event.prevent_default()
                return
            if event.key in ("n", "escape"):
                self.undo_state = None
                self._pending_undo_panel = None
                event.prevent_default()
                return

        # --- E5: Shift+X: dismiss all error banners (only when input not focused) ---
        if key == "X":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                if not inp.has_focus:
                    self.action_dismiss_all_error_banners()
                    event.prevent_default()
                    return
            except Exception:
                pass

        # --- w: toggle workspace overlay (only when input not focused) ---
        if key == "w":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)
                if inp.has_focus:
                    return  # let w type normally into input
            except NoMatches:
                pass
            self.action_toggle_workspace()
            event.prevent_default()
            return

        # --- ctrl+c: copy / cancel overlay / clear / exit ---
        if key == "ctrl+c":
            # Priority 1: copy selected text from output panels
            # (Input handles its own selection copy internally)
            selected = self._get_selected_text()
            if selected:
                self._copy_text_with_hint(selected)
                event.prevent_default()
                return

            # Priority 2: cancel active overlays (deny)
            for state_attr in ("approval_state", "clarify_state"):
                state: ChoiceOverlayState | None = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("deny")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            # Priority 3: clear input or exit (NO interrupt)
            if not self.agent_running:
                try:
                    inp = self.query_one("#input-area")
                    if hasattr(inp, "content") and inp.content:
                        inp.clear()
                    else:
                        self.exit()
                except NoMatches:
                    self.exit()
            event.prevent_default()
            return

        # --- ctrl+shift+c: dedicated agent interrupt ---
        if key == "ctrl+shift+c":
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:
                now = _time.monotonic()
                last = getattr(self, "_last_interrupt_time", 0.0)
                if now - last < 2.0:
                    # Double ctrl+shift+c within 2s → force exit
                    self.exit()
                    event.prevent_default()
                    return
                self._last_interrupt_time = now
                self.cli.agent.interrupt()
                try:
                    _out = self.query_one(OutputPanel)
                    _out.flush_live()
                except NoMatches:
                    pass
                # Show feedback
                try:
                    panel = self.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    self.log.warning("interrupt feedback: OutputPanel not available")
                except Exception as exc:
                    self.log.warning(f"interrupt feedback failed: {exc}")
                event.prevent_default()
                return

        # --- escape: cancel overlay, interrupt agent, browse mode, or enter browse ---
        if key == "escape":
            # Priority -2: dismiss info overlays (help/usage/commands/model).
            # These have no Input focus when shown (except HelpOverlay), so their
            # Binding(escape) doesn't fire — handle here instead.
            from hermes_cli.tui.overlays import ToolPanelHelpOverlay as _TPHO
            # AnimGalleryOverlay and AnimConfigPanel are ModalScreens; they handle
            # their own Escape binding via action_close → self.dismiss().
            for _cls in (HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay, WorkspaceOverlay, SessionOverlay, _TPHO):
                try:
                    _ov = self.query_one(_cls)
                    if _ov.has_class("--visible"):
                        _ov.action_dismiss() if hasattr(_ov, "action_dismiss") else _ov.remove_class("--visible")
                        event.prevent_default()
                        return
                except NoMatches:
                    pass

            # Priority -1: dismiss history search overlay (highest priority — fires
            # before completion overlay so Escape always closes the search first).
            try:
                hs = self.query_one(HistorySearchOverlay)
                if hs.has_class("--visible"):
                    hs.action_dismiss()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # Priority 0: dismiss completion overlay (before everything else so it
            # doesn't fire agent-interrupt or browse-mode on the same keystroke).
            try:
                from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
                _co = self.query_one(_CO)
                if _co.has_class("--visible"):
                    _co.remove_class("--visible")
                    _co.remove_class("--slash-only")
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # Priority 1: exit browse mode
            if self.browse_mode:
                self.browse_mode = False
                event.prevent_default()
                return

            # Priority 2: cancel active overlays (None response)
            for state_attr in ("approval_state", "clarify_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put(None)
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            # Priority 3: interrupt running agent
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:
                self.cli.agent.interrupt()
                try:
                    _out = self.query_one(OutputPanel)
                    _out.flush_live()
                except NoMatches:
                    pass
                try:
                    panel = self.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    self.log.warning("interrupt feedback: OutputPanel not available")
                except Exception as exc:
                    self.log.warning(f"interrupt feedback failed: {exc}")
                event.prevent_default()
                return

            # Priority 4: enter browse mode when idle (no overlay, agent not running).
            # No ToolHeader requirement — unified anchor list supports text-only turns.
            # D1: guard — if input has content, '[' is a typed bracket not a browse activation.
            no_overlay = all(
                getattr(self, a) is None
                for a in ("approval_state", "clarify_state", "sudo_state", "secret_state")
            )
            if no_overlay and not self.agent_running:
                _inp_value = ""
                try:
                    _inp = self.query_one("#input-area")
                    _inp_value = getattr(_inp, "value", "") or ""
                except NoMatches:
                    pass
                if not _inp_value:
                    self.browse_mode = True
                    event.prevent_default()
                    return

        # --- J/K: focus next/prev ToolPanel (Phase 3 panel nav) ---
        # Handle early — works in and out of browse mode so it doesn't fall through
        # to the "printable key exits browse mode" handler.
        if key == "J":
            self._focus_tool_panel(+1)
            event.prevent_default()
            return
        elif key == "K":
            self._focus_tool_panel(-1)
            event.prevent_default()
            return

        # --- Browse mode key handling ---
        if self.browse_mode:
            from hermes_cli.tui.tool_blocks import ToolHeader as _TH
            headers = list(self.query(_TH))
            total = max(1, len(headers))

            if key == "tab":
                self.browse_index = (self.browse_index + 1) % total
                event.prevent_default()
                return
            elif key == "shift+tab":
                self.browse_index = (self.browse_index - 1) % total
                event.prevent_default()
                return
            elif key == "enter":
                # If a ToolGroup has focus, toggle it and enter on expand
                focused = self.focused
                if focused is not None:
                    try:
                        from hermes_cli.tui.tool_group import ToolGroup as _TG
                        if isinstance(focused, _TG):
                            focused.collapsed = not focused.collapsed
                            if not focused.collapsed:
                                focused.focus_first_child()
                            event.prevent_default()
                            return
                    except Exception:
                        pass
                if headers:
                    idx = self.browse_index % len(headers)
                    parent = headers[idx].parent
                    if hasattr(parent, "toggle"):
                        parent.toggle()
                event.prevent_default()
                return
            elif key == "c":
                if headers:
                    idx = self.browse_index % len(headers)
                    h = headers[idx]
                    parent = h.parent
                    if hasattr(parent, "copy_content"):
                        self._copy_text_with_hint(parent.copy_content())
                    h.flash_copy()
                event.prevent_default()
                return
            elif key == "a":
                # Expand all collapsed panels
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.query(_TP):
                    if panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "A":
                # Collapse all expanded panels
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.query(_TP):
                    if not panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "escape":
                # Pop focus to parent ToolGroup if currently inside one
                focused = self.focused
                if focused is not None:
                    try:
                        from hermes_cli.tui.tool_group import ToolGroup as _TG, GroupBody as _GB
                        parent = getattr(focused, "parent", None)
                        if isinstance(parent, _GB):
                            grandparent = getattr(parent, "parent", None)
                            if isinstance(grandparent, _TG):
                                grandparent.focus()
                                event.prevent_default()
                                return
                    except Exception:
                        pass
                self.browse_mode = False
                event.prevent_default()
                return
            elif key == "]":
                self._jump_anchor(+1)
                event.prevent_default()
                return
            elif key == "[":
                self._jump_anchor(-1)
                event.prevent_default()
                return
            elif key == "}":
                self._jump_anchor(+1, BrowseAnchorType.CODE_BLOCK)
                event.prevent_default()
                return
            elif key == "{":
                self._jump_anchor(-1, BrowseAnchorType.CODE_BLOCK)
                event.prevent_default()
                return
            elif key == "alt+down":
                self._jump_anchor(+1, BrowseAnchorType.TURN_START)
                event.prevent_default()
                return
            elif key == "alt+up":
                self._jump_anchor(-1, BrowseAnchorType.TURN_START)
                event.prevent_default()
                return
            elif key == "m":
                self._jump_anchor(+1, BrowseAnchorType.MEDIA)
                event.prevent_default()
                return
            elif key == "M":
                self._jump_anchor(-1, BrowseAnchorType.MEDIA)
                event.prevent_default()
                return
            elif key == "backslash":
                self.call_later(self.action_toggle_minimap)
                event.prevent_default()
                return
            elif key == "T":
                self._open_tools_overlay()
                event.prevent_default()
                return
            elif event.character is not None:
                # Printable key: exit browse mode and insert the character
                self.browse_mode = False
                try:
                    inp = self.query_one("#input-area")
                    if hasattr(inp, "insert_text"):
                        inp.insert_text(event.character)
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # Overlay key handling — check each overlay in priority order
        for state_attr, widget_type in [
            ("approval_state", ApprovalWidget),
            ("clarify_state", ClarifyWidget),
        ]:
            state = getattr(self, state_attr)
            if state is not None:
                if key == "up" and state.selected > 0:
                    state.selected -= 1
                    try:
                        self.query_one(widget_type).update(state)
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "down" and state.selected < len(state.choices) - 1:
                    state.selected += 1
                    try:
                        self.query_one(widget_type).update(state)
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "enter":
                    if state.choices:
                        chosen = state.choices[state.selected]
                        state.response_queue.put(chosen)
                        setattr(self, state_attr, None)
                    event.prevent_default()
                    return

    # --- Input submission handler ---

    def on_hermes_input_submitted(self, event: Any) -> None:
        """Handle input submission from HermesInput.

        When agent is running: interrupt first, then send new message
        (except /queue and /btw which queue without interrupting).
        """
        text = event.value

        # TUI-local commands are intercepted before agent routing
        if isinstance(text, str) and self._handle_tui_command(text):
            return

        # Unknown slash commands: flash hint instead of routing to agent
        if isinstance(text, str) and text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd not in _KNOWN_SLASH_COMMANDS:
                self._flash_hint(f"Unknown command: {cmd}  (F1 for help)", 3.0)
                return

        images = list(self.attached_images)
        if images:
            self._clear_attached_images()
            payload = (text, images)
        else:
            payload = text

        # If agent is running, decide: interrupt or queue
        if self.agent_running and text:
            _cmd = text.lstrip("/").split()[0].lower() if text.startswith("/") else ""
            if _cmd in ("queue", "btw"):
                # /queue and /btw queue without interrupting
                if hasattr(self.cli, "_pending_input"):
                    self.cli._pending_input.put(payload)
                return
            # Everything else: interrupt agent, then send as new message
            # Activate thinking shimmer for the upcoming new turn
            try:
                self.query_one(ThinkingWidget).activate()
            except NoMatches:
                pass
            if hasattr(self.cli, "agent") and self.cli.agent:
                self.cli.agent.interrupt()
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(payload)
            return

        # Normal submission (agent idle)
        # Activate thinking shimmer — deactivated when first chunk arrives
        try:
            self.query_one(ThinkingWidget).activate()
        except NoMatches:
            pass
        if hasattr(self, "cli") and self.cli is not None:
            if hasattr(self.cli, "_pending_input"):
                self.cli._pending_input.put(payload)

    def on_hermes_input_files_dropped(self, event: Any) -> None:
        """Handle terminal drag-and-drop pasted paths from HermesInput."""
        self.handle_file_drop(event.paths)
