# Evaluation

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §24.

## What we measure

| Metric | Definition |
|---|---|
| Chord accuracy | segment overlap-weighted agreement of (root, quality) vs. reference |
| Bass/inversion accuracy | agreement of bass pc (and slash label) where reference states one |
| Voicing soundness | claimed extensions/added notes verifiable by ear in the segment |
| Boundary precision | \|detected − reference boundary\| distribution (target: within a 16th) |
| Confidence calibration | reliability of `confidence` vs. empirical correctness (per material class) |
| Rhythm validity | tempo within ±4 % of felt tempo (allowing ×2/×½); meter correct |

## Completed evaluations (real runs)

### 1. Radiohead — *Creep* (first real-mix test)

Artifacts: `eval/creep.json`, `eval/creep.md`, `eval/creep_before.json`,
`eval/creep.html`. Findings (see `eval/EVALUATION.md` at repo root for the
full narrative):

- Progression G–B–C–Cm correctly recovered end to end.
- Exposed **three systematic defects**, all fixed and regression-tested:
  1. bass-octave weights zeroed the real bass register → 21/21 false
     inversions (fixed in `bass.py` weights + dominance gate),
  2. CQT spectral leakage produced phantom extensions (fixed by spill
     modeling in templates + sub-bin sharpening),
  3. Viterbi evidence scale too low → short real chords swallowed (fixed,
     scale 2.0).

### 2. Gospel production — *"Jesus At The Mention Of Your Name"* (dense mix)

Artifacts: `eval/user_song.{json,md,html}`, `eval/user_song_player.html`.
F major, 112.3 BPM 4/4 (conf 0.69), 184 chord segments, all placed on the
beat grid. Findings:

- Functional layer strong: secondary dominants (A7→Dm turnarounds),
  modal mixture (Fm, Bbm), bVII/bVI borrows, backdoor motions all surfaced
  with sensible effect text.
- Confidence values rank-correct **within** the song but absolutely low on
  the densest sections (0.03–0.28) — calibration is an open item (spec §19).
- Some claimed inversions on dense vamps are likely passing-bass color
  rather than deliberate slash voicings — the dominance gate keeps these
  conservative but the low register of a 10-voice gospel mix is genuinely
  ambiguous (spec §12 ⚠️).

## Target: labeled evaluation set (not yet built) 🧪

50–100 songs spanning pop/rock/jazz/gospel/classical with chord + bass
annotations (e.g. from the McGill Billboard dataset as a starting point,
hand-checked), scored with the metrics above and reported per genre bucket.
This is the prerequisite for confidence calibration and for any "accuracy"
claim in public.

## Method: how to evaluate a song yourself

```bash
.venv/bin/harmony <url-or-file> --json out.json --md out.md --html out.html
```

Then check: (1) the progression against your ear on the strongest sections,
(2) inversions only where the bass is actually audible, (3) whether low-
confidence segments (conf < 0.1) coincide with genuinely ambiguous moments —
they should; if confident and wrong appears, file it as a defect with the
JSON excerpt.
