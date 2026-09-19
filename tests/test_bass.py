import numpy as np
import pytest

from harmony.bass import _inversion_from_bass, label_inversions
from harmony.models import Chord
from harmony.chroma import Features


def test_inversion_from_bass_major():
    assert _inversion_from_bass(0, "maj", 0) == 0
    assert _inversion_from_bass(0, "maj", 4) == 1   # C/E
    assert _inversion_from_bass(0, "maj", 7) == 2   # C/G
    assert _inversion_from_bass(0, "maj7", 11) == 3  # Cmaj7/B
    assert _inversion_from_bass(0, "min7", 10) == 3  # Cm7/Bb
    # Non-chord-tone bass -> root position label
    assert _inversion_from_bass(0, "maj", 2) == 0


def test_label_inversions_picks_dominant_bass_pc():
    # 2 seconds at ~23ms frames ~= 86 frames of C major with G in the bass.
    n = 86
    times = np.arange(n) * 0.023
    cqt = np.zeros((84, n))
    # Put strong C in octave 3 and G in octave 2 (bass register).
    cqt[3 * 12 + 0] = 1.0   # C4 row range (octave index 3)
    cqt[2 * 12 + 7] = 1.2   # G2 (octave index 2 -> bass-weighted)
    features = Features(chroma=np.zeros((12, n)), recognition_chroma=np.zeros((12, n)),
                        bass_chroma=np.zeros((12, n)),
                        cqt_norm=cqt, times=times, tempo=None)
    chord = Chord(start=0.0, end=times[-1], root_pc=0, quality="maj")
    label_inversions([chord], features, times)
    assert chord.bass_pc == 7
    assert chord.inversion == 2
