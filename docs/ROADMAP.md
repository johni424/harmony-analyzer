# Roadmap

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §29–30.

Sequenced by: value to the musician ÷ effort, with the evaluation dataset
pulled early because it unblocks everything that needs evidence.

## Shipped (v1.0 baseline) ✅

- URL (YouTube/Spotify) + file ingest; fully local analysis
- Chords (15 qualities), inversions with honesty gates, voicings + extensions
- Key, roman numerals, functional devices, plain-language effects
- Beat grid, meter, bar/beat placement of every chord
- CLI (JSON/MD/HTML) + web app (landing → progress → player)
- Timeline Player: waveform sync, click-to-seek, function-colored grid, bar
  lines, beat pulse, transport, themes, PDF export, streamed web audio
- CI on every push; evaluation harness + datasets; measured cost model and
  the LOCAL-first architecture decision ([ADR-008](ADR/ADR-008-local-vs-cloud.md))

## Next (v1.1 — product completion)

1. **Jobs library page** — list analyzed songs (title/key/tempo) on the
   landing page, reopen players; needs a persistent store (v1.1 or jump to
   §21 schema).
2. **Docker packaging** — one-command deploy beyond localhost.
3. **CI** — GitHub Actions running the 31-test suite on push/PR.
4. **Standalone-player export button** — download the audio-embedded HTML
   from the web results page.
5. Evaluation dataset v0 (20 songs hand-checked) → first calibrated accuracy
   statement in the README.

## Then (v1.2 — intelligence upgrades)

6. **Modulation-aware key** — section-local key estimates (sliding KK +
   change-point detection); roman numerals re-anchored per section.
7. **Confidence calibration** — isotonic/Platt on the evaluation set; per-
   material-class temperature; comparable numbers across songs.
8. **Harmonic event model v2** — finer events (bass notes, melody line) as
   first-class citizens; piano-roll view of actual detected pitches.
9. **Meter improvements** — 6/8 vs 3/4 disambiguation via beat-subdivision
   accent shape; tempo octave (×2/×½) resolution using chord-change density.

## Later (v2.0 — production)

10. Persistent multi-user storage (Postgres), auth, rate limits. Gated on
    product demand per [ADR-008](ADR/ADR-008-local-vs-cloud.md): measured
    costs say LOCAL first (≤$0.0045/analysis even hosted; a $4.5 VPS covers
    ~42k analyses/month).
11. Hosted service: accounts, billing, sharing links.
12. B2B API (catalog analysis) — gated on licensing posture
    ([LICENSING.md](LICENSING.md) §5–6) and on evidence from the evaluation
    set.

## Explicit non-goals (stable)

See [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) — non-goals
section. Notably: instrument identification, note-exact transcription,
real-time streaming analysis.
