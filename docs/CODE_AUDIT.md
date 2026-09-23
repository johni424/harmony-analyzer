# Code Audit (Phase 0) — file-by-file, against the 28-step architecture

**Status:** v1.0 · **Date:** 2026-09-22 · **Commit audited:** `4980e9e` (post-CI)
**Method (per the plan):** README claims → actual implementation → actual tests →
actual behavior → specification. Every module re-read in full; every claim below
verified by grep/test-run, not memory.

Color taxonomy from the plan:

- **GREEN** — works and is architecturally sound
- **YELLOW** — works but needs refactoring
- **ORANGE** — works but accuracy is questionable
- **RED** — README claims functionality that isn't actually implemented
- **BLUE** — missing functionality

Headline: **no RED findings.** Every README claim traced to implementation and
test. The backlog below is honest maintenance and accuracy work, not repair.

---

## Part 1 — file-by-file audit

### `models.py` (229 lines) — GREEN

All eight dataclasses with documented invariants; the canonical event model
(ADR-004). `Chord.symbol()` covers every quality in `_QUALITY_SUFFIX`;
`pc_from_name` handles flats/doubles.

- 🟡 `N_CHORDQualITIES = len(QUALITY_INTERVALS)` in `chords.py` (re-exported
  surface) is **dead code** — zero consumers — and misspelled. Delete.

### `chroma.py` (112 lines) — GREEN with one ORANGE finding

The DSP is strong and, importantly, **honest**: every non-obvious constant
carries the measured reason it exists (sub-bin sharpening kernel, octave
weights, the deliberate *no-harmonic-residual-subtraction* note matching
ADR-005). 36 bins/octave + point-spread deconvolution is why phantom
`minmaj7` labels died.

- 🟠 **Double HPSS.** `extract_features` runs full-mix HPSS and analyzes
  `y_h + 0.25·y_p`; `rhythm.analyze_rhythm` then calls
  `librosa.effects.percussive(y)` on the *same original waveform* — a second,
  independent median-filter HPSS on the full signal. HPSS is the single most
  expensive stage (librosa decomposition). Fix: compute the mask decomposition
  **once** in `pipeline.analyze`, pass `y_p` (and `y_h`) through. Expected
  saving: ~20–30 % of total analysis CPU (measured baseline: 62 s CPU per
  6.5-min song). Also makes rhythm's transient extraction consistent with the
  harmonic stage's bleed model.

### `chords.py` (212 lines) — GREEN

Template matrix with spill modeling (spectral + harmonic — the measured fixes
from the *Creep* evaluation), rarity prior, evidence-scaled Viterbi, loose
softmax posteriors, sliver merging. The comment block on `EVIDENCE_SCALE`
documents *why 2.0* with the failure it fixed. Tests cover decoding, merging,
template symmetry.

- 🟡 `_merge_short_segments` uses a hard-coded `0.023` s frame duration while
  `viterbi_chords` itself computes `frame_dur` from `times`. Pass it through —
  a future hop-size change silently breaks the 0.6 s threshold.

### `bass.py` (143 lines) — GREEN

The bass register weights, 0.4 consistency gate and 1.8× dominance gate are
the measured fixes that took inversions from 21/21 false to a 0.995 dataset
score. Two structure smells:

- 🟡 **Private-API dependency:** `confidence.py` imports `_weighted_bass_chroma`
  (an underscore function) to re-measure the same dominance evidence. Promote
  it to a public `weighted_bass_chroma()` or return the per-chord dominance
  map from `label_inversions` so the trust stage reads *recorded* evidence
  instead of recomputing it.
- 🟡 Frame indices are recomputed per segment with `round(t / frame_dt)`
  instead of reusing each chord's frame span from the decoder.

### `voicing.py` (144 lines) — GREEN / one ORANGE

Threshold-gated pitch sets, support-weighted extension detection with honest
0.3 confidence floor, octave centroid/spread, spacing classification.

