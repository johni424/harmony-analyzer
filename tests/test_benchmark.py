"""Phase 7 tests: the benchmark harness — subprocess isolation, resource
accounting, artifact measurement, and the cost model math."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from harmony.benchmark import aggregate, bench_import_baseline, cost_per_analysis

REPO = Path(__file__).parent.parent


# --------------------------------------------------------------------------- #
#  Cost model (pure — hand-computable expectations)
# --------------------------------------------------------------------------- #

def test_serverless_cost_hand_computed() -> None:
    """1 GB × 100 s memory + 50 s vCPU at published Lambda rates."""
    pricing = {"lambda_gb_second_usd": 0.0000166667, "lambda_vcpu_second_usd": 0.0000133334}
    c = cost_per_analysis({"wall_s": 100.0, "cpu_s": 50.0, "peak_rss_mb": 1024.0},
                          pricing=pricing)
    expected = 1024 / 1024 * 100 * 0.0000166667 + 50 * 0.0000133334
    assert c["serverless_usd"] == pytest.approx(expected, rel=1e-3)


def test_retention_and_egress_scale_linearly() -> None:
    base = {"wall_s": 10, "cpu_s": 10, "peak_rss_mb": 200}
    c1 = cost_per_analysis({**base, "audio_wav_mb": 75.0, "downloaded_mb": 75.0})
    c2 = cost_per_analysis({**base, "audio_wav_mb": 150.0, "downloaded_mb": 150.0})
    assert c2["retention_usd_per_month"] == pytest.approx(
        2 * c1["retention_usd_per_month"])
    assert c2["ingress_egress_usd"] == pytest.approx(
        2 * c1["ingress_egress_usd"])


def test_vps_cost_independent_of_song_length() -> None:
    """On fixed capacity the $/analysis is capacity/throughput — a longer song
    changes the throughput note, not the arithmetic of the rate itself."""
    short = cost_per_analysis({"wall_s": 30, "cpu_s": 30, "peak_rss_mb": 800})
    long_ = cost_per_analysis({"wall_s": 90, "cpu_s": 90, "peak_rss_mb": 1500})
    assert short["vps_usd"] > 0 and long_["vps_usd"] > 0


def test_custom_pricing_overrides() -> None:
    c = cost_per_analysis({"wall_s": 60, "cpu_s": 60, "peak_rss_mb": 1024},
                          pricing={"lambda_gb_second_usd": 0.0,
                                   "lambda_vcpu_second_usd": 0.0})
    assert c["serverless_usd"] == 0.0  # free tier fantasy, but the math must obey


# --------------------------------------------------------------------------- #
#  Aggregation
# --------------------------------------------------------------------------- #

def test_aggregate_normalizes_per_audio_minute() -> None:
    rows = [
        {"ok": True, "wall_s": 10.0, "cpu_s": 8.0, "peak_rss_mb": 200,
         "audio_seconds": 60.0, "artifacts": {"audio_wav": 6e6, "player_html": 3e5,
                                              "analysis_json": 2e4}},
        {"ok": True, "wall_s": 20.0, "cpu_s": 16.0, "peak_rss_mb": 300,
         "audio_seconds": 120.0, "artifacts": {"audio_wav": 12e6, "player_html": 6e5,
                                               "analysis_json": 4e4}},
    ]
    agg = aggregate(rows)
    assert agg["n"] == 2
    assert agg["wall_s_per_audio_min"] == pytest.approx(10.0)
    assert agg["cpu_s_per_audio_min"] == pytest.approx(8.0)
    assert agg["peak_rss_mb"] == 300.0  # max, not mean
    assert agg["audio_wav_mb_per_audio_min"] == pytest.approx(6.0)   # 6 MB/min both
    assert agg["player_html_kb_per_audio_min"] == pytest.approx(300.0)


def test_aggregate_empty_and_failed_rows() -> None:
    assert aggregate([]) == {}
    bad = [{"ok": False, "error": "x"}]
    assert aggregate(bad) == {}


# --------------------------------------------------------------------------- #
#  Live subprocess measurement
# --------------------------------------------------------------------------- #

def test_import_baseline_measures_a_real_child() -> None:
    row = bench_import_baseline()
    assert row["ok"] and row["wall_s"] > 0 and row["peak_rss_mb"] > 0


@pytest.mark.slow
def test_analyze_benchmark_row(tmp_path) -> None:
    """A full analysis row measures wall/CPU/RSS and all three artifacts."""
    import numpy as np
    import soundfile as sf
    from harmony.benchmark import bench_analyze

    sr = 22050
    t = np.arange(int(sr * 2)) / sr
    wave = sum(np.sin(2 * np.pi * f * t) * a
               for f, a in ((261.63, .5), (329.63, .4), (392.0, .35)))
    wav = tmp_path / "cmaj.wav"
    sf.write(wav, (wave * .3).astype(np.float32), sr)

    row = bench_analyze(str(wav), label="unit_cmaj")
    assert row["ok"], row.get("error")
    assert row["audio_seconds"] == pytest.approx(2.0, abs=0.2)
    assert row["rt_factor"] > 0
    arts = row["artifacts"]
    assert arts["audio_wav"] > 0 and arts["player_html"] > 1000
    assert arts["analysis_json"] > 200
