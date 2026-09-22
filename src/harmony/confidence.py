"""Confidence engine (step 19): per-dimension trust metrics for an analysis.

The engine does not re-run detection; it reads the evidence each stage already
produced and condenses it into 0..1 scores:

- chord      — duration-weighted Viterbi posterior (how strongly the chroma
               supported the chosen chord labels)
- bass       — share of the song whose bass pitch class was readable at all
- inversion  — how unambiguous each claimed bass/inversion is (confirmed root
               position scores full; unresolved bass scores a neutral 0.5)
- voicing    — stability of the detected pitch sets inside segments
- function   — key-profile fit plus the share of chords that are diatonic
- rhythm     — beat-grid coherence (0.0 when no grid was found)
- overall    — weighted combination (dimensions a musician feels most weigh most)

These are trust indicators, not probabilities of correctness — see
docs/HARMONIC_MODEL.md §confidence for the honest interpretation.
"""
from __future__ import annotations

import numpy as np

from .bass import _weighted_bass_chroma  # the exact evidence the bass stage used
from .chroma import Features
from .function import _is_diatonic
from .models import Chord, ConfidenceScores, KeyEstimate, RhythmInfo

# Overall is a weighted mean: label trust and key/function trust dominate the
# listening experience; bass/inversion and voicing refine it; the beat grid
# only matters when it exists.
_WEIGHTS = {
    "chord": 0.35,
    "bass": 0.15,
    "inversion": 0.10,
    "voicing": 0.10,
    "function": 0.20,
    "rhythm": 0.10,
}

_NEUTRAL = 0.5  # score for "no evidence either way" (never punished, never trusted)


def compute_confidence(
    chords: list[Chord],
    features: Features,
    times: np.ndarray,
    key: KeyEstimate,
    rhythm: RhythmInfo | None,
) -> ConfidenceScores:
    """Condense the per-stage evidence into per-dimension trust scores."""
    if not chords:
        return ConfidenceScores()

    chord_score = _chord_dimension(chords)
    bass_score, inversion_score = _bass_dimensions(chords, features, times)
    voicing_score = _voicing_dimension(chords)
    function_score = _function_dimension(chords, key)
    rhythm_score = float(rhythm.confidence) if rhythm is not None else 0.0

    overall = (
        _WEIGHTS["chord"] * chord_score
        + _WEIGHTS["bass"] * bass_score
        + _WEIGHTS["inversion"] * inversion_score
        + _WEIGHTS["voicing"] * voicing_score
        + _WEIGHTS["function"] * function_score
        + _WEIGHTS["rhythm"] * rhythm_score
    )
    return ConfidenceScores(
        chord=round(chord_score, 3),
        bass=round(bass_score, 3),
        inversion=round(inversion_score, 3),
        voicing=round(voicing_score, 3),
        function=round(function_score, 3),
        rhythm=round(rhythm_score, 3),
        overall=round(overall, 3),
    )


def _chord_dimension(chords: list[Chord]) -> float:
    """Duration-weighted mean of the Viterbi posterior confidence."""
    num = den = 0.0
    for c in chords:
        if c.quality == "N":
            continue
        w = max(c.duration, 1e-6)
        num += w * float(c.confidence)
        den += w
    return num / den if den else 0.0


def _bass_dimensions(chords: list[Chord], features: Features, times: np.ndarray) -> tuple[float, float]:
    """(bass readability, inversion unambiguity), both duration-weighted.

    Re-measures the bass-energy dominance with the same weighted low-register
    chroma the bass stage used, so the score reflects the evidence behind the
    label rather than the label itself.
    """
    bass_energy = _weighted_bass_chroma(features)
    frame_dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.023

    total = readable = 0.0
    inv_num = 0.0
    for c in chords:
        if c.quality == "N":
            continue
        w = max(c.duration, 1e-6)
        total += w
        if c.bass_pc is None:
            inv_num += w * _NEUTRAL  # unresolved bass: uncertain, not wrong
            continue
        readable += w
        i0 = int(round(c.start / frame_dt))
        i1 = min(bass_energy.shape[1], int(round(c.end / frame_dt)))
        if i1 <= i0:
            inv_num += w * _NEUTRAL
            continue
        seg = bass_energy[:, i0:i1].mean(axis=1)
        top = float(seg[c.bass_pc])
        runner = float(np.max(np.delete(seg, c.bass_pc)))
        dominance = top / max(runner, 1e-9)
        if c.inversion == 0:
            inv_num += w * 1.0  # confirmed root in the bass: fully unambiguous
        else:
            # The bass gate required >=1.8x dominance to claim an inversion;
            # 3x or more counts as fully unambiguous.
            inv_num += w * min(1.0, dominance / 3.0)

    bass_score = readable / total if total else 0.0
    inversion_score = inv_num / total if total else 0.0
    return bass_score, inversion_score


def _voicing_dimension(chords: list[Chord]) -> float:
    """Duration-weighted mean of the per-chord voicing confidence."""
    num = den = 0.0
    for c in chords:
        if c.quality == "N":
            continue
        w = max(c.duration, 1e-6)
        score = c.voicing.confidence if c.voicing is not None else _NEUTRAL
        num += w * float(score)
        den += w
    return num / den if den else 0.0


def _function_dimension(chords: list[Chord], key: KeyEstimate) -> float:
    """Half key-profile fit, half diatonic coherence of the progression."""
    num = den = 0.0
    for c in chords:
        if c.quality == "N":
            continue
        w = max(c.duration, 1e-6)
        num += w * (1.0 if _is_diatonic(c, key) else 0.0)
        den += w
    diatonic_share = num / den if den else 0.0
    return 0.5 * max(0.0, float(key.confidence)) + 0.5 * diatonic_share
