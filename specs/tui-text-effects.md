# Spec: TUI Text Effects (`/effects`)

**Status:** Implemented (2026-04-11)  
**Priority:** P1  
**Depends on:** textual-migration (implemented)  
**Goal:** Port the TerminalTextEffects easter egg from prompt_toolkit to Textual using `App.suspend()`, rename the command to `/effects`, expand the effect library, and lay the groundwork for a streaming typewriter feature (implemented separately).

---

## 1. Problem

### 1.1 Broken PT suspension

The existing easter egg implementation (`stash@{1}`, `feat/pr5-terminaltexteffects-easteregg`) uses prompt_toolkit's `run_in_terminal` + `self._app.create_background_task` to suspend the PT app before running a TTE animation. Both APIs are gone — we are now on Textual. The command is registered in `commands.py` but calling it will crash at the suspension step.

### 1.2 Ambiguous command name

`/easteregg` is opaque to new users and unsearchable in `/help` output. There is no hint that it plays animations or accepts parameters. The subcommand list (matrix, beams, etc.) is only discoverable via tab completion.

### 1.3 Incomplete effect library

7 of TTE's 37 effects are exposed. The installed version (0.14.2) includes effects directly relevant to an AI coding agent persona — `decrypt`, `print`, `synthgrid`, `highlight`, `laseretch` — that are not available. The "typewriter" family (`print`, `slide`) is absent despite being the primary user expectation for this kind of feature.

### 1.4 TTE not in project venv

`terminaltexteffects` is installed in the conda env at `/home/xush/miniconda3/` but not in the project venv. It is also absent from `pyproject.toml`. Any user who installs the project gets no TTE.

### 1.5 Streaming typewriter is a separate problem

TTE requires the **full text at construction time** — `Effect(text)` pre-computes every frame. It cannot receive tokens incrementally. Running TTE on each arriving token would require suspending and resuming Textual ~50 times per response turn. This is the wrong tool for live streaming.

The streaming typewriter (character-reveal as tokens arrive) is a custom Textual animation on `LiveLineWidget` / `RichLog` — using `render_line` color fades or per-character `set_timer` chains. This is specified separately (see §16 Deferred).

---

## 2. Goals

1. `/effects [effect] [text]` replaces `/easteregg [effect] [text]` with identical parsing logic. `/easteregg` is aliased for backward compat, deprecated in `/help`.
2. Effect runs inside `App.suspend()` so Textual pauses, TTE writes to the raw terminal, then Textual resumes cleanly.
3. Effect library expands from 7 to 15 named effects covering the full persona range.
4. `terminaltexteffects>=0.14.0,<1` added to `pyproject.toml` under a new `[fun]` optional dep group. Graceful fallback when not installed: prints install hint, does not crash.
5. Skin gradient colors applied to effects that support `final_gradient_stops` (behaviour preserved from stash).
6. `/effects list` subcommand prints all available effect names and one-line descriptions.
7. All existing tests for command registration and subcommand completion continue to pass.

---

## 3. Non-Goals

- TTE for live streaming response text. Architecturally incompatible — see §1.5 and §16.
- Auto-playing effects on agent events (e.g. on session start, on error). Deferred — see §16.
- Per-skin default effect config. Deferred — see §16.
- Supporting all 37 TTE effects. We curate a personality-consistent subset; users who want the full library can call TTE directly.
- A TUI-embedded animation widget (effects that play inside the Hermes output panel without suspending). Textual's widget system and TTE's terminal takeover model are mutually exclusive — TTE rewrites the entire terminal area.

---

## 4. Design

### 4.1 Module extraction: `hermes_cli/tui/tte_runner.py`

Extract TTE logic out of `cli.py` into a standalone module. This keeps `cli.py` from growing further and makes the runner testable independently.

