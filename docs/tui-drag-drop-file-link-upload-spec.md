# TUI drag-and-drop file link and upload spec

## Overview

This spec defines terminal drag-and-drop behavior for the Hermes Textual TUI.
In a terminal app, dragging a file usually arrives as pasted text rather than a
native GUI drop event. The goal is to let you drag files into the focused TUI
input and get the correct outcome without extra prompt syntax work:

- text-like files become `@path` references in the input
- image files become queued attachments in the existing image flow
- unsupported or unsafe file types fail clearly instead of being misrouted

Hermes already supports path references through `@` autocomplete, image
attachments through `attached_images` and `ImageBar`, and terminal-side
dragged-path detection through `_detect_file_drop()` in `cli.py`. This spec
extends that model into the TUI through paste-path detection instead of
creating a second attachment system.

> **Note:** This is a preview feature currently under active development.

## Goals

This change exists to make file drop behavior predictable and type-aware.

- Support dragging one or more local files into the focused TUI input.
- Reuse the current TUI path-linking flow for text and code files.
- Reuse the current TUI image-attachment flow for image files.
- Classify file types deterministically before mutating input state.
- Preserve thread-safety and avoid background worker races.
- Keep drop behavior visible through `HintBar`, `ImageBar`, and input changes.
- Add tests for event routing, classification, and failure states.

## Non-goals

This spec narrows scope to local desktop drag-and-drop in the Textual TUI.

- Do not redesign how the model consumes `@path` references.
- Do not add remote uploads, cloud storage, or browser-style multipart logic.
- Do not add generic binary-file attachments in the first patch.
- Do not change non-TUI prompt-toolkit behavior beyond optional helper reuse.
- Do not add directory-drop support in the first patch.

## Current behavior

Today, Hermes TUI has no dedicated dragged-file paste ingestion path.

- `HermesInput` supports typed and pasted text.
- `PathSearchProvider` and completion overlay support `@path` linking.
- `HermesApp.attached_images` drives `ImageBar` for image attachments.
- `cli.py::_detect_file_drop()` already recognizes terminal-pasted file paths
  and distinguishes image suffixes from other files in prompt-toolkit mode.

This means Hermes already has the semantic split needed for TUI drag handling,
but not the paste-path bridge.

## Problem statement

Without a TUI-specific dragged-path pipeline, pasted file paths are ambiguous.

- A dropped image should not become literal text in the prompt.
- A dropped source file should not silently become an image attachment.
- A dropped binary should not be injected as a useless `@path` if the agent
  cannot inspect it meaningfully.
- Multi-file drops need stable ordering and mixed-type handling rules.

The implementation must therefore classify the pasted file targets before deciding
whether to edit the prompt, attach images, reject the drop, or split a mixed
drop into multiple actions.

## User experience

### Activation model

The first patch is paste-driven, not native-drop-event driven.

- The terminal window must be focused.
- `HermesInput` must be the active text target.
- The implementation must detect dragged-file pastes from `events.Paste`.

The TUI does not currently have a native Textual drop event API in this
environment. The spec therefore targets terminal drag behavior, which arrives
as pasted file paths.

### Visible result

After a successful drop, Hermes must provide immediate feedback.

- For linked files, insert or append `@path` references into `HermesInput`.
- For attached images, update `attached_images` so `ImageBar` becomes source of
  truth for files queued for the next turn.
- Flash `HintBar` with a short summary such as `linked 2 files` or
  `attached 1 image`.

If a drop contains both linked files and images, Hermes must apply both
results and report both counts in one hint.

### Blocking states

When a choice or secret overlay is open, Hermes must reject dragged-file
paste handling and flash a short hint explaining that file drop is unavailable
while a modal prompt is active. This matches the existing rule that overlays
suppress input-side completion and other prompt-editing flows.

## File type routing

This feature depends on deterministic classification. The routing decision must
be made per file, then aggregated for the full dragged-file paste.

### Type classes

Hermes must classify dropped files into four classes.

1. `image`
2. `linkable_text`
3. `unsupported_binary`
4. `invalid`

### Routing matrix

Use this matrix for first implementation.

