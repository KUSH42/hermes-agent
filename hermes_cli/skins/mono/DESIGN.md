---
version: alpha
name: mono
description: Pure greyscale — no chromatic accent
colors:
  banner-border: '#555555'
  banner-title: '#e6edf3'
  banner-accent: '#aaaaaa'
  banner-dim: '#444444'
  banner-text: '#c9d1d9'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#aaaaaa'
  ui-label: '#888888'
  ui-ok: '#888888'
  ui-error: '#cccccc'
  ui-warn: '#999999'
  prompt: '#c9d1d9'
  input-rule: '#444444'
  response-border: '#aaaaaa'
  session-label: '#888888'
  session-border: '#555555'
  rule-start: '#444444'
  rule-end: '#222222'
x-hermes:
  schema: 1
  branding:
    agent_name: Hermes Agent
    welcome: Welcome to Hermes Agent! Type your message or /help for commands.
    goodbye: 'Goodbye! ⚕'
    response_label: ' ⚕ Hermes '
    prompt_symbol: '❯ '
    help_header: '[?] Available Commands'
  spinner:
    style: none
  syntax:
    scheme: solarized-dark
  diff:
    deletion_bg: '#3A3030'
    addition_bg: '#2F3A30'
    intra_del_bg: '#4A3A3A'
    intra_add_bg: '#3A4A3A'
    deletion_marker_fg: '#D0D0D0'
    addition_marker_fg: '#F0F0F0'
  tool_prefix: ┊
  component-vars:
    tool-tier-read-accent:     '#aaaaaa'
    tool-tier-write-accent:    '#cccccc'
    tool-tier-exec-accent:     '#cccccc'
    tool-tier-search-accent:   '#aaaaaa'
    tool-tier-shell-accent:    '#cccccc'
    tool-tier-browse-accent:   '#aaaaaa'
    tool-tier-mcp-accent:      '#888888'
    tool-tier-thinking-accent: '#aaaaaa'
    tool-tier-tooling-accent:  '#aaaaaa'
    tool-tier-file-accent:     '#aaaaaa'
    tool-tier-query-accent:    '#aaaaaa'
    tool-tier-agent-accent:    '#e6edf3'
    reasoning-accent:          '#aaaaaa'
    browse-turn:  '#cccccc'
    browse-code:  '#888888'
    browse-tool:  '#aaaaaa'
    browse-diff:  '#bbbbbb'
    browse-media: '#999999'
    cite-chip-bg: '#222222'
    cite-chip-fg: '#cccccc'
    error-dim:        '#444444'
    success-dim:      '#3a3a3a'
    warning-dim:      '#4a4a4a'
    text-muted-dim:   '#2a2a2a'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Mono

Pure greyscale — no chromatic accent. The shared `error-auth`/`error-network`/`error-timeout` triple is the single intentional chromatic exception (error-category semantics).
