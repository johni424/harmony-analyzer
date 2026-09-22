"""Step 25 tests: the evaluation harness — parsing, rendering, metrics,
dataset integrity, calibration math, and a performance budget."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from harmony.evaluation import (
    RefCase, RefChord, load_dataset, parse_symbol, quality_family,
    render_case, score_case,
)
from harmony.models import AnalysisResult, Chord, ConfidenceScores, KeyEstimate

REPO = Path(__file__).parent.parent


# --------------------------------------------------------------------------- #
#  Reference parsing
# --------------------------------------------------------------------------- #

def test_parse_symbol_basic() -> None:
    root, quality, bass = parse_symbol("C")
    assert (root, quality, bass) == (0, "maj", None)


def test_parse_symbol_slash() -> None:
    root, quality, bass = parse_symbol("G/B")
    assert (root, quality, bass) == (7, "maj", 11)


def test_parse_symbol_sevenths_and_flats() -> None:
    root, quality, bass = parse_symbol("Bbm7")
    assert (root, quality, bass) == (10, "min7", None)
    root, quality, _ = parse_symbol("Fmaj7")
    assert (root, quality) == (5, "maj7")


def test_parse_symbol_unknown_suffix_rejected() -> None:
    with pytest.raises(ValueError):
        parse_symbol("Cpower")


def test_quality_family_extension_tolerance() -> None:
    assert quality_family("maj7") == "maj"
    assert quality_family("min7") == "min"
    assert quality_family("7") == "maj"
    assert quality_family("min") == "min"  # passthrough


# --------------------------------------------------------------------------- #
#  Synthetic rendering honors its ground truth
# --------------------------------------------------------------------------- #

def _spec_case(bass_note: str | None) -> RefCase:
    return RefCase(
        id="t", kind="synthetic", genre="test", key="C major", tempo=100, meter=4,
        chords=[RefChord(symbol="G/B" if bass_note == "B" else "C",
                         start=0.0, duration=2.4, bass=bass_note)],
        render={"bpm": 100, "meter": 4, "clicks": False, "chords": [
            {"tones": ["G", "B", "D"] if bass_note == "B" else ["C", "E", "G"],
             "bass": bass_note, "start_beat": 0, "dur_beats": 4},
        ]},
    )


def test_render_respects_declared_bass() -> None:
    """The renderer must reinforce the sounding bass, not always the root —
    otherwise the fixture contradicts its own inversion ground truth."""
    import numpy as np
    audio = render_case(_spec_case("B"))
    n = int(2.4 * 22050)
    seg = audio[:n]
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1 / 22050)
    # B2 ≈ 123.5 Hz must be among the strongest low partials
    lo = (freqs > 80) & (freqs < 300)
    peaks = freqs[lo][np.argsort(spec[lo])[-6:]]
    assert any(abs(f - 123.47) < 3 for f in peaks), f"B2 not prominent: {sorted(peaks)}"


def test_render_length_and_peak() -> None:
    import numpy as np
    audio = render_case(_spec_case(None))
    assert len(audio) == int(3.4 * 22050)  # duration + 1 s tail
    assert 0.1 < float(np.abs(audio).max()) <= 1.0


# --------------------------------------------------------------------------- #
#  Metrics math on constructed results
# --------------------------------------------------------------------------- #

def _result(chords, key_pc=0, mode="major", tempo=None, meter=None, conf=0.5):
    from harmony.models import RhythmInfo
    rhythm = None
    if tempo and meter:
        beats = [i * 0.5 for i in range(32)]
        rhythm = RhythmInfo(tempo=tempo, meter=meter, beat_times=beats,
                            beat_strengths=[0.5] * 32,
                            downbeats=list(range(0, 32, meter)), confidence=0.8)
    return AnalysisResult(
        title="t", source="synthetic", duration=16.0,
        key=KeyEstimate(tonic_pc=key_pc, mode=mode, confidence=0.9),
        tempo=tempo, rhythm=rhythm,
        chords=[Chord(start=s, end=e, root_pc=r, quality=q, bass_pc=b,
                      confidence=conf) for s, e, r, q, b in chords],
        confidence=ConfidenceScores(chord=conf, bass=conf, inversion=1.0,
                                    voicing=conf, function=conf, rhythm=conf,
                                    overall=conf),
    )


def test_perfect_match_scores_one() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=None, meter=None,
                   chords=[RefChord("C", 0.0, 4.0), RefChord("G", 4.0, 4.0)])
    res = _result([(0.0, 4.0, 0, "maj", 0), (4.0, 8.0, 7, "maj", 7)])
    s = score_case(case, res, analysis_seconds=1.0)
    assert s.chord_accuracy == 1.0 and s.root_accuracy == 1.0
    assert s.key_ok and s.boundary_median == 0.0


def test_wrong_quality_penalized_root_still_scores() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=None, meter=None,
                   chords=[RefChord("C", 0.0, 4.0)])
    res = _result([(0.0, 4.0, 0, "min", 0)])
    s = score_case(case, res, analysis_seconds=0.5)
    assert s.chord_accuracy == 0.0 and s.root_accuracy == 1.0
    assert s.family_accuracy == 0.0  # min is not in the maj family


def test_extension_tolerance_family_metric() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=None, meter=None,
                   chords=[RefChord("Cmaj7", 0.0, 4.0)])
    res = _result([(0.0, 4.0, 0, "maj", 0)])
    s = score_case(case, res, analysis_seconds=0.5)
    assert s.chord_accuracy == 0.0       # strict: maj ≠ maj7
    assert s.family_accuracy == 1.0      # tolerant: same family
    assert s.root_accuracy == 1.0


def test_bass_accuracy_only_where_reference_states_bass() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=None, meter=None,
                   chords=[RefChord("C", 0.0, 2.0),
                           RefChord("G/B", 2.0, 2.0, bass="B")])
    res = _result([(0.0, 2.0, 0, "maj", 0), (2.0, 4.0, 7, "maj", 11)])
    s = score_case(case, res, analysis_seconds=0.5)
    assert s.bass_accuracy == 1.0  # only the slash chord is scored


def test_tempo_octave_folding() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=100.0, meter=None,
                   chords=[RefChord("C", 0.0, 4.0)])
    res = _result([(0.0, 4.0, 0, "maj", 0)], tempo=199.0)  # double-time read
    s = score_case(case, res, analysis_seconds=0.5)
    assert s.tempo_ok is True
    assert abs(s.tempo_ratio - 1.0) <= 0.04  # folded back to unity


def test_brier_perfect_when_confident_and_correct() -> None:
    case = RefCase(id="t", kind="synthetic", genre="test", key="C major",
                   tempo=None, meter=None,
                   chords=[RefChord("C", 0.0, 4.0)])
    res = _result([(0.0, 4.0, 0, "maj", 0)], conf=0.9)
    s = score_case(case, res, analysis_seconds=0.5)
    assert s.brier == pytest.approx((0.9 - 1.0) ** 2)


# --------------------------------------------------------------------------- #
#  Dataset integrity (manifests are valid without running audio)
# --------------------------------------------------------------------------- #

def test_synthetic_manifest_parses_and_is_consistent() -> None:
    cases = load_dataset(REPO / "datasets" / "synthetic.json")
    assert len(cases) >= 6
    for c in cases:
        assert c.kind == "synthetic"
        assert c.chords, f"{c.id}: no ground truth"
        assert c.render and c.render.get("chords"), f"{c.id}: no render spec"
        # ground truth tiling: contiguous from 0
        t = 0.0
        for rc in c.chords:
            assert abs(rc.start - t) < 0.05, f"{c.id}: gap before {rc.symbol}"
            t = rc.start + rc.duration
        # every render chord's bass is a chord tone (or the root)
        from harmony.evaluation import _SUFFIX_PCS
        for spec in c.render["chords"]:
            root, quality, bass = parse_symbol(
                next(rc.symbol for rc in c.chords
                     if abs(rc.start - spec["start_beat"] * 60 / (c.render["bpm"])) < 0.3
                     and rc.duration >= spec["dur_beats"] * 60 / (c.render["bpm"]) - 0.3
                     ) if False else _match_symbol(c, spec))
            tone_pcs = {parse_symbol(_match_symbol(c, spec))[0] + iv for iv in
                        _SUFFIX_PCS[_suffix_of(_match_symbol(c, spec))]}
            if spec.get("bass"):
                bass_pc = parse_symbol(f"C/{spec['bass']}")[2]
                assert bass_pc in tone_pcs, f"{c.id}: bass {spec['bass']} not a chord tone"


def _match_symbol(case: RefCase, spec: dict) -> str:
    """Find the ground-truth symbol for a render spec entry by beat timing."""
    spb = 60.0 / case.render["bpm"]
    for rc in case.chords:
        if abs(rc.start - spec["start_beat"] * spb) < 0.3:
            return rc.symbol
    raise AssertionError(f"no ground truth for render chord at beat {spec['start_beat']}")


def _suffix_of(symbol: str) -> str:
    s = symbol.split("/")[0]
    root = s[0] + (s[1] if len(s) > 1 and s[1] in "#b" else "")
    return s[len(root):] or ""


def test_real_manifest_shape() -> None:
    cases = load_dataset(REPO / "datasets" / "real_songs.json")
    assert len(cases) >= 3
    for c in cases:
        assert c.kind == "real" and c.source and c.source.startswith("http")
        assert c.checked  # provenance required for hand-checked entries
    # timed references must tile from 0; sequence-level entries declare empty
    for c in cases:
        t = 0.0
        for rc in c.chords:
            assert abs(rc.start - t) < 0.05, f"{c.id}: timed reference has a gap"
            t = rc.start + rc.duration


# --------------------------------------------------------------------------- #
#  Performance budget (TESTING.md gap → closed)
# --------------------------------------------------------------------------- #

@pytest.mark.slow
def test_performance_budget_sec_per_audio_minute(tmp_path) -> None:
    """Real-time factor budget: analyzing 1 minute of audio must stay under
    3 minutes of CPU (measured baseline on the synthetic set: ~10–60 s/min)."""
    from harmony.evaluation import run_case
    case = [c for c in load_dataset(REPO / "datasets" / "synthetic.json")
            if c.id == "axis_c_major"][0]
    score = run_case(case, work_dir=tmp_path)
    budget = 180.0  # seconds of analysis per 60 s of audio
    assert score.analysis_seconds / score.audio_seconds * 60 < budget, (
        f"performance regression: {score.analysis_seconds:.1f}s for "
        f"{score.audio_seconds:.1f}s audio")