```python
# hermes_cli/tui/tte_runner.py

EFFECT_MAP: dict[str, tuple[str, str]] = {
    # Reveal / dramatic
    "matrix":      ("terminaltexteffects.effects.effect_matrix",      "Matrix"),
    "blackhole":   ("terminaltexteffects.effects.effect_blackhole",    "Blackhole"),
    "decrypt":     ("terminaltexteffects.effects.effect_decrypt",      "Decrypt"),
    "laseretch":   ("terminaltexteffects.effects.effect_laseretch",    "LaserEtch"),
    "binarypath":  ("terminaltexteffects.effects.effect_binarypath",   "BinaryPath"),
    "synthgrid":   ("terminaltexteffects.effects.effect_synthgrid",    "SynthGrid"),
    # Flow / ambient
    "beams":       ("terminaltexteffects.effects.effect_beams",        "Beams"),
    "waves":       ("terminaltexteffects.effects.effect_waves",        "Waves"),
    "rain":        ("terminaltexteffects.effects.effect_rain",         "Rain"),
    "overflow":    ("terminaltexteffects.effects.effect_overflow",     "Overflow"),
    "sweep":       ("terminaltexteffects.effects.effect_sweep",        "Sweep"),
    # Text reveal / typewriter family
    "print":       ("terminaltexteffects.effects.effect_print",        "Print"),
    "slide":       ("terminaltexteffects.effects.effect_slide",        "Slide"),
    "highlight":   ("terminaltexteffects.effects.effect_highlight",    "Highlight"),
    # Fun
    "wipe":        ("terminaltexteffects.effects.effect_wipe",         "Wipe"),
}

EFFECT_DESCRIPTIONS: dict[str, str] = {
    "matrix":     "Digital rain cascade",
    "blackhole":  "Characters spiral into a singularity",
    "decrypt":    "Scrambled characters resolve to final text",
    "laseretch":  "Laser burns text into the terminal",
    "binarypath": "Binary particles assemble into text",
    "synthgrid":  "Retro synth-wave grid reveal",
    "beams":      "Scanning light beams illuminate text",
    "waves":      "Text ripples as a wave",
    "rain":       "Characters fall like rain",
    "overflow":   "Characters overflow and settle",
    "sweep":      "Directional character sweep",
    "print":      "Typewriter-style character-by-character reveal",
    "slide":      "Characters slide in from the edges",
    "highlight":  "Spotlight scans and highlights text",
    "wipe":       "Clean directional wipe",
}


def resolve_effect(name: str) -> tuple[str, str] | None:
    return EFFECT_MAP.get(name.strip().lower())


def run_effect(effect_name: str, text: str, skin=None) -> None:
    """Run a TTE effect synchronously. Caller must have suspended the TUI first."""
    import importlib

    spec = resolve_effect(effect_name)
    if spec is None:
        available = ", ".join(sorted(EFFECT_MAP))
        print(f"  Unknown effect: {effect_name!r}")
        print(f"  Available: {available}")
        return

    try:
        mod = importlib.import_module(spec[0])
        cls = getattr(mod, spec[1])
    except ImportError:
        print("  TerminalTextEffects is not installed.")
        print('  Install it with: pip install "hermes-agent[fun]"')
        return

    effect = cls(text)

    # Skin-aware gradient — preserved from stash implementation
    try:
        if skin is None:
            from hermes_cli.skin_engine import get_active_skin
            skin = get_active_skin()
        gradient = (
            skin.get_color("banner_dim",    "#CD7F32"),
            skin.get_color("banner_accent", "#FFBF00"),
            skin.get_color("banner_title",  "#FFD700"),
        )
        color_mod = importlib.import_module("terminaltexteffects.utils.graphics")
        Color = getattr(color_mod, "Color")
        cfg = getattr(effect, "effect_config", None)
        if cfg and hasattr(cfg, "final_gradient_stops"):
            effect.effect_config.final_gradient_stops = tuple(Color(c) for c in gradient)
        tc = getattr(effect, "terminal_config", None)
        if tc:
            tc.frame_rate = 0   # unlimited — let the terminal pace it
    except Exception:
        pass  # skin failure is non-fatal; default TTE colors apply

    with effect.terminal_output() as terminal:
        for frame in effect:
            terminal.print(frame)
```

