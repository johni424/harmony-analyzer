# ADR-005: No source separation, no harmonic-residual subtraction

**Status:** Accepted · **Date:** 2026-09
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §9.

## Context

Chord detectors often "clean" the mix before analysis: source separation
(e.g. demucs) to isolate harmonic content, or harmonic-residual subtraction
to remove fundamentals' upper partials from the chroma. Both promise purer
chord evidence.

## Decision

**Do neither.** The pipeline uses only HPSS (harmonic/percussive split, keep
harmonic + 0.25× percussive) and models instrument physics *in the templates*
(harmonic spill +7 st ×0.30, +4 st ×0.12) instead of subtracting it from the
signal.

## Rationale

- **Residual subtraction destroys real notes.** In polyphonic music a
  "3rd-harmonic bin" of the root (+19 st = folded +7) is also where a
  genuinely played note sits; subtracting the fundamental's predicted
  partials erases chord tones — measured: a loud G2 bass erased a played D4
  (G + 19 st = D). Modeling spill additively in the template keeps the
  evidence and teaches the decoder to expect it.
- **Source separation cost/benefit:** a separation model is heavy (model
  download, ~minutes of compute vs. our ~30–60 s total), adds a dependency,
  and introduces separation artifacts that are *worse* for chroma than the
  original mix. Revisit only if a calibrated evaluation shows dense-mix
  accuracy below target ([EVALUATION.md](../EVALUATION.md)).

## Consequences

- Dense mixes keep all their intermodulation; the honesty gates (bass
  dominance, extension support) exist precisely because evidence stays messy.
- Sub-bin sharpening ([-0.5, 1, -0.5] kernel) remains the only "destructive"
  DSP step, and it only cancels the CQT's own point-spread skirt.
