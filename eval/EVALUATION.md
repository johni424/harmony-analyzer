# Real-song evaluation: Radiohead — "Creep" (studio, official video)

**Song:** `youtube.com/watch?v=FeK3c6XhiRg` · 235s · dense rock mix (drums, distorted guitars, vocals, strings)
**Why this song:** extremely well-documented harmony — the entire song loops **G – B – C – Cm** with the famous *borrowed iv* (Cm) as its signature sound. A recognizer has nowhere to hide.
**Method:** full pipeline run via the CLI (YT download → HPSS → 36-bpo CQT → deconvolution → Viterbi → bass → voicing → function), then independent empirical checks of the output claims against the raw CQT (low-register argmax for bass, per-pitch-class energy for voicing). Before/after comparison across two pipeline versions.

## Ground truth

| Bar loop | Chord | Note |
|---|---|---|
| 1 | G | plain major triad |
| 2 | B | major, the loop's "wrongness" |
| 3 | C | major |
| 4 | Cm | **borrowed iv** from G minor — the song's defining effect |
| Key | G major | |

## Results

| Metric | Before fixes | After fixes |
|---|---|---|
| Key detection | G major (0.71) | G major (0.72) ✔ |
| Root accuracy (≥3s segments, time-weighted) | 100% | 100% ✔ |
| Inversion claims | 21 (all false: `Gmaj7/D`, `B/F#`, `C/G`… — low-band argmax contradicted 21/21) | **0** (dominance gate blocks unsupported claims) ✔ |
| Borrowed Cm in verses | missed (energy tie Eb≈E in dense mix) | **caught** (33.9–39.1s, annotated `iv`, "borrowed from the parallel minor") ✔ |
| Cm in emphatic chorus/outro | caught (4/4, Eb≫E confirmed) | caught ✔ |
| Phantom `maj7` on G | 52s | 46s (still the weakest area, see below) |
| Spurious `sus4` labels | 10s (sus note often <25% energy) | 3s (survivors have genuinely audible sus notes) ✔ |
| Junk micro-segments (`D#maj7`, `Fsus2`, `A#`…) | ~16s | ~21s (mostly chord-transition splatter, labels are brief and low-confidence) |
| Progression skeleton | G–B–C(–Cm) recovered | G–B–C–Cm recovered ✔ |

## Defects found on real audio, and fixes applied

1. **Bass detector ignored the real bass register.** `bass.py` weighted octaves C1–B2 at zero — exactly where an electric bass fundamental sits — and judged "bass" from the guitar register, producing 21/21 false inversions. → Weights now `[0.2, 1.0, 1.0, 0.4, …]` (C1–B3).
2. **No dominance requirement for inversions.** A chord tone merely *existing* in the low band triggered a slash label. → An inversion is now claimed only when the bass pitch class dominates low-register energy (≥1.8× runner-up).
3. **Transition splatter became phantom chords.** At every chord change, the previous chord's tail notes briefly decoded as short wrong chords (`D#maj7`, `Fsus2` at C→G boundaries). → Slivers < 0.6s merge into their predecessor.
4. **Harmonic spill unmodeled.** Real instruments' 3rd harmonics paint phantom pitch classes (B → F#, which inflated `Gmaj7`). → Templates now include +7st (0.30×) and +4st (0.12×) spill per tone.
5. **Transition costs overpowered evidence.** With cosine emissions, log-emission gaps (~0.1 nats) were dwarfed by chord-switch costs (2×8.1 nats): Viterbi could not afford to insert a short correct chord between similar neighbors (demonstrated on C–Am–F–G). → Emission log-evidence scaled ×2.
6. **Sus labels fired on melody notes.** The sung 4th over a chord is not a suspension. → sus prior made clearly rarer than triads.

All 17 unit + end-to-end tests pass after the changes.

## Output-layer verdict (after fixes)

| Layer | Verdict |
|---|---|
| **Key** | Correct (G major), decent confidence. |
| **Progression (roots + timestamps)** | Effectively correct on sustained material; segments align with the actual loop. |
| **Inversions** | Previously unreliable (invented slash chords); now conservative — reports none on this song, which is correct for Creep's root-position loop. Dominance gate works but hasn't yet been proven *positive* (i.e., catching a real inversion) on real audio; synthetic test covers that path. |
| **Voicing** | Claimed pitch classes are conservative subsets of what sounds — never contradicted, often incomplete (e.g. omits the 5th when it's quieter). Spacing labels (`cluster`/`closed`/`spread`) unstable. Treat as indicative only. |
| **Function/roman numerals** | Correct where chords are correct: `I – III – IV – iv`, with the right "borrowed from the parallel minor — darkens the palette" annotation on Cm. |

## Known remaining limitations (measured, not guessed)

- **maj7 inflation on G:** ~46s of the plain G is labeled `Gmaj7`. Cause: F# energy in G segments measures 0.44–0.53× of G — larger than the modeled 3rd-harmonic spill (0.30×) can explain. Partly real timbre/overdubs, partly spill still underestimated. If precision on 7ths matters, add a "maj7 requires F# ≳ 0.5× threshold + persistence" post-filter.
- **Maj/min third confusion on B:** in the densest verses the D# third ties with D, so B fluctuates between `B` and `Bm` (low confidence 0.05–0.15 — the confidence numbers are honest).
- **Transition slivers:** ~1–2s per boundary decodes as a brief wrong label at very low confidence (<0.08). Merging deeper would smear real fast changes.
- **Voicing completeness & spacing** are heuristic; the honest fix is confidence-gated reporting rather than more guessing.

## Reproduce

```bash
cd song-harmony-analyzer
.venv/bin/harmony "$TMPDIR/harmony_analyzer/FeK3c6XhiRg.wav" \
  --json eval/creep.json --md eval/creep.md --html eval/creep.html
```

Artifacts: `eval/creep.json` (current), `eval/creep_before.json` (pre-fix snapshot), `eval/creep.md`, `eval/creep.html`.