### 4.2 `HermesApp._play_effects` — Textual suspension

`App.suspend()` is a **synchronous** context manager (`@contextmanager`). Use `with`, not `async with`.
`_run_effect_sync` is a **module-level function** in `app.py` (no `self`), passed to `run_in_executor`.

```python
# app.py  (module level — outside HermesApp class)
def _run_effect_sync(effect_name: str, text: str) -> None:
    from hermes_cli.tui.tte_runner import run_effect
    print()
    run_effect(effect_name, text)
    print()


# app.py  (inside HermesApp class)
from textual import work

@work
async def _play_effects(self, effect_name: str, text: str) -> None:
    """Suspend Textual, run TTE animation, resume. Called directly from agent thread."""
    import asyncio
    with self.suspend():                          # sync CM — not async with
        loop = asyncio.get_running_loop()         # get_event_loop() is deprecated in 3.10+
        await loop.run_in_executor(None, _run_effect_sync, effect_name, text)
```

### 4.3 Command handler rewrite — `cli.py`

Replace the PT-specific `_handle_easteregg_command` with a Textual-aware version:

```python
def _handle_effects_command(self, cmd: str) -> None:
    """Handle /effects [effect] [text] — play a terminal text animation."""
    from hermes_cli.tui.tte_runner import (
        resolve_effect, EFFECT_MAP, EFFECT_DESCRIPTIONS
    )
    parts = cmd.strip().split(maxsplit=2)

    # /effects list — print catalogue
    if len(parts) >= 2 and parts[1].strip().lower() == "list":
        print()
        for name, desc in sorted(EFFECT_DESCRIPTIONS.items()):
            print(f"  {name:<14} {desc}")
        print()
        return

    effect_name = "matrix"
    custom_text = ""

    if len(parts) >= 2:
        maybe = parts[1].strip().lower()
        if resolve_effect(maybe):
            effect_name = maybe
            custom_text = parts[2].strip() if len(parts) >= 3 else ""
        else:
            custom_text = cmd.strip().split(maxsplit=1)[1].strip()

    if not custom_text:
        try:
            from hermes_cli.skin_engine import get_active_skin
            custom_text = get_active_skin().get_branding("agent_name", "Hermes")
        except Exception:
            custom_text = "Hermes"

    # Route through Textual suspension.
    # _play_effects is a @work method — safe to call directly from any thread;
    # @work handles its own dispatch. Do NOT wrap in call_from_thread (double-schedules).
    _app = _hermes_app  # module-level ref set in run()
    if _app is not None:
        _app._play_effects(effect_name, custom_text)
    else:
        # Single-query / no-TUI mode — run directly
        from hermes_cli.tui.tte_runner import run_effect
        print()
        run_effect(effect_name, custom_text)
        print()
```

There is no separate `_handle_easteregg_command` method. The deprecation notice is emitted in
`process_command` when `_base_word == "easteregg"` (before alias resolution routes the canonical
to `_handle_effects_command`). The alias mechanism in `CommandDef` means `process_command` already
routes `canonical == "effects"` for both `/effects` and `/easteregg` inputs.

### 4.4 Command registration — `commands.py`

`CommandDef` has no `hidden` field (verified against source). The standard codebase convention
for deprecated aliases is `aliases=("easteregg",)` on the canonical `CommandDef`. The deprecation
warning is emitted in `process_command` when `_base_word == "easteregg"` (before canonical
resolution routes it to `_handle_effects_command`).

`SUBCOMMANDS` is populated from `CommandDef.subcommands` at module load. Do **not** assign
to the `SUBCOMMANDS` dict directly. The 15 effect names are duplicated as a constant in
`commands.py` to avoid importing `tte_runner.py` (optional TTE dependency) at startup:

