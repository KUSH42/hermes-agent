# Slash Command TUI Integration

**Status:** Draft
**Priority:** P1
**Branch:** `feat/textual-migration`
**Goal:** Wire all slash commands to produce native TUI output instead of flat ANSI text dumped into the output panel.

---

## 1. Problem

The TUI currently intercepts only 5 commands (`/undo`, `/retry`, `/rollback`, `/compact`, `/anim`) in `_handle_tui_command()`. Every other slash command falls through to the CLI's `process_command()`, which emits text via `_cprint()` / `ChatConsole().print()` / raw `print()`. This output arrives as flat ANSI lines in the output panel — no structure, no interactivity, no theming consistency.

Four tiers of broken:

| Tier | Issue | Affected Commands |
|------|-------|-------------------|
| **Missing handler** | `/commands` defined in registry but has NO `process_command` handler — falls through to agent as raw message | `/commands` |
| **Broken output** | Raw `print()` bypasses TUI output queue — invisible or garbled in TUI | `/tools` (no args) |
| **Flat** | `_cprint` works but produces unstructured flat text, no TUI affordances | `/help`, `/usage`, `/config`, `/model`, `/skills`, `/plugins`, `/platforms`, `/reasoning`, `/personality`, `/prompt`, `/cron`, `/tools list`, `/toolsets`, `/status`, `/profile`, `/insights`, `/compress`, `/queue`, `/title`, `/resume`, `/branch`, `/save`, `/stop`, `/background`, `/btw`, `/skin`, `/voice`, `/effects`, `/browser`, `/history` |
| **No visual feedback** | Functional but no flash hint or animation | `/clear` (works via `out.erase_screen()` but no fade animation), `/new` (works via `self.new_session()` but no confirmation hint) |

**Note:** `_show_recent_sessions()` (used by `/history`) uses raw `print()` for its table — this renders correctly because it runs in the CLI thread before the TUI takes over the output. However, it bypasses the TUI output queue and may render inconsistently with themed output. Phase 1 converts it to `_cprint` for consistency.

---

## 2. Architecture

### 2.1 Overlay Pattern (browsing/reference)

Reuse existing overlay pattern from `KeymapOverlay` / `HistorySearchOverlay`:

```python
class InfoOverlay(Widget):
    DEFAULT_CSS = """
    InfoOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 24;
        width: 1fr;
        margin: 0 1;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    InfoOverlay.--visible { display: block; }
    """
    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("q", "dismiss", priority=True),
    ]
```

Each command that produces browsable output gets a dedicated overlay widget. Overlay is shown by adding `--visible` class, dismissed by removing it.

**Overlay lifecycle rules:**
- All info overlays auto-dismiss when agent starts running (`watch_agent_running(True)` removes `--visible` from all overlays). Prevents stale info blocking the output view. Add to the `if value:` branch of `watch_agent_running` in `app.py`:
  ```python
  if value:
      self._dismiss_all_info_overlays()
      ...  # existing chevron / metric reset code
  ```
- Only ONE info overlay visible at a time. Opening a new one dismisses the previous. `_dismiss_all_info_overlays()` is a method on `HermesApp` (not a local function) so it can also be called from `watch_agent_running`. See §4.3 for implementation.
- Overlays on `layer: overlay` stack with existing overlays (CompletionOverlay, UndoConfirmOverlay, KeymapOverlay, HistorySearchOverlay). No z-index conflicts because info overlays are dismissable and only one visible at a time.
- Overlays do NOT consume input when hidden (`display: none`). When visible, they intercept keys via priority bindings.
- All overlay classes are imported at the top of `app.py` (same as `HistorySearchOverlay` at line 74) — no deferred imports needed.

### 2.2 Flash Pattern (quick feedback)

For commands that produce 1-3 lines of feedback, use `_flash_hint()` on `HermesApp`:

```python
self._flash_hint("✓  Session title set: my-session", 2.5)
```

Already works for `/statusbar`, `/queue`, `/verbose`, `/yolo`. Extend to:
- `/title` — confirm title set (flash from TUI intercept, not CLI handler)
- `/stop` — confirm processes killed (flash from TUI intercept)
- `/new` — "New session started" (flash BEFORE forwarding to CLI so user sees it)
- `/clear` — "✨  Fresh start!" after fade animation

