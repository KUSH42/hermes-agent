---
version: alpha
name: ares
description: War-room bronze on charcoal
stream_effect: flash
colors:
  foreground: '#F1E6CF'
  background: '#1E1E1E'
  accent: '#DD4A3A'
  accent-dim: '#6B1717'
  success: '#4caf50'
  warning: '#FFA726'
  error: '#ef5350'
  muted: '#555555'
  border: '#333333'
  selection: '#3A5A8C'
  glass-tint: '#1E1E1E'
  glass-border: '#333333'
  glass-edge: '#DD4A3A'
  banner-border: '#9F1C1C'
  banner-title: '#C7A96B'
  banner-accent: '#DD4A3A'
  banner-dim: '#6B1717'
  banner-text: '#F1E6CF'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#DD4A3A'
  ui-label: '#C7A96B'
  ui-ok: '#4caf50'
  ui-error: '#ef5350'
  ui-warn: '#ffa726'
  prompt: '#F1E6CF'
  input-rule: '#9F1C1C'
  response-border: '#C7A96B'
  session-label: '#C7A96B'
  session-border: '#6E584B'
  rule-start: '#6B1717'
  rule-end: '#2A1010'
  status-bar-bg: '#1E1E1E'
  status-bar-text: '#F1E6CF'
x-hermes:
  startup_tte:
    effect: laseretch
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#E8915A'
        - '#D06B3A'
        - '#B8552E'
        - '#9A3520'
        - '#6B1717'
        - '#9A3520'
        - '#B8552E'
  logo_startup_tte:
    effect: laseretch
  schema: 1
  branding:
    agent_name: Ares Agent
    welcome: Welcome to Ares Agent! Type your message or /help for commands.
    goodbye: Farewell, warrior! ⚔
    response_label: ' ⚔ Ares '
    prompt_symbol: '⚔ '
    help_header: (⚔) Available Commands
  spinner:
    style: arrows
    waiting_faces:
    - (⚔)
    - (⛨)
    - (▲)
    - (<>)
    - (/)
    thinking_faces:
    - (⚔)
    - (⛨)
    - (▲)
    - (⌁)
    - (<>)
    thinking_verbs:
    - forging
    - marching
    - sizing the field
    - holding the line
    - hammering plans
    - tempering steel
    - plotting impact
    - raising the shield
    wings:
    - - ⟪⚔
      - ⚔⟫
    - - ⟪▲
      - ▲⟫
    - - ⟪╸
      - ╺⟫
    - - ⟪⛨
      - ⛨⟫
  syntax:
    scheme: gruvbox
  diff:
    deletion_bg: '#6F1D1B'
    addition_bg: '#3F5A2A'
    intra_del_bg: '#8C2F26'
    intra_add_bg: '#557A34'
  tool_prefix: ╎
  banner_logo: '[bold #E8915A] █████╗ ██████╗ ███████╗███████╗       █████╗  ██████╗
    ███████╗███╗   ██╗████████╗[/]

    [bold #D06B3A]██╔══██╗██╔══██╗██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #B8552E]███████║██████╔╝█████╗  ███████╗█████╗███████║██║  ███╗█████╗  ██╔██╗
    ██║   ██║[/]

    [bold #9A3520]██╔══██║██╔══██╗██╔══╝  ╚════██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]

    [#7A1F1B]██║  ██║██║  ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║[/]

    [#6B1717]╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]

    '
  banner_hero: '[#C7A96B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#A8743A]⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⠟⠻⣿⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8552E]⠀⠀⠀⠀⠀⠀⠀⣠⣾⡿⠋⠀⠀⠀⠙⢿⣷⣄⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8552E]⠀⠀⠀⠀⠀⢀⣾⡿⠋⠀⠀⢠⡄⠀⠀⠙⢿⣷⡀⠀⠀⠀⠀⠀[/]

    [#9A3520]⠀⠀⠀⠀⣰⣿⠟⠀⠀⠀⣰⣿⣿⣆⠀⠀⠀⠻⣿⣆⠀⠀⠀⠀[/]

    [#8A2A1B]⠀⠀⠀⢰⣿⠏⠀⠀⢀⣾⡿⠉⢿⣷⡀⠀⠀⠹⣿⡆⠀⠀⠀[/]

    [#9F1C1C]⠀⠀⠀⣿⡟⠀⠀⣠⣿⠟⠀⠀⠀⠻⣿⣄⠀⠀⢻⣿⠀⠀⠀[/]

    [#9F1C1C]⠀⠀⠀⣿⡇⠀⠀⠙⠋⠀⠀⚔⠀⠀⠙⠋⠀⠀⢸⣿⠀⠀⠀[/]

    [#6B1717]⠀⠀⠀⢿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⡿⠀⠀⠀[/]

    [#6B1717]⠀⠀⠀⠘⢿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣾⡿⠃⠀⠀⠀[/]

    [dim #6B1717]⠀⠀⠀⠀⠈⠻⣿⣷⣦⣤⣀⣀⣤⣤⣶⣿⠿⠋⠀⠀⠀⠀[/]

    [dim #6B1717]⠀⠀⠀⠀⠀⠀⠀⠉⠛⠿⠿⠿⠿⠛⠉⠀⠀⠀⠀⠀⠀⠀[/]

    [#DD4A3A]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⚔⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [dim #6B1717]⠀⠀⠀⠀⠀⠀⠀⠀war god online⠀⠀⠀⠀⠀⠀⠀⠀[/]

    '
  component-vars:
    tool-tier-read-accent: '#C7A96B'
    tool-tier-write-accent: '#4caf50'
    tool-tier-exec-accent: '#4caf50'
    tool-tier-search-accent: '#C7A96B'
    tool-tier-shell-accent: '#4caf50'
    tool-tier-browse-accent: '#C7A96B'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#C7A96B'
    tool-tier-tooling-accent: '#C7A96B'
    tool-tier-file-accent: '#C7A96B'
    tool-tier-query-accent: '#C7A96B'
    tool-tier-agent-accent: '#C7A96B'
    reasoning-accent: '#C7A96B'
    user-accent: '#C7A96B'
    browse-turn: '#C7A96B'
    browse-code: '#4caf50'
    browse-tool: '#9b59b6'
    browse-diff: '#DD4A3A'
    browse-media: '#A8746B'
    cite-chip-bg: '#1F1010'
    cite-chip-fg: '#C7A96B'
    error-dim: '#5C1414'
    success-dim: '#1E5C1E'
    warning-dim: '#7A4500'
    text-muted-dim: '#3A2C20'
    error-auth: '#eab308'
    error-network: '#f97316'
    error-timeout: '#f59e0b'
    app-bg: '#1E1E1E'
    cursor-color: '#FFF8DC'
    cursor-selection-bg: '#3A5A8C'
    overlay-selection-bg: '#333399'
    cursor-placeholder: '#555555'
    ghost-text-color: '#555555'
    chevron-base: '#FFF8DC'
    chevron-file: '#FFBF00'
    chevron-stream: '#6EA8D4'
    chevron-shell: '#A8D46E'
    chevron-done: '#4CAF50'
    chevron-error: '#E06C75'
    chevron-rev-search: '#FFBF00'
    chevron-completion: '#5F9FD7'
    chevron-locked: '#666666'
    fuzzy-match-color: '#FFD866'
    status-running-color: '#FFBF00'
    status-error-color: '#ef5350'
    status-warn-color: '#FFA726'
    status-context-color: '#5f87d7'
    running-indicator-hi-color: '#FFA726'
    running-indicator-dim-color: '#6e6e6e'
    fps-hud-bg: '#1a1a2e'
    user-echo-bullet-color: '#FFBF00'
    completion-empty-bg: '#2A2A2A'
    rule-dim-color: '#888888'
    rule-bg-color: '#1E1E1E'
    rule-accent-color: '#FFD700'
    rule-accent-dim-color: '#B8860B'
    primary-darken-3: '#4a7aaa'
    brand-glyph-color: '#FFD700'
    scrollbar: '#5f87d7'
    drawbraille-canvas-color: '#00d7ff'
    panel-border: '#333333'
    footnote-ref-color: '#888888'
    tool-mcp-accent: '#9b59b6'
    tool-vision-accent: '#00bcd4'
    diff-add-bg: '#1a3a1a'
    diff-del-bg: '#3a1a1a'
    info: '#58A6FF'
    nameplate-idle-color: '#888888'
    nameplate-active-color: '#7b68ee'
    nameplate-decrypt-color: '#00ff41'
    spinner-shimmer-dim: '#555555'
    spinner-shimmer-peak: '#d8d8d8'
    attachment-chip-fg: '{colors.ui-accent}'
    attachment-chip-bg: '#1E1E1E'
    attachment-chip-shimmer-dim: '#555555'
    attachment-chip-shimmer-peak: '#d8d8d8'
    attachment-chip-remove-fg: '{colors.ui-error}'
    thinking-spinner-dim: '#4a4a4a'
    thinking-spinner-peak: '#d8d8d8'
    thinking-chroma-a: '#dd4a3a'
    thinking-chroma-b: '#6b1717'
    thinking-hue-shift-speed: '0.20'
    accent-interactive: '#00bcd4'
    plan-now-fg: '#ffb454'
    plan-pending-fg: '#888888'
    pane-border: '#333333'
    pane-border-focused: '#5f87d7'
    pane-title-fg: '#888888'
    pane-divider: '#2a2a2a'
    tool-glyph-mcp: '#9b59b6'
    error-critical: '#ef4444'
    tool-header-max-gap: '8'
    tool-header-gutter-color: '#00bcd4'
---

# Ares

War-room bronze on charcoal — crimson-and-bronze war-god theme.
