# harmony — chord progression, voicing & inversion analyzer

Analyzes the harmony of a song from a YouTube/Spotify link or a local audio
file and reports **exactly what is playing**:

- the **chord progression** with timestamps (triads, 7ths, sus, 6th chords…)
- the **voicing** — which pitch classes actually sound, extensions (9, 11, 13),
  register and spacing (closed / open / cluster / spread)
- the **inversion** of every chord (root / 1st / 2nd / 3rd — e.g. `G7/B`,
  `Am/C`) detected from the bass line
- the **functional analysis** — key, roman numerals, secondary dominants,
  borrowed chords, cadences, pedal points, and what each chord *does*
  musically ("V–vi deceptive cadence — withholds the ending, surprises the ear")
- the **rhythmic analysis** — tempo, meter (4/4, 3/4, …), a full beat/downbeat
  grid, and every chord's bar-and-beat placement ("bar 12, beat 2 · 4 beats,
  pushed entry"), with chord boundaries snapped to the beat grid so the
  harmonic and rhythmic views agree
- the **Harmonic DNA** — the song's signature progression, named when it
  matches a known pattern (the axis I–V–vi–IV, doo-wop, jazz ii–V–I, the
  Andalusian descent, …) plus a device tally, and a per-dimension **trust
  score** (chord labels, bass evidence, inversions, voicing, key/function,
  beat grid) instead of a single opaque confidence number

## Quick start

```bash
cd song-harmony-analyzer
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . yt-dlp pytest

# Analyze a local file
.venv/bin/harmony song.mp3

# Analyze from YouTube (requires ffmpeg on PATH)
.venv/bin/harmony "https://www.youtube.com/watch?v=..." --html report.html

# Interactive player with audio embedded — click chords to hear them
.venv/bin/harmony "https://www.youtube.com/watch?v=..." --html report.html --audio

# Spotify track (metadata resolved via oEmbed, audio via YouTube search)
.venv/bin/harmony "https://open.spotify.com/track/..." --json out.json

# Flat spellings (Bb, Eb instead of A#, D#)
.venv/bin/harmony song.flac --flats --md report.md
```

## Web UI (landing page + player)

A local web app where you paste a YouTube/Spotify link or drop an audio file,
watch the analysis progress, then explore the result in the interactive player.

```bash
# one-time: install the web extras
uv pip install --python .venv/bin/python -e ".[web]"

# start the server on http://127.0.0.1:8600
.venv/bin/harmony-web            # or: .venv/bin/python -m harmony.server
```

Then open <http://127.0.0.1:8600> — two tabs: **link** or **upload**. Jobs run
in the background; the page polls progress through the pipeline stages
(audio → features → chords → inversions & voicing → beat grid → player) and
links to the full Timeline Player when done.

**Programmatic API (v1, stable):** `GET /api/v1/schema` serves the frozen JSON
Schema; `GET /api/v1/jobs/{id}/analysis` returns the full canonical analysis
document (`{"schema_version": "1.0.0", "analysis": {…}}`) — never served
when it fails the contract. See [docs/API.md](docs/API.md).

## Output formats

| Flag | Format |
|---|---|
| *(default)* | Rich terminal table |
| `--json out.json` | Machine-readable JSON (chords, voicings, confidences) |
| `--md out.md` | Markdown table |
| `--html out.html` | Standalone interactive timeline (open in a browser) |
| `--html out.html --audio` | Same, with the audio embedded (base64) for playback sync: play/pause, click-to-seek, waveform, chord highlighting, 0.5/1/1.5× speed, keyboard shortcuts (space, ← →) |

## How it works

```
audio ──► HPSS (drum suppression)
      ──► CQT (36 bins/semitone, high-Q)
      ──► PSF deconvolution (kill ±1-semitone filter skirts)
      ──► max-fold to 12 bins/octave + octave-weighted chroma
      ──► time-median filter (de-splatter)
      ──► Viterbi over 180 chord states (15 qualities × 12 roots)
           · cosine emission scoring against spill-aware templates
           · tempo-adaptive self-loop stickiness
           · rarity prior (dim/aug genuinely rare in pop/jazz)
      ──► chroma-flux boundary snapping
      ──► bass detection (octave-weighted, octave C2–B3)
           · bass pc + median voting per segment → inversions
      ──► voicing analysis (extensions, register, spacing)
      ──► key detection (Krumhansl-Schmuckler profiles)
      ──► functional annotation (roman numerals, devices, cadences)
      ──► rhythm analysis (onset envelope → beat grid → meter/downbeats)
           · chord boundaries snapped to beats; bar/beat placement per chord
           · skipped entirely when no trustworthy pulse exists
```

