"""Tests for the web server: landing page, upload flow, progress polling."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from harmony.server import app

client = TestClient(app)


def _tone_wav() -> bytes:
    """Two seconds of a C major chord — enough for a quick pipeline run."""
    sr = 22050
    t = np.arange(int(sr * 2)) / sr
    wave = sum(
        np.sin(2 * np.pi * f * t) * amp
        for f, amp in ((261.63, 0.5), (329.63, 0.4), (392.0, 0.35))
    )
    buf = io.BytesIO()
    sf.write(buf, (wave * 0.3).astype(np.float32), sr, format="WAV")
    return buf.getvalue()


def test_landing_page_serves() -> None:
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "YouTube" in html and "Analyze" in html
    assert "/api/jobs/url" in html and "/api/jobs/file" in html


def test_healthz() -> None:
    assert client.get("/healthz").json() == {"ok": True}


def test_url_rejects_non_youtube() -> None:
    res = client.post("/api/jobs/url", json={"url": "https://vimeo.com/12345"})
    assert res.status_code == 422


def test_url_rejects_empty() -> None:
    assert client.post("/api/jobs/url", json={"url": "  "}).status_code == 422


def test_unknown_job_404() -> None:
    assert client.get("/api/jobs/deadbeef").status_code == 404


def test_upload_rejects_non_audio() -> None:
    res = client.post(
        "/api/jobs/file",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert res.status_code == 422


def test_upload_full_flow() -> None:
    """Upload a WAV, poll to completion, verify summary and player availability."""
    res = client.post(
        "/api/jobs/file",
        files={"file": ("cmajor.wav", _tone_wav(), "audio/wav")},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    summary = None
    for _ in range(240):  # CI machines can be slow; 4 min ceiling
        status = client.get(f"/api/jobs/{job_id}")
        assert status.status_code == 200
        summary = status.json()
        if summary["stage"] in ("done", "error"):
            break
        import time

        time.sleep(1.0)
    assert summary is not None
    assert summary["stage"] == "done", summary
    assert summary["n_chords"] > 0
    assert summary["key"], "key should be detected even for a synthetic tone"
    assert summary["has_audio"] is True

    player = client.get(f"/player/{job_id}")
    assert player.status_code == 200
    assert "text/html" in player.headers["content-type"]