- 🟠 **Extension risk window.** The extension energy floor is 0.07 with
  support weights as low as 0.15 — on dense mixes a loud melody note can
  still produce a claimed 9/11/13 (the dataset showed synthesized 7ths vanish
  while real-mix docs warn extensions "is heuristic — check the confidence
  values"). Not a defect *claim*, but the weakest link in the trust chain:
  extensions currently bypass the calibration work in `confidence.py`
  (voicing confidence defaults to a flat 0.7 when none are claimed).
  Candidate fix: tie `VoicingInfo.confidence` for extension claims to the
  same dominance-style measure bass uses.

### `function.py` (269 lines) — GREEN

KK key profiles, diatonic-first spelling priority (`F` is IV, not #III),
tritone-#IV convention, secondary dominants/tritone subs, borrowed chords,
cadences, pedal/stepwise bass/pickup/retake annotations. Tests cover the
spelling priorities and devices. This module carries the plain-language
"effect" layer and does it well.

- 🟡 **Modulation is structurally impossible here by design** — one global
  key (`detect_key` over the whole song). The plan (step 14) wants
  section-level keys; the data model already supports it (`KeyEstimate` per
  section) but nothing populates it. BLUE-adjacent (see Part 3).

### `ingest.py` (130 lines) — YELLOW

URL classification, Spotify oEmbed → YouTube search, yt-dlp download.

- 🟡 **Concurrent-download race + wrong-file risk.** Output template is
  `%(id)s.%(ext)s` into a shared `$TMPDIR/harmony_analyzer/`, and the function
  returns `sorted(glob("*.wav"), key=mtime)[-1]` — the *newest* wav in the
  directory. Two simultaneous jobs (the web server runs analyses in threads)
  can interleave and return each other's file; a pre-existing cache from a
  different video can be returned if metadata resolution fails early.
  Fix: unique per-call output template (`%(id)s.<uuid>`) or write into a
  per-call temp dir; return the resolved file path directly (yt-dlp's
  `--print after_move:filepath`).
- 🔵 **Zero test coverage** — no `tests/test_ingest.py` at all. The
  classification functions (`classify_source`, `best_title`) are pure and
  trivially testable; download resolution can be tested with a monkeypatched
  `_ytdlp_download`.

### `pipeline.py` (175 lines) — GREEN

Linear stage flow matching the canonical 14-stage diagram, `on_stage` progress
hooks, fault-isolated rhythm and trust stages, chroma-flux boundary snapping.
The `try/except` around `on_stage` callbacks is 5× duplicated — minor.

- 🟡 **Silent excepts.** Rhythm/trust isolation is deliberate, but `except
  Exception: <pass/None>` with no logging means a real bug in `dna.py` or
  `rhythm.py` looks identical to "no beat grid in this song". At minimum log
  to stderr (or a `notes` field on the result).

### `report.py` (1,003 lines) — GREEN / YELLOW by size

The largest file by 5×: four renderers (terminal/JSON/Markdown/HTML player)
including the full player HTML/CSS/JS template with themes, PDF export,
waveform, detail panel. All features README claims exist and are verified
(print-based PDF export at line 755, theme toggle, keyboard shortcuts).

- 🟡 **Split recommended:** `report_data.py` (the payload serializations —
  `json_report`, `chord_dict`, `markdown_report`, `terminal_report`) and
  `player_html.py` (the template + its substitutions). The player template is
  ~700 of the 1,003 lines and is edited far more often than the JSON/MD
  serializers.

### `cli.py` (57 lines) — GREEN

Clean typer surface, `--json/--md/--html/--audio/--flats/--quiet`, error path
to exit code 1. Smoke-tested in CI.

- 🔵 Minor: no `--version`, and `--audio` docs don't mention it needs
  `keep_audio` (it does pass it — fine).

### `server.py` (597 lines) — GREEN

Job-store in memory (ADR-007), upload validation (extension allow-list, 200 MB
streamed cap), `/api/v1` contract endpoints that refuse to serve schema-
violating documents, range-supporting audio route. Landing page with progress
chips matching the pipeline stages.

- 🟡 `JOBS` cap pruning keeps *finished* jobs but never prunes work dirs on
  disk for evicted jobs (temp files accumulate until OS cleanup).

### `tests/` (10 suites, 79 tests) — GREEN

Coverage map: chords/bass/function/rhythm units; server (upload→poll→player +
contract endpoints); schema contract incl. pipeline-output validation;
trust engines; evaluation harness; benchmark harness; end-to-end synthesis.
Two gaps remain (both tracked in TESTING.md): no ingest tests (above) and no
real-mix golden file (licensing-blocked, synthetic dataset covers the need).

### Cross-cutting — schema/docs parity

- 🟡 `docs/JSON_SCHEMA.md` documents `beat_strengths` in the rhythm block
  (line 51/57), but `_rhythm_dict` doesn't emit it and the frozen schema
  (v1.0.0, correctly) doesn't allow it. The doc page lies about the payload.
  Fix: remove from the doc (or start emitting it — schema minor bump).
- 🔵 `harmony/__init__.py` exports only models/pipeline; the version string is
  hand-maintained (0.1.0) while the project has shipped 6 major phases.

---

## Part 2 — accuracy ledger (what the numbers say)

| claim | evidence | verdict |
|---|---|---|
| root accuracy 0.986 on synthetic set | `harmony-eval` baseline, CI-runnable | GREEN |
| bass/inversion 0.995 (post-fixes) | dataset + 21/21-false history documented | GREEN |
| strict chord quality 0.823 / family 0.905 | synthesized-7th limitation documented | ORANGE, known |
| meter on chord material | **0/6** — `_estimate_meter` normalizes by transient-inflated mean; root-caused, fix designed | ORANGE — top defect |
| confidence calibration | Brier ≈ 0.53 on always-correct cases | ORANGE, quantified |
| modulations | not detected (single global key) | BLUE, planned |

---

## Part 3 — concrete coding backlog (ordered)

Ordering rule from the plan: dependency chain first, user-visible defects
before refactors, refactors that unblock later work before cosmetic ones.

**1. Fix `ingest.py` race + return-path (YELLOW, ~1 h, safety)** —
unique output template or per-call temp dir; resolve the produced path via
`--print after_move:filepath`; add `tests/test_ingest.py`
(`classify_source`, `best_title`, monkeypatched download). *Do this before
any web deployment or parallel-job feature.*

**2. Fix meter estimation (ORANGE — top accuracy defect, ~2 h)** —
`_estimate_meter` scores each meter/phase by the *mean strength ratio* of its
downbeat grid, gated at 1.10. Measured on the `axis_c_major` fixture: the
true 4-beat downbeat lift is **1.067 — rejected by the gate** — while a
spurious 3-beat phase scores 1.107 and wins. Two fix directions, in order:
(a) score candidate meters by **periodicity of the strength sequence**
(autocorrelation at 2–7 beat lags, which is robust to the absolute lift
level), then (b) recalibrate the gate against both the synthetic set and the
original click-track unit tests. *Probed and rejected:* a median-baseline
residual approach — chord-change transients are phase-locked to downbeats,
so "cleaning" them deletes the very signal being measured (residual probe:
meter → 1, coherence → 0). Proof of fix: rerun
`harmony-eval datasets/synthetic.json`; expect meter_ok 0/6 → ≥5/6 without
regressing the click-track unit tests. This is the dataset's #1 finding and
unblocks "bar 12, beat 2" claims on real songs.

**3. Single HPSS decomposition (ORANGE → performance, ~1 h)** —
decompose once in `pipeline.analyze`; thread `y_p` into
`rhythm.analyze_rhythm(y_p, …)` (accept an optional precomputed percussive
signal). Expected ~20–30 % CPU cut; verify with
`harmony-bench --synthetic axis_c_major` before/after and record in
`eval/`.

**4. Confidence calibration v0 (ORANGE, ~3 h)** —
apply a monotone mapping (isotonic or Platt on the dataset's
(confidence, correct) pairs) in `confidence.py`; store the fitted parameters
as constants with the fitting script. Acceptance: Brier on the synthetic set
0.53 → ≤0.2; update spec §19 + HARMONIC_MODEL.md; bump nothing in the schema
(confidence values stay 0–1 floats).

**5. Docs parity: `beat_strengths` (YELLOW, ~15 min)** —
remove from JSON_SCHEMA.md (or emit + minor-bump the schema). Doc must match
payload, not aspirations.

**6. `report.py` split (YELLOW, ~1 h)** —
`report_data.py` + `player_html.py`; `report.py` becomes a compatibility
re-export so `from . import report` keeps working (server/tests untouched).
Do it before the next player-feature request — every day it grows, the split
gets harder.

**7. Promote `_weighted_bass_chroma` (YELLOW, ~30 min)** —
public name + docstring; update the two importers; delete the per-segment
frame-index recomputation in favor of recorded spans.

**8. Modulation-aware key (BLUE, the big one, ~1–2 d)** —
sliding-window key detection over `detect_key` (e.g. 8-bar windows, 2-bar
hop); emit section boundaries where tonic/mode changes and persist; report
per-section keys with the global key as default. Requires docs updates
(spec §15 single-key caveat, JSON_SCHEMA minor bump if adding a `sections`
block — additive, so v1.1.0).

**9. Extension-confidence hardening (ORANGE, ~2 h)** —
dominance-style measure for extension claims (analogous to the bass gate);
wire into `VoicingInfo.confidence`; adds an eval metric column.

**10. Hygiene batch (YELLOW, ~30 min)** —
delete `N_CHORDQualITIES`; log silent excepts in `pipeline.py` (stderr +
`result.notes`); prune work dirs when jobs evict in `server.py`; add
`--version` to CLI; wire `__version__` from package metadata.

**Not recommended now:** neural chord models (ADR-001), source separation
(ADR-005), a networked database (ADR-007), auth hardening (§26 — nothing is
exposed). The ADRs already say no; the audit agrees.

---

## Part 4 — audit-vs-plan coverage table

| plan phase | verdict |
|---|---|
| 1 Foundation (01–04 spec/journeys/architecture/data model) | GREEN — docs suite + `models.py` |
| 2 Audio intelligence (05–14) | GREEN, two ORANGE items (double HPSS, meter) |
| 3 Theory engine (15–17) | GREEN; modulation BLUE |
| 4 Trust (18–19) | GREEN; calibration ORANGE (quantified) |
| 5 Application (20–24) | GREEN (schema, v1 API, web, player); DB BLUE-by-decision (ADR-007) |
| 6 Quality (25–27) | GREEN (harness, datasets, CI); licensing GREEN |
| 7 Business (28) | GREEN (benchmarked cost model, ADR-008) |
