"""Roadmap-to-production steps 1–3: per-song comparison table, doc-format
accuracy report (by musical situation), and the correction interface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from harmony.corrections import (
    ChordCorrection, apply_correction, parse_symbol_strict, to_dataset_case,
)
from harmony.evaluation import (
    RefCase, RefChord, comparison_table, load_dataset, run_case_full,
)
from harmony.models import AnalysisResult, Chord, KeyEstimate
from harmony.report import json_report
from harmony.server import JOBS, JOBS_LOCK, Job, _register, app

REPO = Path(__file__).parent.parent
SR = 22050
client = TestClient(app)


# --------------------------------------------------------------------------- #
#  Step 1: the analyzer-vs-ground-truth comparison table
# --------------------------------------------------------------------------- #

@pytest.mark.slow
def test_comparison_table_matches_doc_format(tmp_path) -> None:
    """Every ground-truth chord of a rendered case shows ✓ in its own row."""
    case = [c for c in load_dataset(REPO / "datasets" / "synthetic.json")
            if c.id == "axis_c_major"][0]
    score, result = run_case_full(case, work_dir=tmp_path)
    table = comparison_table(case, result)
    assert "ground truth" in table and "analyzer" in table
    assert "Key:" in table and "Tempo:" in table
    body_rows = [ln for ln in table.splitlines() if ln.startswith("| ")][1:]
    assert len(body_rows) == 4
    # the analyzer recovered this progression exactly → all ✓ in the chord column
    for row in body_rows:
        cells = [c.strip() for c in row.split("|")]
        assert cells[4] == "✓", row


def test_comparison_table_marks_mismatch() -> None:
    """A wrong detected label must show ✗, not silently pass."""
    case = RefCase(id="t", kind="synthetic", genre="x", key="C major",
                   chords=[RefChord("C", 0.0, 4.0)])
    result = AnalysisResult(
        title="t", source="synthetic", duration=4.0,
        key=KeyEstimate(tonic_pc=0, mode="major", confidence=0.9),
        chords=[Chord(start=0.0, end=4.0, root_pc=7, quality="maj", confidence=0.5)])
    table = comparison_table(case, result)
    assert "✗" in table and "G" in table


# --------------------------------------------------------------------------- #
#  Step 2: accuracy by musical situation + roman/timing metrics
# --------------------------------------------------------------------------- #

def test_situation_scores_split_triads_sevenths_slash() -> None:
    from harmony.evaluation import score_case
    case = RefCase(id="t", kind="synthetic", genre="jazz", key="C major",
                   chords=[RefChord("C", 0.0, 2.0),
                           RefChord("Cmaj7", 2.0, 2.0),
                           RefChord("G/B", 4.0, 2.0, bass="B")])
    result = AnalysisResult(
        title="t", source="synthetic", duration=6.0,
        key=KeyEstimate(tonic_pc=0, mode="major", confidence=0.9),
        chords=[Chord(start=s, end=e, root_pc=r, quality=q, bass_pc=b, confidence=0.5)
                for s, e, r, q, b in [(0.0, 2.0, 0, "maj", 0),
                                      (2.0, 4.0, 0, "maj7", 0),
                                      (4.0, 6.0, 7, "maj", 11)]])
    s = score_case(case, result, analysis_seconds=0.5)
    assert s.situations["triads"] == pytest.approx(1.0)
    assert s.situations["sevenths"] == pytest.approx(1.0)
    assert s.situations["slash"] == pytest.approx(1.0)


def test_roman_accuracy_and_timing_present() -> None:
    from harmony.evaluation import score_case
    case = RefCase(id="t", kind="synthetic", genre="x", key="C major",
                   chords=[RefChord("C", 0.0, 2.0, roman="I"),
                           RefChord("G", 2.0, 2.0, roman="V")])
    result = AnalysisResult(
        title="t", source="synthetic", duration=4.0,
        key=KeyEstimate(tonic_pc=0, mode="major", confidence=0.9),
        chords=[Chord(start=0.0, end=2.0, root_pc=0, quality="maj",
                      confidence=0.5, function="I"),
                Chord(start=2.0, end=4.0, root_pc=7, quality="maj",
                      confidence=0.5, function="V")])
    s = score_case(case, result, analysis_seconds=0.5)
    assert s.roman_accuracy == 1.0
    assert s.timing_median_ms is not None and s.timing_median_ms < 50


def test_by_situation_in_aggregate(tmp_path) -> None:
    from harmony.evaluation import aggregate
    scores = []
    for case in load_dataset(REPO / "datasets" / "synthetic.json"):
        # skip heavy run: only need two cases for the aggregate shape
        if case.id not in ("axis_c_major", "inversions_c_major"):
            continue
        score, _ = run_case_full(case, work_dir=tmp_path)
        scores.append(score)
    agg = aggregate(scores)
    assert "by_situation" in agg
    assert agg["by_situation"]["triads"] > 0.9
    assert agg["by_situation"]["slash"] > 0.9


# --------------------------------------------------------------------------- #
#  Step 3: the correction interface
# --------------------------------------------------------------------------- #

def _doc(chords: list[dict]) -> dict:
    """A schema-complete analysis document with the given chord dicts
    (apply_correction validates the WHOLE document, as the server does)."""
    return {
        "title": "t", "source": "synthetic", "duration": 8.0, "tempo": 100.0,
        "notes": [],
        "key": {"name": "C major", "tonic": "C", "mode": "major",
                "confidence": 0.9},
        "rhythm": {"tempo": 100.0, "meter": 4, "confidence": 0.7,
                   "beat_times": [0.0, 0.5, 1.0, 1.5], "downbeats": [0]},
        "chords": chords,
    }

def test_parse_symbol_strict_accepts_and_rejects() -> None:
    assert parse_symbol_strict("Fmaj7/A") == (5, "maj7", 9)
    assert parse_symbol_strict("C") == (0, "maj", None)
    assert parse_symbol_strict("Bbm7") == (10, "min7", None)
    with pytest.raises(ValueError):
        parse_symbol_strict("Fquarter")
    with pytest.raises(ValueError):
        parse_symbol_strict("H")  # not a note name


def test_apply_correction_sets_inversion_and_provenance() -> None:
    doc = _doc([{"start": 0.0, "end": 2.0, "chord": "C", "root": "C",
                 "quality": "maj", "inversion": 0,
                 "inversion_name": "root position", "bass": "C",
                 "roman": "I", "role": "tonic", "confidence": 0.5}])
    apply_correction(doc, ChordCorrection(index=0, original_symbol="C",
                                          new_symbol="C/E"))
    c = doc["chords"][0]
    assert c["chord"] == "C/E" and c["bass"] == "E" and c["inversion"] == 1
    assert c["human_corrected"] is True


def test_apply_correction_rejects_schema_violation() -> None:
    doc = _doc([{"start": 0.0, "end": 2.0, "chord": "C", "root": "C",
                 "quality": "maj", "inversion": 0,
                 "inversion_name": "root position", "bass": "C",
                 "roman": "I", "role": "tonic", "confidence": 0.5}])
    # "C/F": F is not a C-chord tone → no inversion; correction must be
    # normalized (bass dropped) rather than producing an invalid document.
    apply_correction(doc, ChordCorrection(index=0, original_symbol="C",
                                          new_symbol="C/F"))
    assert doc["chords"][0]["inversion"] == 0


def test_dataset_case_round_trips_through_harness() -> None:
    doc = {"key": {"name": "C major"}, "tempo": 100.0,
           "rhythm": {"meter": 4}, "chords": [
               {"start": 0.0, "end": 2.0, "chord": "C/E", "roman": "I"},
               {"start": 2.0, "end": 4.0, "chord": "G", "roman": "V"}]}
    case = to_dataset_case("job42", doc,
                           [ChordCorrection(index=0, original_symbol="C",
                                            new_symbol="C/E")])
    assert case["id"] == "corrected_job42"
    assert case["checked"].startswith("human-corrected")
    tmp = REPO / ".tmp_test_dataset_case.json"
    try:
        tmp.write_text(json.dumps([case]))
        (loaded,) = load_dataset(tmp)
        assert loaded.chords[0].symbol == "C/E"
        assert loaded.chords[0].n_corrections == 1
        assert loaded.chords[1].n_corrections == 0
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
#  Step 3: HTTP surface (PATCH + corrections log)
# --------------------------------------------------------------------------- #

def _tone_wav() -> bytes:
    t = np.arange(int(SR * 2)) / SR
    wave = sum(np.sin(2 * np.pi * f * t) * a
               for f, a in ((261.63, .5), (329.63, .4), (392.0, .35)))
    import io
    buf = io.BytesIO()
    sf.write(buf, (wave * .3).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


def test_correct_endpoint_full_flow() -> None:
    created = client.post("/api/jobs/file",
                          files={"file": ("cmaj.wav", _tone_wav(), "audio/wav")})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    import time as _t
    deadline = _t.time() + 120
    while _t.time() < deadline:
        if client.get(f"/api/jobs/{job_id}").json().get("stage") in ("done", "error"):
            break
        _t.sleep(0.5)
    assert client.get(f"/api/jobs/{job_id}").json()["stage"] == "done"

    res = client.patch(f"/api/v1/jobs/{job_id}/correct",
                       json={"index": 0, "new_symbol": "C/E"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chord"]["chord"] == "C/E"
    assert body["chord"]["inversion"] == 1
    assert body["dataset_case"]["chords"][0]["symbol"] == "C/E"

    # the log endpoint reflects it
    log = client.get(f"/api/v1/jobs/{job_id}/corrections").json()
    assert log["corrections"][0]["new"] == "C/E"
    assert log["dataset_case"]["chords"][0]["n_corrections"] == 1

    # the /analysis GET serves the corrected, schema-valid document
    analysis = client.get(f"/api/v1/jobs/{job_id}/analysis").json()
    assert analysis["analysis"]["chords"][0]["chord"] == "C/E"

    # bad symbol → 422 with the parser's explanation
    bad = client.patch(f"/api/v1/jobs/{job_id}/correct",
                       json={"index": 0, "new_symbol": "Fquarter"})
    assert bad.status_code == 422

    with JOBS_LOCK:
        JOBS.pop(job_id, None)


def test_correct_endpoint_unknown_job_404() -> None:
    assert client.patch("/api/v1/jobs/deadbeef/correct",
                        json={"index": 0, "new_symbol": "C"}).status_code == 404
