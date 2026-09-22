# Architecture

**Status:** v1.1 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §4–8.

## Canonical pipeline (the 14-stage view)

This is the reference picture of the app. Every stage below maps to a real
module — see the table underneath for the exact binding.

```
                    ┌──────────────────────┐
                    │      USER INPUT      │
                    │ MP3 / WAV / YouTube  │
                    │ Spotify / FLAC       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   1. INGESTION       │
                    │ Audio + metadata     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ 2. AUDIO PREPROCESS  │
                    │ resample / normalize │
                    │ HPSS / channels      │
                    └──────────┬───────────┘
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
        ┌─────────┐      ┌──────────┐      ┌──────────┐
        │ 3 BEAT  │      │ 4 CHROMA │      │ 5 BASS   │
        │ / TEMPO │      │ / PITCH  │      │ TRACK    │
        └────┬────┘      └────┬─────┘      └────┬─────┘
             │                │                 │
             └────────────────┼─────────────────┘
                              ▼
                    ┌──────────────────────┐
                    │ 6 CHORD DETECTION    │
                    │ candidate chords     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ 7 HARMONIC EVENTS    │
                    │ segmentation         │
                    └──────────┬───────────┘
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
             ┌────────┐  ┌──────────┐  ┌──────────┐
             │ 8 BASS │  │ 9 VOICING│  │10 RHYTHM │
             │/INVERS │  │          │  │          │
             └────┬───┘  └────┬─────┘  └────┬─────┘
                  └────────────┼─────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 11 KEY DETECTION      │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 12 ROMAN NUMERALS    │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 13 FUNCTION ENGINE    │
                    │ secondary dominants  │
                    │ borrowed chords      │
                    │ cadences / modulation│
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 14 CONFIDENCE ENGINE │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ CANONICAL ANALYSIS   │
                    │ JSON                 │
                    └──────────┬───────────┘
                               │
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
             Terminal        API           Frontend
                              │
                              ▼
                         Web Application
```

### Stage → code binding

| # | Diagram stage | Implementation | Notes |
|---|---|---|---|
| 1 | Ingestion | `ingest.resolve` | yt-dlp → WAV; Spotify resolved via oEmbed → YouTube search |
| 2 | Audio preprocess | `chroma.load_audio` + `chroma.extract_features` | 22.05 kHz mono, HPSS percussive/harmonic split, CQT |
| 3 | Beat / tempo | `rhythm.analyze_rhythm` | data-parallel with 4/5; *executes* in the late `rhythm` stage — see execution order below |
| 4 | Chroma / pitch | `chroma.extract_features` | recognition + bass chroma variants from one CQT |
| 5 | Bass track | `chroma` (bass variant) extracted here, labeled at stage 8 | low-register weighting |
| 6 | Chord detection | `chords.viterbi_chords` | 180 weighted templates, HMM/Viterbi ([ADR-003](ADR/ADR-003-viterbi-chord-decoder.md)) |
| 7 | Harmonic events | segment merge + `pipeline._snap_boundaries` | < 0.6 s segments absorbed; boundaries snapped to chroma flux (±0.3 s) |
| 8 | Bass / inversion | `bass.label_inversions` | honesty gates before claiming any inversion |
| 9 | Voicing | `voicing.analyze_voicing` | sounding pitch classes, extensions, register/spacing |
| 10 | Rhythm | `rhythm.align_chords_to_beats` | bar / beat_in_bar / beats / pushed |
| 11 | Key detection | `function.detect_key` | Krumhansl–Kessler profiles, one global key |
| 12 | Roman numerals | `function.roman_numeral` | applied inside `annotate_functions` |
| 13 | Function engine | `function.annotate_functions` | cadences, secondary dominants, tritone subs, borrowed chords, bass-line/pickup/retake devices |
| 14 | Confidence engine | `confidence.compute_confidence` | per-dimension trust scores (chord/bass/inversion/voicing/function/rhythm); failure-safe in the pipeline |
| 15 | Harmonic DNA | `dna.analyze` | signature progression + named-pattern matches + device tallies (plan step 18) |
| — | Canonical JSON | `models.AnalysisResult` → `report.json_report` | single serialization, all renderers consume it |
| — | Terminal | `cli.py` → `report.terminal_report` | one-shot process |
| — | API | `server.py` | job store **in memory** ([ADR-007](ADR/ADR-007-in-memory-state.md)) |
| — | Frontend | Timeline Player (`report.py` HTML) served at `/player/{id}` | streams audio from `/audio/{id}` |

### Execution order vs. the diagram

The diagram is the **data-flow** view: stages 3/4/5 genuinely are independent
branches, and 8/9/10 could run in any order. The code executes sequentially
(`pipeline.analyze`), which is a deliberate simplicity choice for a
single-threaded-per-job design:

```
ingest → features(2+4+5) → decode(6+7) → harmony(8+9+11+12+13) → rhythm(3+10) → result
```

Beat/tempo (3) runs **last** and is optional: chord decoding is tempo-adaptive,
so it never needs the grid, and non-percussive material simply gets no rhythm
fields (honest absence, documented in the spec).

## Module map

