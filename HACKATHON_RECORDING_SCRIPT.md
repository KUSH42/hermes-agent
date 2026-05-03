# RECORDING PLAYBOOK v2 — fully deterministic

**Strategy:** standalone demo scripts for visual fireworks (no LLM required, repeatable). Live TUI only for the Kimi hero run + model picker + skin switch.

Total: ~60 min recording + 30 min editing.

**Output:** 75s MP4, beat-locked to 130 BPM `tragic_foil_segment.mp3`.

---

## HELPER SCRIPTS

`record/` directory has helper scripts that handle countdown timing, OBS hotkey toggling (via xdotool), file renaming. Use them where available.

| Script | What it does |
|---|---|
| `record/take1.sh` | skin startup montage — 6 real hermes launches back-to-back (auto) |
| `record/take2.sh` | standalone TTE montage 5 effects, no hermes (auto) |
| `record/take6.sh` | streaming token effects (auto) |
| `record/take7.sh` | drawbraille engines (auto) |
| `record/take8.sh` | syntax highlighting (auto) |
| `record/take13_skin.sh <skin>` | flicker take per skin (semi-auto, types prompt for you) |
| `record/take_emoji.sh` | custom emoji registry — :name: substitution + inline TGP rendering |
| `record/take_drawbraille.sh` | drawbraille engine showcase at 192×52, 14 engines, hue-shift gradient |
| `record/check.sh` | verify all takes exist + are non-trivial |

**Usage pattern:** focus the kitty window, run the script in another terminal (or in the same one — script will clear and run), follow on-screen countdown, press Enter when prompted.

**Manual takes (live TUI):** 3, 4, 5, 9, 10, 11, 12 — these need real interaction. Follow inline instructions.

---

## STEP 0 — Setup (10 min)

```bash
# 0.1 — confirm tools
ffmpeg -version || sudo apt install ffmpeg
ls -lh tragic_foil_segment.mp3   # ~1.7MB, ~1:45 duration

# 0.2 — verify Kimi via OpenRouter
hermes
# In TUI: /model → moonshotai/kimi-k2-thinking
# Send "hi" — confirm response. If it errors, fix BEFORE recording.
# Note: status BAR (bottom) should show model. Nameplate just says "Hermes".
# Ctrl+Q to quit.

# 0.3 — make raw_takes dir
mkdir -p raw_takes

# 0.4 — verify all demo scripts work
cd /home/xush/.hermes
python demo_tte.py --list
python demo_stream_effects_v3.py --list
python scripts/demo_anim.py --help
cd /home/xush/.hermes/hermes-agent
```

**Kitty (start fresh window for every take batch):**

```bash
kitty --override font_size=22 \
      --override window_padding_width=12 \
      --override hide_window_decorations=yes \
      --override initial_window_width=1920 \
      --override initial_window_height=1080
```

**OBS — IMPORTANT: hotkey must NOT be F9** (conflicts with hermes plan panel).
- Settings → Hotkeys → Start/Stop Recording: **F10**
- Output: MKV, x264 CRF 18
- Video: 1920×1080, 60 fps
- Cursor: hidden
- Recording path: `/home/xush/.hermes/hermes-agent/raw_takes/`

---

## ARC OVERVIEW

| beat | t | content | source |
|---|---|---|---|
| **Hook** | 0–4s | matrix skin startup + caption | take1 (matrix segment) |
| **Identity** | 4–14s | 4-5 skin startups, real product | take1 (remaining segments) |
| **Reveal** | 14–18s | "this is hermes" — composer + skill picker | live TUI |
| **MONEY SHOT** | 18–32s | Kimi reasoning visible + tool blocks streaming | live TUI hero run |
| **Creative payoff** | 32–40s | art.html opening in browser — the Lissajous sketch it built | browser screen-cap |
| **Visual flex** | 40–55s | streaming effects + drawbraille engines + syntax highlight | demo scripts |
| **Power** | 55–67s | model picker (Kimi proof) + live skin switch + minimap | live TUI |
| **CTA** | 67–75s | static badge frame | static |

