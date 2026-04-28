---
version: alpha
name: matrix
description: The Matrix — dark void and hacker green phosphor
colors:
  banner-accent: '#00ff41'
  banner-border: '#00a839'
  banner-dim: '#00a839'
  banner-text: '#00d849'
  banner-title: '#aaffc8'
  input-rule: '#00ff41'
  prompt: '#00ff9f'
  response-border: '#00a839'
  rule-end: '#1e1e1e'
  rule-start: '#00ff41'
  session-border: '#004d15'
  session-label: '#00c14d'
  ui-accent: '#00ff9f'
  ui-error: '#ff3333'
  ui-label: '#00e54a'
  ui-ok: '#00ff41'
  ui-warn: '#ffb000'
x-hermes:
  schema: 1
  branding:
    agent_name: Morpheus
    goodbye: Remember... all I'm offering is the truth. ⟁
    help_header: (⟁) Available Commands
    prompt_symbol: '❯ '
    response_label: ' ⟁ Matrix'
    welcome: Wake up, Neo...
  spinner:
    style: pulse
    thinking_faces:
    - (⚡)
    - (⌁)
    - (⟁)
    - (◇)
    thinking_verbs:
    - decrypting
    - tracing
    - jacking in
    - bending spoon
    - following white rabbit
    - dodging bullets
    - seeing through code
    - freeing mind
    waiting_faces:
    - (01)
    - (10)
    - (11)
    - (00)
    wings:
    - - ⟨
      - ⟩
    - - ⟨0
      - 1⟩
    - - ⟨⟁
      - ⟁⟩
  syntax:
    scheme: hermes
    overrides:
      comment: 'italic #4a8a5a'
      keyword: 'bold #00ff41'
      keyword_type: '#00d849'
      name: '#00ff41'
      name_function: '#aaffc8'
      number: '#aaffc8'
      operator: '#00ff9f'
      string: '#00d849'
  diff:
    addition_bg: '#0a2a14'
    addition_fg: '#00ff41'
    context_fg: '#6a8a6a'
    deletion_bg: '#2a0a0a'
    deletion_fg: '#ff6666'
    file_path_fg: '#00c14d'
    filename: 'bold #00ff9f'
    hunk_fg: '#00a839'
    hunk_header: 'bold #aaffc8'
    intra_add_bg: '#0f3d1c'
    intra_add_fg: '#aaffc8'
    intra_del_bg: '#3d0f0f'
    intra_del_fg: '#ff9999'
    line_number: '#00a839'
  markdown:
    blockquote_marker: ▌
    bullets:
    - •
    - ◦
    - ▸
    - ·
    code_span: '#00ff41'
    heading_1: 'bold #00ff9f'
    link: '#00ff9f underline'
    strike: strike
  component-vars:
    app-bg: '#0a0f0a'
    brand-glyph-color: '#aaffc8'
    chevron-base: '#00a839'
    chevron-done: '#00ff41'
    chevron-error: '#ff3333'
    chevron-rev-search: '#FFBF00'
    chevron-completion: '#5F9FD7'
    chevron-locked: '#666666'
    chevron-file: '#00d849'
    chevron-shell: '#00a839'
    chevron-stream: '#aaffc8'
    completion-empty-bg: '#0f1a0f'
    cursor-color: '#aaffc8'
    cursor-placeholder: '#2a6b33'
    cursor-selection-bg: '#00471c'
    fps-hud-bg: '#0f1a0f'
    fuzzy-match-color: '#aaffc8'
    ghost-text-color: '#2a6b33'
    primary-darken-3: '#005a1a'
    rule-accent-color: '#00ff41'
    rule-accent-dim-color: '#005a1a'
    rule-bg-color: '#0a0f0a'
    rule-dim-color: '#00471c'
    running-indicator-dim-color: '#005a1a'
    running-indicator-hi-color: '#aaffc8'
    scrollbar: '#00ff41'
    status-context-color: '#00e54a'
    status-error-color: '#ff3333'
    status-running-color: '#00ff9f'
    status-warn-color: '#ffb000'
    user-echo-bullet-color: '#00d849'
    drawbraille-canvas-color: '#00ff41'
    browse-code: '#aaffc8'
    browse-diff: '#ffb000'
    browse-media: '#00c14d'
    browse-tool: '#00d849'
    browse-turn: '#00ff41'
    cite-chip-bg: '#0f1a0f'
    cite-chip-fg: '#00d849'
    diff-add-bg: '#0a2a14'
    diff-del-bg: '#2a0a0a'
    info: '#58A6FF'
    syntax-theme: ansi_dark
    syntax-scheme: hermes
    footnote-ref-color: '#2a6b33'
    nameplate-active-color: '#00ff41'
    nameplate-decrypt-color: '#aaffc8'
    nameplate-idle-color: '#2a6b33'
    panel-border: '#004d15'
    spinner-shimmer-dim: '#005a1a'
    spinner-shimmer-peak: '#aaffc8'
    accent-interactive: '#00ff41'
    tool-mcp-accent: '#00d849'
    tool-vision-accent: '#aaffc8'
    plan-now-fg: '#00ff41'
    plan-pending-fg: '#2a6b33'
    pane-border: '#1a2f1a'
    pane-border-focused: '#00ff41'
    pane-title-fg: '#008f11'
    pane-divider: '#0d1f0d'
    error-auth: '#eab308'
    error-critical: '#ef4444'
    error-network: '#f97316'
    error-timeout: '#f59e0b'
    tool-glyph-mcp: '#9b59b6'
    overlay-selection-bg: '#003300'
    error-dim: '#4a1a1a'
    success-dim: '#0a2a0a'
    warning-dim: '#2a1e00'
    text-muted-dim: '#1a2a1a'
    tool-header-gutter-color: '#00ff41'
    tool-tier-read-accent: '#00d849'
    tool-tier-write-accent: '#00a839'
    tool-tier-exec-accent: '#aaffc8'
    tool-tier-search-accent: '#00d849'
    tool-tier-shell-accent: '#aaffc8'
    tool-tier-browse-accent: '#00d849'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#00d849'
    reasoning-accent: '#00d849'
    tool-tier-tooling-accent: '#00d849'
    tool-tier-file-accent: '#00cc88'
    tool-tier-query-accent: '#00bbee'
    tool-tier-agent-accent: '#cc44ff'
  tool_prefix: │
  tool_icons:
    search_files: ⌕
    web_search: ⌕
  banner_logo: "___  ___  ___ ___________ _______   __       ___  _____  _____ _   _ _____ \n|  \\/  | / _ \\_   _| ___ \\_   _\\ \\ / /      / _ \\|  __ \\|  ___| \\ | |_   _|\n| .  . |/ /_\\ \\| | | |_/ / | |  \\ V /______/ /_\\ \\ |  \\/| |__ |  \\| | | |  \n| |\\/| ||  _  || | |    /  | |  /   \\______|  _  | | __ |  __|| . ` | | |  \n| |  | || | | || | | |\\ \\ _| |_/ /^\\ \\     | | | | |_\\ \\| |___| |\\  | | |  \n\\_|  |_/\\_| |_/\\_/ \\_| \\_|\\___/\\/   \\/     \\_| |_/\\____/\\____/\\_| \\_/ \\_/  \n"
  banner_hero: "              /\\                \n             /#\\\\                \n            /###\\\\               \n           /#####\\\\              \n          /#######\\\\             \n         /#########\\\\            \n        /####/\\\\####\\\\           \n       /####/  \\\\####\\\\          \n      /####/    \\\\####\\\\         \n     /####/      \\\\####\\\\        \n    /####/        \\\\####\\\\       \n   /####/          \\\\####\\\\      \n  /####/____________\\\\####\\\\     \n /#########################\\\\    \n/###########################\\\\   \n"
---

# Matrix

The Matrix — dark void and hacker green phosphor

This skin is the canonical DESIGN.md form of `skins/matrix.yaml`.
