"""Step 20 contract tests: the frozen JSON Schema is valid, the pipeline emits
conforming documents, and the /api/v1 endpoints serve the contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from harmony import schema
from harmony.pipeline import analyze
from harmony.server import app

client = TestClient(app)
SR = 22050


def _minimal_doc(**overrides) -> dict:
    """A tiny but complete analysis document: every required field, all
    conditional blocks present (voicing, rhythm, dna, confidence)."""
    doc = {
        "title": "Test song",
        "source": "/tmp/test.wav",
        "duration": 8.0,
        "tempo": 120.0,
        "notes": [],
        "key": {"name": "C major", "tonic": "C", "mode": "major", "confidence": 0.9},
        "rhythm": {
            "tempo": 120.0, "meter": 4, "confidence": 0.7,
            "beat_times": [0.0, 0.5, 1.0, 1.5], "downbeats": [0],
        },
        "confidence": {
            "chord": 0.5, "bass": 0.5, "inversion": 1.0, "voicing": 0.5,
            "function": 0.5, "rhythm": 0.7, "overall": 0.6,
        },
        "dna": {
            "signature": "song-specific",
            "devices": {"secondary dominants": 1},
            "matches": [{
                "name": "I–V–vi–IV (axis)", "numerals": ["I", "V"],
                "start": 0.0, "end": 4.0, "count": 1, "annotation": "axis",
            }],
        },
        "chords": [
            {
                "start": 0.0, "end": 4.0, "chord": "C", "root": "C",
                "quality": "maj", "inversion": 0,
                "inversion_name": "root position", "bass": "C",
                "roman": "I", "role": "tonic", "confidence": 0.4,
                "voicing": {
                    "pitch_classes": ["C", "E", "G"], "extensions": [],
                    "spacing": "closed", "added_notes": [], "confidence": 0.8,
                },
                "rhythm": {
                    "bar": 1, "beat_in_bar": 1, "beats": 8,
                    "beat_fraction": 8.0, "pushed": False,
                },
                "effect": "root position — stable",
            },
            {
                "start": 4.0, "end": 8.0, "chord": "G/B", "root": "G",
                "quality": "maj", "inversion": 1,
                "inversion_name": "1st inversion", "bass": "B",
                "roman": "V", "role": "dominant", "confidence": 0.3,
            },
        ],
    }
    doc.update(overrides)
    return doc


# --------------------------------------------------------------------------- #
#  The frozen schema itself
# --------------------------------------------------------------------------- #

def test_schema_file_is_valid_draft_2020_12() -> None:
    assert schema.load_schema()["$schema"].endswith("2020-12/schema")
    assert schema.SCHEMA_VERSION_STRING == "1.1.0"  # additive bump: corrections + full extension enum


def test_minimal_document_is_accepted() -> None:
    assert schema.validate_payload(_minimal_doc()) == []


def test_unknown_top_level_key_rejected() -> None:
    errors = schema.validate_payload(_minimal_doc(bogus_field=1))
    assert any("bogus_field" in e for e in errors)


def test_missing_required_chord_field_rejected() -> None:
    doc = _minimal_doc()
    del doc["chords"][0]["roman"]
    errors = schema.validate_payload(doc)
    assert any("'roman'" in e for e in errors)


def test_confidence_outside_unit_interval_rejected() -> None:
    doc = _minimal_doc()
    doc["confidence"]["overall"] = 1.5
    assert any("overall" in e for e in schema.validate_payload(doc))


def test_unknown_quality_rejected() -> None:
    doc = _minimal_doc()
    doc["chords"][0]["quality"] = "power"
    doc["chords"][0]["chord"] = "C5"  # keep symbol/quality story consistent
    assert any("quality" in e for e in schema.validate_payload(doc))


def test_inversion_name_mismatch_rejected() -> None:
    doc = _minimal_doc()
    doc["chords"][1]["inversion"] = 1
    doc["chords"][1]["inversion_name"] = "root position"
    assert any("inversion_name" in e for e in schema.validate_payload(doc))


def test_inversion_without_bass_rejected() -> None:
    doc = _minimal_doc()
    doc["chords"][1]["bass"] = None
    assert any("bass" in e for e in schema.validate_payload(doc))


# --------------------------------------------------------------------------- #
#  Pipeline → contract (synthesized audio through the real pipeline)
# --------------------------------------------------------------------------- #

def _tone(freq, dur, amp=0.2):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t)
    fade = int(0.01 * SR)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return amp * wave


def _note(name, octave, dur, amp=0.2):
    from harmony.models import pc_from_name
    midi = 12 * (octave + 1) + pc_from_name(name)
    return _tone(440.0 * 2 ** ((midi - 69) / 12), dur, amp)


@pytest.mark.slow
def test_pipeline_output_satisfies_schema(tmp_path) -> None:
    progression = [
        (["C", "E", "G"], ("C", 2)), (["G", "B", "D"], ("G", 2)),
        (["A", "C", "E"], ("A", 2)), (["F", "A", "C"], ("F", 2)),
    ]
    song = np.concatenate([
        np.sum([*[_note(n, 4, 1.5) for n in tones],
                _note(tones[0], 3, 1.5, amp=0.25),
                _note(bass[0], bass[1], 1.5, amp=0.3)], axis=0)
        for tones, bass in progression
    ])
    wav = tmp_path / "prog.wav"
    sf.write(wav, song, SR)

    from harmony.report import json_report
    result = analyze(str(wav), verbose=False)
    payload = json.loads(json_report(result))

    errors = schema.validate_payload(payload)
    assert errors == [], f"pipeline output violates the frozen contract: {errors}"
    assert payload["chords"][0]["start"] == 0.0  # segments tile the span from 0
    assert result.key.tonic_pc == 0 and result.key.mode == "major"  # key check via model


# --------------------------------------------------------------------------- #
#  /api/v1 contract endpoints
# --------------------------------------------------------------------------- #

def test_api_v1_schema_serves_frozen_file() -> None:
    res = client.get("/api/v1/schema")
    assert res.status_code == 200
    assert res.json() == schema.load_schema()


def test_api_v1_analysis_unknown_job_404() -> None:
    assert client.get("/api/v1/jobs/deadbeef/analysis").status_code == 404


def test_api_v1_analysis_not_ready_409() -> None:
    from harmony.server import Job, JOBS, JOBS_LOCK, _register
    job = Job(id="pending01", kind="upload")
    _register(job)
    try:
        res = client.get("/api/v1/jobs/pending01/analysis")
        assert res.status_code == 409
        assert "not ready" in res.json()["detail"].lower()
    finally:
        with JOBS_LOCK:
            JOBS.pop("pending01", None)


def test_api_v1_analysis_full_flow_contract(tmp_path) -> None:
    """Upload → poll → fetch analysis: document passes the frozen contract."""
    import io
    import time as _time

    sr = SR
    t = np.arange(int(sr * 2)) / sr
    wave = sum(np.sin(2 * np.pi * f * t) * amp
               for f, amp in ((261.63, 0.5), (329.63, 0.4), (392.0, 0.35)))
    buf = io.BytesIO()
    sf.write(buf, (wave * 0.3).astype(np.float32), sr, format="WAV")
    buf.seek(0)

    created = client.post("/api/jobs/file",
                          files={"file": ("cmaj.wav", buf, "audio/wav")})
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    deadline = _time.time() + 120
    stage = None
    while _time.time() < deadline:
        stage = client.get(f"/api/jobs/{job_id}").json()
        if stage.get("stage") in ("done", "error"):
            break
        _time.sleep(0.5)
    assert stage and stage.get("stage") == "done", stage

    res = client.get(f"/api/v1/jobs/{job_id}/analysis")
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == "1.1.0"
    errors = schema.validate_payload(body["analysis"])
    assert errors == [], f"API document violates the contract: {errors}"

    # Legacy unversioned summary unchanged for existing clients.
    summary = client.get(f"/api/jobs/{job_id}").json()
    assert summary["n_chords"] == len(body["analysis"]["chords"])
