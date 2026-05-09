---
version: alpha
name: solarized-dark
description: Solarized Dark — precision-crafted warm dark theme with teal/blue/amber
stream_effect: shimmer
  accents
colors:
  foreground: '#839496'
  background: '#002b36'
  accent: '#268bd2'
  accent-dim: '#1a5c99'
  success: '#859900'
  warning: '#b58900'
  error: '#dc322f'
  muted: '#586e75'
  border: '#073642'
  selection: '#073642'
  glass-tint: '#002b36'
  glass-border: '#073642'
  glass-edge: '#2aa198'
  banner-title: '#268bd2'
  banner-accent: '#2aa198'
  banner-dim: '#1a5c99'
  banner-border: '#073642'
  banner-text: '#839496'
  banner-warning: '#cb4b16'
  banner-warning-dim: '#93380f'
  banner-key: '#b58900'
  input-rule: '#268bd2'
  prompt: '#2aa198'
  response-border: '#073642'
  ui-accent: '#2aa198'
  ui-ok: '#859900'
  ui-error: '#dc322f'
  ui-warn: '#b58900'
components:
  app:
    backgroundColor: '{colors.background}'
    textColor: '{colors.foreground}'
x-hermes:
  startup_tte:
    effect: spotlights
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#93a1a1'
        - '#2aa198'
        - '#268bd2'
        - '#1a5c99'
        - '#0d4f7d'
        - '#073642'
  logo_startup_tte:
    effect: highlight
  schema: 1
  vars:
    preview-syntax-theme: solarized-dark
  branding:
    agent_name: Hermes
    welcome: Precision engineered for the eyes.
    goodbye: Until next time. ⟁
    response_label: ' ⟁ Hermes '
    prompt_symbol: '❯ '
    help_header: (⟁) Commands
  spinner:
    style: bounce
    thinking_faces:
    - (◈)
    - (⌁)
    - (◇)
    - (⊙)
    waiting_faces:
    - (·)
    - (.·)
    - (··)
    thinking_verbs:
    - analyzing
    - processing
    - reasoning
    - computing
    - deliberating
  syntax:
    scheme: solarized-dark
    overrides: {}
  diff:
    deletion_bg: '#2a0a08'
    addition_bg: '#0a1a0a'
    deletion_fg: '#dc322f'
    addition_fg: '#859900'
    line_number: '#586e75'
    hunk_header: 'bold #2aa198'
    filename: 'bold #268bd2'
  banner_logo: '[bold #93a1a1]██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #2aa198]██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #268bd2]███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]

    [bold #1a5c99]██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]

    [bold #0d4f7d]██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]

    [bold #073642]╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]

    '
  banner_hero: '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀

    ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀

    ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⡿⠛⢁⡈⠛⢿⣿⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣦⣤⣈⠁⢠⣴⣿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠻⢿⣿⣦⡉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⣦⣈⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣴⠦⠈⠙⠿⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣤⡈⠁⢤⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠑⢶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠁⢰⡆⠈⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⠈⣡⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

    '
  component-vars:
    app-bg: '#002b36'
    brand-glyph-color: '#2aa198'
    browse-code: '#859900'
    browse-diff: '#6c71c4'
    browse-media: '#2aa198'
    browse-tool: '#268bd2'
    browse-turn: '#b58900'
    chevron-base: '#93a1a1'
    chevron-done: '#859900'
    chevron-error: '#dc322f'
    chevron-rev-search: '#FFBF00'
    chevron-completion: '#5F9FD7'
    chevron-locked: '#666666'
    chevron-file: '#b58900'
    chevron-shell: '#859900'
    chevron-stream: '#268bd2'
    cite-chip-bg: '#073642'
    cite-chip-fg: '#2aa198'
    completion-empty-bg: '#073642'
    cursor-color: '#93a1a1'
    cursor-placeholder: '#586e75'
    cursor-selection-bg: '#073642'
    diff-add-bg: '#0a1a0a'
    diff-del-bg: '#2a0a08'
    info: '#268bd2'
    syntax-theme: solarized-dark
    syntax-scheme: solarized-dark
    drawbraille-canvas-color: '#2aa198'
    footnote-ref-color: '#586e75'
    fps-hud-bg: '#073642'
    fuzzy-match-color: '#b58900'
    ghost-text-color: '#586e75'
    nameplate-active-color: '#268bd2'
    nameplate-decrypt-color: '#859900'
    nameplate-idle-color: '#586e75'
    panel-border: '#073642'
    primary-darken-3: '#1a5c99'
    rule-accent-color: '#268bd2'
    rule-accent-dim-color: '#1a5c99'
    rule-bg-color: '#002b36'
    rule-dim-color: '#586e75'
    running-indicator-dim-color: '#586e75'
    running-indicator-hi-color: '#b58900'
    scrollbar: '#268bd2'
    spinner-shimmer-dim: '#586e75'
    spinner-shimmer-peak: '#93a1a1'
    attachment-chip-fg: '{colors.ui-accent}'
    attachment-chip-bg: '#002b36'
    attachment-chip-shimmer-dim: '#586e75'
    attachment-chip-shimmer-peak: '#93a1a1'
    attachment-chip-remove-fg: '{colors.ui-error}'
    status-context-color: '#268bd2'
    status-error-color: '#dc322f'
    status-running-color: '#b58900'
    status-warn-color: '#cb4b16'
    accent-interactive: '#2aa198'
    tool-mcp-accent: '#6c71c4'
    tool-vision-accent: '#2aa198'
    user-echo-bullet-color: '#b58900'
    plan-now-fg: '#2aa198'
    plan-pending-fg: '#586e75'
    pane-border: '#073642'
    pane-border-focused: '#268bd2'
    pane-title-fg: '#586e75'
    pane-divider: '#002b36'
    error-auth: '#eab308'
    error-critical: '#ef4444'
    error-network: '#f97316'
    error-timeout: '#f59e0b'
    tool-glyph-mcp: '#9b59b6'
    overlay-selection-bg: '#073642'
    error-dim: '#8B2020'
    success-dim: '#1E5C1E'
    warning-dim: '#5C4A00'
    text-muted-dim: '#3A3A3A'
    tool-header-gutter-color: '#268bd2'
    tool-tier-read-accent: '#268bd2'
    tool-tier-write-accent: '#859900'
    tool-tier-exec-accent: '#859900'
    tool-tier-search-accent: '#268bd2'
    tool-tier-shell-accent: '#859900'
    tool-tier-browse-accent: '#268bd2'
    tool-tier-mcp-accent: '#6c71c4'
    tool-tier-thinking-accent: '#268bd2'
    reasoning-accent: '#268bd2'
    user-accent: '#268bd2'
    tool-tier-tooling-accent: '#268bd2'
    tool-tier-file-accent: '#2aa198'
    tool-tier-query-accent: '#268bd2'
    tool-tier-agent-accent: '#6c71c4'
    thinking-spinner-dim: '#586e75'
    thinking-spinner-peak: '#93a1a1'
    thinking-chroma-a: '#268bd2'
    thinking-chroma-b: '#2aa198'
    thinking-hue-shift-speed: '0.08'
    tool-header-max-gap: '8'
---

# Solarized-Dark

Solarized Dark — precision-crafted warm dark theme with teal/blue/amber accents

This skin is the canonical DESIGN.md form of `skins/solarized-dark.yaml`.
