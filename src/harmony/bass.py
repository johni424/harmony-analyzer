"""Bass detection: find the lowest sounding pitch class to determine inversions."""
from __future__ import annotations

import numpy as np

from .chroma import Features
from .models import Chord

# Weighting of bass octaves: an electric bass fundamental sits E1–G3, i.e.
# mostly octaves C1–B2 with only the top of its range entering C3–B3.
# The old weights (0,0,1,0.85,...) zeroed exactly that register and judged
# "bass" from the guitar register, which re-rooted chords to whatever the
# rhythm guitar played low (measured on a real mix: 21/21 false inversions).
OCTAVE_WEIGHTS = np.array([0.2, 1.0, 1.0, 0.4, 0.1, 0.0, 0.0])  # C1..B7 octave bias


def _weighted_bass_chroma(features: Features) -> np.ndarray:
    """Rebuild a bass-weighted chroma from the normalized full CQT."""
    cqt = features.cqt_norm
    weighted = np.zeros((12, cqt.shape[1]))
    for oct_idx in range(len(OCTAVE_WEIGHTS)):
        w = OCTAVE_WEIGHTS[oct_idx]
        if w == 0.0:
            continue
        weighted += w * cqt[oct_idx * 12 : (oct_idx + 1) * 12]
    return weighted


def detect_bass_pitch_classes(features: Features, min_strength: float = 0.12) -> list[int | None]:
    """Per-frame estimate of the bass pitch class (or None if unclear).

    A frame has a confident bass only if the strongest low-register pitch
    clearly dominates the others.
    """
    bass = _weighted_bass_chroma(features)
    frames: list[int | None] = []
    for t in range(bass.shape[1]):
        col = bass[:, t]
        total = col.sum()
        if total < 1e-9:
            frames.append(None)
            continue
        best = int(np.argmax(col))
        strength = col[best] / (total + 1e-9)
        frames.append(best if strength >= min_strength else None)
    return frames


def label_inversions(chords: list[Chord], features: Features, times: np.ndarray) -> None:
    """Assign bass pitch class and inversion to each chord segment in place.

    For each segment we collect the confident bass frames inside it and take
    the median (robust against walk-ups and passing bass notes). If the bass
    pitch class matches a chord tone that is not the root, the segment is an
    inversion (slash chord).
    """
    bass_frames = detect_bass_pitch_classes(features)
    bass_energy = _weighted_bass_chroma(features)
    frame_dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.023

    for chord in chords:
        start_f = int(round(chord.start / frame_dt))
        end_f = min(len(bass_frames), int(round(chord.end / frame_dt)))
        observed = [b for b in bass_frames[start_f:end_f] if b is not None]
        if not observed:
            chord.bass_pc = None
            chord.inversion = 0
            continue

        vals, counts = np.unique(observed, return_counts=True)
        order = np.argsort(counts)[::-1]
        top_pc = int(vals[order[0]])
        top_share = counts[order[0]] / len(observed)

        # Only trust the bass if it is consistent (not a busy walking line).
        if top_share < 0.4:
            chord.bass_pc = None
            chord.inversion = 0
            continue

        inversion = _inversion_from_bass(chord.root_pc, chord.quality, top_pc)
        if top_pc == chord.root_pc % 12:
            # Root in the bass: root position.
            chord.bass_pc = top_pc
            chord.inversion = 0
            continue
        if inversion == 0:
            # Bass is not a chord tone (pedal point / passing note):
            # keep root position and suppress the misleading slash label.
            chord.bass_pc = None
            chord.inversion = 0
            chord.confidence *= 0.95
            continue

        # Dominance gate: only claim an inversion when the candidate bass
        # pitch class clearly dominates the low register's energy. Guitar
        # voicings routinely sound a chord tone an octave above the bass;
        # without this gate every major chord becomes a slash chord.
        i0 = int(round(chord.start / frame_dt))
        i1 = min(bass_energy.shape[1], int(round(chord.end / frame_dt)))
        seg = bass_energy[:, i0:i1].mean(axis=1)
        runner_up = float(np.max(np.delete(seg, top_pc)))
        if float(seg[top_pc]) >= 1.8 * max(runner_up, 1e-9):
            chord.bass_pc = top_pc
            chord.inversion = inversion
        else:
            # Ambiguous low register: report root position rather than
            # invent an inversion.
            chord.bass_pc = None
            chord.inversion = 0


# For each quality, semitone offsets from root that count as a chord tone for
# inversion purposes (3rd, 5th, 7th, and sus).
_INVERSION_TONES: dict[str, tuple[int, ...]] = {
    "maj": (4, 7),
    "min": (3, 7),
    "dim": (3, 6),
    "aug": (4, 8),
    "sus4": (5, 7),
    "sus2": (2, 7),
    "maj7": (4, 7, 11),
    "min7": (3, 7, 10),
    "7": (4, 7, 10),
    "hdim7": (3, 6, 10),
    "dim7": (3, 6, 9),
    "minmaj7": (3, 7, 11),
    "maj6": (4, 7, 9),
    "min6": (3, 7, 9),
    "7sus4": (5, 7, 10),
}


def _inversion_from_bass(root_pc: int, quality: str, bass_pc: int) -> int:
    """Map a bass pitch class to an inversion number, 0 if root position/unknown."""
    if bass_pc == root_pc % 12:
        return 0
    tones = _INVERSION_TONES.get(quality, ())
    # Sort tones ascending so the bass above the root maps to the right inversion.
    for inv, interval in enumerate(sorted(tones), start=1):
        if bass_pc == (root_pc + interval) % 12:
            return inv
    return 0
