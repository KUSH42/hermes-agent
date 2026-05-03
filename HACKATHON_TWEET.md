# Tweet copy + writeup

## Primary tweet (the one with the video)

> Built the most feature-complete agentic terminal UI I could fit in 24-bit truecolor. Power-user posture: fast, fully traceable, no feature hidden behind a flag.
>
> 11 skins, each with its own startup animation. Custom animation engines. Streaming everything.
>
> Running kimi-k2-thinking via OpenRouter.
>
> @NousResearch Creative Hackathon · Kimi Track 🏛️
>
> [VIDEO]

## Reply 1 — what I was building toward

> Performance, traceability, and depth. A Python TUI that doesn't feel like one. An agent where every byte sent or received is on screen and addressable. A terminal pushed past the point most agents stop at — truecolor, kitty graphics, OSC52, terminaltexteffects, a custom drawbraille pipeline.

## Reply 2 — what's on screen

> · streaming reasoning trace with a per-row hue lerp
> · tool calls as live blocks with four density tiers, re-tiering under viewport pressure
> · GitHub-flavored Markdown, inline LaTeX, syntax highlighting, fenced code, footnotes
> · custom Kitty Graphics Protocol implementation + extended Textual for inline images
> · custom emoji registry: ~460 :name:-substituted images rendered inline as actual graphics, not unicode fallbacks (animated GIFs planned)
> · OSC52 clipboard
> · slash + $skill pickers with inline autocomplete, one modal stack arbiter for every overlay
> · viewport-pinned minimap, workspace overlay with live git numstat, session bar, opt-in keystroke JSONL recorder
> · /skin repaints every widget in place

## Reply 3 — animation engines + drawbraille overlay

> A terminal can paint character cells. Braille gives you 2×4 dots per cell — eight subpixels for free, no graphics protocol needed. The drawbraille overlay leans on that: helix, flow, organic, geometric, math, and composite engines, all rasterizing into a braille canvas on a single shared clock with worker-exception discipline and a per-frame perf probe.
>
> Config-gated, zero overhead when off. The constraint is the medium; the engines are designed for it instead of around it.

## Reply 4 — by the count

> 37 startup text effects, one per skin plus a registry of more. 13 token-streaming effects — shimmer, decrypt, gradient-tail, breathe, glitch-morph, cascade-reveal, zalgo, nier, cosmic-fade, others. ~28 drawbraille animation engines.
>
> All on a single shared clock. All targeting 60fps. All on a CPU budget that doesn't show up in `top`.
>
> Reference point: Claude Code's text-shimmer animation regularly drops to about 5fps under any real load. That's a Node TUI from a flagship AI lab with hundreds of engineers behind it. Mine is a Python TUI built solo on $400/mo of AI subs and it holds 60fps. Worth thinking about where the polish budget went.

## Reply 5 — performance

> Cold start was the longest fight.
>
> · SHA-1 keyed banner-geometry cache, 24h JSON TTL
> · on-disk TTE frame cache, gzipped + pickled, content-hash keyed
> · streaming producer thread that paints frame 1 while terminaltexteffects is still computing the rest
> · pre-launch worker for slow startup inputs
> · deferred banner data behind an event barrier instead of a sleep
>
> The 10-second first-launch blank screen is gone.

## Reply 6 — context

> Started this before the Hermes team announced their Ink-based rewrite. Pulled through with Python + Textual because the rendering surface I needed for the animation engines, drawbraille, and terminaltexteffects is hard to reach from Node. Different stack, same bet that the agent's UI is the product.
>
> The biggest single challenge of the project was reconciling my work with the upstream Ink TUI migration mid-flight. That's done now. The rebase is clean, my fork stays in sync with hermes-agent, and the Textual UI sits cleanly on top.

## Reply 7 — what's next

> I'm not done with this. Plan is to keep building, keep the fork in sync with upstream hermes-agent as it evolves, and add a textual-serve transport so the same UI runs in a browser without a port or a rewrite. Same widgets, same skins, same animation engines, served over a websocket.

## Reply 8 — by the numbers

> 29 active days. April 1 to May 3, two short breaks. Solo. 1,215 commits, 834 files, +266k / -3k in the diff.
>
> Of those additions: ~78k lines of production code, ~171k lines of tests (test:code ratio of 2.2:1), ~17k lines of concept docs and specs. Quality bar was non-negotiable; the test suite isn't decorative.
>
> Tooling for the build: one ChatGPT Pro sub, one Claude Max 20x sub. That's it. The scope I got through in five weeks on $400/mo of AI subs is the part that surprised me.

## Reply 9 — diff

> github.com/KUSH42/hermes-agent/pull/7
>
> Concept docs in /docs — the tool-block subsystem alone has an 1100-line frame describing its 3-axis state machine. Invariant-lint gates run on every PR that touches the hot paths.

## Reply 10 — the artifact (optional)

> In the demo, kimi writes a working p5.js generative-art sketch live: particles tracing a Lissajous curve, LaTeX for the parametric equations, emitted as one self-contained art.html →
>
> [link to art.html or a screenshot]

---

## Submission post for #creative-hackathon-submissions Discord channel

