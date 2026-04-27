# Claude-derived project rules

Durable project rules extracted from the repo-local
`.claude/CLAUDE.md` and the home-level `/home/xush/.claude/CLAUDE.md`.

## Testing

- Never run `python -m pytest tests/tui/` as a full suite. It consistently
  times out. Run only targeted TUI test files tied to the changed modules.
- If no relevant test file exists yet, use an import check instead of broad
  probing.
- Use one discovery run, fix the full batch, then run one verification pass.
  Use targeted single-test runs only between those two passes.

## Specs

- Specs use `/home/xush/.hermes/spec-template.md` and live in
  `/home/xush/.hermes/`.
- Every spec header must include
  `**Status:** DRAFT | APPROVED | IMPLEMENTED`.
- Update the spec status when the lifecycle changes. Do not leave a completed
  review at `DRAFT`, or finished implementation at `APPROVED`.
- In "review spec / fix spec / loop" work, edit the spec only. Do not start
  production code or tests until the user explicitly asks for implementation.
- In review loops, resolve HIGH issues before MEDIUM before LOW, and stop only
  at zero remaining issues.
- If a spec is still `DRAFT` in a later session, confirm with the user before
  implementing it.
- Split a spec before writing the body if it spans more than two independent
  subsystems, is likely to require more than about 35 tests, or contains a
  risky phase that may need separate rollback.
- Keep spec issue sections concrete: problem with file and line, exact fix,
  behavior table when needed, named tests, and implementation order when there
  are dependencies.

## Workflow

- Never mention `Claude` or `Claude Code` in git commit messages or pull
  requests.
- Before installing a Claude-oriented external skill, scan it with Snyk Agent
  Scan and do not install it unless the scan returns safe.

## Code quality

- Every `except` block must re-raise, log with `exc_info=True`, or include an
  explicit comment explaining why swallowing the exception is correct.
