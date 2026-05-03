# Hermes Hackathon Submission — Recording Plan

**Deadline:** EOD Sunday 2026-05-03
**Target:** 75s MP4, 1920×1080 60fps, captions only, ambient pad music
**Hackathon:** Nous Research Creative Hackathon — Kimi Track ($5k extra pool)

---

## Pre-flight (do once, before any recording)

```bash
# 1. Kitty config — clean recording window
# In ~/.config/kitty/kitty.conf temporarily set or via overrides:
#   font_size 22
#   window_padding_width 12
#   background_opacity 1.0
#   hide_window_decorations yes
#   remember_window_size no
#   initial_window_width  1920
#   initial_window_height 1080
# Launch:
kitty --override font_size=22 --override window_padding_width=12 \
      --override hide_window_decorations=yes \
      --override initial_window_width=1920 --override initial_window_height=1080

# 2. OBS scene
#   - Display Capture (or Window Capture: kitty)
#   - Crop to exactly 1920×1080 of the kitty window
#   - Output: 60 fps, x264 CRF 18, mkv (lossless-ish), convert to mp4 in post
#   - Disable mouse cursor capture
#   - Hotkey: F9 start/stop record (set in OBS settings)

# 3. Verify Kimi via OpenRouter works BEFORE recording
hermes  # then in TUI: /model openrouter moonshotai/kimi-k2-thinking
# Run a tiny test prompt. Confirm response metadata shows moonshotai provider.
# If it lands on Together/DeepInfra, set provider pin in config.

# 4. Clean scrollback before each take
clear && hermes
```

**Recording terminal — keep these always visible:**
- nameplate showing model = `moonshotai/kimi-k2-thinking`
- session bar at bottom
- composer ready

---

## Takes (record each independently, splice in post)

### TAKE 1 — Skin startup montage (6 skins, single recording)
- Skins: matrix → charizard → poseidon → ares → hermes → tokyo-night
- Each skin's own `startup_tte` plays (matrix-rain, burn, waves, laseretch, vhstape, …)
- ~42s raw, automated:
```bash
./record/take1.sh
```
- In edit, slice each skin's segment (~6s) and use the cleanest 2-3 for the cold-open + identity beats. The matrix segment is the first 1.5s — re-shoot if the rain looks dirty.
- Replaces the old single-matrix take + separate skin montage; one recording covers both beats.

### TAKE 2 — Standalone TTE effect reel (no hermes)
Pure terminaltexteffects (`demo_tte.py`) — used as accents / B-roll if take 1 needs filler.
```bash
./record/take2.sh
```

### TAKE 3 — HERO Kimi run (longest take, ~15s of usable footage)
- Skin: hermes (or matrix — pick whichever shows ThinkingWidget colors best)
- Pre-condition: model is `moonshotai/kimi-k2-thinking`
- Type slowly:
  ```
  $plan build a generative p5.js sketch where particles trace a lissajous
  curve. emit it as art.html with inline css. include a brief latex
  explanation of the parametric equations 🎨
  ```
- Hit Enter. Record:
  - ThinkingWidget chroma gradient streaming
  - Tool blocks materializing (Edit/Write tool calls)
  - LaTeX block rendering
  - Emoji rendering
  - Density tier transitions (Shift+D mid-stream is showy)
- Cut at first complete artifact written.
- **Do this run 2-3× to get a clean one.**

### TAKE 4 — Skin live-switch
- During or after a response, in composer:
  ```
  /skin tokyo-night
  /skin poseidon
  /skin charizard
  ```
- Cuts between skins are gold. Each `/skin` re-themes everything live.
- ~6s of footage, will speed to 1.5×.

### TAKE 5 — Navigation features
- Toggle minimap (default keybind — check `/help` or KeymapOverlay)
- Open WorkspaceOverlay (shows git numstat — make sure repo has uncommitted edits)
- Open SessionBar
- Cycle density tiers
- ~10s. Calm pacing here.

