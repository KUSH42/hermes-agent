# PR: block-level markdown rendering

> ⚠️ Stacked on `feat/rich-output-renderer` (inline markdown PR) — merge that first.

**Branch:** `feat/markdown-block-rendering`

## Summary

- Adds `apply_block_line(line)` — single-line-detectable block elements rendered to ANSI
- Extends `apply_inline_markdown` with images, links, and HTML inline tags
- Chains `apply_block_line` before `apply_inline_markdown` in both `format_response` and the streaming path

## What's rendered

| Element | Input | Output |
|---------|-------|--------|
| h1 | `# Foo` | bold bright-white, `#` stripped |
| h2 | `## Foo` | bold white |
| h3 | `### Foo` | bold |
| h4–h6 | `#### Foo` | bold dim |
| Horizontal rule | `---` / `***` / `___` | dim `─` line across terminal |
| Blockquote | `> text` | dim `▌ ` gutter + dim text |
| Nested blockquote | `>> text` | collapses to single `▌` |
| Unordered list | `- item` | `•` at depth 0, `◦` at 1, `▸` at 2, `·` at 3 |
| Ordered list | `1. item` | unchanged (already readable) |
| Reference link def | `[ref]: https://…` | suppressed (metadata, not prose) |
| Image | `![alt](url)` | `[img: alt]` dim placeholder |
| Link | `[text](url)` | underlined text, URL discarded |
| `<em>` | `<em>text</em>` | italic, tags stripped |
| `<strong>` | `<strong>text</strong>` | bold, tags stripped |

## Architecture

`apply_block_line` is purely line-local — no lookahead or state. Two early-exit guards:

- `"\x1b" in line` — already ANSI-rendered, skip
- `"\n" in line` — multi-line block from `StreamingBlockBuffer` (PR4), skip

Headings and blockquotes apply inline spans internally (with `reset_suffix` set to the heading/gutter style) so a closing `\033[0m` from a span doesn't kill the outer colour.

List lines do **not** inject ANSI, so the outer `apply_inline_markdown` call handles their inline spans naturally.

```
format_response(text):
  pass 1: fenced code blocks → ANSI highlighted   (existing)
  pass 2: per non-ANSI line:
            apply_block_line(line) → apply_inline_markdown(result)

Streaming (_emit_stream_text / _flush_stream):
  out is line → apply_inline_markdown(apply_block_line(line), reset_suffix=_tc)
```

## Files changed

- `agent/rich_output.py` — `apply_block_line`, extended `apply_inline_markdown`, updated `format_response`; removed dead `_MD_OL_RE`; fixed `_MD_REF_LINK_RE` to suppress titled reference-link definitions
- `cli.py` — import `apply_block_line`, chain in `_emit_stream_text` and `_flush_stream`
- `tests/test_rich_output.py` — `TestApplyBlockLine` (23 tests), 5 new `TestApplyInlineMarkdown` cases, 3 new `TestFormatResponseInlineMarkdown` cases

## Bug fixes included

- **`format_response` newline loss** — `splitlines(keepends=True)` fed newline-bearing strings into `apply_block_line` whose capture groups stop at `\n`; matched block elements (heading, hr, blockquote, list) were returned without `\n` and concatenated with the following line. Fixed by switching to `splitlines()` + manual `"\n".join` with trailing-newline restoration.
- **Blockquote `reset_suffix`** — inline spans inside blockquotes were resetting to terminal default instead of restoring the dim gutter style. Fixed by passing `reset_suffix=_BLOCKQUOTE_ANSI` to `apply_inline_markdown` in the blockquote branch (mirrors the existing heading branch pattern).
- **`_MD_REF_LINK_RE` titled forms** — the `$` anchor prevented suppression of reference-link definitions that include a title (`[ref]: url "Title"`, `[ref]: url (Title)`). Removed `$`; the URL `\S+` is sufficient to distinguish ref-links from prose.

## Known interim regression

`---` immediately after a paragraph renders as an hr instead of a setext h2. Corrected in PR4 (`StreamingBlockBuffer` intercepts the setext case before `apply_block_line` sees it; see `docs/spec-markdown-stateful-blocks.md`). Setext headings are rare in LLM output; the interim behaviour is acceptable.

## Non-goals (deferred to PR4)

- Setext headings (`===` / `---` underline)
- Tables
- Multi-line blockquote continuation (no `>` prefix on continuation lines)
