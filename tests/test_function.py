import numpy as np
import pytest

from harmony.function import annotate_functions, detect_key, roman_numeral
from harmony.models import Chord, KeyEstimate


def _chord(root, quality, start, dur, bass=None, inv=0):
    return Chord(start=start, end=start + dur, root_pc=root, quality=quality,
                 bass_pc=bass, inversion=inv)


def test_detect_key_c_major():
    chords = [_chord(0, "maj", 0, 2), _chord(9, "min", 2, 2),
              _chord(5, "maj", 4, 2), _chord(7, "maj", 6, 2)]
    key = detect_key(chords)
    assert key.tonic_pc == 0 and key.mode == "major"


def test_detect_key_a_minor():
    # Unambiguous minor progression: Am - F - Dm - Em (opens on tonic minor,
    # contains no C-major tonic triad).
    chords = [_chord(9, "min", 0, 2), _chord(5, "maj", 2, 2),
              _chord(2, "min", 4, 2), _chord(4, "min", 6, 2)]
    key = detect_key(chords)
    assert key.tonic_pc == 9 and key.mode == "minor"


def test_roman_numerals_major_key():
    key = KeyEstimate(tonic_pc=0, mode="major")
    assert roman_numeral(_chord(0, "maj", 0, 1), key) == "I"
    assert roman_numeral(_chord(9, "min", 0, 1), key) == "vi"
    assert roman_numeral(_chord(5, "maj", 0, 1), key) == "IV"
    assert roman_numeral(_chord(7, "7", 0, 1), key) == "V7"
    assert roman_numeral(_chord(2, "maj", 0, 1), key) == "II"     # borrowed II
    assert roman_numeral(_chord(8, "maj", 0, 1), key) == "bVI"    # borrowed bVI


def test_roman_numerals_minor_key():
    key = KeyEstimate(tonic_pc=9, mode="minor")
    assert roman_numeral(_chord(9, "min", 0, 1), key) == "i"
    assert roman_numeral(_chord(0, "maj", 0, 1), key) == "III"
    assert roman_numeral(_chord(5, "maj", 0, 1), key) == "VI"
    assert roman_numeral(_chord(7, "maj", 0, 1), key) == "VII"    # diatonic subtonic
    assert roman_numeral(_chord(10, "maj", 0, 1), key) == "bII"   # Neapolitan
    assert roman_numeral(_chord(8, "maj", 0, 1), key) == "#VII"   # raised 7th (harmonic minor)


def test_secondary_dominant_annotated():
    # V/vi: E7 -> Am in C major.
    chords = [_chord(0, "maj", 0, 2), _chord(4, "7", 2, 2), _chord(9, "min", 4, 2)]
    key = KeyEstimate(tonic_pc=0, mode="major")
    annotate_functions(chords, key)
    assert chords[1].function == "V7/vi"
    assert "secondary dominant" in chords[1].effect


def test_cadence_annotated():
    chords = [_chord(7, "maj", 0, 2), _chord(0, "maj", 2, 2)]
    key = KeyEstimate(tonic_pc=0, mode="major")
    annotate_functions(chords, key)
    assert any("authentic cadence" in (c.effect or "") for c in chords)


def test_bass_line_annotation_stepwise():
    # C - D/E?? Simple: C (bass C) -> F (bass F) -> G (bass G)? not stepwise.
    # Use A minor triads with stepwise bass: C -> D -> E (root position triads).
    chords = [
        _chord(0, "maj", 0, 1, bass=0, inv=0),
        _chord(2, "min", 1, 1, bass=2, inv=0),
        _chord(4, "min", 2, 1, bass=4, inv=0),
    ]
    key = KeyEstimate(tonic_pc=0, mode="major")
    annotate_functions(chords, key)
    joined = " ".join(c.effect or "" for c in chords)
    assert "stepwise" in joined


def test_inversion_effect_annotated():
    chords = [_chord(0, "maj", 0, 1, bass=4, inv=1)]
    key = KeyEstimate(tonic_pc=0, mode="major")
    annotate_functions(chords, key)
    assert "1st inversion" in chords[0].effect
