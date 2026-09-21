# ADR-002: Bass analysis as a separate stage

**Status:** Accepted · **Date:** 2026-09
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §12–13.

## Context

The bass line determines inversions, but the bass also carries the chord
root — naive joint handling re-roots every chord to its bass note, and
inversions become undetectable. Chord detection and bass detection have
conflicting requirements on the same chroma data.

## Decision

Two **separate representations** and a **separate stage**:

1. the chord decoder sees a *recognition chroma* (bass octave down-weighted
   to 0.35, not zeroed);
2. a dedicated `bass.py` stage rebuilds its own low-register-weighted chroma
   (weights `[0.2, 1.0, 1.0, 0.4, 0.1, 0, 0]`, C1..B7) from the normalized
   CQT, estimates the bass pitch class per frame, then labels inversions per
   segment under dominance gates.

## Rationale

- Measured failure of the joint approach: judging "bass" from the guitar
  register produced **21/21 false inversions** on the first real mix.
- The separation lets each stage have its own honesty rules: the decoder
  needs the bass for roots; the inversion engine needs proof the bass is
  *dominant* in the low register before claiming a slash chord.

## Consequences

- Two chroma variants to maintain (documented in
  [AUDIO_PIPELINE.md](../AUDIO_PIPELINE.md)).
- In dense mixes with ambiguous low registers, inversions default to root
  position — the conservative, honest outcome (spec §13 ⚠️).
