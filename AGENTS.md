# Hermes Agent - Development Guide

Instructions for AI coding assistants and developers working on the hermes-agent codebase.

## Project memory

For durable project-specific context that should survive across sessions, use
`~/.hermes/project-memory.md` as the primary memory file.

Keep `docs/project-memory.md` as the repo-local mirror for important project
context that should travel with the repository.

For Codex sessions, also keep
`~/.codex/memories/hermes-agent-project-memory.md` synchronized with the same
project-memory index so the same durable context is available outside this
repository checkout.

## Project Directory

```bash
cd ~/.hermes/hermes-agent
```

## Development Environment

```bash
source venv/bin/activate  # ALWAYS activate before running Python
```

## Additional workflow rules

### Commit and PR language

- Never mention `Claude` or `Claude Code` in git commit messages or pull
  request text.

### Skills

- Before installing any Claude-oriented skill from an external source, scan it
  with Snyk Agent Scan first. Do not install it unless the scan returns safe.
- After every implementation that touches TUI code, update the
  `tui-development` skill files before closing the task:
  `skills/tui-development/SKILL.md` and any relevant reference files inside
  that skill directory. When syncing from the source skill, copy-replace from
  `~/.claude/skills/tui-development/` into the repo-local skill directory.
- TUI skill updates must capture reusable details such as new APIs or methods,
  changed behavior, gotchas hit during implementation, non-obvious test
  patterns, module-level constants or maps, changed dispatch logic,
  Rich/Textual API quirks, and mocking patterns.
- Update memory files under `~/.claude/projects/.../memory/` when a TUI change
  creates durable project context, including spec entries and reusable feedback
  entries. Mirror the resulting memory index into `~/.hermes/project-memory.md`,
  `docs/project-memory.md`, and
  `~/.codex/memories/hermes-agent-project-memory.md`.

### Agents / subagents

- Do not spawn Agent tool subagents unless the user explicitly approves it in
  the current turn. Describe the plan and ask first.
- If subagents are approved, keep each delegated task concrete and scoped to a
  disjoint file or responsibility. Prefer inheriting the current model unless a
  stronger model is explicitly requested or clearly needed.
- Do not carry over more permissive subagent policies from other agent-specific
  instruction files into Codex sessions.

### Specs

- Spec template: `~/.hermes/spec-template.md`
- Specs live in `~/.hermes/`
- Every spec header must include `**Status:** DRAFT | APPROVED | IMPLEMENTED`
- Update the spec header when a lifecycle transition completes. Do not leave a
  reviewed spec at `DRAFT`, or an implemented spec at `APPROVED`.
- During "review spec / fix spec / loop" work, edit the spec only. Do not
  write production code or tests until the user explicitly asks for
  implementation.
- In a spec review loop, fix all HIGH issues before MEDIUM before LOW, and stop
  only when the reviewer reports zero remaining issues.
- If a spec is still `DRAFT` in a later session, confirm with the user before
  implementing it.
- Split a spec before writing the body if it touches more than two independent
  subsystems, if it likely needs more than about 35 tests, or if it contains a
  risky phase that may need independent rollback.
- Spec issue sections must stay concrete: include the problem with file and
  line, the exact fix, behavior tables when needed, named tests with expected
  assertions, and an implementation order section when issues depend on each
  other.
- Spec issue sections must avoid vague language such as "handle X" or
  "improve Y"; each fix must be precise enough to implement without guessing.
- Add an implementation order section when spec issues depend on each other.

### Testing workflow

- Never run `python -m pytest tests/tui/` as a full suite. It times out in this
  repo. Run only targeted TUI test files relevant to the changed modules.
