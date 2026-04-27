---
name: Input mode safety spec
description: Rev-search bash semantics, persistent bash mode indicator, Ctrl+C routing, readline bindings (Ctrl+U/K, Alt+Up), ghost text guard
type: project
originSessionId: f5b2c71d-f9d2-4cd4-9075-7ab63ed81ecb
---
Spec at `/home/xush/.hermes/2026-04-23-input-mode-safety-spec.md` — READY 2026-04-23.

Issues: A-1, A-3, C-1, C-2, D-1, D-2, F-1, F-4 from the 2026-04-23 input audit.

Three implementation phases:
- Phase A: Rev-search correctness — Enter accepts+submits (A-1), ghost text guard (D-1), Ctrl+G abort (F-4)
- Phase B: Bash mode indicator — placeholder + $ glyph + border color (C-1), Ctrl+C state machine (C-2), @file-in-bash decision doc (D-2)
- Phase C: Readline bindings — Ctrl+U/K kill-line (F-1), Alt+Up/Down skip-commands nav (A-3)

**Why:** P0 issues — Enter-in-rev-search submits partial query (muscle memory mismatch), single-character chevron is not load-bearing signal for a mode that shells out.

**How to apply:** Implement Phase A first (smallest, highest P0 impact), then Phase B, then Phase C. ~30 new tests in `tests/tui/test_input_mode_safety.py`.
