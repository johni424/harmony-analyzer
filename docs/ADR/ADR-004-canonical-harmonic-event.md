# ADR-004: One canonical analysis model, one "harmonic event"

**Status:** Accepted · **Date:** 2026-09
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §20–22.

## Context

Multiple output surfaces (terminal, JSON, Markdown, HTML player, web
summary) risk drifting apart if each formats its own idea of a chord. A
"chord" also needs a precise definition before the model can grow.

## Decision

1. `models.py` dataclasses (`AnalysisResult`, `Chord`, `VoicingInfo`,
   `KeyEstimate`, `RhythmInfo`) are the **single source of truth**. Every
   report and frontend serializes from these objects; nothing re-parses text
   or re-derives data.
2. A **harmonic event** (v1) = one maximal time interval with a constant
   (root, quality, bass, voicing) interpretation, plus annotations (roman,
   role, effect, rhythm placement, confidence). Segments tile the analyzed
   span; neighbor boundaries are identical.

## Rationale

- One mutation pipeline (annotation stages fill fields in place) → all
  surfaces are consistent by construction; tested as an invariant.
- JSON schema (see [../JSON_SCHEMA.md](../JSON_SCHEMA.md)) is the stable
  contract for external consumers; Python dataclasses are the internal
  contract. Both change together, in one commit.

## Consequences

- Chord is the only event granularity: no note events, no onsets in the
  model. A v2 event model (bass notes, melody, piano-roll pitch data) is a
  **backward-compatible extension** — add fields, don't redefine the chord.
- Renaming a JSON field is a breaking change → requires a spec version bump
  (see version table in the master spec).
