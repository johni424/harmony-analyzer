# Audio Pipeline

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §9–10.

Implemented in `chroma.py` (features) and `rhythm.py` (onsets). All constants
live at the top of each module; the numbers below are the shipped values.

## 1. Ingest → waveform

- YouTube/Spotify: yt-dlp extracts bestaudio → WAV in
  `$TMPDIR/harmony_analyzer/<video-id>.wav` (up to 600 s timeout).
- Local files: used as-is (soundfile/librosa read mp3, m4a, wav, flac, ogg…).
- `chroma.load_audio`: mono, resampled to **22050 Hz**.

## 2. HPSS pre-filtering

`librosa.effects.hpss` splits harmonic vs. percussive components; analysis
uses `y_harmonic + 0.25 × y_percussive` — percussive content is suppressed but
not removed (a little bleed keeps attacks realistic; pure harmonic residue
smears transients into the chord beds).

Rationale (ADR-005): we do **not** attempt deeper source separation. Harmonic
residual subtraction in particular destroys genuinely played notes whose
partials land where a fundamental would.

## 3. CQT front end

| Parameter | Value | Why |
|---|---|---|
| `fmin` | C1 = 32.70 Hz | covers the electric bass fundamental range |
| `n_bins` | 7 octaves × 36 bins = **252** | 36 bins/octave = 3 per semitone |
| `hop_length` | 512 | ≈ 23 ms frames at 22.05 kHz |
| bins folding | max over the 3 sub-bins | sharper pitch peaks than mean |

**Sub-bin sharpening.** A pure note produces a CQT peak with ±1 sub-bin
skirts at ~50 % of the peak (intrinsic to the filter shape). The kernel
`cqt − 0.5·roll(+1) − 0.5·roll(−1)`, clipped at 0, cancels that skirt so a
played A no longer fakes G♯/A♯ (which produced phantom minmaj7 chords). Edge
rows are zeroed to remove roll artifacts.

**Deliberately absent:** harmonic-residual subtraction
([ADR-005](ADR/ADR-005-no-source-separation.md)); a loud G2 fundamental would
otherwise erase a genuinely played D4 (its 3rd harmonic).

## 4. Derived representations

From the 84-row sharpened CQT (7 octaves × 12 semitones):

1. **Full chroma** (12×T): sum over all 7 octaves. Used for key context and
   the player's voicing display data.
2. **Recognition chroma** (12×T): octave weights `[0.35, 0.55, 0.85, 1.0,
   1.0, 0.7, 0.3]` — the bass octave is *down-weighted, not excluded*: the
   bass must inform the decoder (it carries the root) but a full-weight bass
   fundamental re-roots every chord to the bass note. Then a length-5 median
   filter over time kills frame spikes (splatter, transients).
3. **Bass chroma** (12×T): octaves C2–B2 + C3–B3 summed. Coarse stage input;
   `bass.py` rebuilds its own weighted version from the normalized CQT (see
   HARMONIC_MODEL §bass).
4. **Normalized CQT** (84×T): per-frame L2 normalization — loudness-invariant
   evidence for voicing and bass.

## 5. Onset envelope (rhythm stage)

On the **percussive component only** (`librosa.effects.percussive`):
`onset.onset_strength` with `aggregate=np.median`, hop 512. Median aggregation
is less domineered by big hits than mean; the percussive emphasis sharpens
drum transients while harmonic attacks still mark beats in sparse mixes.

## 6. Frame economics

A 4-minute song ≈ 10,400 frames × 84 bins — the CQT is the dominant memory
item (tens of MB float64). Everything downstream (Viterbi over 180 states ×
T) is a few hundred ms; features are the expensive half of the ~30–60 s
budget, most of which is actually HPSS + CQT compute.

## 7. Known limitations

- One global spectral resolution (no multi-resolution front end).
- 22.05 kHz ceiling: no content above ~11 kHz is analyzed (fine for harmony).
- Octave errors are unresolvable from chroma alone (register evidence in
  `voicing.py` is octave-domain heuristic — see spec §14 🧪).
- Beat tracking inherits librosa's octave ambiguity in tempo (spec §10 🧪).
