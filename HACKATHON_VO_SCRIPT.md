# VO script — female AI voice (ElevenLabs / similar)

**Tone:** calm, low, confident. Slight rasp if available. Not perky. Think night-mode narrator, not product demo.
**Pacing:** ~130 wpm. Leave breath between lines. Do **not** rush to fill the gaps — the silence is the music doing work.
**Pronunciations:**
- `kimi k2 thinking` → "KEE-mee KAY-two THINK-ing"
- `openrouter` → one word, "OPEN-rowt-er"
- `latex` → "LAY-tek" (not "LAY-tex")
- `nous` → "NOOSE"
- `hermes` → "HUR-meez"

---

## Lines (in order, with target in-time)

| # | t (s) | line | notes |
|---|---|---|---|
| 1 | 1.8 | an agent that lives in your terminal | soft open, almost whispered |
| 2 | 7.4 | eleven skins. eleven openings. | even cadence, period beat |
| 3 | 14.8 | running on kimi k2 thinking, via openrouter | proper-noun stress on *kimi k2 thinking* |
| 4 | 22.2 | watch it think, in color | comma is a small breath, not a stop |
| 5 | 29.5 | latex. emoji. tool calls. all native. | four short stabs, equal weight |
| 6 | 33.2 | and it built this. live. | pause before *live*; *live* drops in pitch |
| 7 | 40.5 | with streaming effects you can feel | warm, slight lift on *feel* |
| 8 | 47.9 | animation engines, straight to your terminal | comma is a real beat |
| 9 | 51.7 | every model. one keystroke away. | clipped, confident |
| 10 | 59.0 | every theme repaints, in place | flat delivery, no smile |
| 11 | 68.3 | hermes agent. pull request seven. | matter-of-fact, like a sign-off |
| 12 | 71.1 | kimi track. nous creative hackathon. | last line, slight decay |

---

## Single-block version (paste into ElevenLabs)

```
an agent that lives in your terminal.

eleven skins. eleven openings.

running on kimi k2 thinking, via openrouter.

watch it think, in color.

latex. emoji. tool calls. all native.

and it built this. live.

with streaming effects you can feel.

animation engines, straight to your terminal.

every model. one keystroke away.

every theme repaints, in place.

hermes agent. pull request seven.

kimi track. nous creative hackathon.
```

---

## Voice picks (ElevenLabs)

- **Charlotte** — low, English, calm. Best fit for the night-narrator tone.
- **Matilda** — warmer, American. Use if Charlotte reads too cold.
- **Sarah** — neutral, clean. Fallback.

Stability ~45, similarity ~75, style ~10. Don't crank style — it'll over-perform and ruin the calm.

---

## Files

- `HACKATHON_SUBTITLES.srt` — burn-in subs, beat-locked to the 130 BPM caption schedule in `HACKATHON_RECORDING_SCRIPT.md`.
- `HACKATHON_VO_SCRIPT.md` — this file.