**Flash from CLI handlers:** For commands that MUST run in the CLI (e.g., `/save` writes a file), the CLI handler can flash via `_hermes_app._flash_hint()` if `_hermes_app is not None`. Pattern already exists in `cli.py` — see `_push_tui_status()`.

### 2.3 Animation Pattern (visual feedback)

For `/clear` — fade-out existing messages, then reset:

```python
@work(thread=False, group="clear")
async def _handle_clear_tui(self) -> None:
    """Fade out messages, then clear and reset.

    Uses @work(thread=False) consistent with _run_undo_sequence pattern.
    group="clear" ensures only one runs at a time (Textual cancels the
    previous worker in the group before starting the new one).
    _clear_animation_in_progress flag prevents _handle_tui_command from
    firing a new worker while animation runs; released in finally block.
    """
    try:
        panels = list(self.query(MessagePanel))
        for p in panels:
            p.styles.animate("opacity", value=0.0, duration=0.3)
        await asyncio.sleep(0.35)
        # Delegate actual clear directly — don't re-enter _handle_tui_command
        self.cli.new_session(silent=True)
        if hasattr(self.cli, "_push_tui_status"):
            self.cli._push_tui_status()
        self._flash_hint("✨  Fresh start!", 2.0)
    finally:
        self._clear_animation_in_progress = False  # always release guard
```

**Init flag:** Add `self._clear_animation_in_progress: bool = False` in `HermesApp.__init__` (or `on_mount`). Not in the worker — flag must exist before the first `/clear`.

**Why `@work` not `run_worker(coro)`:** Codebase uses `@work(thread=False)` for async workers (see `_run_undo_sequence`). `run_worker(coro)` also works in Textual 8.2.3 but inconsistent. The decorator form is canonical here.

**Why `finally`:** If animation raises (e.g. widget removed mid-fade), flag is still released so next `/clear` isn't permanently locked.

---

## 3. Command → TUI Mapping

### Phase 1: Fix broken and missing

| Command | Current | Fix |
|---------|---------|-----|
| `/commands` | No handler in `process_command` — falls through to agent | Add handler + wire to `CommandsOverlay` (Phase 2) |
| `/tools` (no args) | Raw `print()` with ASCII box in `show_tools()` | Convert to `_cprint` + `ChatConsole().print()` |
| `/history` (`_show_recent_sessions`) | Raw `print()` table | Convert to `_cprint` for TUI consistency |

### Phase 2: TUI overlay for high-value commands

| Command | Overlay Widget | Content |
|---------|---------------|---------|
| `/help` | `HelpOverlay` | Categorized command list with filter/search. Command names as Static text (not clickable — too complex for v1, keyboard shortcut hints shown instead) |
| `/usage` | `UsageOverlay` | Token usage table with context bar, cost, rate limits |
| `/commands` | `CommandsOverlay` | Paginated browse of all commands + skills. Reuse `gateway_help_lines()` for content. `process_command` handler added in Phase 1 renders via this overlay in TUI mode |
| `/model` (no args) | `ModelOverlay` | Provider list with current model highlighted, keyboard-selectable. `/model <name>` with args still falls through to CLI handler for actual switching |

### Phase 3: Flash hints for quick-feedback commands

| Command | Flash Message | Notes |
|---------|--------------|-------|
| `/title` | `"✓  Title: {title}"` or `"⚠  Usage: /title <name>"` | Flash from TUI intercept before forwarding |
| `/new` | `"✨  New session started"` | Flash from TUI intercept before forwarding to CLI |
| `/clear` | Fade animation → `"✨  Fresh start!"` | TUI intercept handles animation; delegates to CLI after |
| `/stop` | `"⏹  Stopped {n} process(es)"` | Flash from TUI intercept |

**Excluded from Phase 3:**
- `/queue` — already works via `_flash_hint` in existing code
- `/save` — CLI handler does file I/O, can't predict path before execution. Flash from CLI handler via `_hermes_app._flash_hint()` after save completes (follow existing `_push_tui_status` pattern).

### Phase 4: Structured output for info commands

Replace flat `_cprint` tables with themed output using `ChatConsole().print()` with Rich markup:

| Command | Enhancement |
|---------|------------|
| `/config` | Group by section, dim defaults, highlight overrides |
| `/status` | Structured card with model, tokens, context bar |
| `/plugins` | Status icons, grouped by enabled/disabled |
| `/platforms` | Status indicators (connected/disconnected) |
| `/tools list` | Grouped by toolset, enabled/disabled icons |
| `/toolsets` | Tool counts, enabled status |
| `/profile` | Clean card layout |
| `/skills` | Search results with install status |

