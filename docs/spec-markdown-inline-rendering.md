# spec: inline markdown rendering for LLM responses

Convert lightweight markdown inline spans (`**bold**`, `*italic*`, `` `code` ``, `~~strike~~`) to ANSI styles when printing LLM responses in the terminal, both streaming and non-streaming.

## Problem

Plain-text markdown syntax (`**Line 88**`) is printed verbatim.  The asterisks are noise; the semantic signal (emphasis) is lost.

## Scope

**In scope**

| Syntax | ANSI output |
|--------|-------------|
| `**text**` or `__text__` | bold |
| `*text*` or `_text_` | italic (`\033[3m`) |
| `` `code` `` | bright-white, no further highlighting |
| `~~text~~` | strikethrough (`\033[9m`) |

**Out of scope** (handled elsewhere or too complex for line-by-line streaming)

- Fenced code blocks ` ``` ` — already handled by `StreamingCodeBlockHighlighter`
- Block-level elements: headings (`#`), lists (`-`/`*`), blockquotes (`>`)
- Links `[text](url)` — url not renderable in most terminals
- Nested spans (`**bold _italic_**`) — adds regex complexity for rare benefit

## Implementation plan

### 1. `apply_inline_markdown(line: str, reset_suffix: str = "") -> str`  — `agent/rich_output.py`

A pure function that takes a single line of plain text and returns it with ANSI codes injected.

```
apply_inline_markdown("see **Line 88** and `cdOffset`")
→ "see \033[1mLine 88\033[0m and \033[97mcdOffset\033[0m"
```

Implementation notes:
- Process patterns in a fixed priority order to avoid overlapping matches:
  1. Backtick code spans (`` `…` ``) — replace first so `*` inside backticks is untouched
  2. Bold (`**…**` / `__…__`)
  3. Italic (`*…*` / `_…_`) — single delimiters, after bold so `**` is already consumed
  4. Strikethrough (`~~…~~`)
- Use `re.sub` with a single compiled pattern per pass; do not recurse.
- Avoid false positives on `_snake_case_identifiers`, trailing-underscore tokens (`value_`), and cross-word matches (`_foo and bar_`): use `(?<![_\w])_([^_\s\n]+)_(?![_\w])`. The no-space restriction on the content is intentional — underscore italic with spaces is unusual in LLM output and would otherwise match `_word1 ... word2_` when two separate identifier underscores appear on the same line. Asterisk italic `*…*` allows spaces since false positives are far less likely. `__dunder__` is handled by the bold `__` pass running first.
- `reset_suffix` is appended immediately after each `\033[0m` closing a span. In the streaming path this is set to the active response text colour (`_tc`) so the colour is restored between adjacent spans. Defaults to `""` (no restoration needed in the non-streaming path).
- Must be idempotent: if the input already contains ANSI codes (i.e. `"\x1b" in line`), return it unchanged. Highlighted code block lines are fully escape-coded; plain LLM text never contains escape sequences, so this check is reliable.

### 2. `format_response` (non-streaming) — `agent/rich_output.py`

After the existing `re.sub` that handles fenced blocks, run `apply_inline_markdown` line-by-line on every non-code-block segment. Lines that contain `\x1b` are already highlighted code and are passed through untouched.

```python
def format_response(text: str) -> str:
    # existing code block pass
    text = re.sub(r"```(\w*)\n(.*?)```", _highlight, text, flags=re.DOTALL)
    # inline markdown pass — skip lines that are already ANSI (highlighted code)
    lines = text.splitlines(keepends=True)
    return "".join(
        l if "\x1b" in l else apply_inline_markdown(l)
        for l in lines
    )
```

### 3. Streaming path — `cli.py`

Two sites need updating: `_emit_stream_text` (complete lines) and `_flush_stream` (partial final line at end of stream).

Plain-text lines are identified by `out is line` — `StreamingCodeBlockHighlighter.process_line` returns the exact `line` object for pass-through text and a newly constructed highlighted string (which is never `is line`) for code blocks. This is more precise than the existing `"\n" in out` check, which should be replaced in both sites.

