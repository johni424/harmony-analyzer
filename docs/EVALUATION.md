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

## The evaluation harness (built 2026-09, step 25) ✅/🟡

`harmony/evaluation.py` + `harmony-eval` implement every metric in the table
above, over two dataset layers in `datasets/`:

- **`synthetic.json`** — six cases (pop/classical/jazz/rock/folk; triads,
  7ths, inversions, 3/4) rendered to audio at eval time from exact specs.
  Ground truth is the spec itself: hermetic, license-free, CI-able.
- **`real_songs.json`** — hand-checked manifest (gospel vamp, *Let It Be*,
  *Creep*) with provenance notes. Audio is fetched on demand via yt-dlp and
  cached in the temp dir — **never committed**. Timed references only where
  beat-positions were verified; otherwise key/tempo/meter are scored
  sequence-level.

Run it:

```bash
.venv/bin/harmony-eval datasets/synthetic.json --out eval/synthetic   # no network needed
.venv/bin/harmony-eval datasets/real_songs.json --fetch               # yt-dlp required
```

### Baseline (synthetic set, 2026-09)

| metric | value |
|---|---|
| root accuracy | **0.986** |
| chord accuracy (strict root+quality) | 0.823 |
| family accuracy (7th/triad tolerance) | 0.905 |
| bass/inversion accuracy | **0.995** |
| key | 1.000 (relative-key alternates accepted) |
| tempo (±4 %, octave-folded) | 5/6 |
| meter | **0/6 — known engine defect, see below** |
| Brier (calibration) | 0.53 |

### Findings the harness surfaced (each is a measured limitation, not a guess)

1. **Meter detection fails on real chord material** (0/6 on fixtures where
   click-only tests pass). Root cause: `_estimate_meter` normalizes downbeat
   lift by the mean beat strength *including chord-change transients*, which
   inflates the denominator below the 1.10 trust gate. Fix candidate:
   compute the lift on onset-envelope *residuals* after removing chord-boundary
   transients, or gate on the phase-consistency of the accent pattern instead
   of absolute lift. Filed as the top rhythm defect.
2. **Synthesized 7ths lose their 7th** — pure-tone fixtures of Dm7/G7/Cmaj7
   decode as triads (jazz case: 0.00 strict / 0.49 family / 0.98 root). Real
   recordings keep 7ths (the gospel run found m7b5, maj7s), so this is largely
   a fixture-spectrum artifact — but it bounds what synthetic evals can claim
   about extension detection.
3. **Confidence is badly calibrated in absolute terms**: Brier ≈ 0.53 on
   cases where the analyzer is *always correct* (predicted posteriors sit at
   ~0.2–0.3). Calibration (spec §19) is now quantified and reproducible —
   the prerequisite for any "95 % confident ⇒ 95 % correct" claim.

Scaling to the 50–100-song target means adding rows to the manifests —
real-song entries need a URL, a key, and a `checked` provenance note; timed
references only where verified against the player.

## Method: how to evaluate a song yourself

```bash
.venv/bin/harmony <url-or-file> --json out.json --md out.md --html out.html
```

## The doc-format accuracy report (steps 1–2 of the production roadmap) ✅

`harmony-eval --out eval/accuracy --report-song <id>` emits exactly the
report the production roadmap calls for — percentages, not adjectives, plus
accuracy **by musical situation**:

| metric (synthetic baseline) | value |
|---|---|
| chord accuracy (strict) | 82.3 % |
| root accuracy | 98.6 % |
| bass/inversion accuracy | **99.5 %** |
| triads | 98.8 % |
| slash chords | **99.5 %** |
| fast changes | 97.0 % |
| sevenths (synthesized) | 0 % — measured limitation, see findings |
| key | 100 % |
| tempo (±4 %, octave-folded) | 5/6 |
| timing (median onset error) | ~22 ms |

`--report-song <id>` additionally writes the **per-song comparison table**
(analyzer vs ground truth, per-field ✓/✗/~ verdicts, timing in ms):

```markdown
| # | ground truth | analyzer | chord | bass | inv | roman | timing |
| 1 | C            | C        | ✓     | —    | —   | 0 ms ~ |
```

This is the artifact to hand a musician: they can verify every row by ear.

## The correction interface (step 3) ✅

When a musician knows better — the analyzer says `F`, the ear says `F/A` —
the Timeline Player (web-served jobs) shows **✎ Edit chord**. The correction:

1. is validated by a strict symbol parser (real note names, known quality
   suffixes — garbage like `Fquarter` is rejected with an explanation),
2. is applied to the canonical document **and re-validated against the
   frozen schema** (a correction may change labels, never the contract),
3. records provenance (`human_corrected: true`, original symbol kept),
4. feeds `to_dataset_case()`, which emits a ground-truth case in the exact
   format `harmony-eval` consumes — **user corrections become the evaluation
   dataset**, closing the loop: correction → ground truth → future accuracy.

Endpoints: `PATCH /api/v1/jobs/{id}/correct`, `GET /api/v1/jobs/{id}/corrections`.
Schema note: v1.1.0 (additive) — optional `chord.human_corrected` and the full
extension-interval enum.

Then check: (1) the progression against your ear on the strongest sections,
(2) inversions only where the bass is actually audible, (3) whether low-
confidence segments (conf < 0.1) coincide with genuinely ambiguous moments —
they should; if confident and wrong appears, file it as a defect with the
JSON excerpt.