### Phase 5: Interactive overlays for management commands

| Command | Overlay Type |
|---------|-------------|
| `/skin` | Grid of skin previews with live-switch on select |
| `/reasoning` | Slider/config overlay |
| `/personality` | List overlay with preview |
| `/prompt` | Editor overlay for custom system prompt |

---

## 4. Implementation Details

### 4.1 HelpOverlay

```python
class HelpOverlay(Widget):
    """Slash command reference. Toggle with /help; dismiss with Esc/q."""

    DEFAULT_CSS = """
    HelpOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 30;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    HelpOverlay.--visible { display: block; }
    HelpOverlay > #help-content {
        height: auto;
        max-height: 26;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("q", "dismiss", priority=True),
        # NOTE: "/" NOT bound here — would conflict with slash command input.
        # Filtering uses the Input widget's own on_changed handler.
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter commands...", id="help-search")
        yield Vertical(id="help-content")

    def on_mount(self):
        from hermes_cli.commands import COMMANDS_BY_CATEGORY
        self._commands_cache: list[tuple[str, str, str]] = [
            (cat, f"/{cmd}", desc)
            for cat, cmds in COMMANDS_BY_CATEGORY.items()
            for cmd, desc in cmds.items()
        ]
        self._populate(self._commands_cache)

    def show_overlay(self) -> None:
        """Show overlay and focus the filter input. Matches HistorySearchOverlay.show_overlay() pattern."""
        self.add_class("--visible")
        self.query_one("#help-search", Input).focus()

    def _populate(self, entries: list[tuple[str, str, str]]) -> None:
        """Rebuild content list. Uses single batched mount() to avoid per-item repaint."""
        container = self.query_one("#help-content", Vertical)
        container.remove_children()
        children: list[Static] = []
        current_cat = None
        for cat, cmd, desc in entries:
            if cat != current_cat:
                children.append(Static(f"── {cat} ──", classes="category-header"))
                current_cat = cat
            children.append(Static(f"  [bold]{cmd}[/bold]  {desc}"))
        if children:
            container.mount(*children)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter commands as user types. Uses cached list — no re-import per keystroke."""
        query = event.value.lower().strip()
        if not query:
            self._populate(self._commands_cache)
            return
        filtered = [
            (cat, cmd, desc) for cat, cmd, desc in self._commands_cache
            if query in cmd.lower() or query in desc.lower()
        ]
        self._populate(filtered)

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass
```

**Design decisions:**
- No `HelpEntry` subclass — uses `Static` widgets with Rich markup. Simpler, fewer classes.
- No `/` key binding — would conflict with slash command input in HermesInput. Filtering handled by `Input.on_changed`.
- No clickable commands — v1 uses keyboard only. User reads help, dismisses overlay, types command.
- `on_input_changed` filters against `_commands_cache` — no debounce needed (list <50 entries), no re-import per keystroke.
- `_populate` batches with `container.mount(*children)` — single DOM operation instead of one-per-entry; prevents per-item repaint on filter.
- `show_overlay()` follows `HistorySearchOverlay.show_overlay()` pattern — caller uses this instead of `add_class("--visible")` directly so focus is always set.
- `action_dismiss` restores focus to `HermesInput` — matches pattern in `widgets.py:3562` and `:3643`.

### 4.2 UsageOverlay

