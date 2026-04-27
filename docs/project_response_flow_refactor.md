---
name: ResponseFlowEngine refactor (response_flow.py)
description: Method extraction refactor of response_flow.py — _LineClassifier, _init_fields, 5 dispatch methods, ReasoningFlowEngine dedup fix
type: project
originSessionId: 3b942a7a-e93b-4cd8-97ca-87129aec9cb0
---
**DONE** 2026-04-24; commit c3bbafb3; merged feat/textual-migration (4cdd7c4c).

**What changed:**
- `_LineClassifier` class added (13 pure detection methods wrapping module regexes — `is_footnote_def`, `is_citation`, `is_fence_open/close`, `is_indented_code`, `is_block_math_*`, `is_inline_code_label`, `is_code_intro_label`, `is_horizontal_rule`, `looks_like_source_line`)
- `_init_fields()` added to `ResponseFlowEngine` — all 26 app-independent fields in one place; called first in `__init__`
- `process_line()` reduced from 232 lines to 12-line delegating body
- 5 extracted dispatch methods: `_handle_footnote`, `_handle_citation_line`, `_dispatch_normal_state`, `_dispatch_non_normal_state`, `_dispatch_prose`
- `ReasoningFlowEngine.__init__` reduced from 45 lines to ~20: now calls `_init_fields()` then only sets reasoning-specific overrides (math disabled, dim proxy log, citations/emoji gated on `_reasoning_rich_prose`/`_emoji_reasoning`)
- 25 new tests in `tests/tui/test_response_flow_refactor.py` (R01-R15, D01-D04, P01-P06); 17 regression tests in `test_response_flow_parser.py` pass

**Why:** `ReasoningFlowEngine` manually re-declared all 26 fields from `ResponseFlowEngine.__init__` — every new field required a parallel edit or caused `AttributeError` (the `_prose_callback` incident). `process_line()` was a 232-line monolith with 5 inline state machines unreadable and untestable in isolation.

**How to apply:** When adding a new instance field to `ResponseFlowEngine`, add it to `_init_fields()` only — `ReasoningFlowEngine` will inherit it automatically. Test D04 will catch any accidental re-assignment in `ReasoningFlowEngine.__init__`.

**Key design decision:** `_dispatch_non_normal_state` returns `bool` — `False` for IN_INDENTED_CODE/IN_SOURCE_LIKE block-close paths where the closing line must fall through to prose. The `elif` in `process_line` is load-bearing: `elif self._dispatch_non_normal_state(raw): return` → fall-through to `_dispatch_prose` when False.

**Spec:** `/home/xush/.hermes/2026-04-23-response-flow-refactor-spec.md`
