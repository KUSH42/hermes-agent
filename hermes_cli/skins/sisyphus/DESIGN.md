---
version: alpha
name: sisyphus
description: Stone-grey monochrome with a single warm tier accent
stream_effect: generator
colors:
  foreground: '#F5F5F5'
  background: '#1E1E1E'
  accent: '#E7E7E7'
  accent-dim: '#4A4A4A'
  success: '#919191'
  warning: '#B7B7B7'
  error: '#E7E7E7'
  muted: '#656565'
  border: '#4A4A4A'
  selection: '#3A3A3A'
  glass-tint: '#1E1E1E'
  glass-border: '#656565'
  glass-edge: '#B7B7B7'
  banner-border: '#B7B7B7'
  banner-title: '#F5F5F5'
  banner-accent: '#E7E7E7'
  banner-dim: '#4A4A4A'
  banner-text: '#D3D3D3'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#E7E7E7'
  ui-label: '#D3D3D3'
  ui-ok: '#919191'
  ui-error: '#E7E7E7'
  ui-warn: '#B7B7B7'
  prompt: '#F5F5F5'
  input-rule: '#656565'
  response-border: '#B7B7B7'
  session-label: '#919191'
  session-border: '#656565'
  rule-start: '#4A4A4A'
  rule-end: '#222222'
x-hermes:
  startup_tte:
    effect: crumble
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#F5F5F5'
        - '#D3D3D3'
        - '#B7B7B7'
        - '#919191'
        - '#6A6A6A'
        - '#4A4A4A'
        - '#919191'
        - '#6A6A6A'
        - '#4A4A4A'
  logo_startup_tte:
    effect: highlight
  schema: 1
  branding:
    agent_name: Sisyphus Agent
    welcome: Welcome to Sisyphus Agent! Type your message or /help for commands.
    goodbye: The boulder waits. ◉
    response_label: ' ◉ Sisyphus '
    prompt_symbol: '◉ ❯ '
    help_header: (◉) Available Commands
  spinner:
    style: grow
    waiting_faces:
    - (◉)
    - (◌)
    - (◬)
    - (⬤)
    - (::)
    thinking_faces:
    - (◉)
    - (◬)
    - (◌)
    - (○)
    - (●)
    thinking_verbs:
    - finding traction
    - measuring the grade
    - resetting the boulder
    - counting the ascent
    - testing leverage
    - setting the shoulder
    - pushing uphill
    - enduring the loop
    wings:
    - - ⟪◉
      - ◉⟫
    - - ⟪◬
      - ◬⟫
    - - ⟪◌
      - ◌⟫
    - - ⟪⬤
      - ⬤⟫
  syntax:
    scheme: hermes
  diff:
    deletion_bg: '#3E3E3E'
    addition_bg: '#303030'
    intra_del_bg: '#555555'
    intra_add_bg: '#464646'
    deletion_marker_fg: '#D6D6D6'
    addition_marker_fg: '#F5F5F5'
  tool_prefix: │
  banner_logo: '[bold #F5F5F5]███████╗██╗███████╗██╗   ██╗██████╗ ██╗  ██╗██╗   ██╗███████╗       █████╗  ██████╗
    ███████╗███╗   ██╗████████╗[/]

    [bold #D3D3D3]██╔════╝██║██╔════╝╚██╗ ██╔╝██╔══██╗██║  ██║██║   ██║██╔════╝      ██╔══██╗██╔════╝
    ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #B7B7B7]███████╗██║███████╗ ╚████╔╝ ██████╔╝███████║██║   ██║███████╗█████╗███████║██║  ███╗█████╗  ██╔██╗
    ██║   ██║[/]

    [bold #919191]╚════██║██║╚════██║  ╚██╔╝  ██╔═══╝ ██╔══██║██║   ██║╚════██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]

    [bold #6A6A6A]███████║██║███████║   ██║   ██║     ██║  ██║╚██████╔╝███████║      ██║  ██║╚██████╔╝███████╗██║
    ╚████║   ██║[/]

    [bold #4A4A4A]╚══════╝╚═╝╚══════╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝      ╚═╝  ╚═╝
    ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]

    '
  banner_hero: '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⣠⣾⣿⣿⣿⣿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⣿⣿⣷⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠘⢿⣿⣿⣿⣿⣿⡿⠃⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠙⠿⣿⠿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⣰⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⣰⣿⣿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⣰⣿⣿⣿⣿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⣀⣴⣿⣿⣿⣿⣿⣿⣦⣀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀━━━━━━━━━━━━━━━━━━━━━━━⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀the boulder⠀⠀⠀⠀⠀⠀⠀⠀⠀

    '
  component-vars:
    tool-tier-read-accent: '#D3D3D3'
    tool-tier-write-accent: '#919191'
    tool-tier-exec-accent: '#919191'
    tool-tier-search-accent: '#D3D3D3'
    tool-tier-shell-accent: '#919191'
    tool-tier-browse-accent: '#D3D3D3'
    tool-tier-mcp-accent: '#B7B7B7'
    tool-tier-thinking-accent: '#D3D3D3'
    tool-tier-tooling-accent: '#D3D3D3'
    tool-tier-file-accent: '#D3D3D3'
    tool-tier-query-accent: '#D3D3D3'
    tool-tier-agent-accent: '#F5F5F5'
    reasoning-accent: '#D3D3D3'
    user-accent: '#D3D3D3'
    browse-turn: '#E7E7E7'
    browse-code: '#919191'
    browse-tool: '#B7B7B7'
    browse-diff: '#D3D3D3'
    browse-media: '#A8A8A8'
    cite-chip-bg: '#2A2A2A'
    cite-chip-fg: '#D3D3D3'
    error-dim: '#656565'
    success-dim: '#3A3A3A'
    warning-dim: '#5C5C5C'
    text-muted-dim: '#2C2C2C'
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
    brand-glyph-color: '#E7E7E7'
    scrollbar: '#5f87d7'
    drawbraille-canvas-color: '#00d7ff'
    panel-border: '#333333'
    footnote-ref-color: '#888888'
    tool-mcp-accent: '#9b59b6'
    tool-vision-accent: '#00bcd4'
    diff-add-bg: '#1a3a1a'
    diff-del-bg: '#3a1a1a'
    info: '#58A6FF'
    nameplate-idle-color: '#4A4A4A'
    nameplate-active-color: '#E7E7E7'
    nameplate-decrypt-color: '#919191'
    spinner-shimmer-dim: '#555555'
    spinner-shimmer-peak: '#d8d8d8'
    attachment-chip-fg: '{colors.ui-accent}'
    attachment-chip-bg: '#1E1E1E'
    attachment-chip-shimmer-dim: '#555555'
    attachment-chip-shimmer-peak: '#d8d8d8'
    attachment-chip-remove-fg: '{colors.ui-error}'
    thinking-spinner-dim: '#4a4a4a'
    thinking-spinner-peak: '#d8d8d8'
    thinking-chroma-a: '#4a4a4a'
    thinking-chroma-b: '#e7e7e7'
    thinking-hue-shift-speed: '0.0'
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

# Sisyphus

Stone-grey monochrome with a single warm tier accent — austere greyscale with persistence.