```python
class UsageOverlay(Widget):
    """Token usage and rate limit display. Toggle with /usage."""

    DEFAULT_CSS = """
    UsageOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 20;
        width: 1fr;
        max-width: 60;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    UsageOverlay.--visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("q", "dismiss", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="usage-content")

    def refresh_data(self, agent) -> None:
        """Pull current usage from agent, update display.

        Data sources (verified against cli.py §_show_usage and §_snapshot_status):
          agent.session_input_tokens, session_output_tokens,
          session_cache_read_tokens, session_cache_write_tokens,
          session_total_tokens, session_api_calls, agent.model
          agent.context_compressor.last_prompt_tokens, .context_length, .compression_count
          agent.get_rate_limit_state() → RateLimitState | None

        Correct imports (verified against cli.py top-level imports):
          from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
          from agent.rate_limit_tracker import format_rate_limit_display  (conditional on rl_state.has_data)

        Formats into aligned columns via Rich Text on the inner Static.
        """
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
        input_tokens = getattr(agent, "session_input_tokens", 0) or 0
        output_tokens = getattr(agent, "session_output_tokens", 0) or 0
        cache_read = getattr(agent, "session_cache_read_tokens", 0) or 0
        cache_write = getattr(agent, "session_cache_write_tokens", 0) or 0
        total = getattr(agent, "session_total_tokens", 0) or 0
        calls = getattr(agent, "session_api_calls", 0) or 0
        compressor = getattr(agent, "context_compressor", None)
        last_prompt = getattr(compressor, "last_prompt_tokens", 0) if compressor else 0
        ctx_len = getattr(compressor, "context_length", 0) if compressor else 0
        pct = min(100, last_prompt / ctx_len * 100) if ctx_len else 0
        compressions = getattr(compressor, "compression_count", 0) if compressor else 0
        cost_result = estimate_usage_cost(
            agent.model,
            CanonicalUsage(
                input_tokens=input_tokens, output_tokens=output_tokens,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )
        lines = [
            f"[bold]Model:[/bold] {agent.model}",
            f"Input:        {input_tokens:>12,}",
            f"Cache read:   {cache_read:>12,}",
            f"Cache write:  {cache_write:>12,}",
            f"Output:       {output_tokens:>12,}",
            f"Total tokens: {total:>12,}",
            f"API calls:    {calls:>12,}",
        ]
        if cost_result.amount_usd is not None:
            prefix = "~" if cost_result.status == "estimated" else ""
            lines.append(f"Cost:     {prefix}${float(cost_result.amount_usd):>12.4f}")
        elif cost_result.status == "included":
            lines.append("Cost:         included")
        rl_state = agent.get_rate_limit_state() if hasattr(agent, "get_rate_limit_state") else None
        if rl_state and getattr(rl_state, "has_data", False):
            from agent.rate_limit_tracker import format_rate_limit_display
            lines.append("")
            lines.append(format_rate_limit_display(rl_state))
        lines += [
            "",
            f"Context: {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)",
            f"Compressions: {compressions}",
        ]
        self.query_one("#usage-content", Static).update("\n".join(lines))

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass
```

**Design decisions:**
- `compose()` yields an inner `Static` for the content — `refresh_data()` updates it in-place without rebuilding DOM.
- `refresh_data()` called every time overlay is shown (not cached) — ensures fresh data.
- Imports verified against `cli.py §_show_usage` (lines 6536–6620): `CanonicalUsage`/`estimate_usage_cost` from `agent.usage_pricing`; `format_rate_limit_display` from `agent.rate_limit_tracker` (conditional).
- `width: 1fr` not `width: auto` — `auto` can collapse to 0 before content loads on a docked overlay.
- `action_dismiss` restores focus to `HermesInput` — consistent with `KeymapOverlay.action_dismiss` pattern.

### 4.3 Intercept in `_handle_tui_command`

