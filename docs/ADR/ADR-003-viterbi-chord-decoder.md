# ADR-003: Viterbi decoder over 180 template states

**Status:** Accepted · **Date:** 2026-09
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §11.

## Context

Per-frame template argmax yields flickering, contradictory labels; sequence
decoders fix that with varying complexity (HMM/Viterbi, CRF, neural
sequence models).

## Decision

First-order **HMM decoded with Viterbi**: sticky self-loop transitions
(tempo-adaptive, 0.90→0.965), per-quality rarity log-priors, cosine emission
evidence scaled ×2.0, followed by sub-0.6 s sliver merging and chroma-flux
boundary snapping.

## Rationale

- **Tempo-adaptive smoothing without a tempo estimate:** expected chord
  length defaults to 2 quarter notes at 120 BPM; when rhythm analysis runs
  first, the same formula consumes the real tempo.
- **Rarity priors encode repertoire facts** (sus chords in pop are usually
  sung melody tones; aug/dim are rare) that a uniform decoder gets wrong.
- **Evidence scale ×2.0 is load-bearing:** cosine log-emission differences
  (~0.1 nats) otherwise can never outvote the ~16-nat transition cost —
  measured failure: C–Am–F–G decoded without the Am.
- Simple, inspectable, fast; all knobs explain a behavior.

## Consequences

- First-order memory: no explicit chord-transition language model (ii→V
  vs. ii→iv not distinguished). So far priors + gates cover the gap.
- Boundary precision limited by 23 ms frames + flux snapping (±0.3 s window)
  — good enough for beat-grid alignment, not for notation-grade transcription
  (a declared non-goal).
