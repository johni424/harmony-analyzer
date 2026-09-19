import numpy as np
import pytest

from harmony.chords import QUALITY_INTERVALS, build_emission_matrix, viterbi_chords
from harmony.models import pc_from_name, pitch_name


def test_pitch_name_roundtrip():
    for pc in range(12):
        assert pc_from_name(pitch_name(pc)) == pc
    assert pc_from_name("Bb") == 10
    assert pc_from_name("F#") == 6


def test_all_qualities_define_three_or_more_tones():
    for quality, intervals in QUALITY_INTERVALS.items():
        pcs = {iv for iv, _ in intervals}
        assert 0 in pcs
        assert len(pcs) >= 3, quality


def test_emission_matrix_is_normalized():
    E, states = build_emission_matrix()
    np.testing.assert_allclose(np.linalg.norm(E, axis=1), 1.0, rtol=1e-6)
    assert len(states) == 12 * len(QUALITY_INTERVALS)


def _synthetic_chroma(chords, frames_per_chord, tempo=None):
    """Build a chroma matrix for a chord sequence, with the root emphasized
    (x1.5) the way real audio doubles the root in the bass."""
    times = np.arange(len(chords) * frames_per_chord) * 0.023
    chroma = np.zeros((12, len(chords) * frames_per_chord))
    for i, (root, quality) in enumerate(chords):
        w = np.full(12, 0.01)
        for iv, weight in QUALITY_INTERVALS[quality]:
            w[(root + iv) % 12] = weight
        w[root] *= 1.5
        if quality.endswith("7") or quality == "7":
            # Make the 7th clearly audible, as in real recordings where the
            # 7th sits on top of the voicing.
            w[(root + {"7": 10, "maj7": 11, "min7": 10, "hdim7": 10, "dim7": 9, "minmaj7": 11}.get(quality, 10)) % 12] *= 1.4
        chroma[:, i * frames_per_chord : (i + 1) * frames_per_chord] = w[:, None]
    return chroma, times


def test_viterbi_recovers_simple_progression():
    prog = [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")]  # C - Am - F - G
    chroma, times = _synthetic_chroma(prog, frames_per_chord=40)
    segments = viterbi_chords(chroma, times, tempo=120)
    decoded = [(s.root_pc, s.quality) for s in segments]
    assert decoded == prog


def test_viterbi_recovers_seventh_chords():
    prog = [(0, "maj7"), (2, "min7"), (5, "maj7"), (7, "7")]
    chroma, times = _synthetic_chroma(prog, frames_per_chord=40)
    segments = viterbi_chords(chroma, times, tempo=100)
    decoded = [(s.root_pc, s.quality) for s in segments]
    assert decoded == prog


def test_short_glitch_is_merged():
    prog = [(0, "maj"), (0, "maj"), (7, "maj"), (0, "maj")]
    chroma, times = _synthetic_chroma(prog, frames_per_chord=30)
    # Inject a 1-frame spurious chord between segment 2 and 3.
    chroma[:, 65] = 0
    chroma[4, 65] = 1.0  # E alone -> likely misread
    segments = viterbi_chords(chroma, times, tempo=120)
    durations = [(s.end_frame - s.start_frame) for s in segments]
    assert all(d >= 2 for d in durations), durations