```python
def _dismiss_all_info_overlays(self) -> None:
    """Remove --visible from all info overlays. Called before showing a new one
    and from watch_agent_running(True). Defined as a method (not a local fn)
    so it's accessible from watch_agent_running.

    HelpOverlay/UsageOverlay/etc. are imported at the top of app.py alongside
    HistorySearchOverlay — no deferred import needed here.
    """
    for cls in (HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay):
        try:
            self.query_one(cls).remove_class("--visible")
        except NoMatches:
            pass

def _handle_tui_command(self, text: str) -> bool:
    stripped = text.strip()

    # Existing
    if stripped == "/undo": ...
    if stripped == "/retry": ...
    if re.match(r"^/rollback(\s+\d+)?$", stripped): ...
    if stripped == "/compact": ...
    if stripped == "/anim": ...

    # --- Overlay commands ---
    # Note: HelpOverlay/UsageOverlay/etc. imported at top of app.py (same as
    # HistorySearchOverlay) — no deferred imports needed here.

    if stripped == "/help":
        self._dismiss_all_info_overlays()
        self.query_one(HelpOverlay).show_overlay()  # sets focus on search input
        return True

    if stripped == "/usage":
        agent = getattr(self.cli, "agent", None)
        if agent is None:
            self._flash_hint("⚠  No active agent — send a message first", 2.0)
            return True
        self._dismiss_all_info_overlays()
        overlay = self.query_one(UsageOverlay)
        overlay.refresh_data(agent)
        overlay.add_class("--visible")
        return True

    if stripped == "/commands":
        self._dismiss_all_info_overlays()
        self.query_one(CommandsOverlay).add_class("--visible")
        return True

    # /model with NO args → overlay; /model <name> → fall through to CLI
    if stripped == "/model":
        self._dismiss_all_info_overlays()
        self.query_one(ModelOverlay).add_class("--visible")
        return True
    # "/model " with space + args → don't intercept, let CLI handle

    # --- Flash + animation commands ---

    if stripped == "/clear":
        if not self._clear_animation_in_progress:
            self._clear_animation_in_progress = True
            self._handle_clear_tui()  # @work(thread=False, group="clear") — see §2.3
        return True

    cmd_parts = stripped.split()
    if cmd_parts and cmd_parts[0] == "/new":
        # Flash fires to HintWidget (bottom bar) — survives session reset.
        # new_session() does NOT clear the bottom bar, only MessagePanels.
        # Flash fires before forwarding; CLI's new_session() runs after.
        self._flash_hint("✨  New session started", 2.0)
        return False  # forward to CLI for actual session creation

    if cmd_parts and cmd_parts[0] == "/title":
        # Flash confirmation — CLI handler does the actual title set
        if len(cmd_parts) > 1:
            self._flash_hint(f"✓  Title: {' '.join(cmd_parts[1:])}", 2.5)
        else:
            self._flash_hint("⚠  Usage: /title <name>", 2.0)
        return False  # forward to CLI

    if cmd_parts and cmd_parts[0] == "/stop":
        self._flash_hint("⏹  Stopping processes…", 1.5)
        return False  # forward to CLI for actual stop

    return False
```

**Key decisions:**
- `_dismiss_all_info_overlays()` is a method on `HermesApp`, not a local function — accessible from `watch_agent_running`.
- `/help` calls `show_overlay()` which sets focus on the search `Input`; other overlays that have no Input just call `add_class("--visible")`.
- `/model` exact match only — `"/model "` with args falls through to CLI handler.
- `/clear` calls `self._handle_clear_tui()` (worker decorated with `@work(thread=False, group="clear")` — see §2.3), not `run_worker(coro)`.
- `/new` flash lives in `HintWidget` (bottom bar), not output panel — survives `new_session()` DOM clear.
- `/new`, `/title`, `/stop` return `False` — CLI handler still runs for actual state changes.

### 4.4 Fix raw `print()` calls

**`show_tools()`** (cli.py ~4200): Replace all `print()` with `_cprint()` / `ChatConsole().print()`:

```python
def show_tools(self):
    tools = get_tool_definitions(enabled_toolsets=self.enabled_toolsets, quiet_mode=True)
    if not tools:
        _cprint("  (;_;) No tools available")
        return
    _cprint("")
    _cprint("  (^_^)/ Available Tools")
    _cprint(f"  {'─' * 40}")
    toolsets = {}
    for tool in sorted(tools, key=lambda t: t["function"]["name"]):
        name = tool["function"]["name"]
        toolset = get_toolset_for_tool(name) or "unknown"
        if toolset not in toolsets:
            toolsets[toolset] = []
        desc = tool["function"].get("description", "").split("\n")[0]
        if ". " in desc:
            desc = desc[:desc.index(". ") + 1]
        toolsets[toolset].append((name, desc))
    for toolset in sorted(toolsets.keys()):
        _cprint(f"  [{toolset}]")
        for name, desc in toolsets[toolset]:
            ChatConsole().print(f"    [bold {_accent_hex()}]{name:<20}[/] {_escape(desc)}")
        _cprint("")
    _cprint(f"  Total: {len(tools)} tools  ヽ(^o^)ノ")
```

**`_show_recent_sessions()`** (cli.py ~4406): Same pattern — replace `print()` with `_cprint()`.

---

## 5. Testing

### New test files:
- `tests/tui/test_help_overlay.py` — open, filter, dismiss
- `tests/tui/test_usage_overlay.py` — data refresh, display formatting
- `tests/tui/test_commands_overlay.py` — content, pagination
- `tests/tui/test_model_overlay.py` — provider display, selection
- `tests/tui/test_tui_command_intercept.py` — all commands route correctly, overlay stacking, flash hints

