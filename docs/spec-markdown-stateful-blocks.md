# spec: stateful block markdown rendering (PR4)

> ⚠️ Stacked on the block-rendering PR (`spec-markdown-block-rendering.md`)
> — merge that first.

Adds rendering for the three markdown elements that require multi-line
state: setext headings, multi-line blockquote continuation, and tables.

## Why these are separate

`apply_block_line` (PR3) is purely line-local. These three elements need
either lookahead (setext), carry-forward state (blockquote continuation),
or full block buffering (tables). They require a different architecture:

- **`render_stateful_blocks(text: str) -> str`** — string-level pass in
  `format_response`, runs before `apply_block_line`
- **`StreamingBlockBuffer`** — state machine inserted before
  `apply_block_line` in the streaming pipeline

## Architecture

```
format_response(text):
  pass 1: fenced code blocks (existing)
  pass 2: render_stateful_blocks(text)    ← new
  pass 3: per non-ANSI line:
            apply_block_line → apply_inline_markdown

Streaming:
  line → StreamingBlockBuffer.process_line()   ← new
              ↓ None (buffering) or str
          StreamingCodeBlockHighlighter.process_line()
              ↓ None or str
          apply_block_line → apply_inline_markdown → _cprint
```

`render_stateful_blocks` skips lines that already contain `\x1b`
(highlighted code from pass 1).

### `StreamingBlockBuffer` — `agent/rich_output.py`

```python
class StreamingBlockBuffer:
    def process_line(self, line: str) -> str | None: ...
    def flush(self) -> str | None: ...
    def reset(self) -> None: ...
```

`process_line` returns `None` while accumulating a block, or the fully
rendered block string (possibly multi-line, with embedded `\n`) when the
block ends. Plain lines with no active state pass through immediately
(returned as-is).

Instantiated in `_reset_stream_state` alongside `_stream_code_hl`:

```python
if not hasattr(self, "_stream_block_buf"):
    self._stream_block_buf = StreamingBlockBuffer()
else:
    self._stream_block_buf.reset()
```

The streaming inner loop becomes:

```python
out = self._stream_block_buf.process_line(line)
if out is None:
    continue
out2 = self._stream_code_hl.process_line(out)
if out2 is None:
    continue
if out2 is out:
    # plain text — apply block + inline
    if _display._code_highlight_active:
        out = apply_inline_markdown(apply_block_line(out), reset_suffix=_tc)
    _cprint(f"{_tc}{out}{_RST}" if _tc else out)
else:
    # fenced code block — emit as-is
    for hl_line in out2.splitlines():
        _cprint(hl_line)
```

`_flush_stream` similarly chains `_stream_block_buf.flush()` before
`_stream_code_hl.flush()`.

`StreamingBlockBuffer` imported in the existing `try` block in `cli.py`.

---

## Setext headings

**Format**
```
The Title
=========      →  h1  (same style as # The Title)
A Subtitle
----------     →  h2  (same style as ## A Subtitle)
```

`===` marker: two or more `=`, whole line.
`---` marker: two or more `-`, whole line — **disambiguate from hr**: a
`---` preceded by a non-empty non-block line is setext h2; a `---`
preceded by an empty line or start-of-string is a horizontal rule.
`apply_block_line` handles standalone `---` → hr; the stateful pass runs
first and consumes the setext case before `apply_block_line` sees it.

**`render_stateful_blocks` — setext pass**

Single-pass line scan with a `pending` slot:

```python
_SETEXT_H1_RE = re.compile(r"^={2,}$")
_SETEXT_H2_RE = re.compile(r"^-{2,}$")
```

Minimum two characters required. A single `=` or `-` is not a setext
marker in practice and collides with other patterns.

- If line matches `_SETEXT_H1_RE`/`_SETEXT_H2_RE` and `pending` is a
  **valid heading candidate** → emit `pending` as h1/h2, clear `pending`,
  suppress marker line.
- Otherwise → emit `pending` (if set), set `pending = line`.
- At end → flush `pending`.

