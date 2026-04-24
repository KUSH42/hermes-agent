---
name: skin-yaml-authoring
description: >
  Pitfalls and patterns for authoring Hermes CLI skins (YAML in ~/.hermes/skins/).
  Covers Rich markup in banner_logo/banner_hero, YAML escaping for ASCII art,
  and common corruption vectors. Triggered when editing skin YAML files.
---

# Skin YAML Authoring Guide

## Banner Logo / Hero Art

`banner_logo` and `banner_hero` are Rich-markup strings rendered via `Text.from_markup()`.

### Rule 1: No orphan Rich tags
Every `[/]` closing tag MUST have a matching opening tag (e.g. `[#FFD700]`).
If the art is monochrome/plain, use NO tags at all — no `[/]` either.

```yaml
# BAD — orphan [/] causes MarkupError → fallback returns raw markup → corrupted dimensions
banner_hero: "                /\\\\  [/]"

# GOOD — plain art, no markup
banner_hero: "                /\\\\"
```

`resolve_banner_hero_assets()` catches `MarkupError` and falls back to the RAW string
(including literal `[/]` text). This corrupts hero width/height used by TTE animation.

### Rule 2: Backslash escaping in YAML

Three approaches, in order of reliability:

**Option A: `yaml.dump()` (RECOMMENDED)**
Let PyYAML handle escaping. Write art as a Python string, dump via `yaml.dump()`.

```python
import yaml
art_str = "  /\\\n /##\\\n"  # Python string with real backslashes
yaml.dump({"banner_hero": art_str}, f, default_flow_style=False, allow_unicode=True)
```

**Option B: Manual YAML double-quoted string**
Escape `\` as `\\"` in the YAML file. Do NOT use `json.dumps()` — it doubles backslashes.

```python
# json.dumps("/\\") → "/\\\\" (4 chars, double-escaped)
# YAML then reads "\\\\" as "\\" (2 chars) → art has double backslashes

# CORRECT manual escaping:
def yaml_double_quote(s):
    result = ['"']
    for ch in s:
        if ch == '\\': result.append('\\\\')
        elif ch == '"': result.append('\\"')
        elif ch == '\n': result.append('\\n')
        else: result.append(ch)
    result.append('"')
    return ''.join(result)
```

**Option C: YAML literal block scalar `|-`**
Preserves backslashes literally, BUT trailing `\` at end of line causes PyYAML
parser error (interpreted as line continuation). Must not have trailing backslashes.

### Rule 3: `json.dumps()` into YAML doubles backslashes

`json.dumps()` escapes `\` → `\\`. YAML double-quoted then reads `\\` as literal `\\`
(interpreted as two chars). Result: 2x backslash count. Art renders corrupted.

```
Python:  "/\\       (1 backslash)
JSON:    "/\\\\"    (2 backslashes in JSON encoding)
YAML:    reads as "/\\" (2 backslashes)  ← BUG
```

Always use `yaml.dump()` or manual escaping, never `json.dumps()`.

### Rule 4: `yaml.dump()` partial data hazard

When modifying only `banner_logo`/`banner_hero` in an existing skin file:

```python
# DANGEROUS — dumping subset and appending can corrupt sibling values
data = yaml.safe_load(path.read_text())
data["banner_hero"] = new_art
partial = yaml.dump({"banner_hero": new_art})
# If you extract "before" text and append partial, structure breaks

# SAFE — dump entire data structure
data["banner_hero"] = new_art
path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
```

## TTE Startup Effect + Custom Hero Art

TTE (TerminalTextEffects) frames use absolute cursor positioning designed for full
terminal control. They CANNOT be spliced into a partial banner region.

When using a custom `banner_hero` with different dimensions than the default caduceus:
- TTE receives hero text and produces animation frames with absolute ANSI positions
- These frames must be rendered directly, not spliced into the banner template
- After animation, remove the TTE widget and render the full static banner

## Verifying Skin Loads Correctly

```python
from hermes_cli.skin_engine import load_skin
from rich.text import Text

skin = load_skin("mytheme")
hero = skin.banner_hero

# 1. Rich parse
t = Text.from_markup(hero)
assert "[/]" not in t.plain, "Orphan tags in plain text"

# 2. Dimensions
lines = hero.splitlines()
print(f"Lines: {len(lines)}, Max width: {max(len(l) for l in lines)}")

# 3. Backslash count
print(f"Backslashes: {hero.count(chr(92))}")
```