### Pilot test note: CompletionOverlay interference

Typing `/` into `HermesInput` activates SLASH_COMMAND completion mode (`completion_context.py`). In Pilot tests, character-by-character pressing will trigger the completion overlay, and `enter` may select a completion item rather than submit the raw text.

**Pattern to avoid this in all slash-command tests:** Set `inp.value` directly and call `inp.action_submit()`, bypassing the completion cycle:

```python
from hermes_cli.tui.input_widget import HermesInput

async def _submit_command(pilot, app, cmd: str) -> None:
    inp = app.query_one(HermesInput)
    inp.value = cmd
    inp.action_submit()
    await pilot.pause()
```

Use this helper in all tests below instead of `pilot.press()` sequences.

### Test patterns (reuse from existing overlay tests):
```python
async def test_help_overlay_opens_on_slash_help():
    """Typing /help should show HelpOverlay with --visible class."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        overlay = app.query_one(HelpOverlay)
        assert overlay.has_class("--visible")

async def test_help_overlay_dismiss_on_escape():
    """Opening overlay then pressing Escape should hide it."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        overlay = app.query_one(HelpOverlay)
        assert overlay.has_class("--visible")
        await pilot.press("escape")
        assert not overlay.has_class("--visible")

async def test_help_overlay_focus_set_on_open():
    """show_overlay() should move keyboard focus to the search Input."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        search = app.query_one("#help-search", Input)
        assert search.has_focus

async def test_help_overlay_filter():
    """Typing in search Input should filter commands."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        # search input already focused via show_overlay()
        search = app.query_one("#help-search", Input)
        search.value = "model"
        await pilot.pause()
        content = app.query_one("#help-content", Vertical)
        children = list(content.query(Static))
        command_lines = [c for c in children if "/model" in str(getattr(c, 'renderable', ''))]
        assert len(command_lines) > 0

async def test_help_filter_empty_restores_all():
    """Clearing the filter Input should show all commands."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        search = app.query_one("#help-search", Input)
        search.value = "model"
        await pilot.pause()
        filtered_count = len(list(app.query_one("#help-content", Vertical).query(Static)))
        search.value = ""
        await pilot.pause()
        full_count = len(list(app.query_one("#help-content", Vertical).query(Static)))
        assert full_count > filtered_count

async def test_single_overlay_visible_at_a_time():
    """Opening /help then /usage should dismiss help, show usage."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        assert app.query_one(HelpOverlay).has_class("--visible")
        await _submit_command(pilot, app, "/usage")
        assert not app.query_one(HelpOverlay).has_class("--visible")
        assert app.query_one(UsageOverlay).has_class("--visible")

async def test_overlays_dismiss_on_agent_start():
    """All info overlays should auto-dismiss when agent starts running."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/help")
        assert app.query_one(HelpOverlay).has_class("--visible")
        # Simulate agent start — set reactive, then pause for watcher to fire
        app.agent_running = True
        await pilot.pause()
        assert not app.query_one(HelpOverlay).has_class("--visible")

async def test_model_with_args_falls_through_to_cli():
    """/model claude-sonnet-4 should NOT show ModelOverlay."""
    async with app.run_test() as pilot:
        await _submit_command(pilot, app, "/model claude-sonnet-4")
        overlay = app.query_one(ModelOverlay)
        assert not overlay.has_class("--visible")

async def test_help_dismiss_restores_focus_to_input():
    """Dismissing HelpOverlay should return focus to HermesInput."""
    async with app.run_test() as pilot:
        from hermes_cli.tui.input_widget import HermesInput
        await _submit_command(pilot, app, "/help")
        await pilot.press("escape")
        inp = app.query_one(HermesInput)
        assert inp.has_focus

async def test_commands_has_cli_handler():
    """/commands should not fall through to agent as raw message."""
    from hermes_cli.commands import resolve_command
    canonical = resolve_command("commands")
    assert canonical is not None
    # Verify process_command has a handler for "commands"
    # (This test ensures Phase 1 work is done)
```

### Existing tests to update:
- `tests/tui/test_integration.py` — verify new command routing doesn't break existing flows
- `tests/tui/test_tool_blocks.py` — ensure no regressions from `_handle_tui_command` changes

---

## 6. Files to Modify