---

## TAKE 1 — Skin startup montage (6 skins, ~42s raw)

```bash
./record/take1.sh
```

Launches `HERMES_SKIN=$skin hermes` for matrix → charizard → poseidon → ares → hermes → tokyo-night, holds 6s on each (full startup TTE + banner settle), `ctrl+q` between, single continuous recording. Cut into 4-6 hero openings in edit; pick the cleanest 2-3 for the cold-open + identity beats. Each skin has its own startup TTE wired via `x-hermes.startup_tte` so the montage shows real product variety, not synthetic effects.

If a skin's hermes hangs on quit, the script `kill`s the bg PID. Tweak `HOLD_S` / `GAP_S` / `SKINS` at the top of the script.

---

## TAKE 2 — TTE montage (5 effects, ~25s raw)

```bash
./record/take2.sh
```

Plays beams → burn → waves → laseretch → vhstape with 0.4s pauses.

I'll trim each effect to its crystallization moment in edit. You don't have to time anything.

---

## TAKE 3 — Composer + skill picker reveal (5s)

```bash
clear
HERMES_SKIN=hermes hermes
# Wait for full startup. Status bar visible at bottom.
F10
# Type slowly, character by character (don't paste):
$
# Skill picker overlay should appear with $ prefix. Hold 2s.
# Keep typing:
$plan
# Picker filters. Hold 1s.
# Press Esc to dismiss.
# Type:
/
# Slash picker shows. Hold 1s.
# Esc.
F10
mv raw_takes/<latest>.mkv raw_takes/take3.mkv
```

**Don't quit hermes — leave it running for take 4.**

---

## TAKE 4 — HERO Kimi run (the money shot, ~20s raw)

**Pre-conditions:**
- Hermes running from take 3
- Skin: hermes
- Model: `moonshotai/kimi-k2-thinking` (set via `/model` BEFORE F10)
- Status bar at bottom must show the model name

**Actions:**

```bash
# In live TUI, set model:
/model
# pick moonshotai/kimi-k2-thinking
# back to composer

F10                                # start recording

# Type slowly (don't paste):
build a generative p5.js sketch where particles trace a lissajous curve. emit it as a single self-contained art.html with inline css. include latex for the parametric equations. 🎨

# Press Enter.
# Watch the agent think + work. DO NOT TOUCH KEYBOARD.
# Observe these in frame:
#   1. Thinking widget chroma gradient (this is the killer shot)
#   2. Tool blocks materializing (Edit/Write)
#   3. LaTeX block rendering
#   4. Emoji rendering
# Stop ~5s after art.html is fully written.

F10
mv raw_takes/<latest>.mkv raw_takes/take4.mkv
```

**Re-shoot 2-3 times.** Pick the cleanest. If thinking widget doesn't show colors, you may need to set a skin with `$reasoning-accent` defined — `hermes` should be fine.

**Important:** verify the model successfully calls Edit/Write tools. If Kimi-thinking doesn't tool-call cleanly, fall back to a different prompt. We can also use `kimi-k2.6` (less reasoning, more reliable tool use) — tradeoff.

---

## TAKE 5 — Browser opens art.html (the payoff, ~6s)

After take 4 finished and art.html exists:

```bash
# In a separate terminal:
ls .hermes/plans/  # confirm artifact written, find path
# OR if it's just art.html:
ls art.html

# Set up: have Firefox/Chrome already open with about:blank, sized 1920×1080
# Have the file path ready in clipboard
```

**Screen-cap the browser:**

```
F10
# Open art.html in browser (drag from file manager, or paste path)
# Wait for canvas to render — particles should start tracing the lissajous curve
# Hold for 5 seconds — let viewers see the motion
F10
mv raw_takes/<latest>.mkv raw_takes/take5_browser.mkv
```

**This is the creative-hackathon proof shot.** "The agent made this thing live."

If art.html doesn't render or looks bad, retake 4 with a more conservative prompt.

---

## TAKE 6 — Streaming token effects (~8s raw)

```bash
./record/take6.sh
```

