---
version: alpha
name: charizard
description: Volcanic orange on black
stream_effect: glow_settle
colors:
  foreground: '#FFF0D4'
  background: '#1E1E1E'
  accent: '#F29C38'
  accent-dim: '#7A3511'
  success: '#4caf50'
  warning: '#ffa726'
  error: '#ef5350'
  muted: '#555555'
  border: '#333333'
  selection: '#3A5A8C'
  glass-tint: '#1E1E1E'
  glass-border: '#333333'
  glass-edge: '#F29C38'
  banner-border: '#C75B1D'
  banner-title: '#FFD39A'
  banner-accent: '#F29C38'
  banner-dim: '#7A3511'
  banner-text: '#FFF0D4'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#F29C38'
  ui-label: '#FFD39A'
  ui-ok: '#4caf50'
  ui-error: '#ef5350'
  ui-warn: '#ffa726'
  prompt: '#FFF0D4'
  input-rule: '#C75B1D'
  response-border: '#F29C38'
  session-label: '#FFD39A'
  session-border: '#6C4724'
  rule-start: '#7A3511'
  rule-end: '#2A1508'
x-hermes:
  startup_tte:
    effect: burn
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#FFD39A'
        - '#F29C38'
        - '#E2832B'
        - '#C75B1D'
        - '#9A4416'
        - '#7A3511'
        - '#C75B1D'
        - '#7A3511'
        - '#C75B1D'
        - '#F29C38'
  logo_startup_tte:
    effect: highlight
  schema: 1
  branding:
    agent_name: Charizard Agent
    welcome: Welcome to Charizard Agent! Type your message or /help for commands.
    goodbye: Flame out! ✦
    response_label: ' ✦ Charizard '
    prompt_symbol: '✦ ❯ '
    help_header: (✦) Available Commands
  spinner:
    style: pulse
    waiting_faces:
    - (✦)
    - (▲)
    - (◇)
    - (<>)
    - (🔥)
    thinking_faces:
    - (✦)
    - (▲)
    - (◇)
    - (⌁)
    - (🔥)
    thinking_verbs:
    - banking into the draft
    - measuring burn
    - reading the updraft
    - tracking ember fall
    - setting wing angle
    - holding the flame core
    - plotting a hot landing
    - coiling for lift
    wings:
    - - ⟪✦
      - ✦⟫
    - - ⟪▲
      - ▲⟫
    - - ⟪◌
      - ◌⟫
    - - ⟪◇
      - ◇⟫
  syntax:
    scheme: monokai
  diff:
    deletion_bg: '#5A2317'
    addition_bg: '#2E4A24'
    intra_del_bg: '#7A2E1D'
    intra_add_bg: '#3F6530'
  tool_prefix: │
  banner_logo: '[bold #FFD39A] ██████╗██╗  ██╗ █████╗ ██████╗ ██╗███████╗ █████╗ ██████╗
    ██████╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #F29C38]██╔════╝██║  ██║██╔══██╗██╔══██╗██║╚══███╔╝██╔══██╗██╔══██╗██╔══██╗      ██╔══██╗██╔════╝
    ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #E2832B]██║     ███████║███████║██████╔╝██║  ███╔╝ ███████║██████╔╝██║  ██║█████╗███████║██║  ███╗█████╗  ██╔██╗
    ██║   ██║[/]

    [bold #C75B1D]██║     ██╔══██║██╔══██║██╔══██╗██║ ███╔╝  ██╔══██║██╔══██╗██║  ██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]

    [bold #9A4416]╚██████╗██║  ██║██║  ██║██║  ██║██║███████╗██║  ██║██║  ██║██████╔╝      ██║  ██║╚██████╔╝███████╗██║
    ╚████║   ██║[/]

    [bold #7A3511] ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝       ╚═╝  ╚═╝
    ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]

    '
  banner_hero: '⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⠶⠶⠶⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⣴⠟⠁⠀⠀⠀⠀⠈⠻⣦⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⣼⠏⠀⠀⠀✦⠀⠀⠀⠀⠹⣧⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⢰⡟⠀⠀⣀⣤⣤⣤⣀⠀⠀⠀⢻⡆⠀⠀⠀⠀

    ⠀⠀⣠⡾⠛⠁⣠⣾⠟⠉⠀⠉⠻⣷⣄⠀⠈⠛⢷⣄⠀⠀

    ⠀⣼⠟⠀⢀⣾⠟⠁⠀⠀⠀⠀⠀⠈⠻⣷⡀⠀⠻⣧⠀

    ⢸⡟⠀⠀⣿⡟⠀⠀⠀🔥⠀⠀⠀⠀⢻⣿⠀⠀⢻⡇

    ⠀⠻⣦⡀⠘⢿⣧⡀⠀⠀⠀⠀⠀⢀⣼⡿⠃⢀⣴⠟⠀

    ⠀⠀⠈⠻⣦⣀⠙⢿⣷⣤⣤⣤⣾⡿⠋⣀⣴⠟⠁⠀⠀

    ⠀⠀⠀⠀⠈⠙⠛⠶⠤⠭⠭⠤⠶⠛⠋⠁⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⣰⡿⢿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⣼⡟⠀⠀⢻⣧⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀tail flame lit⠀⠀⠀⠀⠀⠀⠀⠀

    '
  component-vars:
    tool-tier-read-accent: '#F29C38'
    tool-tier-write-accent: '#4caf50'
    tool-tier-exec-accent: '#4caf50'
    tool-tier-search-accent: '#F29C38'
    tool-tier-shell-accent: '#4caf50'
    tool-tier-browse-accent: '#F29C38'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#F29C38'
    tool-tier-tooling-accent: '#F29C38'
    tool-tier-file-accent: '#F29C38'
    tool-tier-query-accent: '#F29C38'
    tool-tier-agent-accent: '#FFD39A'
    reasoning-accent: '#F29C38'
    user-accent: '#F29C38'
    browse-turn: '#FFD39A'
    browse-code: '#4caf50'
    browse-tool: '#9b59b6'
    browse-diff: '#E2832B'
    browse-media: '#C75B1D'
    cite-chip-bg: '#2A1508'
    cite-chip-fg: '#FFD39A'
    error-dim: '#7A2E1D'
    success-dim: '#1E5C1E'
    warning-dim: '#7A4500'
    text-muted-dim: '#3A2818'
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
    running-indicator-hi-color: '#ffd54f'
    running-indicator-dim-color: '#7a3511'
    fps-hud-bg: '#1a1a2e'
    user-echo-bullet-color: '#FFBF00'
    completion-empty-bg: '#2A2A2A'
    rule-dim-color: '#888888'
    rule-bg-color: '#1E1E1E'
    rule-accent-color: '#FFD700'
    rule-accent-dim-color: '#B8860B'
    primary-darken-3: '#4a7aaa'
    brand-glyph-color: '#FF5722'
    scrollbar: '#5f87d7'
    drawbraille-canvas-color: '#f29c38'
    panel-border: '#333333'
    footnote-ref-color: '#888888'
    tool-mcp-accent: '#9b59b6'
    tool-vision-accent: '#00bcd4'
    diff-add-bg: '#1a3a1a'
    diff-del-bg: '#3a1a1a'
    info: '#58A6FF'
    nameplate-idle-color: '#5A2A14'
    nameplate-active-color: '#F29C38'
    nameplate-decrypt-color: '#FFD54F'
    spinner-shimmer-dim: '#7a3511'
    spinner-shimmer-peak: '#fff0d4'
    attachment-chip-fg: '{colors.ui-accent}'
    attachment-chip-bg: '#1E1E1E'
    attachment-chip-shimmer-dim: '#555555'
    attachment-chip-shimmer-peak: '#d8d8d8'
    attachment-chip-remove-fg: '{colors.ui-error}'
    thinking-spinner-dim: '#7a3511'
    thinking-spinner-peak: '#fff0d4'
    thinking-chroma-a: '#f29c38'
    thinking-chroma-b: '#7a3511'
    thinking-hue-shift-speed: '0.25'
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

# Charizard

Volcanic orange on black — burnt-orange and ember theme.