| File | Changes |
|------|---------|
| `hermes_cli/tui/app.py` | (1) Top-level import: `from hermes_cli.tui.overlays import HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay` (alongside existing `from hermes_cli.tui.widgets import HistorySearchOverlay` at line 74). (2) Init: add `self._clear_animation_in_progress: bool = False`. (3) `compose()`: yield new overlays alongside existing ones (see below). (4) `watch_agent_running`: call `self._dismiss_all_info_overlays()` in the `if value:` branch. (5) Add `_dismiss_all_info_overlays()` method. (6) Extend `_handle_tui_command()`. (7) Add `_handle_clear_tui()` `@work` worker. |
| `hermes_cli/tui/overlays.py` (NEW) | `HelpOverlay`, `UsageOverlay`, `CommandsOverlay`, `ModelOverlay` classes. Separate from `widgets.py` (already 4000+ lines). |
| `cli.py` | Add `elif canonical == "commands":` handler in `process_command`; fix `show_tools()` raw `print()` → `_cprint`; fix `_show_recent_sessions()` raw `print()` → `_cprint`. |
| `hermes_cli/model_switch.py` | No changes — `ModelOverlay` reads provider/model data self-contained. |
| `hermes_cli/tui/hermes.tcss` | Only if `DEFAULT_CSS` is insufficient. `$surface`/`$primary` are Textual built-in design tokens — no declaration needed. |
| `tests/tui/` | New test files per §5. |

### `compose()` additions (app.py)

Current compose block at lines 390–391 yields `HistorySearchOverlay` and `KeymapOverlay`. Add after them:

```python
yield HistorySearchOverlay(id="history-search")
yield KeymapOverlay(id="keymap-help")
# --- Info overlays (Phase 1-4) ---
yield HelpOverlay(id="help-overlay")
yield UsageOverlay(id="usage-overlay")
yield CommandsOverlay(id="commands-overlay")
yield ModelOverlay(id="model-overlay")
```

### `watch_agent_running` addition (app.py)

In the `if value:` branch, first line:

```python
def watch_agent_running(self, value: bool) -> None:
    self._drawille_show_hide(value)
    if value:
        self._dismiss_all_info_overlays()  # ← add this
        self._response_metrics_active = False
        ...  # existing code unchanged
```

---

## 7. Open Questions

1. **`overlays.py` vs `widgets.py`?** — Resolved: new `overlays.py` module. `widgets.py` is 4000+ lines, adding 4 overlay classes would push it further.

2. **Clickable commands in /help?** — Resolved: no for v1. Static text with keyboard shortcut hints. Click handling adds complexity for marginal gain (user still needs to dismiss overlay).

3. **`/model` overlay provider switching?** — Resolved: overlay shows current state only. Actual switching falls through to CLI handler (complex async provider auth logic stays in `model_switch.py`).

4. **Phase 5 priority?** — Deferred. Interactive overlays (skin preview, prompt editor, personality picker) are high-effort, lower priority. Ship Phase 1-4 first, gather feedback.

5. **`_show_recent_sessions` rendering in TUI?** — The raw `print()` table actually renders correctly because it runs in the CLI thread. However, it bypasses the TUI output queue and may not respect skin theming. Phase 1 converts to `_cprint` for consistency. Low priority if table looks fine as-is.

6. **Overlay dismissal edge cases?** — What if user opens `/help`, then starts typing a message? Answer: `on_hermes_input_submitted` fires, message goes to agent, `watch_agent_running(True)` auto-dismisses overlay. No manual dismissal needed.

7. **`/commands` vs `/help` overlap?** — `/help` = all built-in commands (from `COMMANDS_BY_CATEGORY`). `/commands` = gateway-filtered commands + skills + plugins (from `gateway_help_lines()` which returns `list[str]`, each a pre-formatted `` `/cmd args` -- description `` line). `CommandsOverlay` renders these as `Static` widgets — no further parsing needed. Different content, different use cases.

8. **`/new` flash timing** — Flash goes to `HintWidget` (bottom bar), not the output panel. `new_session()` in `cli.py` clears `MessagePanel`s but does not touch the bottom bar. Flash will be visible for its full duration even after session reset. No timing fix needed.

9. **TCSS `$surface`/`$primary` vars** — These are Textual built-in design tokens, not custom vars. No declaration in `hermes.tcss` required. The `reference_tcss_variable_gotcha.md` only applies to *custom* `$var-name` refs not in the default palette.
