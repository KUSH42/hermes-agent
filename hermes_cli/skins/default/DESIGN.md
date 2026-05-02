---
version: alpha
name: default
description: Hermes default — gold accent on near-black
colors:
  banner-border: '#CD7F32'
  banner-title: '#FFD700'
  banner-accent: '#FFBF00'
  banner-dim: '#B8860B'
  banner-text: '#FFF8DC'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#FFBF00'
  ui-label: '#4dd0e1'
  ui-ok: '#4caf50'
  ui-error: '#ef5350'
  ui-warn: '#ffa726'
  prompt: '#FFF8DC'
  input-rule: '#CD7F32'
  response-border: '#FFD700'
  session-label: '#DAA520'
  session-border: '#8B8682'
  rule-start: '#555555'
  rule-end: '#2A2A2A'
x-hermes:
  schema: 1
  branding:
    agent_name: Hermes Agent
    welcome: Welcome to Hermes Agent! Type your message or /help for commands.
    goodbye: 'Goodbye! ⚕'
    response_label: ' ⚕ Hermes '
    prompt_symbol: '❯ '
    help_header: '(^_^)? Available Commands'
  spinner:
    style: dots
  syntax:
    scheme: hermes
  diff:
    deletion_bg: '#781414'
    addition_bg: '#145a14'
    intra_del_bg: '#9b1c1c'
    intra_add_bg: '#166534'
  tool_prefix: ┊
  component-vars:
    tool-tier-read-accent:     '#FFBF00'
    tool-tier-write-accent:    '#4caf50'
    tool-tier-exec-accent:     '#4caf50'
    tool-tier-search-accent:   '#FFBF00'
    tool-tier-shell-accent:    '#4caf50'
    tool-tier-browse-accent:   '#FFBF00'
    tool-tier-mcp-accent:      '#9b59b6'
    tool-tier-thinking-accent: '#FFBF00'
    tool-tier-tooling-accent:  '#FFBF00'
    tool-tier-file-accent:     '#FFBF00'
    tool-tier-query-accent:    '#FFBF00'
    tool-tier-agent-accent:    '#FFBF00'
    reasoning-accent:          '#FFBF00'
    browse-turn:  '#FFBF00'
    browse-code:  '#4caf50'
    browse-tool:  '#9b59b6'
    browse-diff:  '#e040fb'
    browse-media: '#00bcd4'
    cite-chip-bg: '#1a1a0a'
    cite-chip-fg: '#DAA520'
    error-dim:        '#8B2020'
    success-dim:      '#1E5C1E'
    warning-dim:      '#5C4A00'
    text-muted-dim:   '#3A3A3A'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Default

Hermes default — gold accent on near-black. Canonical reference skin and the last-resort fallback used when no other skin can be resolved.
