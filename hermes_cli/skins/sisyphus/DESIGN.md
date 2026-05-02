---
version: alpha
name: sisyphus
description: Stone-grey monochrome with a single warm tier accent
colors:
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
  schema: 1
  branding:
    agent_name: Sisyphus Agent
    welcome: Welcome to Sisyphus Agent! Type your message or /help for commands.
    goodbye: 'The boulder waits. ◉'
    response_label: ' ◉ Sisyphus '
    prompt_symbol: '◉ ❯ '
    help_header: '(◉) Available Commands'
  spinner:
    style: grow
    waiting_faces: ['(◉)', '(◌)', '(◬)', '(⬤)', '(::)']
    thinking_faces: ['(◉)', '(◬)', '(◌)', '(○)', '(●)']
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
      - ['⟪◉', '◉⟫']
      - ['⟪◬', '◬⟫']
      - ['⟪◌', '◌⟫']
      - ['⟪⬤', '⬤⟫']
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
  banner_logo: |
    [bold #F5F5F5]███████╗██╗███████╗██╗   ██╗██████╗ ██╗  ██╗██╗   ██╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
    [bold #E7E7E7]██╔════╝██║██╔════╝╚██╗ ██╔╝██╔══██╗██║  ██║██║   ██║██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
    [#D7D7D7]███████╗██║███████╗ ╚████╔╝ ██████╔╝███████║██║   ██║███████╗█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║[/]
    [#BFBFBF]╚════██║██║╚════██║  ╚██╔╝  ██╔═══╝ ██╔══██║██║   ██║╚════██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]
    [#8F8F8F]███████║██║███████║   ██║   ██║     ██║  ██║╚██████╔╝███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║[/]
    [#626262]╚══════╝╚═╝╚══════╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]
  banner_hero: |
    [#B7B7B7]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#D3D3D3]⠀⠀⠀⠀⠀⠀⠀⣠⣾⣿⣿⣿⣿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#E7E7E7]⠀⠀⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⣿⣿⣷⠀⠀⠀⠀⠀⠀⠀[/]
    [#F5F5F5]⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀[/]
    [#E7E7E7]⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀[/]
    [#D3D3D3]⠀⠀⠀⠀⠀⠀⠘⢿⣿⣿⣿⣿⣿⡿⠃⠀⠀⠀⠀⠀⠀⠀[/]
    [#B7B7B7]⠀⠀⠀⠀⠀⠀⠀⠀⠙⠿⣿⠿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#919191]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#656565]⠀⠀⠀⠀⠀⠀⠀⠀⠀⣰⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#656565]⠀⠀⠀⠀⠀⠀⠀⠀⣰⣿⣿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#4A4A4A]⠀⠀⠀⠀⠀⠀⠀⣰⣿⣿⣿⣿⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#4A4A4A]⠀⠀⠀⠀⠀⣀⣴⣿⣿⣿⣿⣿⣿⣦⣀⠀⠀⠀⠀⠀⠀[/]
    [#656565]⠀⠀⠀━━━━━━━━━━━━━━━━━━━━━━━⠀⠀⠀[/]
    [dim #4A4A4A]⠀⠀⠀⠀⠀⠀⠀⠀⠀the boulder⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
  component-vars:
    tool-tier-read-accent:     '#D3D3D3'
    tool-tier-write-accent:    '#919191'
    tool-tier-exec-accent:     '#919191'
    tool-tier-search-accent:   '#D3D3D3'
    tool-tier-shell-accent:    '#919191'
    tool-tier-browse-accent:   '#D3D3D3'
    tool-tier-mcp-accent:      '#B7B7B7'
    tool-tier-thinking-accent: '#D3D3D3'
    tool-tier-tooling-accent:  '#D3D3D3'
    tool-tier-file-accent:     '#D3D3D3'
    tool-tier-query-accent:    '#D3D3D3'
    tool-tier-agent-accent:    '#F5F5F5'
    reasoning-accent:          '#D3D3D3'
    browse-turn:  '#E7E7E7'
    browse-code:  '#919191'
    browse-tool:  '#B7B7B7'
    browse-diff:  '#D3D3D3'
    browse-media: '#A8A8A8'
    cite-chip-bg: '#2A2A2A'
    cite-chip-fg: '#D3D3D3'
    error-dim:        '#656565'
    success-dim:      '#3A3A3A'
    warning-dim:      '#5C5C5C'
    text-muted-dim:   '#2C2C2C'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Sisyphus

Stone-grey monochrome with a single warm tier accent — austere greyscale with persistence.