```python
# commands.py — module level, before COMMAND_REGISTRY
_EFFECTS_SUBCOMMANDS: tuple[str, ...] = (
    "beams", "binarypath", "blackhole", "decrypt", "highlight",
    "laseretch", "matrix", "overflow", "print", "rain",
    "slide", "sweep", "synthgrid", "waves", "wipe",
    "list",
)

CommandDef(
    "effects",
    "Play a terminal text animation (TerminalTextEffects)",
    "Configuration",
    aliases=("easteregg",),          # easteregg routes here; deprecation warned in process_command
    cli_only=True,
    subcommands=_EFFECTS_SUBCOMMANDS,
    args_hint="[effect] [text] | list",
),
```

In `process_command`, add before the canonical dispatch:
```python
if _base_word == "easteregg":
    print("  /easteregg is deprecated — use /effects instead.")
```
Then the existing alias resolution sets `canonical = "effects"` and calls `_handle_effects_command`.

### 4.5 `pyproject.toml`

```toml
[project.optional-dependencies]
fun = ["terminaltexteffects>=0.14.0,<1"]
```

Update `[all]` to include `"hermes-agent[fun]"`.

### 4.6 `/effects list` output (example)

```
  beams          Scanning light beams illuminate text
  binarypath     Binary particles assemble into text
  blackhole      Characters spiral into a singularity
  decrypt        Scrambled characters resolve to final text
  highlight      Spotlight scans and highlights text
  laseretch      Laser burns text into the terminal
  matrix         Digital rain cascade
  overflow       Characters overflow and settle
  print          Typewriter-style character-by-character reveal
  rain           Characters fall like rain
  slide          Characters slide in from the edges
  sweep          Directional character sweep
  synthgrid      Retro synth-wave grid reveal
  waves          Text ripples as a wave
  wipe           Clean directional wipe
```

---

## 5. Design Decisions

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| `App.suspend()` | Yes | `run_in_terminal` (PT) | PT is gone; `suspend()` is the Textual equivalent and is stable in ≥1.0 |
| `run_in_executor` inside `suspend()` | Yes | Call `run_effect` directly | TTE is synchronous but blocking the event loop is bad practice even inside suspend; executor is cleaner |
| Extract to `tte_runner.py` | Yes | Keep in `cli.py` | `cli.py` is already large; the runner is independently testable; import is lazy so no cost when TTE not installed |
| `/effects list` subcommand | Yes | Just show in `/help` | Users in session don't read `/help`; discoverability inside the chat session matters |
| `/easteregg` as `aliases=` entry | Yes | Delete immediately | Existing scripts/muscle memory should not hard-crash; one release cycle is reasonable. `CommandDef` has no `hidden` field — alias on the canonical entry is the correct pattern |
| `frame_rate = 0` | Yes | Default TTE rate | Removes artificial throttling; let the terminal and OS pace the animation naturally |
| Curate 15 effects, not all 37 | Yes | Expose all | Many TTE effects (bouncyballs, bubbles, fireworks, vhstape) are playful/gimmicky; curating keeps the persona coherent |

---

## 6. Configuration

No new config keys. Effect selection is per-invocation only.

Future: `effects.default_effect` in `~/.hermes/config.yaml` — not in scope for this spec.

---

## 7. Files Changed

**New:**
- `hermes_cli/tui/tte_runner.py` — `EFFECT_MAP`, `EFFECT_DESCRIPTIONS`, `resolve_effect`, `run_effect`
- `tests/tui/test_tte_runner.py` — 14 tests

**Modified:**
- `cli.py` — `_handle_effects_command`, deprecation notice for `easteregg` in `process_command`, dispatch `canonical == "effects"`
- `hermes_cli/commands.py` — `_EFFECTS_SUBCOMMANDS` constant, `CommandDef("effects", aliases=("easteregg",), subcommands=_EFFECTS_SUBCOMMANDS, ...)`, remove old standalone `/easteregg` entry
- `hermes_cli/tui/app.py` — `_play_effects` `@work` method + module-level `_run_effect_sync`
- `pyproject.toml` — `[fun]` dep group, add to `[all]`
- `tests/hermes_cli/test_commands.py` — update assertions: `/effects` registered, `easteregg` is alias, subcommands include 15 effects + list

