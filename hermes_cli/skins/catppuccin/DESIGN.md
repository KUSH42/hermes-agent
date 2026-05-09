---
version: alpha
name: catppuccin
description: Catppuccin Mocha — soft pastel dark theme with mauve/lavender accents
stream_effect: breathe
colors:
  foreground: '#cdd6f4'
  background: '#1e1e2e'
  accent: '#cba6f7'
  accent-dim: '#7f57b4'
  success: '#a6e3a1'
  warning: '#f9e2af'
  error: '#f38ba8'
  muted: '#585b70'
  border: '#313244'
  selection: '#45475a'
  glass-tint: '#1e1e2e'
  glass-border: '#313244'
  glass-edge: '#cba6f7'
  banner-title: '{colors.accent}'
  banner-accent: '#f5c2e7'
  banner-dim: '{colors.accent-dim}'
  banner-border: '{colors.border}'
  banner-text: '{colors.foreground}'
  input-rule: '{colors.accent}'
  prompt: '#f5c2e7'
  response-border: '{colors.accent}'
  ui-accent: '#f5c2e7'
  ui-ok: '{colors.success}'
  ui-error: '{colors.error}'
  ui-warn: '#fab387'
components:
  app:
    backgroundColor: '{colors.background}'
    textColor: '{colors.foreground}'
  input-cursor:
    backgroundColor: '#f5c2e7'
    textColor: '{colors.background}'
  completion-empty:
    backgroundColor: '{colors.border}'
    textColor: '{colors.foreground}'
