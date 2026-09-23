"""Measured cost model (plan step 28, Phase 7): what one analysis actually costs.

The plan document is explicit: *measure* CPU time, RAM, storage, network and
worker time for one analysis, calculate cost/analysis from those numbers, and
only then decide between LOCAL and CLOUD architectures. This module is the
measuring instrument; docs/BUSINESS.md is the calculation; ADR-008 is the
decision.

Method
------
Each case runs in a **fresh subprocess**. CPU time and peak RSS come from
``resource.getrusage(RUSAGE_CHILDREN)`` deltas around that child (on the
ingest case this honestly includes yt-dlp/ffmpeg descendants). Wall time is
measured in-child. Artifact sizes (wav, player.html, analysis.json) are
measured on disk after the run. An ``import_baseline`` child measures the
interpreter + librosa/numba floor so peak-RSS numbers can be read as
"analysis headroom over baseline".

All pricing in the cost model lives in ``DEFAULT_PRICING`` — published list
prices, easy to swap. Nothing here is an estimate of *work*; only the $/unit
rates are external constants.
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SR = 22050

# --------------------------------------------------------------------------- #
#  Child protocol
# --------------------------------------------------------------------------- #

_CHILD_CODE = r'''
import json, sys, time
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text())
out = {"ok": False}
t0 = time.perf_counter()
try:
    if spec["kind"] == "import_baseline":
        import harmony.pipeline  # noqa: F401  (interpreter + libs floor)
        out.update(ok=True, wall=time.perf_counter() - t0)
    elif spec["kind"] == "analyze":
        from harmony import report
        from harmony.pipeline import analyze
        import soundfile as sf
        result = analyze(spec["source"], verbose=False, keep_audio=True)
        out["audio_seconds"] = float(sf.info(spec["source"]).duration)
        wd = Path(spec["work_dir"])
        artifacts = {}
        if result.audio_path and Path(result.audio_path).exists():
            artifacts["audio_wav"] = Path(result.audio_path).stat().st_size
        player = wd / "player.html"
        player.write_text(report.html_report(result, sharp=False, audio_src="/audio/bench"))
        artifacts["player_html"] = player.stat().st_size
        doc = wd / "analysis.json"
        doc.write_text(report.json_report(result))
        artifacts["analysis_json"] = doc.stat().st_size
        out.update(ok=True, wall=time.perf_counter() - t0, artifacts=artifacts,
                   n_chords=len(result.chords), title=result.title)
    elif spec["kind"] == "ingest":
        from harmony import ingest
        path, title, kind = ingest.resolve(spec["source"])
        out.update(ok=True, wall=time.perf_counter() - t0,
                   downloaded_bytes=Path(path).stat().st_size,
                   audio_seconds=float(__import__("soundfile").info(path).duration),
                   title=title, kind=kind)
    else:
        out["error"] = f"unknown kind {spec['kind']!r}"
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {exc}"
    out["wall"] = time.perf_counter() - t0
Path(sys.argv[2]).write_text(json.dumps(out))
'''


def _rss_mb() -> float:
    """Peak RSS of waited children so far, in MB (platform-correct units)."""
    raw = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    factor = 1 if sys.platform == "darwin" else 1024  # macOS: bytes; Linux: KiB
    return raw * factor / (1024 * 1024)


def _run_child(spec: dict) -> tuple[dict, float, float, float]:
    """Spawn a fresh child for one spec. Returns (result, cpu_s, peak_mb, wall_s)."""
    with tempfile.TemporaryDirectory(prefix="harmony_bench_") as td:
        spec_path = Path(td) / "spec.json"
        res_path = Path(td) / "result.json"
        spec = {**spec, "work_dir": td}
        spec_path.write_text(json.dumps(spec))

        pre_u = resource.getrusage(resource.RUSAGE_CHILDREN)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD_CODE, str(spec_path), str(res_path)],
            capture_output=True, text=True, timeout=900,
        )
        wall = time.perf_counter() - t0
        post = resource.getrusage(resource.RUSAGE_CHILDREN)

        cpu = ((post.ru_utime - pre_u.ru_utime)
               + (post.ru_stime - pre_u.ru_stime))
        peak = _rss_mb()
        if proc.returncode != 0:
            return ({"ok": False, "error": f"child crashed: {proc.stderr[-400:]}"},
                    cpu, peak, wall)
        return json.loads(res_path.read_text()), cpu, peak, wall


# --------------------------------------------------------------------------- #
#  Cases
# --------------------------------------------------------------------------- #


def bench_import_baseline() -> dict:
    res, cpu, peak, wall = _run_child({"kind": "import_baseline"})
    return {"case": "import_baseline", "ok": res.get("ok", False),
            "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
            "peak_rss_mb": round(peak, 1),
            "note": "interpreter + librosa/numba import floor"}


def bench_analyze(source: str, label: str | None = None) -> dict:
    """Benchmark one full analysis of a local audio file."""
    res, cpu, peak, wall = _run_child({"kind": "analyze", "source": source})
    row = {"case": label or Path(source).stem, "ok": res.get("ok", False),
           "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
           "peak_rss_mb": round(peak, 1)}
    if res.get("ok"):
        row.update(audio_seconds=round(res["audio_seconds"], 1),
                   n_chords=res["n_chords"], title=res["title"],
                   artifacts=res["artifacts"],
                   rt_factor=round(wall / res["audio_seconds"], 3))
    else:
        row["error"] = res.get("error")
    return row


def bench_ingest(url: str) -> dict:
    """Benchmark URL ingest only (yt-dlp download + decode), not analysis."""
    res, cpu, peak, wall = _run_child({"kind": "ingest", "source": url})
    row = {"case": f"ingest:{url[:48]}", "ok": res.get("ok", False),
           "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
           "peak_rss_mb": round(peak, 1)}
    if res.get("ok"):
        row.update(downloaded_mb=round(res["downloaded_bytes"] / 1e6, 1),
                   audio_seconds=round(res["audio_seconds"], 1), title=res["title"])
    else:
        row["error"] = res.get("error")
    return row


# --------------------------------------------------------------------------- #
#  Cost model (pure — unit-testable without audio)
# --------------------------------------------------------------------------- #

# Published list prices (USD), September 2026. Swap freely; the model is the code.
DEFAULT_PRICING = {
    "lambda_gb_second_usd": 0.0000166667,     # AWS Lambda memory billing
    "lambda_vcpu_second_usd": 0.0000133334,   # AWS Lambda vCPU billing
    "s3_gb_month_usd": 0.023,                 # object storage retention
    "egress_gb_usd": 0.09,                    # outbound transfer
    "vps_month_usd": 4.5,                     # small VPS: 2 vCPU / 4 GB class
    "vps_cores": 2,
    "utilization": 0.5,                       # fraction of the month the cores do paid work
}


def cost_per_analysis(m: dict, pricing: dict | None = None,
                      analyses_per_month: int = 1000) -> dict:
    """Compute cost/analysis per hosting tier from measured aggregates.

    `m` (per-analysis measured means):
      wall_s, cpu_s, peak_rss_mb, downloaded_mb (0 for local files),
      audio_wav_mb (retained per player, optional)
    """
    p = {**DEFAULT_PRICING, **(pricing or {})}
    wall = max(m["wall_s"], 1e-6)
    cpu = m["cpu_s"]
    peak_gb = m["peak_rss_mb"] / 1024

    # Serverless: billed for memory-and-vCPU while the worker runs.
    serverless = (peak_gb * wall * p["lambda_gb_second_usd"]
                  + cpu * p["lambda_vcpu_second_usd"])

    # Small VPS: fixed capacity shared across analyses.
    month_seconds = 30 * 24 * 3600
    per_vps = max(int(month_seconds * p["utilization"] * p["vps_cores"] / max(cpu, 1e-6)), 1)
    vps = p["vps_month_usd"] / min(per_vps, analyses_per_month)

    # Retention (per analysis, per month of keeping the player playable) + egress.
    retention = m.get("audio_wav_mb", 0.0) / 1024 * p["s3_gb_month_usd"]
    egress = m.get("downloaded_mb", 0.0) / 1024 * p["egress_gb_usd"]

    return {
        "serverless_usd": round(serverless, 8),
        "vps_usd": round(vps, 8),
        "retention_usd_per_month": round(retention, 8),
        "ingress_egress_usd": round(egress, 8),
        "notes": {
            "vps": f"one ${p['vps_month_usd']} VPS sustains ~{per_vps} analyses/month "
                   f"at {p['utilization']:.0%} utilization ({p['vps_cores']} cores)",
            "serverless": f"{peak_gb:.2f} GB × {wall:.0f} s memory + {cpu:.0f} s CPU",
        },
    }


def aggregate(rows: list[dict]) -> dict:
    """Mean resource profile over successful analyze rows (per audio-minute)."""
    ok = [r for r in rows if r.get("ok") and r.get("audio_seconds")]
    if not ok:
        return {}
    per_min = lambda vals, aud: sum(v / a["audio_seconds"] * 60
                                    for v, a in zip(vals, ok)) / len(ok)
    arts = [r.get("artifacts", {}) for r in ok]
    # artifacts scale with audio duration → normalize to per-audio-minute too
    art_per_min = lambda k: sum(a.get(k, 0) / r["audio_seconds"] * 60
                                for a, r in zip(arts, ok)) / len(arts)
    return {
        "n": len(ok),
        "wall_s_per_audio_min": round(per_min([r["wall_s"] for r in ok], ok), 1),
        "cpu_s_per_audio_min": round(per_min([r["cpu_s"] for r in ok], ok), 1),
        "peak_rss_mb": round(max(r["peak_rss_mb"] for r in ok), 1),
        "audio_wav_mb_per_audio_min": round(art_per_min("audio_wav") / 1e6, 1),
        "player_html_kb_per_audio_min": round(art_per_min("player_html") / 1e3, 1),
        "analysis_json_kb_per_audio_min": round(art_per_min("analysis_json") / 1e3, 1),
    }


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure CPU/RAM/storage/network per analysis (step 28)")
    parser.add_argument("--synthetic", default=None, metavar="N",
                        help="comma-separated synthetic case ids (default: all)")
    parser.add_argument("--wav", default=None, help="benchmark one local audio file")
    parser.add_argument("--url", default=None,
                        help="benchmark a full URL ingest + analysis (network)")
    parser.add_argument("--ingest-only", action="store_true",
                        help="with --url: measure the download only")
    parser.add_argument("--out", default=None, help="write bench.json + bench.md")
    args = parser.parse_args()

    rows = [bench_import_baseline()]

    if args.wav:
        rows.append(bench_analyze(args.wav))
    elif args.url and args.ingest_only:
        rows.append(bench_ingest(args.url))
    elif args.url:
        rows.append(bench_ingest(args.url))
        # after ingest the wav is cached in $TMPDIR/harmony_analyzer; analyze it
        cache = Path(tempfile.gettempdir()) / "harmony_analyzer"
        wavs = sorted(cache.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        if wavs:
            rows.append(bench_analyze(str(wavs[-1]), label="url_song"))
    else:
        from harmony.evaluation import load_dataset
        ds = Path(__file__).resolve().parent.parent.parent / "datasets" / "synthetic.json"
        if not ds.exists():
            print("datasets/synthetic.json not found", file=sys.stderr)
            raise SystemExit(1)
        cases = load_dataset(ds)
        if args.synthetic:
            wanted = {s.strip() for s in args.synthetic.split(",")}
            cases = [c for c in cases if c.id in wanted]
        for c in cases:
            from harmony.evaluation import render_case
            import soundfile as sf
            tmp = Path(tempfile.mkdtemp(prefix="harmony_bench_"))
            wav = tmp / f"{c.id}.wav"
            sf.write(wav, render_case(c), SR)
            row = bench_analyze(str(wav), label=c.id)
            shutil.rmtree(tmp, ignore_errors=True)
            rows.append(row)

    agg = aggregate(rows)
    cpu = agg.get("cpu_s_per_audio_min", 0.0) / 60 * 6.5   # 6.5-min song ≈ gospel case
    profile = cost_per_analysis({
        "wall_s": agg.get("wall_s_per_audio_min", 0) * 6.5 / 60,
        "cpu_s": agg.get("cpu_s_per_audio_min", 0) * 6.5 / 60,
        "peak_rss_mb": agg.get("peak_rss_mb", 0),
        "audio_wav_mb": agg.get("audio_wav_mb_per_audio_min", 0) * 6.5,
        # retention uses the real ingest wav (stereo 44.1 kHz), not synthetic mono:
        "downloaded_mb": next((r.get("downloaded_mb", 0) for r in rows
                               if r.get("downloaded_mb")), 0),
    }) if agg else {}

    result = {
        "platform": {"python": platform.python_version(), "machine": platform.machine(),
                     "system": platform.system(), "cpus": __import__("os").cpu_count()},
        "rows": rows,
        "aggregate_per_audio_minute": agg,
        "example_profile_65min_song": {
            "cpu_minutes": round(cpu / 60, 2),
            "audio_wav_mb": round(agg.get("audio_wav_mb_per_audio_min", 0) * 6.5, 1),
            "peak_rss_mb": agg.get("peak_rss_mb"),
            "cost": profile,
        },
    }
    print(json.dumps(result, indent=2))

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(result, indent=2))
        lines = ["# Benchmark — measured per-analysis resources", "",
                 f"`{platform.system()}` · {platform.machine()} · Python "
                 f"{platform.python_version()} · {result['platform']['cpus']} cores", "",
                 "| case | ok | wall s | cpu s | peak RSS MB | rt× |", "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['case']} | {'✓' if r.get('ok') else '✗'} | {r['wall_s']} "
                         f"| {r['cpu_s']} | {r['peak_rss_mb']} | {r.get('rt_factor', '—')} |")
        if agg:
            lines += ["", f"**Per audio-minute:** cpu {agg['cpu_s_per_audio_min']} s · "
                      f"peak RSS {agg['peak_rss_mb']} MB · wav {agg['audio_wav_mb_per_audio_min']} MB · "
                      f"player {agg['player_html_kb_per_audio_min']} KB · doc "
                      f"{agg['analysis_json_kb_per_audio_min']} KB"]
        out.with_suffix(".md").write_text("\n".join(lines) + "\n")
        print(f"wrote {out.with_suffix('.json')} and {out.with_suffix('.md')}", file=sys.stderr)


if __name__ == "__main__":
    main()
