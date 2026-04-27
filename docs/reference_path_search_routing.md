---
name: PathSearchProvider → HermesInput routing
description: PathSearchProvider.post_message(Batch) never reaches HermesInput directly — App-level relay required
type: reference
originSessionId: ed050e17-3ae2-499a-8423-90363c30a7d6
---
`PathSearchProvider` and `HermesInput` are siblings (both children of Screen).
Textual only bubbles messages upward through the parent chain.  A batch posted
by `PathSearchProvider` goes: provider → Screen → App.  It never reaches
`HermesInput`.

**Fix:** `HermesApp.on_path_search_provider_batch` relays directly to
`self.query_one(HermesInput).on_path_search_provider_batch(message)`.

This applies to **any sibling-to-sibling message routing** in the Hermes TUI.
The general pattern: catch the message at App level and call the target widget's
handler method directly (sync call, not post_message).

**Tests that set inp.value = "@..."** will now trigger a real filesystem walk.
Reset `inp._raw_candidates = []` before injecting a synthetic batch, or avoid
setting inp.value and set `inp._current_trigger` directly instead.