- Example TUI test targets: changes to `drawbraille_overlay.py` should use
  `test_anim_overlay.py` and `test_drawille_v2.py`; changes to `tool_blocks/`
  should use `test_tool_blocks.py`, `test_tool_panel.py`, and
  `test_invariants.py`; changes to `tool_panel/` should use
  `test_tool_panel.py`, `test_density_resolver.py`, and `test_invariants.py`;
  changes to `body_renderers/` should use
  `test_tool_body_renderer_regression.py`,
  `test_renderer_registry_streaming.py`, and `test_invariants.py`; changes to
  `services/tools.py`, `services/plan_sync.py`, or `services/feedback.py`
  should use `test_tool_call_state_machine.py`,
  `test_tool_call_lifecycle_regression.py`, and `test_invariants.py`; changes
  to `app.py` should use `test_app.py` if it exists, not the whole TUI suite.
- If no relevant test file exists yet, use an import check as the fallback:
  `python3 -c "from hermes_cli.tui.xxx import Foo; print('OK')"`
- Use `pytest path/to/test.py::TestClass::test_name` to verify an individual
  fix.
- If a non-TUI full suite is truly needed, use a timeout of at least 1200000 ms
  and run it in the background.
- Use one discovery run to collect failures, fix the full batch, then run one
  verification pass. Use targeted single-test runs between those passes instead
  of rerunning whole suites repeatedly.

### Tool call system

`docs/concept.md` is the canonical concept note for the tool call system:
PHASE x KIND x DENSITY, plus surrounding surfaces such as PHASE transitions,
ToolGroup/PlanSyncBroker, feedback contract, error recovery, hint pipeline, and
user overrides.

- Always read `docs/concept.md` before working on `tool_blocks/`,
  `tool_panel/`, `body_renderers/`, `services/tools.py`,
  `services/plan_sync.py`, `services/feedback.py`, or the renderer registry.
- Use the frame's vocabulary in specs and reviews, including questions such as
  which axis a change touches and whether the change is vocabulary or resolver
  work.
- Suggest `docs/concept.md` updates when implementation drifts from the doc,
  when a new surface needs naming, or when the frame stops fitting cleanly.
  Flag drift to the user; do not edit the concept doc silently.

#### Concept doc freeze

`docs/concept.md` is frozen at v3.6 through May 11, 2026. During the freeze:

- Allowed: typo fixes, broken cross-reference fixes, factual corrections, and
  changelog entries that describe implementation work closing existing clauses.
- Rejected: new clauses, new contract surfaces, new perception budgets, new
  channel rules, new axis values, new role catalogue entries, new redundant
  signal rows, or a version bump to v3.7 or higher.
- Redirect new clause requests to
  `/home/xush/.hermes/tool_block_convergence_plan.md`.

#### Tool block definition of done

The tool block subsystem is done, and auditing should stop, only when all four
conditions hold simultaneously for 14 consecutive days:

- `tests/tui/test_invariants.py` passes on every PR touching `tool_blocks/`,
  `tool_panel/`, `body_renderers/`, `services/tools.py`,
  `services/plan_sync.py`, or `services/feedback.py`.
- `docs/concept.md` has no edits other than typo fixes and changelog entries.
- Targeted tests for the owner paths are green on every PR, with no skipped or
  xfail-tagged tests.
- Audit produces at most 3 MED issues and 0 HIGH issues against the frozen
  concept.

When all four hold, close `/home/xush/.hermes/tool_block_convergence_plan.md`.
Re-open only when targeted tests fail or the concept intentionally bumps to
v3.7.

#### UX audit freeze

As of April 28, 2026, UX audit Specs A, B, D, E, and F are
`IMPLEMENTED`. Their soft freezes are lifted. Spec C
(`/home/xush/.hermes/2026-04-28-ux-audit-C-affordance-discoverability-spec.md`)
is still `DRAFT`, so only its owned surface remains soft-frozen; unrelated PRs
touching it are review blocks:

| Surface | Owner spec | Lift freeze when |
|---|---|---|
| `_remediation_hint` field on `ToolHeader` and remediation lookup table | C (C1) | Spec C is IMPLEMENTED |

Allowed during the freeze: bug fixes inside Spec C's scope, read-only
references to the frozen surface, and tests that exercise it.

Rejected during the freeze: unrelated `_remediation_hint` behavior changes or a
new remediation lookup shape outside Spec C.

### Code quality

