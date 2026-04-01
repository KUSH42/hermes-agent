# spec: block-level markdown rendering (PR3)

> ⚠️ Stacked on the inline markdown PR — merge that first.

Extends `apply_inline_markdown` to handle single-line block structures:
headings, horizontal rules, blockquotes, list bullets, HTML inline tags,
and link text extraction. All transforms are stateless and line-local —
usable in both the streaming path and `format_response` with no
architectural change.

Stateful elements (setext headings, tables, multi-line blockquote
continuation) are covered in the follow-up spec
`spec-markdown-stateful-blocks.md`.

## What's currently rendered vs raw

| Element | Input | Current output | Should be |
|---------|-------|----------------|-----------|
| Heading h1 | `# Foo` | `# Foo` (raw) | bold bright-white, no `#` |
| Heading h2–h6 | `## Foo` | `## Foo` (raw) | progressively dimmer bold |
| Horizontal rule | `---` | `---` (raw) | dim `─` line across terminal |
| Blockquote | `> text` | `> text` (raw) | dim `▌ ` gutter + dim text |
| Unordered list | `- item` / `* item` | raw | `•` / `◦` / `▸` by indent depth |
| Ordered list | `1. item` | raw | number preserved, body unchanged |
| HTML `<em>` | `<em>text</em>` | raw tags | italic, tags stripped |
| HTML `<strong>` | `<strong>text</strong>` | raw tags | bold, tags stripped |
| Link | `[text](url)` | raw | underlined text, URL discarded |
| Image | `![alt](url)` | raw | `[img: alt]` placeholder |

Inline bold/italic/code/strikethrough are already handled (previous PR).

## Architecture

Every element in this PR is **single-line detectable** — the entire
transformation is determined by the current line alone, no lookahead or
state carryover.

**New function**: `apply_block_line(line: str) -> str` — pure line-in /
line-out, analogous to `apply_inline_markdown`. Called on every plain-text
line in both the streaming path and `format_response`.

```
Streaming (_emit_stream_text / _flush_stream):
  out is line → apply_block_line(line) → apply_inline_markdown(result)

format_response(text):
  ├─ pass 1: fenced code blocks → ANSI highlighted   (existing)
  └─ pass 2: per non-ANSI line:
               apply_block_line(line) → apply_inline_markdown(result)
```

## Implementation plan

### `apply_block_line(line: str) -> str` — `agent/rich_output.py`

Returns the line unchanged if no block pattern matches. Two early-exit guards:

1. `"\x1b" in line` — already ANSI-rendered (same guard as `apply_inline_markdown`)
2. `"\n" in line` — multi-line string from `StreamingBlockBuffer` (table or setext
   block); skip pattern matching, return as-is

Guard 2 is only relevant in streaming; `format_response` feeds single lines.

Add `apply_block_line` to the module docstring public API section alongside
`apply_inline_markdown`. Add `import shutil` at the top of `rich_output.py`
(needed for `get_terminal_size` in the hr transform).

**Headings**

```python
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
```

| Level | ANSI style |
|-------|-----------|
| h1 | `\033[1;97m` bold bright-white |
| h2 | `\033[1;37m` bold white |
| h3 | `\033[1m` bold |
| h4–h6 | `\033[1;2m` bold dim |

`#` markers stripped. Inline spans applied to the heading text *inside*
`apply_block_line` before the heading colour wraps it — prevents a bare
`\033[0m` from a span resetting the heading colour mid-line.

**Horizontal rule**

Detect `^(-{3,}|\*{3,}|_{3,})$` — three or more identical rule chars,
whole line only. Replace with:

```python
f"\033[2m{'─' * shutil.get_terminal_size((80, 24)).columns}\033[0m"
```

`---` preceded by non-empty text is a setext heading marker — handled in
PR4. `apply_block_line` only fires when `---` is a standalone line (stateful
pass runs first in `format_response`; in streaming `StreamingBlockBuffer`
runs before `apply_block_line`).

**PR3-only behaviour** (before PR4 merges): `---` immediately following a
paragraph will be incorrectly rendered as an hr. This is an acceptable
interim regression — setext headings are rare in LLM output compared to ATX
(`#`), and it is corrected when PR4 lands.

**Blockquote**

Detect `^>+\s?(.*)`. Strip all leading `>` chars (nested blockquotes
collapse to one level). Apply inline spans to the content, then wrap:

```python
content_rendered = apply_inline_markdown(content)
return f"\033[2m▌ {content_rendered}\033[0m"
```

Inline spans are applied internally here because the outer
`apply_inline_markdown` call skips lines that already contain `\x1b`.

**Unordered list**

Detect `^(\s*)([-*+])\s+(.+)`. Bullet symbol chosen by indent depth:

```python
level = len(indent) // 2
bullets = ["•", "◦", "▸", "·"]
bullet  = bullets[min(level, 3)]
return f"{indent}{bullet} {content}"
```

