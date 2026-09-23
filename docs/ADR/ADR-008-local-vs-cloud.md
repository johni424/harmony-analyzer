# ADR-008: LOCAL-first deployment; CLOUD deferred until product demand

**Status:** Accepted · **Date:** 2026-09-22
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §28 ·
Measurements: [BUSINESS.md](../BUSINESS.md) · Instrument: `harmony/benchmark.py`

## Context

The plan's step 28 requires choosing between two architectures — LOCAL
(desktop/CLI) and CLOUD (API → worker → analysis) — based on **measured**
per-analysis costs, not preference. Phase 7 produced those measurements
(2026-09-22, macOS/x86_64/4-core; see BUSINESS.md for the full table):

- CPU 62 s, wall 70 s per 6.5-min real song (0.18× realtime)
- peak RSS **1.47 GB** on real mixes (230 MB on synthetic one-minute clips —
  memory scales with clip length, so capacity must plan for ~1.5 GB)
- artifacts: 75 MB WAV, 0.4 MB streamed player, 0.2 MB analysis.json
- ingest: 7 s (yt-dlp)
- computed cost: **$0 local**, **~$0.0025 serverless**, **≤$0.0045 on a $4.5
  VPS that sustains ~42k analyses/month**; retention $0.0017/analysis/month
  and egress $0.0066 per full playback — i.e. storage/streaming dominates
  compute for any hosted variant

## Decision

**LOCAL is the architecture. CLOUD remains designed-for but unimplemented**
until a concrete product requirement exists (hosted multi-user, a public
API with third-party consumers, or a results library across devices).

Concretely:

1. CLI + local web app stay the product surface (current state, ADR-007
   in-memory store unchanged).
2. The cloud path stays cheap to build *because of* earlier decisions:
   streamed players (ADR-006) already avoid embedding audio; the v1 API
   contract (step 21) is worker-agnostic; the §21 SQLite sketch is the
   only missing piece.
3. When CLOUD is triggered: 2 GB+ worker slices, audio TTL ≤ 7 days,
   SQLite-backed job store, no yt-dlp at commercial scale (§27 licensing
   path instead).

## Consequences

- Positive: $0 marginal cost at current scale; no audio-custody or
  yt-dlp-ToS exposure; every engineering hour goes into analysis quality,
  not ops.
- Positive: the decision is **measured and reversible** — the benchmark
  harness re-proves the numbers on demand (`harmony-bench`), so a future
  cost change (cheaper memory-billing, bigger real-song memory growth)
  is detectable, not anecdotal.
- Negative: no multi-device results library and no third-party API
  consumers until the store exists (accepted; consistent with ADR-007).
- Negative: users on machines with < ~2 GB free RAM will hit swap on long
  songs — a CLI note (streaming CQT / block-wise analysis) is the future
  engine fix if it matters in practice.

## Revisit triggers

- A results library or hosted players become a requested feature (→ §21
  store, then cloud worker).
- Peak RSS on typical songs approaches the 2 GB worker-slice assumption
  (re-run `harmony-bench --wav …`; if real mixes exceed ~1.8 GB, revisit
  memory-billing tier choice).
- Any plan to exceed ~1,000 analyses/month hosted (→ re-run the VPS
  throughput math; still likely one box).
