"""Tests for the rhythmic analysis stage: meter estimation, chord alignment,
and beat-grid recovery from a synthetic click track."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

from harmony.models import Chord, RhythmInfo
from harmony.rhythm import _estimate_meter, align_chords_to_beats, analyze_rhythm

SR = 22050


def _mk_rhythm(meter=4, n_beats=32, tempo=120.0):
    spb = 60.0 / tempo
    beats = [round(i * spb, 3) for i in range(n_beats)]
    strengths = [1.0 if i % meter == 0 else 0.55 for i in range(n_beats)]
    downs = [i for i in range(n_beats) if i % meter == 0]
    return RhythmInfo(tempo=tempo, meter=meter, beat_times=beats,
                      beat_strengths=strengths, downbeats=downs, confidence=0.8)


def test_meter_estimation_prefers_strong_downbeats():
    rng = np.random.default_rng(7)
    # 4/4 profile with noise: every 4th beat strong
    strengths = np.array([1.0, 0.5, 0.6, 0.45] * 12) + rng.normal(0, 0.05, 48)
    meter, downs, coherence = _estimate_meter(np.arange(48.0), strengths)
    assert meter == 4
    assert downs[0] == 0 and len(downs) == 12
    assert coherence > 0.2


def test_meter_estimation_3_4():
    strengths = np.array([1.0, 0.5, 0.55] * 10)
    meter, downs, _ = _estimate_meter(np.arange(30.0), strengths)
    assert meter == 3
    assert downs[0] == 0


def test_meter_estimation_rejects_flat_profile():
    strengths = np.ones(32)  # no accent pattern at all
    meter, downs, coherence = _estimate_meter(np.arange(32.0), strengths)
    assert meter == 1 or coherence < 0.15


def test_align_chords_places_chords_in_bar():
    r = _mk_rhythm(meter=4, n_beats=32, tempo=120.0)  # 0.5s per beat
    # chord per bar (2s), 8 chords
    chords = [Chord(start=i * 2.0, end=(i + 1) * 2.0, root_pc=0, quality="maj")
              for i in range(8)]
    align_chords_to_beats(chords, r)
    for i, c in enumerate(chords):
        assert c.bar == i + 1
        assert c.beat_in_bar == 1
        assert c.beats == 4
        assert c.beat_fraction == 4.0
        assert c.pushed is False


def test_align_chords_detects_pushed_entry():
    r = _mk_rhythm(meter=4, n_beats=32, tempo=120.0)
    # second chord enters 0.15s before beat 4 (within tol 0.16*0.5=0.08? -> use closer)
    chords = [
        Chord(start=0.0, end=1.44, root_pc=0, quality="maj"),   # ends just before beat 3
        Chord(start=1.44, end=2.5, root_pc=5, quality="maj"),   # enters off-grid
        Chord(start=2.5, end=4.0, root_pc=7, quality="maj"),
    ]
    align_chords_to_beats(chords, r)
    # boundary at 1.44 should snap to beat at 1.5 (within 0.08s)
    assert chords[0].end == pytest.approx(1.5)
    # 1.5 is beat index 3 -> bar 1, beat 4
    assert chords[1].beat_in_bar == 4
    assert chords[1].bar == 1


def test_align_chords_off_grid_far_from_beats_not_snapped():
    r = _mk_rhythm(meter=4, n_beats=32, tempo=120.0)
    chords = [Chord(start=0.0, end=0.9, root_pc=0, quality="maj"),
              Chord(start=0.9, end=2.0, root_pc=5, quality="maj")]
    align_chords_to_beats(chords, r)
    # 0.9 is 0.15s from the 1.0 beat -> beyond tol (0.08): not snapped
    assert chords[0].end == pytest.approx(0.9)


@pytest.mark.slow
def test_click_track_end_to_end():
    """Render a 4/4 click track with a sustained chord and recover the grid."""
    import librosa
    import soundfile as sf
    import tempfile, os

    tempo = 100.0
    spb = 60.0 / tempo
    n_bars = 8
    dur = n_bars * 4 * spb
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    y = np.zeros_like(t)
    # kick-ish clicks on every beat, louder on downbeats
    for i in range(n_bars * 4):
        start = int(i * spb * SR)
        seg = np.exp(-np.linspace(0, 40, 600)) * np.sin(
            2 * np.pi * 200 * np.linspace(0, 600 / SR, 600))
        seg *= 1.0 if i % 4 == 0 else 0.4
        y[start:start + len(seg)] += seg
    # sustained triad (C4 E4 G4) over the whole thing
    for f in (261.63, 329.63, 392.0):
        y += 0.12 * np.sin(2 * np.pi * f * t)

    info = analyze_rhythm(y, SR)
    assert info is not None
    assert info.meter == 4
    assert abs(info.tempo - tempo) < 2.0
    assert len(info.beat_times) >= n_bars * 4 - 2
    # Downbeats must land near the click's downbeat times (0, 4*spb, 8*spb, …).
    # Compare in TIME, not index: the tracker may skip the very first click,
    # shifting every subsequent beat index by one.
    bar_len = 4 * spb
    for db in info.downbeats:
        t = info.beat_times[db]
        nearest_downbeat = round(t / bar_len) * bar_len
        assert abs(t - nearest_downbeat) < spb * 0.75
