# Business — measured cost model & architecture decision

**Status:** v1.0 · **Last updated:** 2026-09-22
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §28.
Instrument: `harmony/benchmark.py` (`harmony-bench`). Decision: [ADR-008](ADR/ADR-008-local-vs-cloud.md).

The plan (Phase 7 / step 28) demands **measurements first, cost second,
architecture decision third**. Every work-number below was measured by
`harmony-bench` on 2026-09-22 (macOS, x86_64, 4 cores, Python 3.12); only the
$/unit rates are published list prices (see `DEFAULT_PRICING` in
`benchmark.py` — swap freely, the model is code and unit-tested).

## 1. Measured resource profile

| measurement | synthetic mix (per audio-minute) | real dense mix (6.5-min gospel song) |
|---|---|---|
| wall time | 47.9 s | 69.6 s |
| CPU time | 46.0 s | 62.1 s |
| peak RSS | ~230 MB | **1.47 GB** |
| realtime factor | 0.80× | 0.18× (≈ 5.6× faster than the song) |
| produced WAV (44.1 kHz stereo) | — | 75.2 MB |
| player HTML (streamed) | — | 0.4 MB |
| analysis.json | — | 0.2 MB |

Import floor: 0.25 s wall / 25 MB RSS (interpreter + librosa/numba) — so the
real-mix peak of 1.47 GB is genuine analysis headroom (CQT over long audio),
not library overhead. Ingest of a 6.5-min song: **7.0 s**, producing the
75.2 MB WAV (the network stream itself is compressed and smaller; the WAV is
the on-disk artifact).

The two profiles disagree most on **memory**: synthetic 1-minute fixtures sit
at 230 MB while the 6.5-minute real mix peaks at 1.47 GB — peak RAM scales
with clip length, not per-minute. Capacity planning must use the long-clip
number (~1.5 GB), which is exactly the kind of conclusion estimates get wrong.

## 2. Cost per analysis (computed from the measurements)

For the 6.5-minute real song:

| tier | cost/analysis | derivation |
|---|---|---|
| **LOCAL** (CLI/desktop) | **$0** | user's own CPU/RAM; ~70 s wall |
| **Serverless** (memory-billed) | **$0.0025** | 1.47 GB × 70 s × $0.0000167/Gb·s + 62 s CPU × $0.0000133/vCPU·s |
| **Small VPS** ($4.5/mo, 2 vCPU) | **≈ $0.0004–0.0045** | one box sustains ~42,000 analyses/month at 50 % utilization (CPU-bound math); below ~1,000 analyses/month the flat price dominates: $4.5/1000 = $0.0045 |
| **Storage retention** | $0.0017/analysis/month | 75 MB × $0.023/GB-month — the dominant *recurring* cost if players stay playable |
| **Delivery egress** | $0.0066 per full playback | 75 MB streamed × $0.09/GB — dwarfs compute the moment users actually listen |

Readings:

1. **Compute is cheap; memory is the sizing constraint.** ~$0.003 per analysis
   on serverless, but the 1.5 GB peak rules out small function limits and
   containers below 2 GB.
2. **Retention and egress beat compute.** Keeping one player playable for a
   year costs ~5× the analysis itself; one full playback costs ~2.6× the
   analysis. A real service is an *audio-storage/streaming* cost problem with
   an occasional CPU bill — hence ADR-006's streamed players and the audio-TTL
   mitigation already noted in spec §28.
3. **A single $4.5 VPS is ~40k analyses/month of headroom** — the project is
   nowhere near needing horizontal scale (consistent with ADR-007's in-memory
   stance).

## 3. LOCAL vs CLOUD — the decision

The measured numbers say: analysis cost is negligible at every scale this
project will realistically touch in v1.x; the binding constraints are
**memory per worker (~1.5 GB)** and **audio storage/streaming**. The plan's
two architectures therefore resolve to:

- **LOCAL (desktop/CLI) — the default and current product.** $0 per analysis,
  no audio custody (user analyzes what they already possess), no ToS exposure,
  no infra. This is where 100 % of current usage lives.
- **CLOUD (API → worker → analysis) — deferred until product demand exists.**
  When needed: one small worker per ~1.5 GB RAM slice, audio with a TTL,
  streamed playback, SQLite job store (§21). Entrypoint sizing: a $4.5 VPS
  already covers ~40k analyses/month.

Full reasoning and revisit triggers: [ADR-008](ADR/ADR-008-local-vs-cloud.md).

## 4. Reproducing these numbers

```bash
.venv/bin/harmony-bench --synthetic axis_c_major                 # quick CPU/RAM row
.venv/bin/harmony-bench --synthetic                              # full synthetic set
.venv/bin/harmony-bench --wav /path/to/song.wav                  # a real mix
.venv/bin/harmony-bench --url "https://youtube.com/watch?v=…"    # + network ingest
```