```
Hermes Agent — Power-User Agentic Terminal UI
Kimi Track + Main Track

Tweet: [paste twitter URL after posting]

A from-scratch Textual 8.x rewrite of my terminal agent. The aim was
the most feature-complete agentic TUI I could ship, built around
performance, traceability, and visual depth.

Performance because a Python TUI shouldn't feel like one. Traceability
because a power user should be able to see every prompt, response,
tool call, raw stream, classifier decision, density transition, and
error the agent produces — nothing tucked behind a debug flag, nothing
unreachable. Depth because the terminal can do more than it usually
gets asked to: 24-bit truecolor, kitty graphics, OSC52,
terminaltexteffects, a custom drawbraille pipeline.

Highlights:

· 11 skins, each shipping its own terminaltexteffects startup
  animation, wired through an x-hermes.startup_tte block in the
  skin's DESIGN.md. Live /skin switch repaints every widget in
  place, no reload.
· A reasoning-trace widget that lerps hue per row, so a long Kimi
  think reads as a moving spectrum instead of grey wall.
· Tool calls render as live blocks with four density tiers and
  re-tier under viewport pressure. The subsystem has an 1100-line
  concept doc in /docs and an invariant-lint suite gating every PR
  that touches it.
· Full GitHub-flavored Markdown: inline LaTeX, syntax highlighting,
  fenced code, footnotes. Every output streams.
· A custom Kitty Graphics Protocol implementation, plus Textual
  extended to mount inline images as widgets. OSC52 clipboard.
· A custom emoji registry: ~460 named images at $HERMES_HOME/emojis/,
  resolved by :name: substitution at render time and drawn inline as
  actual graphics via the TGP impl. Discord-style custom emoji
  rendering in a TUI agent — the only one I've seen that does it.
  Animated GIF playback is on the roadmap; today the first frame
  renders.
· A drawbraille overlay subsystem: helix, flow, organic, geometric,
  math, and composite engines that rasterize into a braille
  subpixel canvas (2×4 dots per terminal cell, eight subpixels for
  free, no graphics protocol required). One shared clock,
  worker-exception discipline, per-frame perf probes, config-gated
  and zero-overhead when off. The cleverness here is in the
  constraint — character-grid only, but smooth, dense motion that
  reads as actual graphics.

By the count: 37 startup text effects (one per skin plus a
registry), 13 token-streaming effects (shimmer, decrypt,
gradient-tail, breathe, glitch-morph, cascade-reveal, zalgo, nier,
cosmic-fade, others), and roughly 28 drawbraille animation engines.
All on one shared clock, all targeting 60fps, all with a CPU
footprint that doesn't show up in `top`.

Reference point on the perf claim: Claude Code's text-shimmer
animation regularly drops to about 5fps under any real load. That's
a Node TUI from a flagship AI lab with hundreds of engineers behind
it. This is a Python TUI built solo on $400/mo of AI subs, holding
60fps across more than seventy effects and engines simultaneously.
The polish budget went somewhere different here.
· Slash + $skill pickers with inline autocomplete, one modal stack
  arbiter for every overlay, viewport-pinned minimap, workspace
  overlay with live git numstat, session bar, opt-in keystroke JSONL
  recorder.

The performance work I'm proudest of is the cold start. SHA-1 keyed
banner-geometry cache with a 24h JSON TTL. On-disk TTE frame cache,
gzipped and pickled, content-hash keyed. A streaming producer thread
that paints frame 1 while terminaltexteffects is still computing the
run. A pre-launch worker for slow startup inputs. Deferred banner
data behind an event barrier instead of a sleep. Cold start now
paints on mount; the 10-second first-launch blank screen is gone.

Running on moonshotai/kimi-k2-thinking via OpenRouter for the demo.

By the numbers: this PR is 29 active days of solo work between
April 1 and May 3, with two short breaks. 1,215 commits. 834 files
touched, +266k / -3k in the diff. That's roughly 78k lines of
production code, 171k lines of tests (a 2.2:1 test-to-code ratio),
and 17k lines of concept docs and specs. Quality bar was
non-negotiable; the test suite isn't decorative — it's invariant-lint
gates on the hot paths and ~3000 targeted tests across the suite.

The toolchain that got me through this scope was one ChatGPT Pro
subscription and one Claude Max 20x subscription. That's the entire
budget. The amount of complexity I was able to land in five weeks on
$400/mo of AI subs is the part of this project that surprised me the
most.

One note on framing: I started this work before the Hermes team
announced their Ink-based front-end rewrite. I pulled through with
Python + Textual because the rendering surface I needed for the
animation engines, drawbraille, and terminaltexteffects is hard to
reach from Node. Different stack, same bet that the agent's UI is
the product.

The single biggest challenge of the whole project was reconciling
this work with the upstream Ink TUI migration mid-flight. Hard
merges, a moving target on the Node side, and a UI surface I was
extending in parallel. That's done now. The rebase is clean, the
fork sits cleanly on top of upstream, and going forward I plan to
keep it in sync with hermes-agent as it evolves.

I'm not done with this project. Roadmap from here:

· stay synced with upstream hermes-agent
· land a textual-serve transport so the same UI runs in a browser —
  same widgets, same skins, same animation engines, served over
  websocket. No separate web rewrite, no second codebase.
· keep grinding on the parts of the agent loop the TUI exposes:
  deeper traceability, more inline media surfaces, more density
  control on tool calls

PR: github.com/KUSH42/hermes-agent/pull/7
```
