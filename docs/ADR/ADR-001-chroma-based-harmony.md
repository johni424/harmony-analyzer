# ADR-001: Chroma-based harmony (no neural chord model)

**Status:** Accepted · **Date:** 2026-09 (project start)
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §11.

## Context

Chord recognition from audio has two mainstream families: chroma/template
methods (DSP, interpretable, tunable, no training data) and neural models
(trained on labeled corpora, strong out-of-the-box accuracy, opaque).

## Decision

Build harmony detection on a **CQT-derived chroma front end with weighted
templates decoded by Viterbi**. No neural network in the pipeline.

## Rationale

1. **Explainability is a product feature.** Every wrong chord can be traced
   to a mechanism (spill, leak, transition cost) and fixed in the template —
   exactly what happened during the *Creep* evaluation, where three defects
   were diagnosed and repaired by reasoning about the pipeline, not by
   retraining anything.
2. **The hard part here isn't triad ID — it's inversions and voicing.**
   Those need bass-register and per-pitch-class evidence that we compute
   explicitly; a black-box chord labeler would not give us that decomposition.
3. **No dataset dependency** at a stage where the evaluation set doesn't
   exist yet ([EVALUATION.md](../EVALUATION.md)).
4. Real-time cost is trivial; features dominate compute.

## Consequences

- Accuracy ceiling on dense mixes is lower than a strong neural model's
  (mitigation: spill/leak modeling, priors, gates; revisit with evidence).
- Future neural components (e.g. note-level multi-pitch estimation for
  voicing) can slot into the *same* Features interface without re-architecting.

## When to revisit

If a calibrated evaluation set shows template decoding materially below
state of the art on the target repertoire (spec §24), consider a neural
chord model as an *alternative decoder behind the same Features interface*.
