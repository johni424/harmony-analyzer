# HARMONY ANALYZER
## Technical Specification

**Version:** 1.0
**Status:** Active Development
**Last Updated:** 2026-09-21
**Repository:** [johni424/harmony-analyzer](https://github.com/johni424/harmony-analyzer)

### Version history

| Version | Scope |
|---|---|
| v1.0 | Architecture baseline — documents the shipped engine (chroma → Viterbi → bass/inv → voicing → key/function → rhythm) and the web service |

Future: v1.1 audio-pipeline refinement · v1.2 harmonic event model · v2.0 production architecture.

---

## How to read this document

This is the **master contract** for the project: what the system is supposed to
do, what "correct" means, and where the implementation stands today. Every
section is marked against the actual repository:

| Mark | Meaning |
|---|---|
| ✅ | implemented and tested |
| 🟡 | partially implemented |
| 🔴 | not implemented |
| ⚠️ | implemented but technically risky |
| 🧪 | implemented, needs validation on more data |
| 💡 | future / commercial feature |

Deep details live in linked documents, not here:

```
TECHNICAL_SPECIFICATION.md (this file)
├── ARCHITECTURE.md            — module map, data flow, deploy topology
├── AUDIO_PIPELINE.md          — signal processing: CQT, chroma variants, HPSS
├── HARMONIC_MODEL.md          — qualities, Viterbi, bass, voicing, key, function
├── API.md                     — HTTP surface, job lifecycle, errors
├── JSON_SCHEMA.md             — canonical output schema (reference)
├── EVALUATION.md              — how we measure correctness; links to measured runs
├── TESTING.md                 — test strategy, what each suite guarantees
├── LICENSING.md               — copyright position and third-party licenses
├── ROADMAP.md                 — MVP → commercial sequence
└── ADR/                       — architecture decision records
    ├── ADR-001-chroma-based-harmony.md
    ├── ADR-002-separate-bass-analysis.md
    ├── ADR-003-viterbi-chord-decoder.md
    ├── ADR-004-canonical-harmonic-event.md
    ├── ADR-005-no-source-separation.md
    └── ADR-006-streamed-web-player.md
```

---

## Analysis philosophy

The system separates four layers and never lets one masquerade as another:

1. **Observation** — what acoustic evidence exists? (CQT magnitudes, onset
   envelope, low-register energy)
2. **Detection** — what structures are detected? (pitch classes, chord states,
   bass line, beat grid)
3. **Interpretation** — which chord, inversion, voicing, and harmonic function
   *best explain* those observations?
4. **Explanation** — how is the result presented to a musician? (symbols,
   roman numerals, plain-language effects, confidence)

Consequence: **the system reports the best-supported harmonic interpretation
of the recording — it never claims certainty where the evidence is ambiguous.**
Ambiguity is resolved toward the musically likelier reading (rarity priors,
dominance gates), and the confidence number travels with every claim.

## Non-goals

Harmony Analyzer is not intended to:

- identify every individual instrument in a mixed recording
- guarantee exact transcription of every note (no MIDI-level transcription)
- replace a professional music transcriber
- infer undocumented performer intent (e.g. *why* a player chose a voicing)
- claim certainty where the audio evidence is ambiguous
- support real-time / streaming analysis (batch, whole-file analysis only)
- detect modulation across song sections (one global key per analysis, see §15 ⚠️)

---

# A. Product

## 1. Product definition ✅

Harmony Analyzer takes a song (YouTube/Spotify link or local audio file) and
produces the **full harmonic + rhythmic analysis**: the chord progression with
timestamps, each chord's quality (triads, 7ths, sus, 6ths…), the **inversion**
(slash chords like `G7/B`), the **voicing** (sounding pitch classes,
extensions 9/11/13, register/spacing, added notes), the **functional
interpretation** (key, roman numerals, cadences, secondary dominants, modal
mixture, plain-language effects), and the **rhythmic placement** (tempo,
meter, bar/beat position of every chord).

Delivery surfaces: CLI (`harmony`), interactive web app (`harmony-web`,
FastAPI + embedded Timeline Player), and machine-readable reports
(JSON / Markdown / standalone HTML).

**What "correct" means:** the reported progression, inversions, and voicings
are the best-supported *interpretation* of the mix, with honest confidence
values, snapped to the beat grid where one exists. Ground truth is what a
trained musician hears in the recording, not the printed sheet music
(recordings differ from charts; the analyzer analyzes the recording).

## 2. User journeys ✅ / 💡

| Journey | Status |
|---|---|
| Musician pastes a YouTube link, gets an interactive chord timeline synced to audio | ✅ |
| Producer uploads an MP3, studies inversions and voicings per chord | ✅ |
| Student follows along bar-by-bar with the beat pulse and chord grid | ✅ |
| Music teacher exports a printable/PDF chart of the progression + voicings | ✅ (browser print) |
| Developer consumes analyses via JSON/HTTP API for their own tooling | 🟡 (API exists, not versioned/authenticated) |
| Batch analysis of a playlist/library with persistent history | 🔴 |

## 3. Commercial positioning / use cases 💡

- **Individual musicians** (students, hobbyists, gigging players): "what
  exactly is played in this song" — practice and learning tool.
- **Content creators / DJs**: harmonic compatibility and structure insight.
- **Music education**: guided harmonic listening; the effect annotations
  ("deceptive cadence — withholds the ending") are the differentiator.
- **Pro sumo later (💡)**: API access for catalog analysis (music supervision,
  sample clearance research) — gated by licensing posture, see §27.

Differentiators: inversion + voicing analysis (rare in chord detectors),
functional/effect explanation layer, rhythm-aligned output, fully local
processing option.

---

# B. System

## 4. System architecture ✅

Six-stage pipeline, single process, fully local:

```
source (URL / file)
   │  ingest.py        yt-dlp download → wav; Spotify via oEmbed + YT search
   ▼
audio (mono, 22.05 kHz)
   │  chroma.py        HPSS → CQT (36 bins/semitone·3) → sharpened chroma,
   │                   recognition chroma, bass chroma, normalized CQT
   ▼
Features
   │  chords.py        180-state template matching + Viterbi → segments
   │  (pipeline)       chroma-flux boundary snapping; sliver merging
   ▼
Chord segments
   │  bass.py          low-register dominance → bass pc → inversion
   │  voicing.py       sounding pcs, extensions, spacing
   │  function.py      key (KK profiles) → roman numerals, roles, effects
   ▼
Annotated chords
   │  rhythm.py        beat grid, meter, chord↔beat alignment
   ▼
AnalysisResult ──► report.py ──► terminal / JSON / Markdown / HTML player
                 └► server.py ──► web UI + streamed audio player
```

Module-by-module detail: [ARCHITECTURE.md](ARCHITECTURE.md).

## 5. Frontend architecture ✅

Two self-contained HTML surfaces, no build step, no external dependencies:

- **Landing page** (served from `server.py`): tabs for URL vs. file upload,
  drag & drop, live pipeline-stage progress, result card → player link.
  Dark/light theme with persistence.
- **Timeline Player** (generated by `report.py`): waveform with click-to-seek,
  chord blocks colored by harmonic function, bar lines + numbers, transport
  (Start/Stop, Pause, 0.5×/1×/1.5×), detail panel with piano-voicing diagram,
  PDF export via print layout, JSON/MD download, beat pulse HUD.

The web player **streams** audio from `/audio/{job_id}` (HTTP range requests)
instead of embedding base64 (365 KB page instead of ~100 MB) —
[ADR-006](ADR/ADR-006-streamed-web-player.md). The CLI `--html --audio` export
still embeds audio to remain a single portable file.

## 6. Backend architecture ✅ / ⚠️

- FastAPI app in `server.py`; analysis jobs run in daemon threads
  (`threading.Thread`), one per job, progress reported through the pipeline's
  `on_stage` callback.
- **In-memory job store** (`JOBS` dict + lock, max 40, pruned LRU) —
  ⚠️ jobs and players are lost on restart; acceptable for single-user local
  use, a real store is v2 (see §21).
- Job artifacts: `player.html` written to a per-job temp work dir; audio
  streamed from the ingest path.
- Long operations (yt-dlp: up to 600 s timeout) are subprocess calls; failures
  surface as job `error` state.

## 7. API architecture ✅ / 🟡

Job-based async REST (details: [API.md](API.md)):

| Route | Method | Purpose | Status |
|---|---|---|---|
| `/` | GET | landing page | ✅ |
| `/healthz` | GET | liveness | ✅ |
| `/api/jobs/url` | POST | create job from YouTube/Spotify URL | ✅ |
| `/api/jobs/file` | POST | create job from uploaded audio (multipart, ≤200 MB) | ✅ |
| `/api/jobs/{id}` | GET | poll stage/summary | ✅ |
| `/player/{id}` | GET | interactive player HTML | ✅ |
| `/audio/{id}` | GET | stream audio (range requests) | ✅ |
| API versioning (`/v1/`) | — | — | 🔴 |
| Auth / rate limiting | — | — | 🔴 |

Errors: HTTP status + `{"detail": …}`; client errors 4xx are explicit
(unsupported source, bad file type, size limit), worker failures surface as
job `stage: "error"` with the exception text (truncated to 500 chars).

## 8. Database architecture 🔴 (target) / 🟡 (current)

- **Current:** no database. Job objects live in memory; finished analyses are
  only as durable as the temp work dir. Job IDs are random 12-hex strings.
- **Target (v2, 💡):** SQLite (single-user) or Postgres (hosted) with tables
  `songs` (dedup hash, title, duration), `analyses` (parameters, engine
  version, JSON payload), `jobs` (lifecycle audit). Schema sketch in §21.
  Rationale: re-analysis without re-download, library/journey #6, engine
  versioning of results.

---

# C. Music Intelligence

## 9. Audio pipeline ✅

Mono resample to 22.05 kHz → HPSS (harmonic component + 0.25× percussive
bleed) → CQT from C1 across 7 octaves at **36 bins/octave** → sub-bin
sharpening `[-0.5, 1, -0.5]` (cancels the CQT point-spread skirt that made a
played A fake a G♯/A♯) → max-folding to 84 semitone bins → four derived
representations: full chroma, **recognition chroma** (octave-weighted to
de-emphasize bass without excluding it), **bass chroma** (C2–B3), per-frame
L2-normalized CQT for voicing.

Frame resolution: hop 512 ≈ **23 ms**.

**Deliberately absent:** harmonic-residual subtraction (a "3rd-harmonic bin"
is also where genuinely played notes sit — subtracting it destroys real chord
tones; [ADR-005](ADR/ADR-005-no-source-separation.md)).

Details: [AUDIO_PIPELINE.md](AUDIO_PIPELINE.md).

## 10. Beat detection ✅ / 🧪

Onset-strength envelope (median-aggregated) on the **percussive-emphasized**
mix → librosa beat tracker → tempo + beat grid. Honest failure: if the
material has no trustworthy pulse (fewer than 8 beats, non-positive tempo, or
no accent hierarchy), the stage returns **no grid at all** rather than
guessing; chords then simply carry no bar placement.

Known limits (🧪): beat trackers report the *tatum-level* tempo, which can be
half/double the felt tempo; the meter estimator partially absorbs this, but a
6/8 ballad may read as slow-3 or fast-6.

## 11. Chord detection ✅

15 qualities × 12 roots = **180 states**. Weighted template per quality
(root 1.3 to disambiguate same-pc-set chords like Dm7 vs F6) with three
explicit degradation models baked into the templates:

- baseline leak 0.03 across all pcs,
- spectral spill ±1 semitone (0.12×weight) — CQT window leakage,
- harmonic spill +7 st (0.30×) and +4 st (0.12×) — 3rd/5th harmonics painting
  phantom pitch classes (unmodeled, every G looks like Gmaj7).

Scoring: cosine similarity of L2-normalized templates vs. L2-normalized
recognition chroma. Decoding: Viterbi with tempo-adaptive self-loop
transition, per-quality rarity log-priors, evidence-scale 2.0 — see
[HARMONIC_MODEL.md](HARMONIC_MODEL.md) and
[ADR-003](ADR/ADR-003-viterbi-chord-decoder.md).

Post-processing: segments < 0.6 s merge into their predecessor (kills
transition slivers), adjacent equal labels coalesce, boundaries re-snapped to
chroma-flux maxima within ±0.3 s.

## 12. Bass detection ✅ / ⚠️

Bass chroma rebuilt from the normalized CQT with octave weights
`[0.2, 1.0, 1.0, 0.4, 0.1, 0, 0]` (electric-bass register E1–G3; an earlier
weighting that zeroed the actual bass register produced 21/21 false
inversions on a real mix). Per frame: argmax kept only if it clearly dominates
(share ≥ 0.12). Per segment: modal bass pc kept only if it appears in ≥ 40 %
of confident frames (robust against walking lines).

⚠️ In dense gospel/band mixes the low register is often ambiguous; see §13
for the gate that keeps the analyzer from inventing inversions.

## 13. Inversion engine ✅ / ⚠️

Bass pc → inversion via per-quality chord-tone tables (3rd/5th/7th/sus
intervals). Three honesty gates:

1. non-chord-tone bass → **root position**, slash label suppressed, small
   confidence penalty (pedal/passing note, not an inversion);
2. bass pc == root → root position;
3. **dominance gate:** an inversion is claimed only if the candidate bass
   energy ≥ 1.8× the runner-up in the low register — otherwise the segment is
   reported as root position rather than a speculative slash chord.

⚠️ Residual risk: on dense mixes some claimed inversions may be passing-bass
color; confidence marks the shaky ones. Inversion *labels* are exact only when
the bass register is unambiguous — this is stated in user-facing docs.

## 14. Voicing engine ✅ / 🧪

Per segment, from the normalized CQT: pitch classes ≥ max(0.02, 0.25 × max pc
energy) count as sounding. Extensions (9/11/13/b9/#11/b13…) are claimed only
for qualities that plausibly support them (support table), when the extension
pc carries ≥ 0.07 relative energy, with a per-extension confidence. Anything
sounding that is neither a chord tone nor a claimed extension is reported as
an **added note**. Register (octave centroid + spread) classifies spacing:
`spread / cluster / open / closed`.

🧪 Spacing categories are heuristic (octave-domain, not true note-domain);
a real note-level estimate needs multi-pitch estimation — future.

## 15. Key detection ✅ / ⚠️

Duration-weighted chord pitch-class histogram correlated against all 24
rotated Krumhansl-Kessler profiles; best Pearson correlation wins.
⚠️ **One global key per analysis.** Modulation is not tracked; sections in
other keys get interpreted through the home key (a bridge in the relative
minor still reads as vi-based). Local/section key estimation is a v1.2 goal.

## 16. Roman numeral engine ✅

Scale-degree resolution is diatonic-first, then chromatic with spelling
priority: exact diatonic match → tritone spelled #IV → flat-side alterations
(bVII, bVI, bIII…) except bI/bV (nonsense) → sharp-side (#IV/#V) → fallback.
Quality → case + suffix (lowercase minor/dim, °, ø7, +, sus/maj7 suffixes).
Inversions are **not** encoded in the numeral (figured bass 6/6/4 is not
emitted; inversion lives in the slash symbol and the inversion field) — a
deliberate simplification, revisit with the figured-bass feature (💡).

## 17. Harmonic-function engine ✅

Roles by degree: tonic (I/III/VI), predominant (II/IV), dominant (V/VII).
Device detection over the decoded sequence:

- **secondary dominants** `V7/x` (dominant-quality chord a fifth above a
  diatonic target, root ≠ tonic),
- **tritone substitutions** `subV7/x` (dominant a semitone above the target),
- **borrowed chords / modal mixture** (diatonic in the parallel mode),
  incl. bVII mixolydian and Neapolitan bII special cases,
- **cadences** at song end: authentic, plagal, deceptive, backdoor, half,
- **bass-line devices**: pedal points (3+ segments), stepwise runs with
  direction + affect,
- **rhythmic-rhetorical devices**: pickup chord (anacrusis), immediate
  retake (ostinato reinforcement),
- **quality color** lines ("maj7 color — warm, dreamy, jazz-inflected").

These feed the plain-language `effect` field shown in the player and reports.

## 18. Rhythm engine ✅

Beat grid + meter (2–7) estimated by phase-scoring beat strengths; downbeats
must beat the average by ≥ 10 % with ≥ 3 samples, near-ties resolve to the
simplest meter, else no grid is reported. Chord boundaries within 0.16 beats
snap to the grid; every chord gets `bar`, `beat_in_bar`, `beats` (grid count),
`beat_fraction` (exact length in beats), and `pushed` (off-grid anticipatory
entry).

## 19. Confidence model ✅ + Harmonic DNA (step 18) ✅

The trust layer is two engines run as the pipeline's final `trust` stage;
both read only already-computed evidence, so a failure there can never sink
the analysis.

**Confidence (`confidence.py`, step 19).** Per-dimension scores, duration-
weighted over the whole song:

- **chord** = duration-weighted mean of the per-segment softmax posterior
  over the 180 cosine emissions (temperature 0.045, bounded below 1 by design);
- **bass** = share of the song whose bass pitch class was readable at all
  (re-measured with the same weighted low-register chroma the bass stage used);
- **inversion** = unambiguity of each bass claim: confirmed root position → 1,
  claimed inversion → observed dominance / 3 (the claim gate is 1.8×),
  unresolved bass → neutral 0.5 (uncertain, not wrong);
- **voicing** = duration-weighted voicing confidence (0.7 default when no
  extensions);
- **function** = ½ key correlation + ½ diatonic share of the progression;
- **rhythm** = beat-grid coherence (0.0 when no grid was found);
- **overall** = fixed-weight blend (chord .35, function .20, bass .15,
  voicing/inversion/rhythm .10 each).

⚠️ **Not calibrated across material.** On dense mixes the softmax flattens
and absolute values read low (0.03–0.28 observed on a dense gospel
production) while remaining rank-correct within the song. Do not compare
confidence values *across* songs. Calibration (e.g. isotonic on labeled data)
requires the evaluation dataset of §24 — 🧪.

**Harmonic DNA (`dna.py`, step 18).** The song's identity at progression
level, recomputed from plain roman numerals (immune to `V7/x` relabeling):

- **signature** — the most characteristic loop, named when it matches one of
  15 catalogued progressions (axis + rotations, doo-wop, jazz ii–V–I, classic
  rock, mixolydian, aeolian epic, Andalusian, harmonic-minor cadence,
  Pachelbel ground, circle-of-fifths descent, extended jazz loop, backdoor
  ascent); else the most frequent recurring 2–3-gram ("song-specific"), else
  the opening progression;
- **devices** — per-song tallies of secondary dominants, tritone subs,
  borrowed chords, pedal points, stepwise bass, cadences, Neapolitans,
  suspensions, inversions, pushed entries, extended voicings;
- **matches** — every named pattern found, with occurrence counts, the time
  span of its first appearance, and a one-line musical annotation.

Surfaced in JSON (`confidence`, `dna` blocks), Markdown, the terminal report,
and a dedicated player card.

---

# D. Data

## 20. Canonical JSON schema ✅

Single canonical payload emitted by `report.json_report`; the HTML player,
Markdown report, and web summary all derive from the same
`AnalysisResult`. Reference (field-by-field, with types and invariants):
[JSON_SCHEMA.md](JSON_SCHEMA.md). Top level: `title, source, duration, key,
tempo, rhythm, chords[], notes`. Per chord: `start, end, chord, root, quality,
inversion, inversion_name, bass, roman, role, confidence`, optional
`voicing{pitch_classes, extensions, spacing, added_notes, confidence}`,
optional `rhythm{bar, beat_in_bar, beats, beat_fraction, pushed}`, optional
`effect`.

## 21. Database schema 🔴 (v2 design)

Current persistence is the filesystem (temp work dirs) — see §8. Planned
relational shape (sketch, not yet implemented):

```sql
songs     (id PK, source_kind, source_url, title, duration_s, fingerprint,
           created_at)            -- fingerprint = audio hash for dedup
analyses  (id PK, song_id FK, engine_version, params_json, result_json,
           key_name, tempo_bpm, n_chords, created_at)
jobs      (id PK, song_id FK NULL, kind, stage, error, started_at,
           finished_at)           -- audit trail; replaces in-memory JOBS
```

Index `songs.fingerprint` unique; `analyses` versioned by engine so a v1.1
re-analysis coexists with v1.0 results.

## 22. Analysis / event model ✅

The single source of truth is the `AnalysisResult` dataclass tree in
`models.py` (`Chord`, `VoicingInfo`, `KeyEstimate`, `RhythmInfo`) —
[ADR-004](ADR/ADR-004-canonical-harmonic-event.md). Every report format and
both frontends serialize from these objects; nothing re-derives data from
text. A "harmonic event" today is a chord segment (start/end/label +
annotations); finer-grained events (notes, onsets) are intentionally not part
of the model.

---

# E. Quality & Operations

## 23. Error handling ✅ / 🟡

- CLI: exceptions are caught and printed to stderr with exit code 1.
- Server: worker exceptions → job `error` stage + truncated message; invalid
  input → 422 with a human explanation; oversized upload → 413; unknown job →
  404; player-not-ready → 409; cleaned-up audio → 410.
- Rhythm stage is fault-isolated: any exception → no grid, analysis continues.
- 🟡 Gaps: no structured logging, no retry/backoff on yt-dlp, no
  Sentry/equivalent telemetry.

## 24. Evaluation dataset 🧪

Today: two reference analyses under `eval/` (Radiohead — *Creep*; a dense
gospel production) with before/after JSONs and findings in
[eval/EVALUATION.md](../eval/EVALUATION.md). That was enough to drive three
real defect fixes (bass register weights, inversion dominance gate, spill
modeling) — it is **not** enough to claim accuracy. Target (see
[EVALUATION.md](EVALUATION.md)): a 50–100-song labeled set spanning genres,
with chord + bass annotations, scored for root/quality/inversion accuracy and
confidence calibration.

## 25. Testing strategy ✅

31 tests across six suites (`tests/`): chord decoding (synthetic chroma),
bass/inversion gates, function/roman logic, rhythm (synthetic click track +
meter), server (upload → poll → player via TestClient), end-to-end (synthesized
multi-chord audio through the whole pipeline). What each suite guarantees:
[TESTING.md](TESTING.md). Gaps: 🟡 no golden-file test on a real-mix fixture,
🔴 no CI workflow yet (tests run locally), 🔴 no performance regression test.

## 26. Security 🔴 (hardening) / 🟡 (baseline)

Current posture is **single-user, localhost by default** (`127.0.0.1:8600`):
- ✅ Upload type allow-list + 200 MB cap (streamed, 1 MiB chunks)
- ✅ URL scheme/host validation (YouTube/Spotify patterns only)
- ✅ No HTML injection surface: analysis data is JSON-dumped / escaped, not
  interpolated raw into the page
- 🔴 No auth, no rate limiting, no CSRF posture — required before any network
  exposure; do not deploy as-is on a LAN/WAN.
- 🔴 No sandboxing of yt-dlp subprocess (runs with user privileges).

## 27. Licensing 🟡

The code is the user's; third-party runtime deps are MIT/BSD/Apache-2.0
(librosa, numpy, scipy, FastAPI, …) with yt-dlp as an external tool
(Unlicense). Analysis of copyrighted recordings is legal in most
jurisdictions for **private study**; any commercial/exposed deployment must
ship with a takedown policy and must not redistribute audio. Full position:
[LICENSING.md](LICENSING.md). ⚠️ Copyrighted song audio in `eval/` is
git-ignored and must stay out of any distribution.

---

# F. Business

## 28. Cost model 💡 (estimates, not measurements)

- **Local use:** cost ≈ 0 (user's CPU; ~30–60 s per song, single core-ish).
- **Hosted per analysis (est.):** CPU-bound analysis ~0.5–1 core-minute;
  yt-dlp egress (audio download ~3–10 MB); storage ~75 MB wav (or ~9 MB m4a)
  per retained player + 0.4 MB HTML. At typical cloud CPU pricing this is
  cents per analysis; the dominant real cost is **storage retention** of audio
  for player playback — mitigate with short audio TTL and on-demand re-fetch.
- **Scale risk:** yt-dlp against YouTube ToS at commercial scale; a licensed
  catalog source is the sanctioned path (ties into §27).

## 29. MVP roadmap ✅ / 🟡

Shipped MVP (v1.0): URL/file → full harmonic + rhythmic analysis; CLI + web;
player with sync, themes, PDF export; JSON/MD/HTML reports; streamed web
player. See [ROADMAP.md](ROADMAP.md) for the sequenced next steps:
library page → persistent storage → modulation-aware key → evaluation dataset
→ calibration → hosted multi-user build.

## 30. Commercial roadmap 💡

Phase 1 (now): personal/local tool, open development on GitHub.
Phase 2: polished self-hostable product (Docker, library, sharing links).
Phase 3: hosted service with accounts (auth, billing, quotas) for musicians
and education. Phase 4: B2B API for catalogs (music supervision, education
platforms) — contingent on the licensing posture of §27 and the evaluation
evidence of §24. Details: [ROADMAP.md](ROADMAP.md).
