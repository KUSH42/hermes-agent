---
version: alpha
name: poseidon
description: Deep ocean blue with cyan highlights
stream_effect: cascade
colors:
  foreground: '#EAF7FF'
  background: '#1E1E1E'
  accent: '#5DB8F5'
  accent-dim: '#153C73'
  success: '#4caf50'
  warning: '#ffa726'
  error: '#ef5350'
  muted: '#555555'
  border: '#333333'
  selection: '#153C73'
  glass-tint: '#1E1E1E'
  glass-border: '#2A6FB9'
  glass-edge: '#5DB8F5'
  banner-border: '#2A6FB9'
  banner-title: '#A9DFFF'
  banner-accent: '#5DB8F5'
  banner-dim: '#153C73'
  banner-text: '#EAF7FF'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#5DB8F5'
  ui-label: '#A9DFFF'
  ui-ok: '#4caf50'
  ui-error: '#ef5350'
  ui-warn: '#ffa726'
  prompt: '#EAF7FF'
  input-rule: '#2A6FB9'
  response-border: '#5DB8F5'
  session-label: '#A9DFFF'
  session-border: '#496884'
  rule-start: '#1a4a7a'
  rule-end: '#0d2540'
x-hermes:
  startup_tte:
    effect: waves
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#A9DFFF'
        - '#EAF7FF'
        - '#5DB8F5'
        - '#2A6FB9'
        - '#153C73'
        - '#2A6FB9'
        - '#5DB8F5'
  logo_startup_tte:
    effect: highlight
  schema: 1
  branding:
    agent_name: Poseidon Agent
    welcome: Welcome to Poseidon Agent! Type your message or /help for commands.
    goodbye: Fair winds! Ψ
    response_label: ' Ψ Poseidon '
    prompt_symbol: 'Ψ ❯ '
    help_header: (Ψ) Available Commands
  spinner:
    style: bounce
    waiting_faces:
    - (≈)
    - (Ψ)
    - (∿)
    - (◌)
    - (◠)
    thinking_faces:
    - (Ψ)
    - (∿)
    - (≈)
    - (⌁)
    - (◌)
    thinking_verbs:
    - charting currents
    - sounding the depth
    - reading foam lines
    - steering the trident
    - tracking undertow
    - plotting sea lanes
    - calling the swell
    - measuring pressure
    wings:
    - - ⟪≈
      - ≈⟫
    - - ⟪Ψ
      - Ψ⟫
    - - ⟪∿
      - ∿⟫
    - - ⟪◌
      - ◌⟫
  syntax:
    scheme: nord
  diff:
    deletion_bg: '#433047'
    addition_bg: '#244A44'
    intra_del_bg: '#5A4060'
    intra_add_bg: '#2F6259'
  tool_prefix: │
  banner_logo: '[bold #A9DFFF]██████╗  ██████╗ ███████╗███████╗██╗██████╗  ██████╗
    ███╗   ██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #A9DFFF]██╔══██╗██╔═══██╗██╔════╝██╔════╝██║██╔══██╗██╔═══██╗████╗  ██║      ██╔══██╗██╔════╝
    ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #5DB8F5]██████╔╝██║   ██║███████╗█████╗  ██║██║  ██║██║   ██║██╔██╗ ██║█████╗███████║██║  ███╗█████╗  ██╔██╗
    ██║   ██║[/]

    [bold #5DB8F5]██╔═══╝ ██║   ██║╚════██║██╔══╝  ██║██║  ██║██║   ██║██║╚██╗██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]

    [bold #153C73]██║     ╚██████╔╝███████║███████╗██║██████╔╝╚██████╔╝██║ ╚████║      ██║  ██║╚██████╔╝███████╗██║
    ╚████║   ██║[/]

    [bold #153C73]╚═╝      ╚═════╝ ╚══════╝╚══════╝╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═══╝      ╚═╝  ╚═╝
    ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]

    '
  banner_hero: '[#EAF7FF]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#A9DFFF]⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣾⣿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#A9DFFF]⠀⠀⠀⠀⠀⠀⠀⢠⣿⠏⠀Ψ⠀⠹⣿⡄⠀⠀⠀⠀⠀⠀⠀[/]

    [#5DB8F5]⠀⠀⠀⠀⠀⠀⠀⣿⡟⠀⠀⠀⠀⠀⢻⣿⠀⠀⠀⠀⠀⠀⠀[/]

    [#5DB8F5]⠀⠀⠀≈≈≈≈≈⣿⡇⠀⠀⠀⠀⠀⢸⣿≈≈≈≈≈⠀⠀⠀[/]

    [#2A6FB9]⠀⠀⠀⠀⠀⠀⠀⣿⡇⠀⠀⠀⠀⠀⢸⣿⠀⠀⠀⠀⠀⠀⠀[/]

    [#2A6FB9]⠀⠀⠀⠀⠀⠀⠀⢿⣧⠀⠀⠀⠀⠀⣼⡿⠀⠀⠀⠀⠀⠀⠀[/]

    [#153C73]⠀⠀⠀⠀⠀⠀⠀⠘⢿⣷⣄⣀⣠⣾⡿⠃⠀⠀⠀⠀⠀⠀⠀[/]

    [#153C73]⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣿⣿⡿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [dim #153C73]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#2A6FB9]⠀⠀⠀⠀⠀≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈⠀⠀⠀⠀⠀[/]

    [#5DB8F5]⠀⠀⠀⠀⠀⠀≈≈≈≈≈≈≈≈≈≈≈≈≈⠀⠀⠀⠀⠀⠀[/]

    [dim #153C73]⠀⠀⠀⠀⠀⠀⠀deep waters hold⠀⠀⠀⠀⠀⠀⠀[/]

    '
  component-vars:
    tool-tier-read-accent: '#5DB8F5'
    tool-tier-write-accent: '#4caf50'
    tool-tier-exec-accent: '#4caf50'
    tool-tier-search-accent: '#5DB8F5'
    tool-tier-shell-accent: '#4caf50'
    tool-tier-browse-accent: '#5DB8F5'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#5DB8F5'
    tool-tier-tooling-accent: '#5DB8F5'
    tool-tier-file-accent: '#5DB8F5'
    tool-tier-query-accent: '#5DB8F5'
    tool-tier-agent-accent: '#A9DFFF'
    reasoning-accent: '#5DB8F5'
    user-accent: '#5DB8F5'
    browse-turn: '#A9DFFF'
    browse-code: '#4caf50'
    browse-tool: '#9b59b6'
    browse-diff: '#7AB8E0'
    browse-media: '#5DB8F5'
    cite-chip-bg: '#0E2238'
    cite-chip-fg: '#A9DFFF'
    error-dim: '#5C2828'
    success-dim: '#1E5C1E'
    warning-dim: '#5C4A00'
    text-muted-dim: '#1F3A55'
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
    thinking-chroma-a: '#153c73'
    thinking-chroma-b: '#5db8f5'
    thinking-hue-shift-speed: '0.12'
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

# Poseidon

Deep ocean blue with cyan highlights — ocean-god theme.