**`_emit_stream_text`** (inner loop):
```python
if out is line:
    # Plain text — apply inline markdown, then response text colour
    if _RICH_RESPONSE and _display._code_highlight_active:
        line = apply_inline_markdown(line, reset_suffix=_tc)
    _cprint(f"{_tc}{line}{_RST}" if _tc else line)
else:
    # Highlighted code block — emit as-is (has its own ANSI colouring)
    for hl_line in out.splitlines():
        _cprint(hl_line)
```

**`_flush_stream`** (partial line at end of stream):
```python
if _RICH_RESPONSE:
    out = self._stream_code_hl.process_line(self._stream_buf)
    if out is not None:
        if out is self._stream_buf and _display._code_highlight_active:
            out = apply_inline_markdown(out, reset_suffix=_tc)
        _cprint(f"{_tc}{out}{_RST}" if _tc else out)
    tail = self._stream_code_hl.flush()
    if tail:
        _cprint(tail)
```

Note: `_tc = getattr(self, "_stream_text_ansi", "")` is already assigned earlier in both methods.

### 4. Toggle

Inline markdown rendering is gated on both `_RICH_RESPONSE` (module-level, set at import time when `rich_output` is available) and `_display._code_highlight_active` (runtime toggle, driven by `/code-highlight`). This mirrors how the streaming code block highlighter is already gated: `_RICH_RESPONSE` enables the feature class, `_code_highlight_active` lets the user suppress it at runtime. When the user runs `/code-highlight off`, markdown rendering is also suppressed.

Access the flag via a module reference. `cli.py` currently only imports individual names from `agent.display` (e.g. `set_code_highlight_active`); add a module-level import:

```python
import agent.display as _display
```

Then check `_display._code_highlight_active` at call time. Do **not** use `from agent.display import _code_highlight_active` — that captures the value at import time and won't reflect runtime mutations made by `set_code_highlight_active()`.

Alternatively, add a public getter to `display.py`:

```python
def get_code_highlight_active() -> bool:
    return _code_highlight_active
```

and call `_display.get_code_highlight_active()`. Either approach works; the module-level import is simpler.

## Tests  — `tests/test_rich_output.py`

Add `TestApplyInlineMarkdown` class:

| test | input | expected |
|------|-------|----------|
| bold double-asterisk | `**foo**` | `\033[1mfoo\033[0m` |
| bold double-underscore | `__foo__` | `\033[1mfoo\033[0m` |
| italic single-asterisk | `*foo*` | `\033[3mfoo\033[0m` |
| italic single-underscore | `_foo_` | `\033[3mfoo\033[0m` |
| underscore inside word ignored | `snake_case_var` | unchanged |
| trailing underscore ignored | `value_` | unchanged |
| leading underscore ignored | `_private` | unchanged |
| backtick code span | `` `foo` `` | `\033[97mfoo\033[0m` |
| strikethrough | `~~foo~~` | `\033[9mfoo\033[0m` |
| mixed bold + code | `**Line 88**: \`cdOffset\`` | both spans rendered |
| asterisks inside backtick untouched | `` `**not bold**` `` | raw `**not bold**` preserved inside the code span |
| already-ANSI input passed through | `\033[32mgreen\033[0m` | unchanged |
| empty string | `""` | `""` |
| no markdown | `"plain text"` | `"plain text"` |
| reset_suffix restored between spans | `**a** and *b*` with `reset_suffix="\033[32m"` | `\033[0m\033[32m` between spans |

Add one integration case to `TestFormatResponse`: a response string mixing a fenced code block with surrounding prose that contains `**bold**` — assert code block lines are not double-escaped and prose bold is rendered.

## Non-goals / follow-up

- Heading / list / blockquote rendering — separate PR if wanted
- Nested span support — punted, adds regex complexity for rare benefit
- Rich `Markdown` widget — the line-by-line streaming constraint makes the Rich renderer impractical without a full buffering rewrite
