---
name: TUI mixin structure + R4 services layer (2026-04-22)
description: HermesApp MRO, services/ subpackage, mixin adapter pattern, deleted files, body_renderer split — prevents ghost imports and wrong patch targets
type: reference
originSessionId: be7a341b-8e14-4d76-b938-c12b25920470
---
## HermesApp class declaration (R4 — no mixin bases)

```python
class HermesApp(App):
```

All 10 `_app_*.py` mixin files deleted in R4. `HermesApp(App)` only. app.py is **2654 lines** (as of R5 cleanup 2026-04-23).

## RX4 lifecycle hooks

`self.hooks: AgentLifecycleHooks` — instantiated in `__init__` BEFORE R4 services. Cleanup registry for agent transitions.

- Register in `on_mount`, unregister via `hooks.unregister_owner(self)` in `on_unmount`
- Do NOT set the reactive that owns the transition inside a hook callback
- `_lc_*` methods on `HermesApp` are the Phase a callback implementations

## R4 services layer

Logic lives in `hermes_cli/tui/services/`:

| `app._svc_X` | Service class | Owns |
|---|---|---|
| `_svc_theme` | `ThemeService` | `flash_hint`, `apply_skin`, `copy_text_with_hint` |
| `_svc_spinner` | `SpinnerService` | `set_hint_phase`, `tick_spinner`, helix cache |
| `_svc_io` | `IOService` | `consume_output`, `commit_lines` |
| `_svc_tools` | `ToolRenderingService` | `_streaming_map`, `_turn_tool_calls`, `_agent_stack` |
| `_svc_browse` | `BrowseService` | `_browse_anchors`, `_browse_cursor` |
| `_svc_sessions` | `SessionsService` | `_sessions_index` |
| `_svc_context` | `ContextMenuService` | stateless |
| `_svc_commands` | `CommandsService` | `handle_tui_command`, `handle_layout_command` |
| `_svc_watchers` | `WatchersService` | `handle_file_drop`, all `on_X(value)` watcher bodies |
| `_svc_keys` | `KeyDispatchService` | `dispatch_key`, `dispatch_input_submitted` |

### Method naming rules
- `watch_X` stays on mixin (Textual calls by name); service gets `on_X(value)`
- Textual event handlers (`on_key`, `on_hermes_input_submitted`) stay on mixin; service gets `dispatch_X(event)`
- Private adapters: `# DEPRECATED: remove in Phase 3`
- Public permanent API (`handle_file_drop`, `flush_output`): no DEPRECATED comment

### `_flash_hint` exception
`_ThemeMixin._flash_hint` routes via **`FeedbackService`** (RX1), NOT `_svc_theme.flash_hint()`. Never change this routing. To test flash in tests, patch `app.feedback.flash` or `app._flash_hint` — NOT `app._svc_theme.flash_hint`.

### Backward-compat @property proxies on App
- `app._turn_tool_calls` → `app._svc_tools._turn_tool_calls`
- `app._streaming_map` → `app._svc_tools._streaming_map`

## DEPRECATED forwarder stub status (R5, 2026-04-23)

**64 DEPRECATED markers remain in app.py** — all have live external callers in services/ or tests/. Do NOT delete without migrating callers first.

11 zero-caller stubs deleted in commit 864ac9fe: `_cell_width`, `_input_bar_width`, `_next_spinner_frame`, `_helix_width`, `_helix_spinner_frame`, `_build_helix_frames`, `_mount_minimap_default`, `_append_attached_images`, `_insert_link_tokens`, `_drop_path_display`, `_handle_file_drop_inner`.

Next step to reduce further: migrate callers in services/ and tests/ to call `self.app._svc_X.method()` directly, then delete the stub.

## Body renderer split

`body_renderer.py` **deleted**. Two systems, do not unify APIs:

**Streaming (live tool execution):**
- Module: `hermes_cli.tui.body_renderers.streaming`
- Base: `StreamingBodyRenderer` (was `BodyRenderer` — renamed to avoid clash)
- Factory: `StreamingBodyRenderer.for_category(ToolCategory)`
- Methods: `render_stream_line()`, `finalize()`, `render_diff_line()`, `highlight_line()`

**Post-hoc (ToolPanel rich rendering):**
- Module: `hermes_cli.tui.body_renderers` (ABC)
- Base: `BodyRenderer` (ABC, `body_renderers/base.py`)
- Factory: `pick_renderer(cls_result, payload)`
- Methods: `can_render()`, `build()`, `build_widget()`

**Wrong import (will fail):** `from hermes_cli.tui.body_renderer import BodyRenderer`  
**Correct:** `from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer`
