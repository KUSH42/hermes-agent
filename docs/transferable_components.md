---
name: Transferable components from local codebases
description: Audit of ai-agent-dev-dumbeddown, ai-orchestrator, ai-orchestrator2 for components worth porting to hermes-agent
type: project
originSessionId: 3f10e824-98d6-421d-a868-c53ad3723984
---
Audit performed 2026-04-09. Three codebases surveyed:
- `/home/xush/Documents/prog/ai-agent-dev-dumbeddown` (TUI/interface-heavy)
- `/home/xush/Documents/prog/ai-orchestrator`
- `/home/xush/Documents/prog/ai-orchestrator2`

**Why:** Identify reusable implementations before writing new features from scratch for hermes-agent.

**How to apply:** Before implementing any of the categories below in hermes-agent, check the source file first — may save significant work. Port the logic, not the scaffolding.

---

## Tier 1 — High Impact (Investigated in Depth)

### event_bus.py — PORTED ✅
- **Source:** `ai-orchestrator/control_plane/event_bus.py` (364 LOC)
- **Destination:** `agent/event_bus.py` — ported 2026-04-09. `get_event_bus()` singleton, db at `~/.hermes/events.db`.
- SQLite-backed pub/sub with glob pattern subscriptions. Thread-safe, WAL mode.
- **Status:** Not yet wired — no emit points in run_agent.py yet.

### context_zones.py — DROPPED ❌
- **Source:** `ai-agent-dev-dumbeddown/src/intelligence/context_zones.py`
- **Reason:** Architecturally incompatible. Outputs a flat string, not `List[Dict]` the API requires. Importance scores are unpopulated stubs. Missing tool pair integrity entirely. hermes's `ContextCompressor` already handles everything this claims to add, more robustly.

### context_compactor.py — DROPPED ❌
- **Source:** `ai-orchestrator2/control_plane/context_compactor.py`
- **Reason:** hermes's `agent/context_compressor.py` is already far superior — LLM summarization, iterative updates, tool pair sanitization, token-budget tail protection, cheap pre-pass tool pruning. The orchestrator version is a simpler prototype in comparison.

### virtual_scroll_chat_container.py — NOT portable ❌
- **Source:** `ai-agent-dev-dumbeddown/src/interface/tui/lazy_loading/virtual_scroll_chat_container.py`
- **Reason:** Textual-only. Virtual scrolling also disabled by a "TEMPORARY FIX" that renders all messages.

### approval_manager.py — Port effort: MEDIUM ⚠️
- **Source:** `ai-agent-dev-dumbeddown/src/safety/approval_manager.py` (676 LOC)
- Risk-gated approval workflow. ApprovalDecision enum, whitelist/blacklist, async interactive mode with timeout, callback-based TUI integration, approve-all session mode.
- Deps: local `RiskAssessor`, `WhitelistManager` — would need porting or replacing with simpler heuristics.
- **Integration:** Hook before dangerous tool execution in `run_agent.py`.
- **Gotchas:** `AGENT_ETHICS_OVERRIDE=true` env var backdoor; recursive input parsing (stack overflow risk); no audit log persistence.

### chunked_multi_edit_tool.py — Port effort: HIGH ⚠️
- **Source:** `ai-agent-dev-dumbeddown/src/tools/chunked_multi_edit_tool.py` (462 LOC) + `src/tools/chunked_multi_edit/` (7 modules)
- Batches edits into size-based/locality-aware/hybrid chunks with all-or-nothing atomicity. Validates all edits before applying.
- Deps: entire `chunked_multi_edit/` subpackage, Kode-style renderer, LangChain `@tool` decorator.
- **Integration:** `tools/smart_edit_tool.py`; strip Kode rendering, replace LangChain decorator with hermes registry.
- **Gotchas:** All 7 subpackage files needed; asyncio loop management; atomicity via rename (fails on network FS).

### context_discoverer.py — Port effort: MEDIUM-HIGH ⚠️
- **Source:** `ai-agent-dev-dumbeddown/src/intelligence/context_discoverer.py` (710 LOC)
- Async filesystem walk to discover README/CLAUDE.md/docs with 30-min TTL cache. Keyword relevance scoring on filenames.
- Deps: local `memory_manager`, `directory_manager`.
- **Integration:** Early in conversation loop to pre-load project docs into context.
- **Gotchas:** Class defined twice (bug); broken async/await in `_store_discovery_results`; relevance is filename-only.

---

## Tier 2 — Medium Impact (Surface-level reviewed)

| Component | Source | Notes |
|---|---|---|
| Streaming manager with lifecycle | `ai-agent-dev-dumbeddown/src/interface/tui/streaming_manager.py` | Widget lifecycle + queue; eliminates stream start/stop races |
| Kode-style output renderer | `ai-agent-dev-dumbeddown/src/interface/tui/kode_style_output_renderer.py` | Semantic tool output formatting for diffs/file ops |
| Lazy MCP handler | `ai-orchestrator2/control_plane/mcp_tool_handler.py` | Defers MCP server connection to first use; faster startup |
| Capability-gated tool registry | `ai-orchestrator/control_plane/tool_registry.py` | Per-profile tool restrictions; persists custom tools |
| Conversation memory tracker | `ai-orchestrator/control_plane/conversation_memory.py` | Tracks goals/files/tools per turn; compact prompt summaries |

---

## Tier 3 — Specialized / Conditional

- Hyper-research engine: `ai-agent-dev-dumbeddown/src/intelligence/hyper_research_engine.py` — only if search is core feature
- Trigger router: `ai-orchestrator2/control_plane/trigger_router.py` — cron/fs/webhook event-driven workflows
- Vector store: `ai-agent-dev-dumbeddown/src/intelligence/vector/vector_store.py` — ChromaDB abstraction for semantic search
- Adaptive documentation engine: `ai-agent-dev-dumbeddown/src/intelligence/adaptive_documentation_engine.py` — auto-generates/updates docs
