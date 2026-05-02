---
version: alpha
name: poseidon
description: Deep ocean blue with cyan highlights
colors:
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
  schema: 1
  branding:
    agent_name: Poseidon Agent
    welcome: Welcome to Poseidon Agent! Type your message or /help for commands.
    goodbye: 'Fair winds! Ψ'
    response_label: ' Ψ Poseidon '
    prompt_symbol: 'Ψ ❯ '
    help_header: '(Ψ) Available Commands'
  spinner:
    style: bounce
    waiting_faces: ['(≈)', '(Ψ)', '(∿)', '(◌)', '(◠)']
    thinking_faces: ['(Ψ)', '(∿)', '(≈)', '(⌁)', '(◌)']
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
      - ['⟪≈', '≈⟫']
      - ['⟪Ψ', 'Ψ⟫']
      - ['⟪∿', '∿⟫']
      - ['⟪◌', '◌⟫']
  syntax:
    scheme: nord
  diff:
    deletion_bg: '#433047'
    addition_bg: '#244A44'
    intra_del_bg: '#5A4060'
    intra_add_bg: '#2F6259'
  tool_prefix: │
  banner_logo: |
    [bold #B8E8FF]██████╗  ██████╗ ███████╗███████╗██╗██████╗  ██████╗ ███╗   ██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
    [bold #97D6FF]██╔══██╗██╔═══██╗██╔════╝██╔════╝██║██╔══██╗██╔═══██╗████╗  ██║      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
    [#75C1F6]██████╔╝██║   ██║███████╗█████╗  ██║██║  ██║██║   ██║██╔██╗ ██║█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║[/]
    [#4FA2E0]██╔═══╝ ██║   ██║╚════██║██╔══╝  ██║██║  ██║██║   ██║██║╚██╗██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║[/]
    [#2E7CC7]██║     ╚██████╔╝███████║███████╗██║██████╔╝╚██████╔╝██║ ╚████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║[/]
    [#1B4F95]╚═╝      ╚═════╝ ╚══════╝╚══════╝╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═══╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝[/]
  banner_hero: |
    [#2A6FB9]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#5DB8F5]⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣾⣿⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#5DB8F5]⠀⠀⠀⠀⠀⠀⠀⢠⣿⠏⠀Ψ⠀⠹⣿⡄⠀⠀⠀⠀⠀⠀⠀[/]
    [#A9DFFF]⠀⠀⠀⠀⠀⠀⠀⣿⡟⠀⠀⠀⠀⠀⢻⣿⠀⠀⠀⠀⠀⠀⠀[/]
    [#A9DFFF]⠀⠀⠀≈≈≈≈≈⣿⡇⠀⠀⠀⠀⠀⢸⣿≈≈≈≈≈⠀⠀⠀[/]
    [#5DB8F5]⠀⠀⠀⠀⠀⠀⠀⣿⡇⠀⠀⠀⠀⠀⢸⣿⠀⠀⠀⠀⠀⠀⠀[/]
    [#2A6FB9]⠀⠀⠀⠀⠀⠀⠀⢿⣧⠀⠀⠀⠀⠀⣼⡿⠀⠀⠀⠀⠀⠀⠀[/]
    [#2A6FB9]⠀⠀⠀⠀⠀⠀⠀⠘⢿⣷⣄⣀⣠⣾⡿⠃⠀⠀⠀⠀⠀⠀⠀[/]
    [#153C73]⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣿⣿⡿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#153C73]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
    [#5DB8F5]⠀⠀⠀⠀⠀≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈⠀⠀⠀⠀⠀[/]
    [#A9DFFF]⠀⠀⠀⠀⠀⠀≈≈≈≈≈≈≈≈≈≈≈≈≈⠀⠀⠀⠀⠀⠀[/]
    [dim #153C73]⠀⠀⠀⠀⠀⠀⠀deep waters hold⠀⠀⠀⠀⠀⠀⠀[/]
  component-vars:
    tool-tier-read-accent:     '#5DB8F5'
    tool-tier-write-accent:    '#4caf50'
    tool-tier-exec-accent:     '#4caf50'
    tool-tier-search-accent:   '#5DB8F5'
    tool-tier-shell-accent:    '#4caf50'
    tool-tier-browse-accent:   '#5DB8F5'
    tool-tier-mcp-accent:      '#9b59b6'
    tool-tier-thinking-accent: '#5DB8F5'
    tool-tier-tooling-accent:  '#5DB8F5'
    tool-tier-file-accent:     '#5DB8F5'
    tool-tier-query-accent:    '#5DB8F5'
    tool-tier-agent-accent:    '#A9DFFF'
    reasoning-accent:          '#5DB8F5'
    browse-turn:  '#A9DFFF'
    browse-code:  '#4caf50'
    browse-tool:  '#9b59b6'
    browse-diff:  '#7AB8E0'
    browse-media: '#5DB8F5'
    cite-chip-bg: '#0E2238'
    cite-chip-fg: '#A9DFFF'
    error-dim:        '#5C2828'
    success-dim:      '#1E5C1E'
    warning-dim:      '#5C4A00'
    text-muted-dim:   '#1F3A55'
    error-auth:       '#eab308'
    error-network:    '#f97316'
    error-timeout:    '#f59e0b'
---

# Poseidon

Deep ocean blue with cyan highlights — ocean-god theme.
