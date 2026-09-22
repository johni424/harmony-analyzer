"""Phase 4 (Trust) tests: confidence engine (step 19) + Harmonic DNA (step 18).

The confidence tests build Features objects directly so the bass-evidence
calibration can be exercised without audio; the DNA tests feed synthetic
chord lists; one slow integration test runs the full pipeline on a
synthesized I–V–vi–IV loop (played twice) and checks every report surface.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

from harmony import confidence as confidence_engine
from harmony import dna as dna_engine
from harmony.chroma import Features
from harmony.function import annotate_functions
from harmony.models import Chord, KeyEstimate, VoicingInfo, pc_from_name
from harmony.pipeline import analyze
from harmony.report import html_report, json_report, markdown_report, terminal_report

SR = 22050
KEY_C = KeyEstimate(tonic_pc=0, mode="major", confidence=0.9)


def _chord(root_pc, quality, start, end, conf=0.9, **kw):
    return Chord(start=start, end=end, root_pc=root_pc, quality=quality,
                 confidence=conf, **kw)


def _voice(pcs, conf=0.8):
    return VoicingInfo(pitch_classes=frozenset(pcs), confidence=conf)


# ---------------------------------------------------------------------------
# Harmonic DNA
# ---------------------------------------------------------------------------

def test_dna_recognizes_axis_progression_and_counts_repeats():
    # I–V–vi–IV in C major, played twice.
    loop = [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")]
    chords = [_chord(r, q, i * 1.5, (i + 1) * 1.5) for i, (r, q) in enumerate(loop * 2)]
    rep = dna_engine.analyze(chords, KEY_C)

    assert rep.matches, "axis progression must be recognized"
    top = rep.matches[0]
    assert top.numerals == ("I", "V", "vi", "IV")
    assert top.count == 2
    assert "axis" in top.name.lower()
    assert "I → V → vi → IV" in rep.signature
    assert rep.devices == {} or isinstance(rep.devices, dict)


def test_dna_falls_back_to_recurring_ngram():
    # V–ii–IV is not in the named-pattern catalog; it recurs 3×.
    loop = [(7, "maj"), (2, "min"), (5, "maj")]
    chords = [_chord(r, q, i * 1.0, (i + 1) * 1.0) for i, (r, q) in enumerate(loop * 3)]
    rep = dna_engine.analyze(chords, KEY_C)

    assert rep.matches == []
    assert rep.signature.startswith("V → ii → IV")
    assert "song-specific" in rep.signature


def test_dna_device_summary_counts():
    chords = [
        _chord(0, "maj", 0.0, 1.0, effect="secondary dominant — builds tension"),
        _chord(5, "maj", 1.0, 2.0, effect="borrowed from the parallel minor (modal mixture)"),
        _chord(7, "maj", 2.0, 3.0, bass_pc=4, inversion=1, pushed=True),
    ]
    rep = dna_engine.analyze(chords, KEY_C)
    assert rep.devices.get("secondary dominants") == 1
    assert rep.devices.get("borrowed chords (modal mixture)") == 1
    assert rep.devices.get("inversions used") == 1
    assert rep.devices.get("off-beat (pushed) entries") == 1


def test_dna_handles_empty_and_no_chord_lists():
    rep = dna_engine.analyze([], KEY_C)
    assert rep.signature == "—"
    assert rep.matches == []

    chords = [_chord(0, "N", 0.0, 1.0)]  # silence-only
    assert dna_engine.analyze(chords, KEY_C).signature == "—"


def test_dna_matches_by_degree_even_with_seventh_qualities():
    # Imaj7–V7–vi7–IVmaj7 must still fire the axis pattern (suffixes stripped).
    loop = [(0, "maj7"), (7, "7"), (9, "min7"), (5, "maj7")]
    chords = [_chord(r, q, i * 1.5, (i + 1) * 1.5) for i, (r, q) in enumerate(loop)]
    rep = dna_engine.analyze(chords, KEY_C)
    assert rep.matches and rep.matches[0].numerals == ("I", "V", "vi", "IV")


# ---------------------------------------------------------------------------
# Confidence engine
# ---------------------------------------------------------------------------

def _features(times):
    T = len(times)
    return Features(
        chroma=np.zeros((12, T)),
        recognition_chroma=np.zeros((12, T)),
        bass_chroma=np.zeros((12, T)),
        cqt_norm=np.zeros((84, T)),
        times=np.asarray(times),
        tempo=None,
    )


def test_confidence_bass_and_inversion_calibration():
    times = np.arange(0, 10, 0.023)
    feats = _features(times)
    k = int(round(2.0 / 0.023))
    feats.cqt_norm[1 * 12 + 0, :k] = 1.0        # C owns the low register, first half
    feats.cqt_norm[1 * 12 + 4, k:2 * k] = 1.0   # E owns it, second half
    feats.cqt_norm[3 * 12 + 0, k:2 * k] = 1.0   # ...but C hums below (weight 0.4)

    c_root = _chord(0, "maj", 0.0, 2.0, bass_pc=0, inversion=0,
                    voicing=_voice({0, 4, 7}))
    c_inv = _chord(0, "maj", 2.0, 4.0, bass_pc=4, inversion=1,
                   voicing=_voice({0, 4, 7}))

    s = confidence_engine.compute_confidence([c_root, c_inv], feats, times, KEY_C, None)

    assert s.bass == 1.0                    # both segments: readable low register
    # E dominates C by 2.5x → 2.5/3 of full confidence; root position is full.
    assert 0.8 < s.inversion < 1.0
    assert s.chord == pytest.approx(0.9, abs=0.01)   # duration-weighted posterior


def test_confidence_unresolved_bass_is_neutral_not_wrong():
    times = np.arange(0, 10, 0.023)
    feats = _features(times)
    c = _chord(0, "maj", 0.0, 2.0, bass_pc=None, inversion=0, voicing=_voice({0, 4, 7}))

    s = confidence_engine.compute_confidence([c], feats, times, KEY_C, None)

    assert s.bass == 0.0                    # no readable bass anywhere
    assert s.inversion == pytest.approx(0.5, abs=0.01)  # neutral, not punished
    assert 0.0 <= s.overall <= 1.0


def test_confidence_all_dimensions_bounded_and_overall_weighted():
    times = np.arange(0, 10, 0.023)
    feats = _features(times)
    chords = [
        _chord(0, "maj", 0.0, 1.0, conf=0.8, voicing=_voice({0, 4, 7})),
        _chord(7, "maj", 1.0, 2.0, conf=0.6, voicing=_voice({7, 11, 2})),
    ]
    s = confidence_engine.compute_confidence(chords, feats, times, KEY_C, None)

    for v in (s.chord, s.bass, s.inversion, s.voicing, s.function, s.rhythm, s.overall):
        assert 0.0 <= v <= 1.0
    assert s.rhythm == 0.0                  # no grid passed in
    # overall = 0.35*0.7 + 0.15*0 + 0.10*0.5 + 0.10*0.8 + 0.20*function + 0.10*0
    # (chord dim: (1.0*0.8 + 1.0*0.6)/2.0 = 0.7)
    assert s.overall == pytest.approx(
        0.35 * 0.7 + 0.15 * 0.0 + 0.10 * 0.5 + 0.10 * 0.8
        + 0.20 * (0.5 * 0.9 + 0.5 * 1.0), abs=0.01
    )


def test_confidence_empty_chord_list():
    s = confidence_engine.compute_confidence([], _features(np.arange(10)), np.arange(10), KEY_C, None)
    assert s.overall == 0.0


# ---------------------------------------------------------------------------
# End-to-end through the pipeline + report surfaces
# ---------------------------------------------------------------------------

def _tone(freq, dur, amp=0.2):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t)
    fade = int(0.01 * SR)
    env = np.ones_like(wave)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return amp * wave * env


def _note(name, octave, dur, amp=0.2):
    midi = 12 * (octave + 1) + pc_from_name(name)
    return _tone(440.0 * 2 ** ((midi - 69) / 12), dur, amp)


def _chord_audio(tones, bass, dur):
    parts = [_note(n, 4, dur) for n in tones]
    parts.append(_note(tones[0], 3, dur, 0.25))
    parts.append(_note(bass[0], bass[1], dur, 0.3))
    return np.sum(parts, axis=0)


@pytest.mark.slow
def test_trust_layer_end_to_end_and_report_surfaces(tmp_path):
    import soundfile as sf

    dur = 1.5
    prog = [
        (["C", "E", "G"], ("C", 2)),
        (["G", "B", "D"], ("G", 2)),
        (["A", "C", "E"], ("A", 2)),
        (["F", "A", "C"], ("F", 2)),
    ]
    song = np.concatenate([_chord_audio(t, b, dur) for t, b in prog] * 2)
    wav = tmp_path / "axis.wav"
    sf.write(wav, song, SR)

    result = analyze(str(wav))

    # Trust layer attached
    assert result.confidence is not None and result.dna is not None
    cs = result.confidence
    for v in (cs.chord, cs.bass, cs.inversion, cs.voicing, cs.function, cs.overall):
        assert 0.0 <= v <= 1.0
    assert cs.chord > 0.15                  # clean synthetic: decoder posteriors are
    # intentionally loose (temperature softmax), so trust the low-but-nonzero value

    # DNA: the axis loop, found twice
    assert "axis" in result.dna.signature.lower()
    assert result.dna.matches and result.dna.matches[0].count == 2

    # JSON surface
    import json as _json
    payload = _json.loads(json_report(result))
    assert payload["confidence"]["overall"] == cs.overall
    assert payload["dna"]["signature"] == result.dna.signature
    assert payload["dna"]["matches"][0]["count"] == 2

    # Markdown + terminal surfaces
    md = markdown_report(result)
    assert "**Harmonic DNA:**" in md and "**Trust:**" in md
    tr = terminal_report(result)
    assert "Harmonic DNA" in tr and "Trust" in tr

    # Player surface: DNA & trust card present
    html = html_report(result)
    assert 'id="dnacard"' in html
    assert "Harmonic DNA" in html
    assert "dimbar" in html


def test_reports_omit_trust_blocks_when_absent():
    result_chords = [_chord(0, "maj", 0.0, 1.0)]
    annotate_functions(result_chords, KEY_C)
    from harmony.models import AnalysisResult

    bare = AnalysisResult(title="t", source="s", duration=1.0, key=KEY_C, chords=result_chords)
    import json as _json
    payload = _json.loads(json_report(bare))
    assert "confidence" not in payload and "dna" not in payload
    assert "__DNA_CARD__" not in html_report(bare)
