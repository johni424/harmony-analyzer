"""End-to-end test with synthesized audio.

Renders a simple I-V-vi-IV progression as sustained sine chords with a bass
line, writes a wav, and runs the full pipeline on it.
"""
import librosa
import numpy as np
import pytest

from harmony.pipeline import analyze
from harmony.models import pc_from_name

SR = 22050


def _tone(freq, dur, sr=SR, amp=0.2):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    # Pure sine with a short fade (10 ms) to avoid envelope splatter.
    wave = np.sin(2 * np.pi * freq * t)
    fade = int(0.01 * sr)
    env = np.ones_like(wave)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return amp * wave * env


def _chord_audio(tones, bass, dur):
    """Keyboard-style voicing: chord tones at octave 4, root doubled at
    octave 3, bass note as given."""
    parts = [_note(n, 4, dur) for n in tones]
    parts.append(_note(tones[0], 3, dur, amp=0.25))  # doubled root
    parts.append(_note(bass[0], bass[1], dur, amp=0.3))
    return np.sum(parts, axis=0)


def _note(name, octave, dur, amp=0.2):
    midi = 12 * (octave + 1) + pc_from_name(name)
    freq = 440.0 * 2 ** ((midi - 69) / 12)
    return _tone(freq, dur, amp=amp)


@pytest.mark.slow
def test_end_to_end_c_major_progression(tmp_path):
    dur = 1.5
    progression = [
        # (chord tones by name, bass note name+octave)
        (["C", "E", "G"], ("C", 2)),
        (["G", "B", "D"], ("G", 2)),
        (["A", "C", "E"], ("A", 2)),
        (["F", "A", "C"], ("F", 2)),
    ]
    # Mix chord tones SIMULTANEOUSLY (sum), not sequentially.
    song = np.concatenate([
        _chord_audio(tones, (b, bo), dur)
        for tones, (b, bo) in progression
    ])
    wav = tmp_path / "prog.wav"
    librosa.output.write_wav if hasattr(librosa, "output") else None
    import soundfile as sf
    sf.write(wav, song, SR)

    result = analyze(str(wav))

    # Key should be C major.
    assert result.key.tonic_pc == 0 and result.key.mode == "major"

    # We should find at least the roots C, G, A, F somewhere in the top labels.
    roots_found = [c.root_pc for c in result.chords if c.duration >= 0.5]
    for expected_root in (0, 7, 9, 5):
        assert expected_root in roots_found, f"missing root {expected_root} in {roots_found}"

    # Roman numerals should include I and V for the opening.
    functions = [c.function for c in result.chords]
    assert any(f and f.startswith("I") for f in functions)
    assert any(f and f.startswith("V") for f in functions)
