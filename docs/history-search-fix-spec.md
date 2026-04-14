# History search fix spec

## Overview

This spec narrows `HistorySearchOverlay` behavior to two explicit modes:

1. Empty query: keep today's "browse all turns" behavior, but each row must
   preview the accompanying user message for that turn instead of the first
   assistant response line.
2. Non-empty query: filter turns by case-insensitive consecutive substring
   matches only. Fuzzy subsequence matching must not be used.

This is a TUI-only spec. It does not change slash-command history, prompt
history, or session database search.

## Goals

This change exists to make Ctrl+F history search predictable.

- Show turn list immediately on open, with no required typing.
- Make the row preview identify the turn by what the user asked.
- Make typed search behave like normal substring search.
- Keep result ordering and jump behavior stable.
- Keep the search snapshot frozen after the overlay opens.

## Non-goals

This spec does not redesign the overlay layout or navigation model.

- Do not change keybindings, hint text, or jump/highlight behavior.
- Do not add match highlighting in result rows in this patch.
- Do not search tool output, reasoning blocks, or non-TUI transcripts.
- Do not make results live-update while the overlay is already open.

## Current behavior

Current implementation in
`hermes_cli/tui/widgets.py:HistorySearchOverlay` builds `_TurnEntry` values
from `MessagePanel` only:

- `_TurnEntry.plain_text` uses `MessagePanel.all_prose_text()`
- `_TurnEntry.display` uses `MessagePanel.first_response_line()`
- `_candidates` are built from `entry.plain_text`
- `_render_results()` calls `fuzzy_rank(...)`

This causes two UX problems:

- Empty query rows are labeled by assistant response text, not the user
  message that started the turn.
- Typed search uses subsequence fuzzy matching, so unrelated turns can match
  when letters appear in order but not as one contiguous phrase.

## Required behavior

### Turn model

History search must index one logical turn as:

- one assistant `MessagePanel`
- paired with the user message that immediately preceded that assistant turn

For the TUI, "accompanying user message" means the text shown in the preceding
`UserMessagePanel`, or an equivalent stored copy of that same submitted user text.
The implementation may derive this either from DOM adjacency at index-build
time or from explicit turn metadata stored on `MessagePanel` or another
turn-owned structure. The final behavior matters more than the storage choice.

The pairing rule must be deterministic:

- If a `MessagePanel` has a preceding `UserMessagePanel`, use that echo text.
- If no paired user text exists, use `"(no user message)"` as display text.
- Assistant prose may still exist on the turn. It must not drive the
  empty-query row label, but it must participate in the non-empty-query
  filter predicate in this patch.

### Empty query

When the overlay opens, or when the search input becomes empty again:

- show all indexed turns
- keep reverse-chronological order, newest first
- set each row label from paired user text
- keep `_selected_idx = 0` unless clamped by zero results

Example:

- user: `fix history search`
- assistant: `I found two code paths ...`

Empty-query result row must preview `fix history search`, not assistant text.

### Non-empty query

When the input contains text, filtering must use case-insensitive consecutive
substring matching.

Rules:

- Match with `query.casefold() in haystack.casefold()`.
- A match must be contiguous. Subsequence matching is not allowed.
- `haystack` must include both paired user text and assistant plain text for
  that turn.
- Assistant text here means unprocessed plain assistant prose, not rendered
  markup or derived preview text.
- Preserve existing reverse-chronological ordering among matches. Do not
  reorder by fuzzy score.

Examples:

- Query `mem` matches `Memory architecture`.
- Query `MEM` also matches `Memory architecture`.
- Query `mry` does not match `Memory architecture`.
- Query `hist sea` matches `Fix hist search` only if exact contiguous text
  exists after case folding.

### Snapshot semantics

`open_search()` must continue to build a frozen snapshot. Once open:

- new turns added to the transcript must not appear until the user closes and
  reopens the overlay
- edits to result labels must come only from filtering the existing snapshot

## Data model changes

`_TurnEntry` must carry user-facing preview text explicitly. One acceptable
shape:

```python
@dataclass
class _TurnEntry:
    panel: MessagePanel
    index: int
    user_text: str
    assistant_text: str
    search_text: str
    display: str
```

Required semantics:

- `display` must be derived from `user_text`
- `assistant_text` must be unprocessed plain assistant prose for that turn
- `search_text` must contain both `user_text` and `assistant_text`
- non-empty filtering must use `search_text`

Implementation note:

- If the code keeps `TurnCandidate`, its `display` field should no longer mean
  "row label." It may hold `search_text` for filtering, while row rendering
  still uses `entry.display`.
- If `TurnCandidate` becomes unnecessary, remove it from the history-search
  path entirely.

## Rendering and filtering algorithm

Recommended `HistorySearchOverlay` flow:

1. `_build_index()` collects assistant panels and pairs each with user text.
2. Empty query returns `self._index` in reverse order without ranking.
3. Non-empty query filters reversed entries with a contiguous case-insensitive
   predicate.
4. `_render_results()` updates `TurnResultItem` rows from filtered entries.

Pseudo-code:

```python
entries = list(reversed(self._index))
if not query:
    results = entries
else:
    needle = query.casefold()
    results = [e for e in entries if needle in e.search_text.casefold()]
results = results[:15]
```

`fuzzy_rank()` must be removed from the history-search path after this change.

## Edge cases

The implementation must define behavior for sparse or odd transcripts.

- No turns: show zero rows and `0 of 0 turns`.
- One assistant turn with paired user text but empty assistant prose: row
  still shows that user text.
- One turn with empty user text: row shows `"(no user message)"`.
- Multi-line user text: row uses first line plus existing truncation behavior,
  or another stable one-line summary of that user text.
- Re-clearing the input after a non-empty query restores full browse-all list.

## Test changes

Update `tests/tui/test_history_search.py` to reflect new semantics.

Required assertions:

1. Empty query shows all turns in reverse order and row labels come from user
   messages, not assistant response lines.
2. Non-empty query uses contiguous case-insensitive matching.
3. Query can match user text even when assistant text does not.
4. Query can match assistant plain text even when user text does not.
5. Query `mry` does not match `Memory architecture`.
6. Clearing input after a query restores full result set.
7. Snapshot remains frozen after open.

Recommended fixture change:

- Build realistic turns with both `UserMessagePanel` and `MessagePanel` instead of
  response-only helper rows, because this spec depends on turn pairing.

## File scope

Expected implementation touchpoints:

- `hermes_cli/tui/widgets.py`
  - `_TurnEntry`
  - `_turn_result_label()`
  - `HistorySearchOverlay._build_index()`
  - `HistorySearchOverlay._render_results()`
- `tests/tui/test_history_search.py`

Potential follow-up only if needed:

- `hermes_cli/tui/app.py` if explicit turn metadata storage is cleaner than DOM
  pairing

## Acceptance criteria

This change is done when all statements below are true:

- Ctrl+F still opens a populated reverse-chronological turn list.
- With empty input, each row previews user message for that turn.
- With typed input, matching is case-insensitive contiguous substring search.
- Fuzzy subsequence matches no longer appear.
- Enter-jump, click-jump, hint save/restore, and frozen-snapshot behavior still
  pass existing tests.
