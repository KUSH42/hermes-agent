---
version: alpha
name: ares
description: War-room bronze on charcoal
colors:
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
x-hermes:
  schema: 1
  branding:
    agent_name: Ares Agent
    welcome: Welcome to Ares Agent! Type your message or /help for commands.
    goodbye: 'Farewell, warrior! ⚔'
    response_label: ' ⚔ Ares '
    prompt_symbol: '⚔ '
    help_header: '(⚔) Available Commands'
  spinner:
    style: arrows
    waiting_faces: ['(⚔)', '(⛨)', '(▲)', '(<>)', '(/)']
    thinking_faces: ['(⚔)', '(⛨)', '(▲)', '(⌁)', '(<>)']
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
      - ['⟪⚔', '⚔⟫']
      - ['⟪▲', '▲⟫']
      - ['⟪╸', '╺⟫']
      - ['⟪⛨', '⛨⟫']
  syntax:
    scheme: gruvbox
  diff:
    deletion_bg: '#6F1D1B'
    addition_bg: '#3F5A2A'
    intra_del_bg: '#8C2F26'
    intra_add_bg: '#557A34'
  tool_prefix: ╎
  banner_logo: |
    [bold #A3261F] █████╗ ██████╗ ███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
    [bold #B73122]██╔══██╗██╔══██╗██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
    [#C93C24]███████║██████╔╝█████╗  ███████╗█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║[/]
    [#D84A28]██╔══██║██╔══██╗██╔══╝  ╚════██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]
    [#E15A2D]██║  ██║██║  ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║[/]
    [#EB6C32]╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]
  banner_hero: |
    [#9F1C1C]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#9F1C1C]⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⠟⠻⣿⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#C7A96B]⠀⠀⠀⠀⠀⠀⠀⣠⣾⡿⠋⠀⠀⠀⠙⢿⣷⣄⠀⠀⠀⠀⠀⠀⠀[/]
    [#C7A96B]⠀⠀⠀⠀⠀⢀⣾⡿⠋⠀⠀⢠⡄⠀⠀⠙⢿⣷⡀⠀⠀⠀⠀⠀[/]
    [#DD4A3A]⠀⠀⠀⠀⣰⣿⠟⠀⠀⠀⣰⣿⣿⣆⠀⠀⠀⠻⣿⣆⠀⠀⠀⠀[/]
    [#DD4A3A]⠀⠀⠀⢰⣿⠏⠀⠀⢀⣾⡿⠉⢿⣷⡀⠀⠀⠹⣿⡆⠀⠀⠀[/]
    [#9F1C1C]⠀⠀⠀⣿⡟⠀⠀⣠⣿⠟⠀⠀⠀⠻⣿⣄⠀⠀⢻⣿⠀⠀⠀[/]
    [#9F1C1C]⠀⠀⠀⣿⡇⠀⠀⠙⠋⠀⠀⚔⠀⠀⠙⠋⠀⠀⢸⣿⠀⠀⠀[/]
    [#6B1717]⠀⠀⠀⢿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⡿⠀⠀⠀[/]
    [#6B1717]⠀⠀⠀⠘⢿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣾⡿⠃⠀⠀⠀[/]
    [#C7A96B]⠀⠀⠀⠀⠈⠻⣿⣷⣦⣤⣀⣀⣤⣤⣶⣿⠿⠋⠀⠀⠀⠀[/]
    [#C7A96B]⠀⠀⠀⠀⠀⠀⠀⠉⠛⠿⠿⠿⠿⠛⠉⠀⠀⠀⠀⠀⠀⠀[/]
    [#DD4A3A]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⚔⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [dim #6B1717]⠀⠀⠀⠀⠀⠀⠀⠀war god online⠀⠀⠀⠀⠀⠀⠀⠀[/]
  component-vars:
    tool-tier-read-accent:     '#C7A96B'
    tool-tier-write-accent:    '#4caf50'
    tool-tier-exec-accent:     '#4caf50'
    tool-tier-search-accent:   '#C7A96B'
    tool-tier-shell-accent:    '#4caf50'
    tool-tier-browse-accent:   '#C7A96B'
    tool-tier-mcp-accent:      '#9b59b6'
    tool-tier-thinking-accent: '#C7A96B'
    tool-tier-tooling-accent:  '#C7A96B'
    tool-tier-file-accent:     '#C7A96B'
    tool-tier-query-accent:    '#C7A96B'
    tool-tier-agent-accent:    '#C7A96B'
    reasoning-accent:          '#C7A96B'
    browse-turn:  '#C7A96B'
    browse-code:  '#4caf50'
    browse-tool:  '#9b59b6'
    browse-diff:  '#DD4A3A'
    browse-media: '#A8746B'
    cite-chip-bg: '#1F1010'
    cite-chip-fg: '#C7A96B'
    error-dim:        '#5C1414'
    success-dim:      '#1E5C1E'
    warning-dim:      '#7A4500'
    text-muted-dim:   '#3A2C20'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Ares

War-room bronze on charcoal — crimson-and-bronze war-god theme.
