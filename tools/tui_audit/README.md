# tui_audit — Real-PTY tmux Audit Driver

A thin tmux wrapper for driving `hermes` through a real PTY during live audits. Complements the Pilot harness — use it for TTY-only flows (kitty/sixel probes, real SIGWINCH, OSC color queries) that Pilot's headless screen buffer cannot reach. Never use it as a Pilot replacement.

Full procedure: [`~/.claude/skills/tui-development/references/tmux-audit.md`](~/.claude/skills/tui-development/references/tmux-audit.md)

## Smoke check (run before each audit cycle)

```bash
python3 tools/tui_audit/test_tmux_smoke.py
```

Verifies tmux is on PATH, sessions spawn and kill cleanly, and `capture()` returns real output.