- Every `except` block must re-raise, log with `exc_info=True`, or include an
  explicit comment explaining why swallowing the exception is correct.
- `except Exception: pass` is always wrong. Narrow `except SomeType: pass` is
  acceptable only when that type is the only expected failure mode and
  swallowing is genuinely correct.
- `@work(thread=True)` bodies must wrap top-level logic in a `try`/`except`
  that logs, because worker exceptions are otherwise easy to miss.
- User-facing "see log for details" messages require the enclosing exception
  path to call `_log.exception(...)` or an equivalent full-traceback log.
- Every module that catches recoverable exceptions must define
  `import logging` and `_log = logging.getLogger(__name__)` at module top.
- Use `_log.exception(...)` or `_log.error(..., exc_info=True)` for unexpected
  errors, `_log.warning(...)` for expected-but-recoverable failures that leave
  inconsistent state, and `_log.debug(...)` for teardown or best-effort
  failures where partial failure is acceptable.

### Quality bar

- Each spec issue section must include the problem with file and line, the
  exact fix, a behavior table when multiple cases exist, and named tests with
  expected assertions.
- Avoid vague language such as "handle X" or "improve Y"; each fix must be
  precise enough to implement without guessing.
- Add an implementation order section when issues depend on each other.

## Project Structure

```
hermes-agent/
├── run_agent.py          # AIAgent class — core conversation loop
├── model_tools.py        # Tool orchestration, _discover_tools(), handle_function_call()
├── toolsets.py           # Toolset definitions, _HERMES_CORE_TOOLS list
├── cli.py                # HermesCLI class — interactive CLI orchestrator
├── hermes_state.py       # SessionDB — SQLite session store (FTS5 search)
├── agent/                # Agent internals
│   ├── prompt_builder.py     # System prompt assembly
│   ├── context_compressor.py # Auto context compression
│   ├── prompt_caching.py     # Anthropic prompt caching
│   ├── auxiliary_client.py   # Auxiliary LLM client (vision, summarization)
│   ├── model_metadata.py     # Model context lengths, token estimation
│   ├── models_dev.py         # models.dev registry integration (provider-aware context)
│   ├── display.py            # KawaiiSpinner, tool preview formatting
│   ├── skill_commands.py     # Skill slash commands (shared CLI/gateway)
│   └── trajectory.py         # Trajectory saving helpers
├── hermes_cli/           # CLI subcommands and setup
│   ├── main.py           # Entry point — all `hermes` subcommands
│   ├── config.py         # DEFAULT_CONFIG, OPTIONAL_ENV_VARS, migration
│   ├── commands.py       # Slash command definitions + SlashCommandCompleter
│   ├── callbacks.py      # Terminal callbacks (clarify, sudo, approval)
│   ├── setup.py          # Interactive setup wizard
│   ├── skin_engine.py    # Skin/theme engine — CLI visual customization
│   ├── skills_config.py  # `hermes skills` — enable/disable skills per platform
│   ├── tools_config.py   # `hermes tools` — enable/disable tools per platform
│   ├── skills_hub.py     # `/skills` slash command (search, browse, install)
│   ├── models.py         # Model catalog, provider model lists
│   ├── model_switch.py   # Shared /model switch pipeline (CLI + gateway)
│   └── auth.py           # Provider credential resolution
├── tools/                # Tool implementations (one file per tool)
│   ├── registry.py       # Central tool registry (schemas, handlers, dispatch)
│   ├── approval.py       # Dangerous command detection
│   ├── terminal_tool.py  # Terminal orchestration
│   ├── process_registry.py # Background process management
│   ├── file_tools.py     # File read/write/search/patch
│   ├── web_tools.py      # Web search/extract (Parallel + Firecrawl)
│   ├── browser_tool.py   # Browserbase browser automation
│   ├── code_execution_tool.py # execute_code sandbox
│   ├── delegate_tool.py  # Subagent delegation
│   ├── mcp_tool.py       # MCP client (~1050 lines)
│   └── environments/     # Terminal backends (local, docker, ssh, modal, daytona, singularity)
├── gateway/              # Messaging platform gateway
│   ├── run.py            # Main loop, slash commands, message dispatch
│   ├── session.py        # SessionStore — conversation persistence
│   └── platforms/        # Adapters: telegram, discord, slack, whatsapp, homeassistant, signal
├── acp_adapter/          # ACP server (VS Code / Zed / JetBrains integration)
├── cron/                 # Scheduler (jobs.py, scheduler.py)
├── environments/         # RL training environments (Atropos)
├── tests/                # Pytest suite (~3000 tests)
└── batch_runner.py       # Parallel batch processing
```

