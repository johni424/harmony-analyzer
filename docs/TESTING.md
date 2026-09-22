# Testing Strategy

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §25.

Run everything:

```bash
cd song-harmony-analyzer && .venv/bin/python -m pytest tests/ -q
```

Current state: **71 tests, all passing** (~25 s; librosa emits harmless
`n_fft` warnings on synthetic short fixtures).

## Suites and what each guarantees

| Suite | Count | Guarantees |
|---|---|---|
| `test_chords.py` | — | Viterbi decodes known chroma patterns to the right root/quality; sliver merging; template symmetry (no phantom states win) |
| `test_bass.py` | — | inversion labeling: root-in-bass stays root; 3rd-in-bass → 1st inversion; dominance gate suppresses ambiguous bass; non-chord-tone bass → root position |
| `test_function.py` | — | roman numerals incl. chromatic spelling priorities (bVII, #IV, bVI); secondary dominant `V7/x` detection; borrowed-chord effects; cadence labels |
| `test_rhythm.py` | — | meter estimation on synthetic click tracks (4/4 recovered); downbeat phase; chord↔beat alignment (`bar`, `beat_in_bar`, `beats`, `pushed`); honest `None` for pulseless input |
| `test_server.py` | 7 | landing page 200; URL job creation + validation; upload job (multipart) incl. oversize/type rejection; poll lifecycle; player + audio routes; full upload→poll→player flow via TestClient |
| `test_end_to_end.py` | — | synthesized multi-chord audio (numpy-generated waveform of known chords) through the whole pipeline recovers progression + key |
| `test_trust.py` | 11 | confidence engine calibration (bass dominance → inversion score, unresolved bass neutral 0.5, bounded dimensions, weighted overall); DNA engine (axis recognition + repeat counts, 7th-quality tolerance, n-gram fallback, device tallies, empty input); end-to-end trust through the pipeline and all four report surfaces (JSON/MD/terminal/player card) |
| `test_schema.py` | 13 | step-20 contract: frozen schema is metaschema-valid at v1.0.0; synthetic-doc rejections (unknown keys, missing required fields, out-of-range confidence, unknown quality, inversion-name/bass mismatches); pipeline output validates on synthesized audio; `/api/v1/schema` serves the frozen file; analysis endpoint 404/409 + full upload→poll→contract-valid-document flow |
| `test_evaluation.py` | 16 | step-25 harness: reference parsing (slash/flat/7th symbols, quality families), renderer honors declared bass (FFT check), metrics math (perfect match = 1.0, extension tolerance, bass scored only where referenced, tempo octave-folding, Brier), manifest integrity (tiling, chord-tone bass, provenance on real entries), performance budget (analysis < 3× realtime, `slow`-marked) |

## Conventions

- Tests are hermetic: synthetic signals only, **no network, no real songs** —
  the suite runs offline in CI-able time.
- `tests/conftest.py` puts `src/` on `sys.path` (no editable install needed).
- Ground truth = what we synthesize. Real-mix ground truth lives in evals
  (see [EVALUATION.md](EVALUATION.md)), not in the unit suite.

## Known gaps

- 🟡 no golden-file regression on a fixed real-mix fixture (blocked by
  licensing — a licensed/licensable fixture would unblock it; the synthetic
  dataset provides the hermetic equivalent today)
- 🔴 no CI workflow (tests run locally today; GitHub Actions is a one-file add)
- 🟡 server tests don't cover the yt-dlp path (network) — by design; it is
  exercised in manual/eval runs

Closed 2026-09 (step 25): performance regression budget
(`test_performance_budget_sec_per_audio_minute`, < 3× realtime).