Content is passed to the outer `apply_inline_markdown` call. This works
because `apply_block_line` does not inject `\x1b` into list lines (only the
bullet char changes), so the outer `apply_inline_markdown` is not blocked by
the ANSI guard. Headings and blockquotes, by contrast, inject ANSI
internally and handle their own inline spans before the outer call.

**Ordered list**

Detect `^(\s*)(\d+\.)\s+(.+)`. No transformation — number and dot already
render acceptably. Included for completeness; implementation is a pass-through.

**Reference link suppression**

Detect `^\[[^\]]+\]:\s+\S+$` (whole-line reference definition). Return
empty string — reference definitions are metadata, not prose.

**HTML tags and links** — handled in `apply_inline_markdown` (inline, not
block), added as new passes after the existing span passes:

```python
# step 5a — images before links (![  starts with !)
_MD_IMAGE_RE  = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
# step 5b — links
_MD_LINK_RE   = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# step 5c — HTML inline tags
_MD_EM_RE     = re.compile(r"<em>(.*?)</em>",     re.IGNORECASE)
_MD_STRONG_RE = re.compile(r"<strong>(.*?)</strong>", re.IGNORECASE)
```

- `![alt](url)` → `\033[2m[img: alt]\033[0m{reset_suffix}`
- `[text](url)` → `\033[4mtext\033[0m{reset_suffix}`
- `<em>` → `\033[3m…\033[0m{reset_suffix}`
- `<strong>` → `\033[1m…\033[0m{reset_suffix}`

All four added before the placeholder-restore step so content inside
backtick spans is protected.

## Integration in `format_response`

```python
def format_response(text: str) -> str:
    text = re.sub(r"```(\w*)\n(.*?)```", _highlight, text, flags=re.DOTALL)
    lines = text.splitlines(keepends=True)
    return "".join(
        l if "\x1b" in l else apply_inline_markdown(apply_block_line(l))
        for l in lines
    )
```

## Integration in streaming path (`cli.py`)

```python
if out is line:
    if _RICH_RESPONSE and _display._code_highlight_active:
        line = apply_inline_markdown(apply_block_line(line), reset_suffix=_tc)
    _cprint(f"{_tc}{line}{_RST}" if _tc else line)
```

Same change at the `_flush_stream` partial-line site, using `out is self._stream_buf`
as the plain-text identity check (not `out is line`) since the buffer variable name differs.

`apply_block_line` imported alongside `apply_inline_markdown` in the
existing `try` block in `cli.py`.

> **Note**: PR4 (`StreamingBlockBuffer`) replaces this streaming snippet.
> The `out is line` branch will be restructured — PR3's version is the
> correct interim state, not the final one.

## Tests — `tests/test_rich_output.py`

Add `TestApplyBlockLine`:

| test | input | expected |
|------|-------|----------|
| h1 stripped and bold | `# Foo` | no `#`, `\033[1;97m` present |
| h2 dimmer than h1 | `## Foo` | `\033[1;37m`, not `97m` |
| h4–h6 bold-dim | `#### Foo` | `\033[1;2m` |
| h1 with inline span | `# **Foo**` | bold `Foo` inside h1 colour |
| hr `---` replaced | `---` | `─` repeated, no `-` |
| hr `***` replaced | `***` | `─` repeated |
| non-hr dashes unchanged | `some --- text` | unchanged |
| blockquote gutter | `> hello` | `▌` present, `hello` present |
| blockquote nested collapsed | `>> deep` | single `▌` |
| blockquote inline span | `> **bold**` | bold rendered inside gutter |
| list bullet `•` | `- item` | `• item` |
| list bullet `◦` nested | `  - item` | `◦ item` |
| list bullet `▸` double-nested | `    - item` | `▸ item` |
| list `*` and `+` | `* item`, `+ item` | `• item` each |
| ordered list unchanged | `1. item` | `1. item` |
| reference link suppressed | `[ref]: https://x.com` | empty |
| ANSI lines skipped | line starting with `\x1b` | unchanged |

Add to `TestApplyInlineMarkdown`:

| test | input | expected |
|------|-------|----------|
| `<em>` italic | `<em>foo</em>` | `\033[3m` + `foo`, no tags |
| `<strong>` bold | `<strong>foo</strong>` | `\033[1m` + `foo`, no tags |
| link underlined | `[click here](https://x.com)` | `\033[4mclick here\033[0m` |
| image placeholder | `![logo](img.png)` | `[img: logo]`, dim |
| image before link | `![a](u) [b](v)` | both processed, correct order |

## Non-goals (this PR)

- Setext headings, tables, multi-line blockquote continuation — see
  `spec-markdown-stateful-blocks.md`
- Nested blockquotes beyond single-level collapse
- HTML block elements (`<div>`, `<p>`, etc.)
