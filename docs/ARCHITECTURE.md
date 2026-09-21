# Architecture

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §4–8.

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
| `pipeline.py` | 155 | Stage orchestration (`on_stage` progress hook), boundary snapping |
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