---

## 8. Implementation Plan

**Step 0 — Dep and scaffolding**
- Add `terminaltexteffects>=0.14.0,<1` to `pyproject.toml [fun]`
- Create `hermes_cli/tui/tte_runner.py` with `EFFECT_MAP`, `EFFECT_DESCRIPTIONS`, `resolve_effect`, `run_effect` (verbatim lift + expansion from stash)
- `pip install -e ".[fun]"` in dev env

**Step 1 — Command registration**
- Add `_EFFECTS_SUBCOMMANDS` tuple constant to `commands.py` (15 effect names + "list"; no import of `tte_runner`)
- Add `CommandDef("effects", aliases=("easteregg",), subcommands=_EFFECTS_SUBCOMMANDS, ...)` to `commands.py`
- Remove (or update) the standalone `/easteregg` `CommandDef` entry
- Update `test_commands.py` assertions: `/effects` registered; `easteregg` is alias (not a separate entry); subcommands = 16 items

**Step 2 — App suspension bridge**
- Add module-level `_run_effect_sync(effect_name, text)` to `app.py`
- Add `_play_effects(@work async)` to `HermesApp` using `with self.suspend()` (sync CM) and `asyncio.get_running_loop()`
- Tests: mock `App.suspend`, verify `run_in_executor` called (2 tests)

**Step 3 — CLI handler rewrite**
- Rewrite `_handle_effects_command` calling `_app._play_effects(...)` directly (not via `call_from_thread`)
- Add fallback path for no-TUI mode
- Add `/effects list` output path
- In `process_command`: emit deprecation notice when `_base_word == "easteregg"`; dispatch `canonical == "effects"` → `_handle_effects_command`
- Tests: parsing (effect name, text, list, defaults), no-TUI fallback, invalid effect, deprecation notice (8 tests)

**Step 4 — Runner tests**
- `test_resolve_effect`: known names, unknown names, case-insensitive
- `test_run_effect_import_error`: TTE not installed → print hint, no crash
- `test_run_effect_unknown_name`: print available list, no crash
- `test_run_effect_skin_gradient`: mock skin, verify `final_gradient_stops` applied
- `test_run_effect_skin_failure`: skin raises → effect still runs with default colors
- Total: 14 tests in `test_tte_runner.py`

---

## 9. State Changes

No `OrchestratorState` fields modified. `_play_effects` is a transient `@work` coroutine — no reactive state persists beyond the animation.

---

## 10. Capabilities Required

None. `/effects` is always available. TTE must be installed (`hermes-agent[fun]`) or the command gracefully degrades.

---

## 11. Cost Impact

Zero. No LLM calls.

---

## 12. Error Conditions

| Condition | Handling |
|---|---|
| TTE not installed | `ImportError` caught in `run_effect`; prints install hint; no crash |
| Unknown effect name | `resolve_effect` returns `None`; prints available list |
| Skin import fails | `except Exception: pass` in gradient block; TTE default colors used |
| `App.suspend()` unavailable (Textual < 1.0) | Not possible — we pin `textual>=1.0,<9` |
| `_hermes_app` is `None` (no-TUI mode) | Fallback to direct `run_effect` call |
| TTE animation raises mid-frame | Exception propagates out of `run_in_executor`; `@work` logs it; Textual resumes |
| Terminal too small for effect | TTE handles internally (clips or skips); no Hermes-level handling needed |

---

## 13. Determinism Impact

None. Effects are visual-only.

---

## 14. Backward Compatibility