| Class | Detection rule | TUI result |
| --- | --- | --- |
| `image` | Suffix in existing image allowlist or MIME starts with `image/` | Append to `attached_images` |
| `linkable_text` | Text-like extension or MIME in text family | Insert `@path` token into input |
| `unsupported_binary` | File exists but not image and not text-like | Reject with hint |
| `invalid` | Missing path, non-file, unreadable target, or directory | Reject with hint |

### Required image types

The image class must include the existing prompt-toolkit list at minimum:

- `.png`
- `.jpg`
- `.jpeg`
- `.gif`
- `.webp`
- `.bmp`
- `.tiff`
- `.tif`
- `.svg`
- `.ico`

If MIME sniffing is available cheaply, it may accept additional `image/*`
files even when the suffix is unknown. Suffix-based acceptance remains source
of truth when MIME detection is absent.

### Required linkable text types

The linkable-text class must cover common files Hermes can reason about as
path references. The implementation must ship with an explicit allowlist rather
than a vague "non-binary" guess.

Initial allowlist:

- source code: `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.rs`, `.go`, `.java`,
  `.c`, `.cc`, `.cpp`, `.h`, `.hpp`, `.cs`, `.rb`, `.php`, `.swift`, `.kt`,
  `.scala`, `.sh`, `.bash`, `.zsh`, `.fish`
- config and data: `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.env`,
  `.xml`, `.csv`
- docs and prose: `.md`, `.txt`, `.rst`
- web and style assets: `.html`, `.css`, `.scss`, `.sass`, `.less`
- SQL and infra: `.sql`, `.tf`, `.dockerfile`

Files accepted by MIME as `text/*`, `application/json`, `application/xml`, or
`application/yaml` may also route to `linkable_text`.

### Filenames with spaces

The current TUI `@path` grammar does not accept spaces.

- `CompletionContext.PATH_REF` matches `[\w./\-]*`
- `PathCandidate.display` values therefore cannot contain spaces

For the first patch:

- image files with spaces are allowed as attachments
- linkable-text files with spaces must be rejected with a clear hint

Do not invent quoting or escaping rules for `@path` in this patch. That would
be a separate parser change.

### Unsupported binary types

The first patch must reject these as link targets and as uploads:

- archives such as `.zip`, `.tar`, `.gz`, `.bz2`, `.xz`, `.7z`
- office documents such as `.pdf`, `.docx`, `.xlsx`, `.pptx`
- media such as `.mp3`, `.wav`, `.mp4`, `.mov`, `.mkv`
- executables and disk images such as `.exe`, `.bin`, `.dmg`, `.iso`

These files are not useless forever. They are explicitly out of scope for the
initial TUI feature because Hermes does not have a clear attachment semantics
for them yet. Rejecting them is safer than pretending they are readable via
`@path`.

## Path formatting rules

Linkable files must be inserted as path references, not raw absolute paths.

- Prefer paths relative to `Path.cwd()` when possible.
- Use the same relative display style as `PathCandidate.display`.
- Fall back to absolute paths only when the file is outside `cwd`.

For files inside `cwd`, that means path tokens such as:

- `@src/app.py`
- `@docs/spec.md`

The final inserted token format must stay compatible with the existing
`CompletionContext.PATH_REF` and `CompletionContext.PLAIN_PATH_REF` behavior.
The drop path must not invent a new inline syntax.

### Multi-file insertion

When a dragged-file paste contains multiple linkable files, Hermes must insert
them in paste order separated by single spaces:

`@src/app.py @docs/spec.md @tests/test_app.py`

If the input already contains text, Hermes must add one leading space before
the first inserted token unless the cursor is already adjacent to whitespace.

## Event architecture

The implementation must stay inside current TUI ownership boundaries.

### New responsibilities

- `HermesInput`
  - detect dragged-file pastes in `_on_paste` or equivalent input-level hook
  - normalize pasted payload into local file paths
  - forward paths upward instead of mutating global app state directly
- `HermesApp`
  - own classification, routing, and user feedback
  - mutate `attached_images`
  - mutate `HermesInput` content through its public APIs
- shared helper
  - new pure helper to classify dropped files for both TUI and non-TUI use

### Proposed helper module

Add a small helper module or pure functions near TUI input code. Minimum API:

```python
@dataclass(frozen=True)
class DroppedFile:
    path: Path
    kind: Literal["image", "linkable_text", "unsupported_binary", "invalid"]
    reason: str = ""

def classify_dropped_file(path: Path, cwd: Path) -> DroppedFile: ...
def format_link_token(path: Path, cwd: Path) -> str: ...
```

If practical, refactor `cli.py::_detect_file_drop()` to reuse the same
allowlists so prompt-toolkit mode and TUI mode stop drifting.

### App-level handler

`HermesApp` must expose one handler for normalized file-path drops:

```python
def handle_file_drop(self, paths: list[Path]) -> None: ...
```

That method must:

1. reject dragged-file paste during blocking overlays
2. classify each path
3. attach accepted images
4. insert accepted `@path` tokens at current cursor
5. emit one consolidated hint
6. reject unsupported items without partial silent failure

Partial success is allowed, but the hint must mention rejected items.

## Detection details

The input side must not assume one terminal-specific payload shape.

The normalization layer must handle:

- one local file path
- multiple local file paths separated by newlines
- shell-escaped spaces in pasted paths, matching prompt-toolkit behavior
- URI forms such as `file:///...` when terminals expose them that way

The first implementation may reject directory pastes outright. If a directory
is detected, Hermes must flash a hint such as `directories not supported yet`.

## Mixed-drop behavior

Mixed dragged-file pastes must be legal when each item class is independently
legal.

Examples:

- one image + one `.py` file
  - result: image attached, `@file.py` inserted
- two images + one `.zip`
  - result: images attached, `.zip` rejected, hint mentions partial success
- one `.png` + one `.svg`
  - result: both attached as images

This avoids forcing users to separate a realistic working set into multiple
drop actions.

## Failure handling

Failures must be visible and specific.

- Missing file: `drop failed: file no longer exists`
- Directory: `drop failed: directories not supported`
- Unsupported binary: `drop failed: unsupported file type`
- Modal active: `file drop unavailable while prompt is open`

Hermes must never inject broken path text into the input as fallback.

## Security and safety

This feature accepts only local file references. It must not dereference
network URLs or shell-like pseudo paths.

- Do not expand arbitrary shell expressions.
- Do not run commands to inspect the file.
- Do not read full file contents during classification.
- Keep classification cheap: suffix first, MIME second only if inexpensive.

The TUI preview panel is not part of the drop pipeline. Preview remains tied to
autocomplete selection, not automatic file-drop inspection.

## Testing plan

Add focused TUI tests and pure-unit tests.

### Unit tests

Create pure tests for classification and token formatting.

- image suffix routes to `image`
- known text suffix routes to `linkable_text`
- binary suffix routes to `unsupported_binary`
- missing path routes to `invalid`
- relative-path formatter prefers `PathCandidate.display`-style relative paths
- formatter falls back to absolute path outside cwd
- spaced filenames route to rejection for `linkable_text`
- spaced image filenames still attach correctly

### TUI tests

Add async tests under `tests/tui/`.

- pasting one dragged text file inserts one `@path`
- pasting one dragged image updates `attached_images` and shows `ImageBar`
- mixed dragged-file paste performs both actions
- unsupported binary flashes rejection and does not mutate input
- dragged-file paste during active overlay is rejected
- multi-file text paste preserves order

Because Textual does not expose a native drop event here, keep the paste
normalizer thin and test `HermesApp.handle_file_drop()` directly. Add one
targeted input test for the dragged-file paste interception path.

## Implementation plan

Implement this in three phases.

1. Add pure classification and formatting helpers plus tests.
2. Add `HermesApp.handle_file_drop()` and direct tests for routing behavior.
3. Wire `HermesInput` dragged-file paste handling to the app handler and add
   end-to-end TUI tests where feasible.

This sequencing keeps file-type policy stable before UI event plumbing lands.

## Open questions

This spec intentionally leaves a few choices open for final patch review.

- Whether `.pdf` should stay rejected or later become a linkable path type.
- Whether `.svg` should remain image-only or become dual-routed as image plus
  linkable text in a future patch.
- Whether directory drops should later expand into multiple link tokens behind
  an explicit confirmation step.

## Next steps

Implement the helper layer first. After that, wire the TUI event path and add
tests before exposing the feature in help text or idle tips.