### Rhythmic analysis

- Beat tracking runs on the percussive-emphasized mix (spectral flux); the
  meter is chosen by testing each candidate meter 2–7 against the beat-strength
  profile (downbeats must be ≥10% stronger than the average beat, with
  near-ties resolved toward the simplest meter).
- Chords report `bar`, `beat_in_bar`, `beats` (grid count), `beat_fraction`
  (exact length in beats) and `pushed` (off-beat anticipatory entry).
- The HTML player pulses a dot on every beat (larger, orange on downbeats),
  draws bar lines + bar numbers and light beat ticks under the chord blocks,
  and shows "bar X, beat Y" in the detail panel — so you can follow along
  while listening.

### Design decisions worth knowing

- **No harmonic-residual subtraction.** A "3rd harmonic bin" (root + 19
  semitones) is also where genuinely played notes live; subtracting the
  fundamental's energy there erases real chord tones.
- **Mid-register emphasis, bass included.** Chord quality lives in C3–C6;
  a full-weight bass fundamental would re-root every chord to the bass note,
  but the bass must stay present for root detection and inversions.
- **The bass is decoded separately** from the chord quality, then combined:
  bass pc = root → root position; bass pc = 3rd/5th/7th → inversion;
  bass pc ∉ chord tones → pedal/passing note (root-position label, flagged).
- **Confidence scores everywhere.** Voicing and inversion detection from a
  mixed stereo recording is inherently uncertain; every claim carries a score.

## Accuracy & limits

Validated on synthetic material with exact ground truth (chords, inversions,
bass lines). On real-world recordings expect:

- high reliability on triads/7ths with clear harmony and bass
- moderate reliability on dense mixes, extended chords and fast changes
- extension detection (9/11/13) is heuristic — check the confidence values

## Documentation

Full engineering docs live in [`docs/`](docs/TECHNICAL_SPECIFICATION.md),
grounded in the actual implementation with a code-to-spec gap analysis
(✅ implemented · 🟡 partial · 🔴 missing · ⚠️ risky · 🧪 needs validation · 💡 future):

| Doc | Contents |
|---|---|
| [TECHNICAL_SPECIFICATION.md](docs/TECHNICAL_SPECIFICATION.md) | master spec — 30 sections: product, system, music intelligence, data, quality, business |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | module map, data flow, invariants, failure isolation |
| [AUDIO_PIPELINE.md](docs/AUDIO_PIPELINE.md) | CQT front end, sharpening, chroma variants, onset envelope |
| [HARMONIC_MODEL.md](docs/HARMONIC_MODEL.md) | templates, Viterbi, bass/inversion gates, voicing, key/function, rhythm |
| [API.md](docs/API.md) | HTTP surface, job lifecycle, error model |
| [JSON_SCHEMA.md](docs/JSON_SCHEMA.md) | canonical output schema + machine-checkable invariants |
| [EVALUATION.md](docs/EVALUATION.md) | metrics, completed real-mix evaluations, dataset plan |
| [TESTING.md](docs/TESTING.md) | what each test suite guarantees, known gaps |
| [LICENSING.md](docs/LICENSING.md) | copyright position, third-party licenses, audio-handling rules |
| [ROADMAP.md](docs/ROADMAP.md) | v1.1 → v2.0 sequenced plan |
| [docs/ADR/](docs/ADR/) | architecture decision records (chroma, bass separation, Viterbi, event model, no source separation, streamed player) |

## Tests

```bash
.venv/bin/python -m pytest -q          # 55 tests: units + contract + server + synthetic end-to-end
```

The end-to-end test renders a I–V7–vi–IV progression (including a first-
inversion V7) to a wav and asserts the full pipeline recovers it.

## Project layout

```
docs/           # engineering documentation (see table above)
src/harmony/
├── models.py     # dataclasses: Chord, VoicingInfo, KeyEstimate, AnalysisResult
├── chroma.py     # CQT features, PSF deconvolution, chroma variants
├── chords.py     # templates + Viterbi decoder
├── bass.py       # bass detection & inversion labeling
├── voicing.py    # extensions, register, spacing
├── function.py   # key, roman numerals, harmonic devices, effects
├── ingest.py     # yt-dlp / Spotify oEmbed / local files
├── pipeline.py   # orchestration + boundary snapping
├── report.py     # terminal / JSON / Markdown / HTML output
└── cli.py        # typer CLI
```