**User config:** `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (API keys)

## File Dependency Chain

```
tools/registry.py  (no deps — imported by all tool files)
       ↑
tools/*.py  (each calls registry.register() at import time)
       ↑
model_tools.py  (imports tools/registry + triggers tool discovery)
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

---

## AIAgent Class (run_agent.py)

```python
class AIAgent:
    def __init__(self,
        model: str = "anthropic/claude-opus-4.6",
        max_iterations: int = 90,
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str = None,           # "cli", "telegram", etc.
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        # ... plus provider, api_mode, callbacks, routing params
    ): ...

    def chat(self, message: str) -> str:
        """Simple interface — returns final response string."""

    def run_conversation(self, user_message: str, system_message: str = None,
                         conversation_history: list = None, task_id: str = None) -> dict:
        """Full interface — returns dict with final_response + messages."""
```

### Agent Loop

The core loop is inside `run_conversation()` — entirely synchronous:

```python
while api_call_count < self.max_iterations and self.iteration_budget.remaining > 0:
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args, task_id)
            messages.append(tool_result_message(result))
        api_call_count += 1
    else:
        return response.content
```

Messages follow OpenAI format: `{"role": "system/user/assistant/tool", ...}`. Reasoning content is stored in `assistant_msg["reasoning"]`.

---

## CLI Architecture (cli.py)

- **Rich** for banner/panels, **prompt_toolkit** for input with autocomplete
- **KawaiiSpinner** (`agent/display.py`) — animated faces during API calls, `┊` activity feed for tool results
- `load_cli_config()` in cli.py merges hardcoded defaults + user config YAML
- **Skin engine** (`hermes_cli/skin_engine.py`) — data-driven CLI theming; initialized from `display.skin` config key at startup; skins customize banner colors, spinner faces/verbs/wings, tool prefix, response box, branding text
- `process_command()` is a method on `HermesCLI` — dispatches on canonical command name resolved via `resolve_command()` from the central registry
- Skill slash commands: `agent/skill_commands.py` scans `~/.hermes/skills/`, injects as **user message** (not system prompt) to preserve prompt caching

### Slash Command Registry (`hermes_cli/commands.py`)

All slash commands are defined in a central `COMMAND_REGISTRY` list of `CommandDef` objects. Every downstream consumer derives from this registry automatically:

- **CLI** — `process_command()` resolves aliases via `resolve_command()`, dispatches on canonical name
- **Gateway** — `GATEWAY_KNOWN_COMMANDS` frozenset for hook emission, `resolve_command()` for dispatch
- **Gateway help** — `gateway_help_lines()` generates `/help` output
- **Telegram** — `telegram_bot_commands()` generates the BotCommand menu
- **Slack** — `slack_subcommand_map()` generates `/hermes` subcommand routing
- **Autocomplete** — `COMMANDS` flat dict feeds `SlashCommandCompleter`
- **CLI help** — `COMMANDS_BY_CATEGORY` dict feeds `show_help()`

### Adding a Slash Command

1. Add a `CommandDef` entry to `COMMAND_REGISTRY` in `hermes_cli/commands.py`:
```python
CommandDef("mycommand", "Description of what it does", "Session",
           aliases=("mc",), args_hint="[arg]"),
```
2. Add handler in `HermesCLI.process_command()` in `cli.py`:
```python
elif canonical == "mycommand":
    self._handle_mycommand(cmd_original)
```
3. If the command is available in the gateway, add a handler in `gateway/run.py`:
```python
if canonical == "mycommand":
    return await self._handle_mycommand(event)
```
4. For persistent settings, use `save_config_value()` in `cli.py`

**CommandDef fields:**
- `name` — canonical name without slash (e.g. `"background"`)
- `description` — human-readable description
- `category` — one of `"Session"`, `"Configuration"`, `"Tools & Skills"`, `"Info"`, `"Exit"`
- `aliases` — tuple of alternative names (e.g. `("bg",)`)
- `args_hint` — argument placeholder shown in help (e.g. `"<prompt>"`, `"[name]"`)
- `cli_only` — only available in the interactive CLI
- `gateway_only` — only available in messaging platforms
- `gateway_config_gate` — config dotpath (e.g. `"display.tool_progress_command"`); when set on a `cli_only` command, the command becomes available in the gateway if the config value is truthy. `GATEWAY_KNOWN_COMMANDS` always includes config-gated commands so the gateway can dispatch them; help/menus only show them when the gate is open.

**Adding an alias** requires only adding it to the `aliases` tuple on the existing `CommandDef`. No other file changes needed — dispatch, help text, Telegram menu, Slack mapping, and autocomplete all update automatically.

---

## Adding New Tools

Requires changes in **3 files**:

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add import** in `model_tools.py` `_discover_tools()` list.

**3. Add to `toolsets.py`** — either `_HERMES_CORE_TOOLS` (all platforms) or a new toolset.

The registry handles schema collection, dispatch, availability checking, and error wrapping. All handlers MUST return a JSON string.

**Path references in tool schemas**: If the schema description mentions file paths (e.g. default output directories), use `display_hermes_home()` to make them profile-aware. The schema is generated at import time, which is after `_apply_profile_override()` sets `HERMES_HOME`.

**State files**: If a tool stores persistent state (caches, logs, checkpoints), use `get_hermes_home()` for the base directory — never `Path.home() / ".hermes"`. This ensures each profile gets its own state.

**Agent-level tools** (todo, memory): intercepted by `run_agent.py` before `handle_function_call()`. See `todo_tool.py` for the pattern.

---

## Adding Configuration

### config.yaml options:
1. Add to `DEFAULT_CONFIG` in `hermes_cli/config.py`
2. Bump `_config_version` (currently 5) to trigger migration for existing users

### .env variables:
1. Add to `OPTIONAL_ENV_VARS` in `hermes_cli/config.py` with metadata:
```python
"NEW_API_KEY": {
    "description": "What it's for",
    "prompt": "Display name",
    "url": "https://...",
    "password": True,
    "category": "tool",  # provider, tool, messaging, setting
},
```

### Config loaders (two separate systems):

| Loader | Used by | Location |
|--------|---------|----------|
| `load_cli_config()` | CLI mode | `cli.py` |
| `load_config()` | `hermes tools`, `hermes setup` | `hermes_cli/config.py` |
| Direct YAML load | Gateway | `gateway/run.py` |

---

## Skin/Theme System

The skin engine (`hermes_cli/skin_engine.py`) provides data-driven CLI visual customization. Skins are **pure data** — no code changes needed to add a new skin.

### Architecture

```
hermes_cli/skin_engine.py    # SkinConfig dataclass, built-in skins, YAML loader
~/.hermes/skins/*.yaml       # User-installed custom skins (drop-in)
```

- `init_skin_from_config()` — called at CLI startup, reads `display.skin` from config
- `get_active_skin()` — returns cached `SkinConfig` for the current skin
- `set_active_skin(name)` — switches skin at runtime (used by `/skin` command)
- `load_skin(name)` — loads from user skins first, then built-ins, then falls back to default
- Missing skin values inherit from the `default` skin automatically

### What skins customize

| Element | Skin Key | Used By |
|---------|----------|---------|
| Banner panel border | `colors.banner_border` | `banner.py` |
| Banner panel title | `colors.banner_title` | `banner.py` |
| Banner section headers | `colors.banner_accent` | `banner.py` |
| Banner dim text | `colors.banner_dim` | `banner.py` |
| Banner body text | `colors.banner_text` | `banner.py` |
| Response box border | `colors.response_border` | `cli.py` |
| Spinner faces (waiting) | `spinner.waiting_faces` | `display.py` |
| Spinner faces (thinking) | `spinner.thinking_faces` | `display.py` |
| Spinner verbs | `spinner.thinking_verbs` | `display.py` |
| Spinner wings (optional) | `spinner.wings` | `display.py` |
| Tool output prefix | `tool_prefix` | `display.py` |
| Per-tool emojis | `tool_emojis` | `display.py` → `get_tool_emoji()` |
| Agent name | `branding.agent_name` | `banner.py`, `cli.py` |
| Welcome message | `branding.welcome` | `cli.py` |
| Response box label | `branding.response_label` | `cli.py` |
| Prompt symbol | `branding.prompt_symbol` | `cli.py` |

### Built-in skins

- `default` — Classic Hermes gold/kawaii (the current look)
- `ares` — Crimson/bronze war-god theme with custom spinner wings
- `mono` — Clean grayscale monochrome
- `slate` — Cool blue developer-focused theme

### Adding a built-in skin

Add to `_BUILTIN_SKINS` dict in `hermes_cli/skin_engine.py`:

```python
"mytheme": {
    "name": "mytheme",
    "description": "Short description",
    "colors": { ... },
    "spinner": { ... },
    "branding": { ... },
    "tool_prefix": "┊",
},
```

### User skins (YAML)

Users create `~/.hermes/skins/<name>.yaml`:

```yaml
name: cyberpunk
description: Neon-soaked terminal theme

colors:
  banner_border: "#FF00FF"
  banner_title: "#00FFFF"
  banner_accent: "#FF1493"

spinner:
  thinking_verbs: ["jacking in", "decrypting", "uploading"]
  wings:
    - ["⟨⚡", "⚡⟩"]

branding:
  agent_name: "Cyber Agent"
  response_label: " ⚡ Cyber "

tool_prefix: "▏"
```

Activate with `/skin cyberpunk` or `display.skin: cyberpunk` in config.yaml.

---

## Important Policies
### Prompt Caching Must Not Break

Hermes-Agent ensures caching remains valid throughout a conversation. **Do NOT implement changes that would:**
- Alter past context mid-conversation
- Change toolsets mid-conversation
- Reload memories or rebuild system prompts mid-conversation

Cache-breaking forces dramatically higher costs. The ONLY time we alter context is during context compression.

### Working Directory Behavior
- **CLI**: Uses current directory (`.` → `os.getcwd()`)
- **Messaging**: Uses `MESSAGING_CWD` env var (default: home directory)

### Background Process Notifications (Gateway)

When `terminal(background=true, check_interval=...)` is used, the gateway runs a watcher that
pushes status updates to the user's chat. Control verbosity with `display.background_process_notifications`
in config.yaml (or `HERMES_BACKGROUND_NOTIFICATIONS` env var):

- `all` — running-output updates + final message (default)
- `result` — only the final completion message
- `error` — only the final message when exit code != 0
- `off` — no watcher messages at all

---

## Profiles: Multi-Instance Support

Hermes supports **profiles** — multiple fully isolated instances, each with its own
`HERMES_HOME` directory (config, API keys, memory, sessions, skills, gateway, etc.).

The core mechanism: `_apply_profile_override()` in `hermes_cli/main.py` sets
`HERMES_HOME` before any module imports. All 119+ references to `get_hermes_home()`
automatically scope to the active profile.

### Rules for profile-safe code

1. **Use `get_hermes_home()` for all HERMES_HOME paths.** Import from `hermes_constants`.
   NEVER hardcode `~/.hermes` or `Path.home() / ".hermes"` in code that reads/writes state.
   ```python
   # GOOD
   from hermes_constants import get_hermes_home
   config_path = get_hermes_home() / "config.yaml"

   # BAD — breaks profiles
   config_path = Path.home() / ".hermes" / "config.yaml"
   ```

2. **Use `display_hermes_home()` for user-facing messages.** Import from `hermes_constants`.
   This returns `~/.hermes` for default or `~/.hermes/profiles/<name>` for profiles.
   ```python
   # GOOD
   from hermes_constants import display_hermes_home
   print(f"Config saved to {display_hermes_home()}/config.yaml")

   # BAD — shows wrong path for profiles
   print("Config saved to ~/.hermes/config.yaml")
   ```

3. **Module-level constants are fine** — they cache `get_hermes_home()` at import time,
   which is AFTER `_apply_profile_override()` sets the env var. Just use `get_hermes_home()`,
   not `Path.home() / ".hermes"`.

4. **Tests that mock `Path.home()` must also set `HERMES_HOME`** — since code now uses
   `get_hermes_home()` (reads env var), not `Path.home() / ".hermes"`:
   ```python
   with patch.object(Path, "home", return_value=tmp_path), \
        patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / ".hermes")}):
       ...
   ```

5. **Gateway platform adapters should use token locks** — if the adapter connects with
   a unique credential (bot token, API key), call `acquire_scoped_lock()` from
   `gateway.status` in the `connect()`/`start()` method and `release_scoped_lock()` in
   `disconnect()`/`stop()`. This prevents two profiles from using the same credential.
   See `gateway/platforms/telegram.py` for the canonical pattern.

6. **Profile operations are HOME-anchored, not HERMES_HOME-anchored** — `_get_profiles_root()`
   returns `Path.home() / ".hermes" / "profiles"`, NOT `get_hermes_home() / "profiles"`.
   This is intentional — it lets `hermes -p coder profile list` see all profiles regardless
   of which one is active.

## Known Pitfalls

### DO NOT hardcode `~/.hermes` paths
Use `get_hermes_home()` from `hermes_constants` for code paths. Use `display_hermes_home()`
for user-facing print/log messages. Hardcoding `~/.hermes` breaks profiles — each profile
has its own `HERMES_HOME` directory. This was the source of 5 bugs fixed in PR #3575.

### DO NOT use `simple_term_menu` for interactive menus
Rendering bugs in tmux/iTerm2 — ghosting on scroll. Use `curses` (stdlib) instead. See `hermes_cli/tools_config.py` for the pattern.

### DO NOT use `\033[K` (ANSI erase-to-EOL) in spinner/display code
Leaks as literal `?[K` text under `prompt_toolkit`'s `patch_stdout`. Use space-padding: `f"\r{line}{' ' * pad}"`.

### `_last_resolved_tool_names` is a process-global in `model_tools.py`
`_run_single_child()` in `delegate_tool.py` saves and restores this global around subagent execution. If you add new code that reads this global, be aware it may be temporarily stale during child agent runs.

### DO NOT hardcode cross-tool references in schema descriptions
Tool schema descriptions must not mention tools from other toolsets by name (e.g., `browser_navigate` saying "prefer web_search"). Those tools may be unavailable (missing API keys, disabled toolset), causing the model to hallucinate calls to non-existent tools. If a cross-reference is needed, add it dynamically in `get_tool_definitions()` in `model_tools.py` — see the `browser_navigate` / `execute_code` post-processing blocks for the pattern.

### Tests must not write to `~/.hermes/`
The `_isolate_hermes_home` autouse fixture in `tests/conftest.py` redirects `HERMES_HOME` to a temp dir. Never hardcode `~/.hermes/` paths in tests.

**Profile tests**: When testing profile features, also mock `Path.home()` so that
`_get_profiles_root()` and `_get_default_hermes_home()` resolve within the temp dir.
Use the pattern from `tests/hermes_cli/test_profiles.py`:
```python
@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home
```

---

## Testing

```bash
source venv/bin/activate
python -m pytest tests/ -q          # Full suite (~3000 tests, ~3 min)
python -m pytest tests/test_model_tools.py -q   # Toolset resolution
python -m pytest tests/test_cli_init.py -q       # CLI config loading
python -m pytest tests/gateway/ -q               # Gateway tests
python -m pytest tests/tools/ -q                 # Tool-level tests
```

Always run the full suite before pushing changes.
