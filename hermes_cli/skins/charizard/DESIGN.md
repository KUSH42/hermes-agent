---
version: alpha
name: charizard
description: Volcanic orange on black
colors:
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
  schema: 1
  branding:
    agent_name: Charizard Agent
    welcome: Welcome to Charizard Agent! Type your message or /help for commands.
    goodbye: 'Flame out! ✦'
    response_label: ' ✦ Charizard '
    prompt_symbol: '✦ ❯ '
    help_header: '(✦) Available Commands'
  spinner:
    style: pulse
    waiting_faces: ['(✦)', '(▲)', '(◇)', '(<>)', '(🔥)']
    thinking_faces: ['(✦)', '(▲)', '(◇)', '(⌁)', '(🔥)']
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
      - ['⟪✦', '✦⟫']
      - ['⟪▲', '▲⟫']
      - ['⟪◌', '◌⟫']
      - ['⟪◇', '◇⟫']
  syntax:
    scheme: monokai
  diff:
    deletion_bg: '#5A2317'
    addition_bg: '#2E4A24'
    intra_del_bg: '#7A2E1D'
    intra_add_bg: '#3F6530'
  tool_prefix: │
  banner_logo: |
    [bold #FFF0D4] ██████╗██╗  ██╗ █████╗ ██████╗ ██╗███████╗ █████╗ ██████╗ ██████╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
    [bold #FFD39A]██╔════╝██║  ██║██╔══██╗██╔══██╗██║╚══███╔╝██╔══██╗██╔══██╗██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
    [#F29C38]██║     ███████║███████║██████╔╝██║  ███╔╝ ███████║██████╔╝██║  ██║█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║[/]
    [#E2832B]██║     ██╔══██║██╔══██║██╔══██╗██║ ███╔╝  ██╔══██║██╔══██╗██║  ██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]
    [#C75B1D]╚██████╗██║  ██║██║  ██║██║  ██║██║███████╗██║  ██║██║  ██║██████╔╝      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║[/]
    [#7A3511] ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]
  banner_hero: |
    [#FFD39A]⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⠶⠶⠶⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#F29C38]⠀⠀⠀⠀⠀⠀⣴⠟⠁⠀⠀⠀⠀⠈⠻⣦⠀⠀⠀⠀⠀⠀[/]
    [#F29C38]⠀⠀⠀⠀⠀⣼⠏⠀⠀⠀✦⠀⠀⠀⠀⠹⣧⠀⠀⠀⠀⠀[/]
    [#E2832B]⠀⠀⠀⠀⢰⡟⠀⠀⣀⣤⣤⣤⣀⠀⠀⠀⢻⡆⠀⠀⠀⠀[/]
    [#E2832B]⠀⠀⣠⡾⠛⠁⣠⣾⠟⠉⠀⠉⠻⣷⣄⠀⠈⠛⢷⣄⠀⠀[/]
    [#C75B1D]⠀⣼⠟⠀⢀⣾⠟⠁⠀⠀⠀⠀⠀⠈⠻⣷⡀⠀⠻⣧⠀[/]
    [#C75B1D]⢸⡟⠀⠀⣿⡟⠀⠀⠀🔥⠀⠀⠀⠀⢻⣿⠀⠀⢻⡇[/]
    [#7A3511]⠀⠻⣦⡀⠘⢿⣧⡀⠀⠀⠀⠀⠀⢀⣼⡿⠃⢀⣴⠟⠀[/]
    [#7A3511]⠀⠀⠈⠻⣦⣀⠙⢿⣷⣤⣤⣤⣾⡿⠋⣀⣴⠟⠁⠀⠀[/]
    [#C75B1D]⠀⠀⠀⠀⠈⠙⠛⠶⠤⠭⠭⠤⠶⠛⠋⠁⠀⠀⠀⠀[/]
    [#F29C38]⠀⠀⠀⠀⠀⠀⠀⠀⣰⡿⢿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#F29C38]⠀⠀⠀⠀⠀⠀⠀⣼⡟⠀⠀⢻⣧⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [dim #7A3511]⠀⠀⠀⠀⠀⠀⠀tail flame lit⠀⠀⠀⠀⠀⠀⠀⠀[/]
  component-vars:
    tool-tier-read-accent:     '#F29C38'
    tool-tier-write-accent:    '#4caf50'
    tool-tier-exec-accent:     '#4caf50'
    tool-tier-search-accent:   '#F29C38'
    tool-tier-shell-accent:    '#4caf50'
    tool-tier-browse-accent:   '#F29C38'
    tool-tier-mcp-accent:      '#9b59b6'
    tool-tier-thinking-accent: '#F29C38'
    tool-tier-tooling-accent:  '#F29C38'
    tool-tier-file-accent:     '#F29C38'
    tool-tier-query-accent:    '#F29C38'
    tool-tier-agent-accent:    '#FFD39A'
    reasoning-accent:          '#F29C38'
    browse-turn:  '#FFD39A'
    browse-code:  '#4caf50'
    browse-tool:  '#9b59b6'
    browse-diff:  '#E2832B'
    browse-media: '#C75B1D'
    cite-chip-bg: '#2A1508'
    cite-chip-fg: '#FFD39A'
    error-dim:        '#7A2E1D'
    success-dim:      '#1E5C1E'
    warning-dim:      '#7A4500'
    text-muted-dim:   '#3A2818'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Charizard

Volcanic orange on black — burnt-orange and ember theme.
