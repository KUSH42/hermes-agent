---
version: alpha
name: tokyo-night
description: Tokyo Night — deep navy dark theme with blue-purple neon accents
colors:
  foreground: '#c0caf5'
  background: '#1a1b26'
  accent: '#7aa2f7'
  accent-dim: '#3d5994'
  success: '#9ece6a'
  warning: '#e0af68'
  error: '#f7768e'
  muted: '#565f89'
  border: '#292e42'
  selection: '#364a82'
  glass-tint: '#1a1b26'
  glass-border: '#292e42'
  glass-edge: '#7aa2f7'
  banner-title: '#7aa2f7'
  banner-accent: '#bb9af7'
  banner-dim: '#3d5994'
  banner-border: '#292e42'
  banner-text: '#c0caf5'
  input-rule: '#7aa2f7'
  prompt: '#bb9af7'
  response-border: '#7aa2f7'
  ui-accent: '#bb9af7'
  ui-ok: '#9ece6a'
  ui-error: '#f7768e'
  ui-warn: '#e0af68'
components:
  app:
    backgroundColor: '{colors.background}'
    textColor: '{colors.foreground}'
x-hermes:
  schema: 1
  vars:
    preview-syntax-theme: tokyo-night
  branding:
    agent_name: Hermes
    welcome: All your dreams are in this city at night.
    goodbye: Goodnight. ⟁
    response_label: ' ⟁ Hermes '
    prompt_symbol: '❯ '
    help_header: (⟁) Commands
  spinner:
    style: dots
    thinking_faces:
    - (◈)
    - (⌁)
    - (◇)
    - (⊛)
    waiting_faces:
    - (·)
    - (.·)
    - (··)
    thinking_verbs:
    - processing
    - thinking
    - analyzing
    - computing
    - reasoning
  syntax:
    scheme: tokyo-night
    overrides: {}
  diff:
    deletion_bg: '#2a1020'
    addition_bg: '#0f2a1a'
    deletion_fg: '#f7768e'
    addition_fg: '#9ece6a'
    line_number: '#565f89'
    hunk_header: 'bold #bb9af7'
    filename: 'bold #7aa2f7'
  component-vars:
    app-bg: '#1a1b26'
    brand-glyph-color: '#bb9af7'
    browse-code: '#9ece6a'
    browse-diff: '#bb9af7'
    browse-media: '#73daca'
    browse-tool: '#7aa2f7'
    browse-turn: '#e0af68'
    chevron-base: '#c0caf5'
    chevron-done: '#9ece6a'
    chevron-error: '#f7768e'
    chevron-rev-search: '#FFBF00'
    chevron-completion: '#5F9FD7'
    chevron-locked: '#666666'
    chevron-file: '#e0af68'
    chevron-shell: '#9ece6a'
    chevron-stream: '#7aa2f7'
    cite-chip-bg: '#1f2335'
    cite-chip-fg: '#7aa2f7'
    completion-empty-bg: '#24283b'
    cursor-color: '#c0caf5'
    cursor-placeholder: '#444b6a'
    cursor-selection-bg: '#33467c'
    diff-add-bg: '#0f2a1a'
    diff-del-bg: '#2a1020'
    info: '#7aa2f7'
    syntax-theme: tokyo-night
    syntax-scheme: tokyo-night
    drawbraille-canvas-color: '#7aa2f7'
    footnote-ref-color: '#565f89'
    fps-hud-bg: '#16161e'
    fuzzy-match-color: '#e0af68'
    ghost-text-color: '#444b6a'
    nameplate-active-color: '#7aa2f7'
    nameplate-decrypt-color: '#9ece6a'
    nameplate-idle-color: '#444b6a'
    panel-border: '#292e42'
    primary-darken-3: '#3d5994'
    rule-accent-color: '#7aa2f7'
    rule-accent-dim-color: '#3d5994'
    rule-bg-color: '#1a1b26'
    rule-dim-color: '#444b6a'
    running-indicator-dim-color: '#444b6a'
    running-indicator-hi-color: '#e0af68'
    scrollbar: '#7aa2f7'
    spinner-shimmer-dim: '#444b6a'
    spinner-shimmer-peak: '#c0caf5'
    status-context-color: '#7aa2f7'
    status-error-color: '#f7768e'
    status-running-color: '#e0af68'
    status-warn-color: '#ff9e64'
    accent-interactive: '#7dcfff'
    tool-mcp-accent: '#bb9af7'
    tool-vision-accent: '#73daca'
    user-echo-bullet-color: '#e0af68'
    plan-now-fg: '#7dcfff'
    plan-pending-fg: '#444b6a'
    pane-border: '#1f2335'
    pane-border-focused: '#7aa2f7'
    pane-title-fg: '#444b6a'
    pane-divider: '#16161e'
    error-auth: '#eab308'
    error-critical: '#ef4444'
    error-network: '#f97316'
    error-timeout: '#f59e0b'
    tool-glyph-mcp: '#9b59b6'
    overlay-selection-bg: '#3d4863'
    error-dim: '#8B2020'
    success-dim: '#1E5C1E'
    warning-dim: '#5C4A00'
    text-muted-dim: '#3A3A3A'
    tool-header-gutter-color: '#7aa2f7'
    tool-tier-read-accent: '#7aa2f7'
    tool-tier-write-accent: '#9ece6a'
    tool-tier-exec-accent: '#9ece6a'
    tool-tier-search-accent: '#7aa2f7'
    tool-tier-shell-accent: '#9ece6a'
    tool-tier-browse-accent: '#7aa2f7'
    tool-tier-mcp-accent: '#bb9af7'
    tool-tier-thinking-accent: '#7aa2f7'
    reasoning-accent: '#7aa2f7'
    tool-tier-tooling-accent: '#7aa2f7'
    tool-tier-file-accent: '#73daca'
    tool-tier-query-accent: '#7dcfff'
    tool-tier-agent-accent: '#bb9af7'
---

# Tokyo-Night

Tokyo Night — deep navy dark theme with blue-purple neon accents

This skin is the canonical DESIGN.md form of `skins/tokyo-night.yaml`.