decrypt (matrix-style reveal) + nier (char mangling) + zalgo (glitch text).

---

## TAKE 7 — DrawBraille engines (~8s raw)

```bash
./record/take7.sh
```

aurora_ribbon → plasma → matrix_rain with gradient. Edit script to adjust duration if needed.

---

## TAKE 8 — Syntax highlighting (~4s raw)

```bash
./record/take8.sh
```

---

## TAKE 9 — Live skin switch (~10s raw)

```bash
clear
HERMES_SKIN=hermes hermes
# wait for startup
F10
# Type slowly:
/skin tokyo-night<Enter>
# wait 2s
/skin charizard<Enter>
# wait 2s
/skin matrix<Enter>
# wait 2s
F10
mv raw_takes/<latest>.mkv raw_takes/take9.mkv
# Don't quit yet — leave for take 10
```

---

## TAKE 10 — Model picker (Kimi proof shot, ~6s raw)

Hermes still running:

```bash
F10
/model
# Picker overlay opens. Scroll to moonshotai/kimi-k2-thinking.
# **HOLD on this for 3 full seconds** — judges need to see this.
# Press Enter to confirm.
# Status bar updates.
F10
mv raw_takes/<latest>.mkv raw_takes/take10.mkv
```

---

## TAKE 11 — Navigation overlays (~10s raw)

Hermes still running, has output from earlier takes in the panel:

```bash
F10
F4              # workspace overlay
# Hold 2s
Esc
F1              # keymap help
# Hold 2s
Esc
Ctrl+B          # browse mode (minimap visible)
# Wait 2s, navigate with arrow keys briefly
Esc
Ctrl+J          # sessions
# Hold 1.5s
Esc
F10
mv raw_takes/<latest>.mkv raw_takes/take11.mkv
```

