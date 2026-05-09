---
version: alpha
name: hermes
description: Hermes — gold accent on near-black
stream_effect: decrypt
colors:
  foreground: '#FFF8DC'
  background: '#1E1E1E'
  accent: '#FFBF00'
  accent-dim: '#B8860B'
  success: '#4caf50'
  warning: '#FFA726'
  error: '#ef5350'
  muted: '#555555'
  border: '#333333'
  selection: '#3A5A8C'
  glass-tint: '#1E1E1E'
  glass-border: '#333333'
  glass-edge: '#FFBF00'
  banner-border: '#CD7F32'
  banner-title: '#FFD700'
  banner-accent: '#FFBF00'
  banner-dim: '#B8860B'
  banner-text: '#FFD580'
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
  startup_tte:
    effect: vhstape
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#FFD700'
        - '#FFBF00'
        - '#CD7F32'
        - '#B8860B'
      noise_colors:
        - '#1e1e1f'
        - '#3c3b3d'
        - '#4a3200'
        - '#8B6914'
        - '#B8860B'
        - '#CD7F32'
      glitch_line_colors:
        - '#FFD700'
        - '#FFBF00'
        - '#CD7F32'
        - '#B8860B'
        - '#FFD700'
      glitch_wave_colors:
        - '#FFD700'
        - '#FFBF00'
        - '#CD7F32'
        - '#B8860B'
        - '#FFD700'
  logo_startup_tte:
    effect: highlight
  schema: 1
  branding:
    agent_name: Hermes Agent
    welcome: Welcome to Hermes Agent! Type your message or /help for commands.
    goodbye: Goodbye! ⚕
    response_label: ' ⚕ Hermes '
    prompt_symbol: '❯ '
    help_header: (^_^)? Available Commands
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
  banner_logo: '[bold #FFD700]██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #FFD700]██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #FFBF00]███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]

    [bold #FFBF00]██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]

    [bold #B8860B]██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]

    [bold #B8860B]╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]

    '
  banner_hero: '[#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFD700]⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀[/]

    [#FFD700]⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀[/]

    [#FFD700]⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀[/]

    [#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⡿⠛⢁⡈⠛⢿⣿⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣦⣤⣈⠁⢠⣴⣿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠻⢿⣿⣦⡉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⣦⣈⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣴⠦⠈⠙⠿⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣤⡈⠁⢤⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠑⢶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠁⢰⡆⠈⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⠈⣡⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    '
  component-vars:
    tool-tier-read-accent: '#FFBF00'
    tool-tier-write-accent: '#4caf50'
    tool-tier-exec-accent: '#4caf50'
    tool-tier-search-accent: '#FFBF00'
    tool-tier-shell-accent: '#4caf50'
    tool-tier-browse-accent: '#FFBF00'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#FFBF00'
    tool-tier-tooling-accent: '#FFBF00'
    tool-tier-file-accent: '#FFBF00'
    tool-tier-query-accent: '#FFBF00'
    tool-tier-agent-accent: '#FFBF00'
    reasoning-accent: '#FFBF00'
    user-accent: '#4db6ac'
    browse-turn: '#FFBF00'
    browse-code: '#4caf50'
    browse-tool: '#9b59b6'
    browse-diff: '#e040fb'
    browse-media: '#00bcd4'
    cite-chip-bg: '#1a1a0a'
    cite-chip-fg: '#DAA520'
    error-dim: '#8B2020'
    success-dim: '#1E5C1E'
    warning-dim: '#5C4A00'
    text-muted-dim: '#3A3A3A'
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
    thinking-chroma-a: '#b8860b'
    thinking-chroma-b: '#ffbf00'
    thinking-hue-shift-speed: '0.10'
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

# Default

Hermes default — gold accent on near-black. Canonical reference skin and the last-resort fallback used when no other skin can be resolved.