**Valid heading candidate**: `pending` is non-empty AND `apply_block_line(pending) is pending`
(i.e. `apply_block_line` returns it unchanged — not a list item, blockquote,
heading, hr, or reference link). This reuses the already-defined block
detector as the veto condition and ensures `"- x\n---"` renders `- x` as a
list bullet followed by an hr, not as an h2.

Heading output uses the same ANSI styles as ATX headings from
`apply_block_line`, with inline spans applied to the heading text before
wrapping.

**`StreamingBlockBuffer` — setext**

Same 1-line lookahead: hold `_pending`. `process_line` returns `None` when
storing `_pending` and returns the emitted output (pending rendered or
`pending + "\n" + current`) when the setext marker arrives or when the
current line is not a marker.

The 1-line display delay affects all lines (every line is held one tick)
— acceptable given the setext pattern is common enough in LLM output to
warrant it.

---

## Multi-line blockquote continuation

**Format**
```
> This is a blockquote
that continues here       ← no > prefix, but still part of the quote

Normal text resumes.
```

Continuation lines (no `>` prefix, non-empty, following a `>` line)
receive the same `▌` gutter treatment as explicit `>` lines.

**`render_stateful_blocks` — blockquote continuation pass**

Track `_in_blockquote: bool`:

- Line matches `^>+\s?(.*)` → `_in_blockquote = True`, emit with gutter.
- Empty line while `_in_blockquote` → `_in_blockquote = False`, emit
  blank line.
- Non-empty line while `_in_blockquote` and no `>` prefix → continuation:
  emit with gutter (same as explicit `>` line).
- Any other non-empty line → `_in_blockquote = False`, emit plain.

Inline spans applied to content inside the gutter construction (same
pattern as `apply_block_line` blockquote handling).

**`StreamingBlockBuffer` — blockquote continuation**

Track `_in_blockquote`. Each line is emitted immediately (no buffering) —
state just carries forward. Continuation lines are indistinguishable from
plain lines until `_in_blockquote` is checked. The state machine is
purely stateful, not buffering.

---

## Tables

**Input**
```
| Name    | Age | City  |
|---------|-----|-------|
| Alice   | 28  | NYC   |
| Bob     | 32  | LA    |
```

**Output** — padded columns, `─` separator after header:
```
 Name      Age   City
 ───────── ───── ──────
 Alice     28    NYC
 Bob       32    LA
```

**Detection**

- Table row: `^\|.+\|$` (starts and ends with `|`)
- Separator row: all cells (split on `|`, strip whitespace) match
  `^[\s:\-]+$`
- Block ends on the first non-table line or end of string

**Column alignment** from separator row cells (strip whitespace, then check):

```python
def _parse_align(cell: str) -> str:
    c = cell.strip()
    if c.startswith(":") and c.endswith(":"):
        return "centre"
    if c.endswith(":"):
        return "right"
    return "left"   # `:---` or `---` both default to left
```

**Number detection** for auto-right-align — use a regex rather than
`str.isdigit()` (which rejects floats, negatives, and comma-formatted numbers):

```python
_NUM_RE = re.compile(r"^-?[\d,]+\.?\d*$")
```

`_NUM_RE.match(cell.strip())` → treat as numeric → right-align.

**`render_stateful_blocks` — table pass**

Accumulate rows into `_table_rows: list[list[str]]` and detect the
separator row index. On block end, call `_render_table`:

```python
def _render_table(rows, sep_idx, align) -> str:
    cols   = len(rows[0])
    # Exclude the separator row from width calculation (its cells contain
    # only dashes/colons and would inflate column widths).
    data_rows = [r for idx, r in enumerate(rows) if idx != sep_idx]
    widths = [max((len(row[i].strip()) for row in data_rows if i < len(row)),
                  default=0)
              for i in range(cols)]
    out = []
    for r_idx, row in enumerate(rows):
        if r_idx == sep_idx:
            out.append(" " + "  ".join("─" * w for w in widths))
            continue
        cells = []
        for i, w in enumerate(widths):
            cell = row[i].strip() if i < len(row) else ""
            if align[i] == "right" or _NUM_RE.match(cell):
                cells.append(cell.rjust(w))
            elif align[i] == "centre":
                cells.append(cell.center(w))
            else:
                cells.append(cell.ljust(w))
        out.append(" " + "  ".join(cells))
    return "\n".join(out)
```