| Module | Lines | Responsibility |
|---|---|---|
| `models.py` | 189 | Canonical dataclasses: `Chord`, `VoicingInfo`, `KeyEstimate`, `RhythmInfo`, `AnalysisResult`; pitch spelling tables |
| `ingest.py` | 130 | Source classification, yt-dlp download→wav, Spotify oEmbed→YouTube search, title resolution |
| `chroma.py` | 112 | Audio load (22.05 kHz mono), HPSS, CQT, sharpening, chroma variants, normalized CQT |
| `chords.py` | 212 | 180-state weighted templates, emission matrix, Viterbi decode, segment merge, softmax confidence |
| `bass.py` | 143 | Low-register bass estimation, per-segment inversion labeling with honesty gates |
| `voicing.py` | 144 | Sounding pitch classes, extension detection, added notes, register/spacing |
| `function.py` | 269 | Key detection (KK profiles), roman numerals, roles, cadences, secondary dominants, tritone subs, borrowed chords, bass-line/pickup/retake devices |
| `rhythm.py` | 173 | Onset envelope → beat grid → meter/downbeats → chord↔beat alignment |
| `confidence.py` | 147 | Per-dimension trust scores from existing stage evidence (plan step 19) |
| `dna.py` | 214 | Named-progression matching, device tallies, song signature (plan step 18) |
| `pipeline.py` | 175 | Stage orchestration (`on_stage` progress hook), boundary snapping, trust stage |
| `report.py` | 874 | Terminal/JSON/Markdown renderers + the full Timeline Player HTML template |
| `server.py` | 546 | FastAPI web app: landing page, job store, player/audio routes |
| `cli.py` | 57 | Typer CLI (`harmony`) |

## Data flow (one analysis)

```
analyze(source)
 ├─ ingest.resolve            → (audio_path, title, source_kind)
 ├─ chroma.load_audio         → y, sr                     [~23 ms frames]
 ├─ chroma.extract_features   → Features(chroma, recognition_chroma,
 │                              bass_chroma, cqt_norm, times)
 ├─ chords.viterbi_chords     → [RawSegment] (frame indices)
 │    └─ _merge_short_segments (< 0.6 s absorbed)
 ├─ Chord(...) + pipeline._snap_boundaries (chroma flux, ±0.3 s)
 ├─ bass.label_inversions     → fills bass_pc, inversion (in place)
 ├─ voicing.analyze_voicing   → fills .voicing per chord
 ├─ function.detect_key       → KeyEstimate
 ├─ function.annotate_functions → fills .function/.role/.effect
 ├─ rhythm.analyze_rhythm     → RhythmInfo | None (None ⇒ no grid, honestly)
 │    └─ rhythm.align_chords_to_beats → fills bar/beat_in_bar/beats/pushed
 └─ AnalysisResult → report.{terminal,json,markdown,html}_report
```

In-place mutation convention: annotation stages mutate `Chord` objects rather
than copying — a deliberate simplicity choice; the pipeline is single-threaded
per job.

## Deployment topology

- **Local single process**: `harmony-web` runs uvicorn in-process; analysis
  threads are daemons of that process. Audio never leaves the machine.
- **CLI**: one-shot process per analysis.
- No external services except: YouTube (via yt-dlp) and Spotify oEmbed during
  ingest, when the source is a URL.

## In-memory state (by design)

All application state lives in process memory. Nothing is persisted between
restarts, and that is a documented decision — [ADR-007](ADR/ADR-007-in-memory-state.md):

- **Job store**: `JOBS: dict[str, Job]` in `server.py`, guarded by
  `JOBS_LOCK`, capped at `MAX_JOBS = 40`; finished jobs are pruned
  oldest-first to make room.
- **Analysis workers**: daemon threads of the uvicorn process — one job, one
  thread, no worker pool, no queue outside memory.
- **Artifacts**: per-job audio + player data live in a per-job directory under
  the OS temp dir (never the repo, never durable). The only durable output is
  what the user explicitly exports (JSON/PDF/standalone HTML).
- **No database, no sessions, no external cache.** A server restart clears all
  jobs — acceptable for v1 because results are re-derivable from the source in
  ~1 minute, and it keeps the deployment a single `harmony-web` command with
  zero state to manage.

## Key invariants (enforced by tests)

1. Chord segments are non-overlapping and cover the analyzed span; boundaries
   are identical between neighbors.
2. `inversion > 0` ⇒ `bass_pc` is a chord tone of (`root_pc`, `quality`) and
   ≠ `root_pc`.
3. `rhythm` fields are either all set (grid exists) or all `None`.
4. Every report format serializes the same `AnalysisResult` — no format has
   private data.
5. Job stage transitions: `queued → ingest → features → decode → harmony →
   rhythm → render → done` or `… → error`.

## Failure isolation

- Rhythm exceptions are caught in `pipeline.analyze` → analysis continues
  without a grid.
- yt-dlp failures raise `RuntimeError` → CLI exit 1 / job `error` stage.
- A single bad chord segment cannot crash annotation stages (all operate on
  complete segments; degenerate segments are ≥ 0.1 s by construction).
