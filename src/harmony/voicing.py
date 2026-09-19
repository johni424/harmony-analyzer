"""Voicing analysis: what pitches actually sound, beyond the basic chord."""
from __future__ import annotations

import numpy as np

from .chroma import Features
from .models import Chord, VoicingInfo

# Extension intervals relative to root -> interval name.
EXTENSION_CANDIDATES: dict[int, str] = {
    1: "b9",
    2: "9",
    3: "#9",
    5: "11",
    6: "#11",
    8: "b13",
    9: "13",
    10: "7",  # minor 7 as extension over maj triad etc.
    11: "maj7",
}

# How strongly each quality supports a given extension interval.
_SUPPORT = {
    "maj": {9: 0.3, 11: 0.2, 13: 0.2, 10: 0.1},
    "min": {2: 0.5, 5: 0.4, 9: 0.4, 10: 0.3},
    "7": {1: 0.4, 3: 0.3, 5: 0.2, 6: 0.3, 8: 0.3, 9: 0.5},
    "maj7": {2: 0.4, 6: 0.4, 9: 0.4},
    "min7": {2: 0.5, 5: 0.4, 9: 0.4},
    "hdim7": {9: 0.3},
    "dim7": {},
    "aug": {9: 0.3},
    "sus4": {2: 0.3, 9: 0.3},
    "sus2": {5: 0.3},
    "maj6": {2: 0.3},
    "min6": {2: 0.3},
    "7sus4": {2: 0.3},
    "minmaj7": {9: 0.3},
}


def analyze_voicing(
    chord: Chord,
    features: Features,
    times: np.ndarray,
) -> VoicingInfo:
    """Estimate the voicing of one chord segment from the normalized CQT."""
    start_f = _frame_of(chord.start, times)
    end_f = _frame_of(chord.end, times)
    seg = features.cqt_norm[:, start_f:end_f]
    if seg.shape[1] == 0:
        return VoicingInfo(pitch_classes=frozenset())

    # Average energy per pitch class over the segment.
    pc_energy = np.zeros(12)
    for oct_idx in range(7):
        pc_energy += seg[oct_idx * 12 : (oct_idx + 1) * 12].mean(axis=1)

    total = pc_energy.sum()
    if total < 1e-9:
        return VoicingInfo(pitch_classes=frozenset())
    pc_energy /= total

    threshold = max(0.02, 0.25 * pc_energy.max())
    sounding = frozenset(int(pc) for pc in np.where(pc_energy >= threshold)[0])

    # ---- extensions --------------------------------------------------------
    chord_tones = _chord_tone_pcs(chord)
    extensions: list[int] = []
    ext_confidences: list[float] = []
    for semitone, name in EXTENSION_CANDIDATES.items():
        pc = (chord.root_pc + semitone) % 12
        if pc in chord_tones or pc not in sounding:
            continue
        support = _SUPPORT.get(chord.quality, {}).get(semitone, 0.15)
        energy = float(pc_energy[pc])
        if energy < 0.07:
            continue
        conf = min(0.9, energy * 3.0 * (0.4 + support))
        if conf >= 0.3:
            extensions.append(semitone)
            ext_confidences.append(conf)

    # Sort extensions by interval so symbol looks natural (9, 11, 13).
    extensions.sort()

    # ---- added / passing notes ---------------------------------------------
    added = tuple(sorted(pc for pc in sounding if pc not in chord_tones and pc not in
                         {(chord.root_pc + e) % 12 for e in extensions}))

    # ---- register & spacing -------------------------------------------------
    # Octave centroid of the chord tones' energy.
    weighted_octave_sum = 0.0
    weight_sum = 0.0
    for oct_idx in range(7):
        band = seg[oct_idx * 12 : (oct_idx + 1) * 12].mean(axis=1)
        w = float(band.sum())
        weighted_octave_sum += oct_idx * w
        weight_sum += w
    centroid_octave = weighted_octave_sum / (weight_sum + 1e-9)

    # Spread: std dev of octave indices weighted by energy.
    var = 0.0
    for oct_idx in range(7):
        band = seg[oct_idx * 12 : (oct_idx + 1) * 12].mean(axis=1)
        var += (oct_idx - centroid_octave) ** 2 * float(band.sum())
    spread = float(np.sqrt(var / (weight_sum + 1e-9)))

    spacing = _classify_spacing(sounding, chord, spread)

    conf = float(np.mean(ext_confidences)) if ext_confidences else 0.7
    return VoicingInfo(
        pitch_classes=sounding,
        bass_pc=chord.bass_pc,
        extensions=tuple(extensions),
        register_spread_semitones=spread * 12.0,
        spacing=spacing,
        added_notes=added,
        confidence=conf,
    )


def _chord_tone_pcs(chord: Chord) -> set[int]:
    from .chords import QUALITY_INTERVALS

    return {chord.root_pc} | {(chord.root_pc + iv) % 12 for iv, _ in QUALITY_INTERVALS.get(chord.quality, ())}


def _classify_spacing(sounding: frozenset[int], chord: Chord, spread: float) -> str:
    pcs = sorted(sounding)
    if len(pcs) < 2:
        return "single note"
    gaps = np.diff(pcs)
    if spread > 1.6:
        return "spread"
    if gaps.size and gaps.max() <= 2:
        return "cluster"
    if len(pcs) >= 4 and gaps.min() >= 1:
        return "open"
    return "closed"


def _frame_of(t: float, times: np.ndarray) -> int:
    idx = int(np.searchsorted(times, t))
    return max(0, min(idx, len(times) - 1))