x-hermes:
  startup_tte:
    effect: bubbles
    max_wall_s: 7.0
    max_frames: 360
    params:
      final_gradient_stops:
        - '#f5c2e7'
        - '#f0a3d7'
        - '#cba6f7'
        - '#b48ead'
        - '#9272b8'
        - '#7f57b4'
  logo_startup_tte:
    effect: highlight
  schema: 1
  vars:
    preview-syntax-theme: catppuccin
  syntax:
    scheme: catppuccin
    overrides: {}
  diff:
    deletion_bg: '#2a1420'
    addition_bg: '#142a1a'
    deletion_fg: '#f38ba8'
    addition_fg: '#a6e3a1'
    line_number: '#6c7086'
    hunk_header: 'bold #cba6f7'
    filename: 'bold #89b4fa'
  spinner:
    style: dots
    thinking_faces:
    - (☕)
    - (◈)
    - (⌁)
    - (✦)
    waiting_faces:
    - (·)
    - (··)
    - (···)
    thinking_verbs:
    - brewing
    - pondering
    - simmering
    - steeping
    - contemplating
  branding:
    agent_name: Hermes
    welcome: Cozy and efficient. ☕
    goodbye: Farewell. ⟁
    response_label: ' ⟁ Hermes '
    prompt_symbol: '❯ '
    help_header: (⟁) Commands
  banner_logo: '[bold #f5c2e7]██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]

    [bold #f0a3d7]██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]

    [bold #cba6f7]███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗      ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]

    [bold #b48ead]██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]

    [bold #9272b8]██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]

    [bold #7f57b4]╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]

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
    app-bg: '{colors.background}'
    brand-glyph-color: '#f5c2e7'
    browse-code: '{colors.success}'
    browse-diff: '{colors.accent}'
    browse-media: '#89dceb'
    browse-tool: '#89b4fa'
    browse-turn: '{colors.warning}'
    chevron-base: '{colors.foreground}'
    chevron-done: '{colors.success}'
    chevron-error: '{colors.error}'
    chevron-rev-search: '#FFBF00'
    chevron-completion: '#5F9FD7'
    chevron-locked: '#666666'
    chevron-file: '{colors.warning}'
    chevron-shell: '{colors.success}'
    chevron-stream: '#89dceb'
    cite-chip-bg: '#181825'
    cite-chip-fg: '#89b4fa'
    completion-empty-bg: '{colors.border}'
    cursor-color: '#f5c2e7'
    cursor-placeholder: '{colors.muted}'
    cursor-selection-bg: '{colors.selection}'
    diff-add-bg: '#142a1a'
    diff-del-bg: '#2a1420'
    info: '#89b4fa'
    syntax-theme: catppuccin
    syntax-scheme: catppuccin
    drawbraille-canvas-color: '#89dceb'
    footnote-ref-color: '#6c7086'
    fps-hud-bg: '#181825'
    fuzzy-match-color: '{colors.warning}'
    ghost-text-color: '{colors.muted}'
    nameplate-active-color: '{colors.accent}'
    nameplate-decrypt-color: '{colors.success}'
    nameplate-idle-color: '{colors.muted}'
    panel-border: '{colors.border}'
    primary-darken-3: '{colors.accent-dim}'
    rule-accent-color: '{colors.accent}'
    rule-accent-dim-color: '{colors.accent-dim}'
    rule-bg-color: '{colors.background}'
    rule-dim-color: '{colors.muted}'
    running-indicator-dim-color: '{colors.muted}'
    running-indicator-hi-color: '{colors.warning}'
    scrollbar: '{colors.accent}'
    spinner-shimmer-dim: '{colors.muted}'
    spinner-shimmer-peak: '{colors.foreground}'
    attachment-chip-fg: '{colors.ui-accent}'
    attachment-chip-bg: '{colors.background}'
    attachment-chip-shimmer-dim: '{colors.muted}'
    attachment-chip-shimmer-peak: '{colors.foreground}'
    attachment-chip-remove-fg: '{colors.ui-error}'
    status-context-color: '#89b4fa'
    status-error-color: '{colors.error}'
    status-running-color: '{colors.warning}'
    status-warn-color: '#fab387'
    accent-interactive: '#89dceb'
    tool-mcp-accent: '{colors.accent}'
    tool-vision-accent: '#89dceb'
    user-echo-bullet-color: '#fab387'
    plan-now-fg: '#89dceb'
    plan-pending-fg: '#6c7086'
    pane-border: '{colors.border}'
    pane-border-focused: '#89b4fa'
    pane-title-fg: '{colors.muted}'
    pane-divider: '#181825'
    error-auth: '#eab308'
    error-critical: '#ef4444'
    error-network: '#f97316'
    error-timeout: '#f59e0b'
    tool-glyph-mcp: '#9b59b6'
    overlay-selection-bg: '#45475a'
    error-dim: '#8B2020'
    success-dim: '#1E5C1E'
    warning-dim: '#5C4A00'
    text-muted-dim: '#3A3A3A'
    tool-header-gutter-color: '#89b4fa'
    tool-tier-read-accent: '#89b4fa'
    tool-tier-write-accent: '#a6e3a1'
    tool-tier-exec-accent: '#a6e3a1'
    tool-tier-search-accent: '#89b4fa'
    tool-tier-shell-accent: '#a6e3a1'
    tool-tier-browse-accent: '#89b4fa'
    tool-tier-mcp-accent: '#cba6f7'
    tool-tier-thinking-accent: '#89b4fa'
    reasoning-accent: '#89b4fa'
    user-accent: '#89b4fa'
    tool-tier-tooling-accent: '#89b4fa'
    tool-tier-file-accent: '#94e2d5'
    tool-tier-query-accent: '#89dceb'
    tool-tier-agent-accent: '#cba6f7'
    thinking-spinner-dim: '#585b70'
    thinking-spinner-peak: '#cdd6f4'
    thinking-chroma-a: '#cba6f7'
    thinking-chroma-b: '#f5c2e7'
    thinking-hue-shift-speed: '0.10'
    tool-header-max-gap: '8'
---

# Catppuccin

Catppuccin Mocha — soft pastel dark theme with mauve/lavender accents.

This skin is the canonical DESIGN.md form of the legacy `skins/catppuccin.yaml`.
The runtime reads this file directly via `load_design_md_payload()`. See
`lint-report.md` for the most recent `npx @google/design.md lint` result.