Ragged rows: pad short rows with empty strings to `cols` length; truncate
long rows.

**`StreamingBlockBuffer` — table**

Accumulate rows in `_table_buf`. Return `None` while rows arrive. On
first non-table line, flush `_render_table(...)` (returned as a
multi-line string), then return the current non-table line for normal
processing. On `flush()`, emit any accumulated partial table.

---

## Integration in `format_response`

```python
def format_response(text: str) -> str:
    text = re.sub(r"```(\w*)\n(.*?)```", _highlight, text, flags=re.DOTALL)
    text = render_stateful_blocks(text)          # new
    lines = text.splitlines(keepends=True)
    return "".join(
        l if "\x1b" in l else apply_inline_markdown(apply_block_line(l))
        for l in lines
    )
```

`render_stateful_blocks` runs a single left-to-right scan with independent
state variables (`_pending` for setext, `_in_blockquote`, `_table_rows`).

**State priority** (earlier rule wins):
1. If `_in_blockquote` is True — blockquote continuation mode. Table and
   setext detection are suppressed; lines are emitted with the `▌` gutter
   or, if blank/non-continuation, blockquote mode is exited.
2. If `_table_rows` is non-empty — table accumulation mode. All
   `^\|.+\|$` lines are appended; any other line flushes the table.
3. Otherwise — check for setext marker against `_pending`, table-row
   start, or blockquote start. Plain lines update `_pending`.

This means a blockquote overrides table detection, and a table overrides
setext detection. Cross-element nesting (e.g. a table inside a blockquote)
is not supported — the first matching state wins.

---

## Tests — `tests/test_rich_output.py`

Add `TestRenderStatefulBlocks` and `TestStreamingBlockBuffer`.

**Setext**

| test | input | expected |
|------|-------|----------|
| `===` → h1 | `"Foo\n==="` | `\033[1;97m` present, `===` absent |
| `---` setext → h2 | `"Bar\n---"` | `\033[1;37m` present |
| blank-line `---` → hr | `"\n---"` | `─` line, not h2 |
| list-item `---` → hr | `"- x\n---"` | hr, `- x` unchanged |
| setext with inline span | `"**Foo**\n==="` | bold `Foo` inside h1 style |

**Multi-line blockquote**

| test | input | expected |
|------|-------|----------|
| continuation has gutter | `"> q\ncontinuation"` | both lines have `▌` |
| blank line ends continuation | `"> q\n\nnormal"` | `normal` has no `▌` |
| explicit `>` resets state | `"> q\n\n> new"` | two separate guttered sections |

**Tables**

| test | input | expected |
|------|-------|----------|
| basic table rendered | header + sep + 2 rows | padded cells, `─` separator line |
| right column | `---:` separator | cell right-justified |
| centre column | `:---:` separator | cell centred |
| number auto-right | numeric cell | right-justified regardless of spec |
| ragged row padded | row with fewer cells | empty cell fills gap |
| table at end of string | no trailing newline | rendered, not raw |

**`StreamingBlockBuffer`**

| test | description |
|------|-------------|
| setext: h1 on marker | feed `"Foo"` → None; feed `"==="` → rendered h1 |
| setext: non-marker flushes pending | feed `"Foo"` → None; feed `"bar"` → `"Foo"` emitted, `"bar"` pending |
| table: rows → None until done | each row returns None; non-table line flushes rendered table |
| table: `flush()` emits partial | incomplete table at stream end is rendered |
| blockquote: continuation stateful | continuation line without `>` emitted with `▌` |
| reset clears all state | after `reset()`, pending / table / blockquote state all cleared |

## Non-goals

- Nested blockquotes beyond single-level collapse (handled in PR3).
- Table captions, footnote rows, or multi-line cells.
- Setext headings inside blockquotes or list items.