### TAKE 6 — Drawbraille engine showcase (~42s raw)
- Run `./record/take_drawbraille.sh` (with `FPS=60` for the actual take)
- 14-engine cycle at 192×52 cells with 4-stop chroma palette + hue-shift drift
- Slice 1.5–2s per engine for fast-cut montage, OR hold 3-4s on aurora_ribbon / plasma / fluid_field as hero stills
- This is the "art" beat. Runs in a dedicated kitty (font_size=10), no hermes needed.

### TAKE EMOJI — Custom emoji registry (~10s raw)
- Run `./record/take_emoji.sh` inside the regular recording kitty with hermes already up
- ~460 named images at $HERMES_HOME/emojis/, :name: substitution, drawn inline via the custom Kitty Graphics Protocol impl
- Hold 6s on the agent response so the rendered images stay on screen
- 1.5× crop in post if you want a hero close-up beat (do not retake at huge font)
- Animated GIFs are roadmap-only today — only static .webp emojis used in the take

### TAKE 7 — Composer power
- Slash command picker: type `/` slowly, show overlay
- Skill picker: type `$` slowly, show overlay
- `/model` → scroll to `moonshotai/kimi-k2-thinking` (Kimi-track proof shot — **hold here 2s**)
- ~10s.

### TAKE 8 — Rapid feature flash
- KeymapOverlay open/close
- ConfigPanel open/close
- One feature per ~1s; cuts in post will be jump-cut style

### TAKE 9 — Final hold
- Static frame: best skin (matrix or hermes), banner showing
- Will overlay PR URL + "Kimi Track" badge in post
- Just need 5s of clean static for the hold

---

## Edit pipeline (DaVinci Resolve free / Kdenlive)

1. Import all takes
2. Cut to the structure in `HACKATHON_SHOT_LIST.md` t-table
3. Speed adjustments:
   - Take 2 montage: 1.5×
   - Take 3 hero run typing: 2× on the typing portion only
   - Take 8 flash: 1.75×
4. Captions: burn-in, large (≥48pt), bottom-third, white with black stroke
5. Music: single ambient pad, −12 dB; suggested free options:
   - Pixabay "Ambient Pad" tracks (CC0)
   - YouTube Audio Library "Cinematic Pad" tags
6. Export: H.264, 1920×1080, 60fps, ~10 Mbps, MP4

### One-shot ffmpeg fallback (if video editor crashes)

```bash
# Concatenate (after manual trim of each take to .mp4)
cat <<EOF > concat.txt
file 'take1.mp4'
file 'take2a.mp4'
file 'take2b.mp4'
file 'take2c.mp4'
file 'take2d.mp4'
file 'take3.mp4'
file 'take4.mp4'
file 'take5.mp4'
file 'take6.mp4'
file 'take7.mp4'
file 'take8.mp4'
file 'take9.mp4'
EOF
ffmpeg -f concat -safe 0 -i concat.txt -c copy rough.mp4

# Burn captions from an SRT
ffmpeg -i rough.mp4 -vf "subtitles=captions.srt:force_style='FontName=Inter,FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,BorderStyle=1,Outline=2'" \
       -c:v libx264 -crf 18 -preset slow -c:a copy captioned.mp4

# Add music at -12 dB
ffmpeg -i captioned.mp4 -i pad.mp3 \
  -filter_complex "[1:a]volume=-12dB[a1];[0:a][a1]amix=inputs=2:duration=first[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k final.mp4
```

---

## Caption text (per shot, ~6-8 words each)

| t | caption |
|---|---|
| 1.5s | an agent that lives in your terminal |
| 5s | 11 skins. each opens differently. |
| 9s | running on **kimi-k2-thinking** via openrouter |
| 16s | watch it think in color |
| 22s | latex. emoji. code. no browser needed. |
| 32s | minimap. workspace. sessions. |
| 42s | (silence — let the anims breathe) |
| 52s | every model. every skill. one keystroke away. |
| 62s | and a hundred more things you'll find in the diff |
| 72s | github.com/KUSH42/hermes-agent · PR #7 |
| 73s | Kimi Track · Nous Creative Hackathon |
