---
version: alpha
name: slate
description: Cool blue-grey with steel highlights
stream_effect: gradient_tail
colors:
  foreground: '#c9d1d9'
  background: '#1E1E1E'
  accent: '#7eb8f6'
  accent-dim: '#4b5563'
  success: '#63D0A6'
  warning: '#e6a855'
  error: '#F7A072'
  muted: '#555555'
  border: '#4b5563'
  selection: '#2d3748'
  glass-tint: '#1E1E1E'
  glass-border: '#4b5563'
  glass-edge: '#7eb8f6'
  banner-border: '#4169e1'
  banner-title: '#7eb8f6'
  banner-accent: '#8EA8FF'
  banner-dim: '#4b5563'
  banner-text: '#c9d1d9'
  banner-warning: '#FF8C00'
  banner-warning-dim: '#CD6500'
  banner-key: '#FFD700'
  ui-accent: '#7eb8f6'
  ui-label: '#8EA8FF'
  ui-ok: '#63D0A6'
  ui-error: '#F7A072'
  ui-warn: '#e6a855'
  prompt: '#c9d1d9'
  input-rule: '#4169e1'
  response-border: '#7eb8f6'
  session-label: '#7eb8f6'
  session-border: '#4b5563'
  rule-start: '#3a5a8a'
  rule-end: '#1a2a40'
x-hermes:
  startup_tte:
    effect: binarypath
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#c9d1d9'
        - '#7eb8f6'
        - '#8EA8FF'
        - '#4b5563'
        - '#1a2a40'
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
    style: pulse
  syntax:
    scheme: one-dark
  diff:
    deletion_bg: '#3F2630'
    addition_bg: '#203D36'
    intra_del_bg: '#5A3240'
    intra_add_bg: '#2A544A'
  tool_prefix: ┊
  banner_logo: '[bold #8EA8FF]██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #8EA8FF]██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #7eb8f6]███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]

    [bold #7eb8f6]██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]

    [bold #4b5563]██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]

    [bold #4b5563]╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]

    '
  banner_hero: '[#8EA8FF]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#8EA8FF]⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀[/]

    [#8EA8FF]⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀[/]

    [#8EA8FF]⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀[/]

    [#8EA8FF]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⡿⠛⢁⡈⠛⢿⣿⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#7eb8f6]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣦⣤⣈⠁⢠⣴⣿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#7eb8f6]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠻⢿⣿⣦⡉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#7eb8f6]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⣦⣈⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#7eb8f6]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣴⠦⠈⠙⠿⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#7eb8f6]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣤⡈⠁⢤⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#4b5563]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#4b5563]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠑⢶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#4b5563]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠁⢰⡆⠈⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#4b5563]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⠈⣡⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    [#4b5563]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]

    '
  component-vars:
    tool-tier-read-accent: '#7eb8f6'
    tool-tier-write-accent: '#63D0A6'
    tool-tier-exec-accent: '#63D0A6'
    tool-tier-search-accent: '#7eb8f6'
    tool-tier-shell-accent: '#63D0A6'
    tool-tier-browse-accent: '#7eb8f6'
    tool-tier-mcp-accent: '#9b59b6'
    tool-tier-thinking-accent: '#7eb8f6'
    tool-tier-tooling-accent: '#7eb8f6'
    tool-tier-file-accent: '#7eb8f6'
    tool-tier-query-accent: '#7eb8f6'
    tool-tier-agent-accent: '#8EA8FF'
    reasoning-accent: '#7eb8f6'
    user-accent: '#7eb8f6'
    browse-turn: '#8EA8FF'
    browse-code: '#63D0A6'
    browse-tool: '#9b59b6'
    browse-diff: '#F7A072'
    browse-media: '#5C99D6'
    cite-chip-bg: '#1a2436'
    cite-chip-fg: '#8EA8FF'
    error-dim: '#7A4030'
    success-dim: '#2D5C48'
    warning-dim: '#6B4F28'
    text-muted-dim: '#2C3848'
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
    thinking-chroma-a: '#4b5563'
    thinking-chroma-b: '#8ea8ff'
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

# Slate

Cool blue-grey with steel highlights — developer-focused.