- `/easteregg` continues to work via `aliases=("easteregg",)` on the `effects` `CommandDef`; `process_command` emits a deprecation notice before routing to `_handle_effects_command`.
- Subcommand completions for `/easteregg` are inherited from the `effects` entry's `subcommands` tuple via alias resolution in `SUBCOMMANDS`.
- The 7 effects from the stash are all present in the new `EFFECT_MAP` with identical names.
- `terminaltexteffects` remains optional — existing installs without `[fun]` are unaffected.

---

## 15. Test Plan

| Step | Tests | Focus |
|---|---|---|
| 0 | 0 | Scaffolding — no tests yet |
| 1 | 4 | `/effects` in registry; `easteregg` is alias (not separate entry); 16 subcommands present; `/effects list` in SUBCOMMANDS |
| 2 | 2 | `_play_effects` calls `App.suspend`; `run_in_executor` called with correct args |
| 3 | 8 | Parsing (valid effect + text; default effect; no text → skin fallback; list subcommand; invalid effect; no-TUI fallback; deprecated alias notice) |
| 4 | 14 | resolve_effect × 4; import error; unknown name; skin gradient; skin failure; run_effect happy path × 7 effects |

**Total: 28 tests**

---

## 16. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `App.suspend()` leaves terminal in bad state if TTE crashes | Low | High | `try/finally` around `run_effect` call inside executor; Textual's `suspend()` context manager handles resume regardless |
| TTE 0.14 API changes in 0.15+ | Medium | Low | Version pin `<1`; API is stable within minor versions |
| `run_in_executor` overhead adds latency before animation starts | Low | Low | ~1ms; negligible vs animation duration |
| Users invoke `/effects` during agent run | Possible | Low | `_handle_effects_command` runs on agent's command thread; `_play_effects` is a `@work` method, safe to call from any thread — Textual's worker machinery handles dispatch |

---

## 17. Interaction with Other Specs

**Depends on (in):**
- `textual-migration` — `HermesApp`, `_hermes_app` module-level ref, `@work` decorator

**Enables (out):**
- `tui-context-menu` — `_flash_hint` idiom reused for post-effect copy confirmation
- `tui-streaming-typewriter` *(future)* — shares the "visual reveal" design space but is architecturally separate

---

## Deferred

### Streaming typewriter (separate spec: `tui-streaming-typewriter`)

**Why TTE cannot do this:** `Effect(text)` pre-computes all frames before the animation starts. Each frame is a full re-render of the entire text region. The full text is unknown during streaming. Calling TTE per-token would require suspending and resuming Textual ~50× per response — visually broken and architecturally wrong.

**What the right implementation looks like:**
- Hook into `LiveLineWidget` or `RichLog.write()` — intercept newly written characters
- Apply a brief CSS animation or `render_line` color transform: new characters appear at reduced opacity/dim color, then normalize over ~150ms
- Pure Textual, no TTE. Could use `reactive(int)` watermark + `set_interval` to advance the "revealed" position
- Configurable: off by default, opt-in via `display.streaming_typewriter: true` in config

This spec is **not yet written**. It is a P2 feature — desirable for the competitive demo, but requires deeper `LiveLineWidget` work.

### Per-skin default effect

`effects.default_effect` key in `~/.hermes/config.yaml` — sets which effect plays when `/effects` is called with no name. Currently hardcoded to `matrix`. Deferred to a config pass.

### Auto-play on agent events

- Play a brief `print` or `slide` effect when a session starts (configurable banner animation)
- Play `sweep` or `wipe` after a long agent turn completes
- Requires: a config gate, a "turn complete" hook in the agent loop, and a short-text target (session title, turn summary)
- Deferred — could be jarring if not done carefully.

### Full TTE catalogue exposure

The remaining 22 effects (bouncyballs, bubbles, burn, colorshift, crumble, errorcorrect, expand, fireworks, middleout, orbittingvolley, pour, random_sequence, rings, scattered, smoke, spotlights, spray, swarm, thunderstorm, unstable, vhstape, waves) are not exposed. Users who want them can call TTE directly. A `--raw` flag to bypass the curated list is a potential future addition.