If any binding fails (overlay doesn't show), skip it and continue. I'll work with what's there.

---

## TAKE DRAWBRAILLE — Engine showcase at 192×52 (~45s raw)

```bash
./record/take_drawbraille.sh
```

Spawns a dedicated kitty at `font_size=10` (yields ~192 cols × 52 rows in 1920×1080), runs `scripts/demo_anim.py` through 14 curated engines with a 4-stop chroma gradient (`#ff0080,#ffaa00,#00ffcc,#8800ff`) and hue-shift drift (1.0). 3s per engine, 60 FPS default (matches the OBS capture target). The matrix_rain motion is `dt`-driven — at 60 fps the per-frame positional delta is half what it is at 30, which is exactly what makes it read as smooth instead of steppy. 60 is also the ceiling that survives the OBS pipeline; going higher gets resampled down anyway. Override with `FPS=30 ./record/take_drawbraille.sh` if you want the lower-budget version.

Engine arc: matrix_rain → rotating → dna → triple_helix → torus_3d → wireframe_cube → lissajous_weave → aurora_ribbon → plasma → fluid_field → neural_pulse → mandala_bloom → kaleidoscope → strange_attractor. Bold opener, motion, math/geometric, atmospheric, esoteric close.

In edit, slice 1.5–2s per engine for a fast-cut montage, or hold a single beat (aurora_ribbon + plasma both make great hero stills) for the "visual flex" beat at 40-55s in the arc table.

Override knobs are env vars at the top of the script: `FONT_SIZE`, `PER_ENGINE_S`, `FPS`, `PALETTE`, `HUE_SHIFT`.

## TAKE EMOJI — Custom registry, inline TGP rendering (~10s raw)

```bash
./record/take_emoji.sh
```

Run inside the regular recording kitty (font_size=22, 1080p) with hermes already running. Types a composer line using a handful of `:name:` emojis (`:pepeclown:` `:5Head:` `:smartboi:` `:based:`, all static .webp), submits, holds 6s on the agent's response so the rendered images stay on screen for the cut.

This is the "no other agent TUI does this" shot. ~460 custom emojis in `~/.hermes/emojis/`, `:name:` substitution at render time, drawn inline as actual graphics via the custom Kitty Graphics Protocol implementation. (Animated GIF playback is on the roadmap; today the first frame renders, which still beats unicode-fallback on every other terminal agent.)

At 1080p / 22pt an emoji cell is ~26-30px — visible but small. If you want a hero close-up beat in the cut, do a modest 1.5× crop in post on the relevant region. Well within the resolution ceiling and avoids a separate large-font take that wouldn't match the rest of the footage.

## TAKE 12 — Static final hold (5s)

```bash
Ctrl+Q          # quit hermes
clear
HERMES_SKIN=matrix hermes
# Wait for full TTE finish + 2s settle
F10
# Don't touch keyboard for 5s
F10
mv raw_takes/<latest>.mkv raw_takes/take12.mkv
```

---

## TAKE 13 — Multi-skin flicker shots (optional, ~5min)

For each skin run the helper. Auto-types the prompt with consistent cadence so all 6 are identical except theme.

```bash
./record/take13_skin.sh matrix
./record/take13_skin.sh charizard
./record/take13_skin.sh poseidon
./record/take13_skin.sh ares
./record/take13_skin.sh tokyo-night
./record/take13_skin.sh solarized-dark
```

Between runs the script quits hermes cleanly. If a take looks bad, just rerun it — the rename overwrites.

I'll cut these into a 3s strobing montage (~0.5s per skin) at ~60-65s of the final video.

---

## VERIFY

```bash
./record/check.sh
```

Lists all takes, flags missing or undersized files. When this prints "All required takes present", message me `takes ready`.

---

## CHECKLIST

```
raw_takes/
├── take1.mkv             # 6-skin startup montage (real hermes launches)
├── take2.mkv             # standalone TTE effect reel (B-roll)
├── take3.mkv             # composer + skill/slash picker
├── take4.mkv             # HERO Kimi run (REDO until clean)
├── take5_browser.mkv     # art.html in browser (the payoff)
├── take6.mkv             # streaming effects
├── take7.mkv             # syntax highlighting
├── take8.mkv             # live skin switch
├── take9.mkv             # /model picker — Kimi proof
├── take10.mkv            # navigation overlays
├── take11.mkv            # static final hold
├── take_drawbraille.mkv  # 14-engine showcase at 192×52 (the "art" beat)
└── take_emoji.mkv        # custom emoji registry, inline TGP
```

**13 files. Tell me `takes ready` when done. I'll write `edit.sh`.**

---

## NEW CAPTION SCHEDULE (130 BPM, beat-aligned)

| video t | bar | caption |
|---|---|---|
| 1.8s | 2 | *an agent that lives in your terminal* |
| 7.4s | 5 | *eleven skins. eleven openings.* |
| 14.8s | **9 drop** | *running on kimi-k2-thinking via openrouter* |
| 22.2s | 13 | *watch it think in color* |
| 29.5s | 17 | *latex. emoji. tool calls. all native.* |
| 33.2s | 19 | *— and it built this, live* |
| 40.5s | 23 | *with streaming effects you can feel* |
| 47.9s | 27 | *animation engines straight to your terminal* |
| 51.7s | 29 | *every model. one keystroke away.* |
| 59.0s | 33 | *every theme re-paints in place* |
| 68.3s | 38 | *github.com/KUSH42/hermes-agent · PR #7* |
| 71.1s | 39 | *Kimi Track · Nous Creative Hackathon* |

---

## Risks + mitigations

- **Take 4 (Kimi run) is the most fragile.** Re-shoot up to 5x. If kimi-k2-thinking refuses to tool-call, switch to `moonshotai/kimi-k2.6` and re-run. Document which model in the tweet.
- **F9 conflict** — moved OBS to F10. Don't accidentally hit F9 during any take.
- **Status bar must be visible** in takes 3, 4, 9, 10, 11 for the Kimi proof to land.
- **Browser take 5 fragility:** if art.html is broken or empty, redo the prompt with a simpler ask. Backup prompt: `write a self-contained art.html with a sine wave animation in p5.js`.
- **Don't quit hermes between takes 3↔4, 9↔10↔11** — keeps state consistent and saves time.
