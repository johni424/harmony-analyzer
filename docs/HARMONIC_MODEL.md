# Harmonic Model

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §11–19.

## 1. Chord alphabet

15 qualities (`chords.QUALITY_INTERVALS`), each an interval→weight template:

`maj, min, dim, aug, sus4, sus2, maj7, min7, 7, hdim7, dim7, minmaj7, maj6, min6, 7sus4`

12 roots × 15 qualities = **180 Viterbi states**. The root is weighted 1.3 so
same-pitch-class-set chords disambiguate by emphasis (Dm7 = F6 as sets; the
root emphasis + rarity priors decide). Chord symbols render via
`models._QUALITY_SUFFIX` (e.g. `hdim7` → `m7b5`).

## 2. Template degradation models

Each template row starts from a flat leak of 0.03 across all 12 pitch classes
and adds, per chord tone at weight *w*:

| Model | Offset | Weight | Counterfactual |
|---|---|---|---|
| base tone | +0 | 1.0·w (+1.3 root) | — |
| spectral spill | ±1 st | 0.12·w | CQT windows leak ~10 % amplitude into neighbor bins |
| harmonic spill | +7 st | 0.30·w | 3rd harmonic (~0.30 of fundamental in real mixes): unmodeled, the 3rd of a triad fakes the 7th — every G looks like Gmaj7 |
| harmonic spill | +4 st | 0.12·w | 5th harmonic paints a major-third-two-octaves-up pc |

Rows are L2-normalized so cosine scoring keeps 4-note qualities competitive
with triads.

## 3. Scoring and decoding

`emissions = E @ chroma_normalized` → cosine similarity per state per frame
(frames L2-normalized; silent frames stay zero).

**Viterbi** (`chords.viterbi_chords`):

- **Self-loop transition** 0.90 base, capped 0.965, raised by a tempo-aware
  length bias: expected chord ≈ 2 quarter notes (clipped 0.5–4 s). No tempo
  available → 0.5 s default. Purpose: prefer fewer, longer segments without
  forbidding short real chords.
- **Rarity log-prior** per quality: triads 0; 7ths/maj7/min7 −0.03; maj6/min6
  −0.08; hdim7 −0.15; sus4/sus2 −0.18 (pop "sus" is usually a sung melody
  tone); dim/dim7/aug/7sus4 −0.2; minmaj7 −0.25.
- **Evidence scale 2.0**: log-emissions ×2.0. Without scaling, per-frame
  cosine log-differences (~0.1 nats) can never outvote the ~16-nat transition
  cost — measured failure: C–Am–F–G decoded without the Am.
- **Confidence**: per-frame softmax over emissions, temperature 0.045,
  segment score = mean posterior of the winning state. Loose by design (values
  stay well below 1.0); not calibrated across material.

**Post-processing:** segments < 0.6 s merge into the predecessor regardless of
label (transition moments briefly paint the old chord's tail); equal-label
neighbors coalesce; then `pipeline._snap_boundaries` re-snaps each boundary to
the chroma-flux maximum within ±0.3 s (min segment 0.1 s).

## 4. Bass & inversions (`bass.py`)

Bass chroma from the normalized CQT, octave weights `[0.2, 1.0, 1.0, 0.4,
0.1, 0, 0]` (C1..B7) targeting the E1–G3 electric-bass register. History: the
first version zeroed exactly that register and judged "bass" from the guitar
register — 21/21 false inversions on the first real-mix evaluation.

Per frame: argmax kept if it holds ≥ 12 % of low-register energy. Per segment:
modal bass pc kept if it spans ≥ 40 % of confident frames (walking-line
robustness). Then the honesty gates (spec §13): non-chord-tone bass → root
position + confidence ×0.95; root bass → root position; otherwise inversion
claimed **only if** the bass pc energy ≥ 1.8× the runner-up — else root
position. Inversion number maps through per-quality chord-tone tables
(`_INVERSION_TONES`), sorted ascending (3rd → 1st inv, 5th → 2nd, 7th → 3rd).

## 5. Voicing (`voicing.py`)

From the normalized CQT, per segment: pitch-class energies averaged over the
segment, normalized to sum 1. Sounding set = pcs ≥ max(0.02, 0.25 × max).
Extensions: candidates {b9, 9, #9, 11, #11, b13, 13, 7, maj7} that are (a) not
chord tones of the detected quality, (b) present in the sounding set, (c)
≥ 0.07 relative energy, (d) plausible for the quality (`_SUPPORT` table).
Confidence per extension = min(0.9, energy × 3 × (0.4 + support)). Added
notes = sounding pcs that are neither chord tones nor claimed extensions.
Register = energy-weighted octave centroid ± spread; spacing ∈ {single note,
cluster, closed, open, spread} by gap/spread rules.

## 6. Key & function (`function.py`)

- **Key**: duration-weighted chord pc histogram (root 1.0 + template tones)
  correlated (Pearson) against all 24 rotated Krumhansl–Kessler profiles.
  Confidence = correlation.
- **Roman numerals**: diatonic-first degree resolution, tritone → #IV,
  flat-side before sharp-side (never bI/bV), case by quality, suffix per
  `_CASE_SUFFIX`.
- **Roles**: tonic {I, III, VI}, predominant {II, IV}, dominant {V, VII}.
- **Devices** (append to `effect`): secondary dominant `V7/x` (dominant-class
  chord a fifth above a diatonic target ≠ I); tritone sub `subV7/x` (dominant
  a semitone above target); borrowed chords via parallel-mode diatonic test
  (+ bVII mixolydian, Neapolitan bII); cadences at song end (authentic,
  plagal, deceptive, backdoor, half); pedal point (3+ segments, same bass);
  stepwise bass runs (direction + affect); pickup chord (< 0.5 × median
  duration); immediate retake (A–B–A ostinato); quality-color one-liners.

## 7. Rhythm (`rhythm.py`)

Beat grid from the percussive onset envelope (librosa beat_track). Meter =
argmax over {2..7} × phase of (mean downbeat strength / mean beat strength);
requires ≥ 3 downbeat samples and ≥ 1.10 lift; ties within 5 % resolve to the
simplest meter; coherence = lift clamped to [0,1]; below the lift threshold →
**no grid** (None). Alignment: boundaries snap to beats within 0.16 beats;
per chord `bar`/`beat_in_bar` (1-based), `beats` (grid count),
`beat_fraction` (duration / sec-per-beat), `pushed` (entry off-grid but within
half a beat of the next beat = anticipation).
