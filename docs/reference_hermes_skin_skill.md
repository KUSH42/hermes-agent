---
name: Hermes skin skill + reference file
description: Standalone skin authoring skill and companion reference file location in tui-development skill folder
type: reference
originSessionId: 427b68dc-fc00-464c-9405-975dcaf8dfd3
---
Skin authoring skill: `~/.claude/skills/hermes-skin/SKILL.md`
- Full skin creation guide: minimal starter, complete YAML schema, all component_vars, gotchas, TTE effects, precedence rules, programmatic API.

Canonical skin reference: `~/.claude/skills/tui-development/skin-reference.md`
- Detailed flat reference consumed by both the `hermes-skin` skill and `tui-development` skill.
- Update this file when new `component_vars`, semantic keys, or TTE effects are added.
- `tui-development/SKILL.md` has a quick-facts pointer + inline copy; `skin-reference.md` is the canonical version.

Checklist for adding a new CSS component var:
1. `COMPONENT_VAR_DEFAULTS` in `theme_manager.py`
2. `hermes.tcss` under `/* Component Part variables */`
3. `skin_engine.py` module docstring `component_vars:` block
4. `skin-reference.md` component_vars table
5. `hermes-skin/SKILL.md` component_vars table
