"""Evaluation harness (plan step 25): ground-truth scoring of the analyzer.

Two dataset layers (see datasets/ and docs/EVALUATION.md):

- **synthetic** — cases rendered to audio at eval time from exact specs;
  ground truth is the spec itself (no licensing issues, hermetic).
- **real songs** — a hand-checked manifest (title/URL/key/progression/
  inversions/tempo); audio is fetched on demand via yt-dlp and cached in a
  temp dir, never committed.

Metrics follow docs/EVALUATION.md: overlap-weighted chord (root+quality)
accuracy, root-only accuracy, bass agreement where the reference states one,
boundary precision, tempo validity (±4 % with ×2/×½ octave allowance), meter,
key, and confidence calibration (per-bucket empirical correctness + Brier).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .models import AnalysisResult, pc_from_name
from .pipeline import analyze

SR = 22050

# --------------------------------------------------------------------------- #
#  Reference model
# --------------------------------------------------------------------------- #


@dataclass
class RefChord:
    """One ground-truth chord span (start/duration in seconds OR beats)."""

    symbol: str  # e.g. "C", "G/B", "Fmaj7" — parsed into root/quality/bass
    start: float  # seconds (already resolved from beats if needed)
    duration: float
    bass: str | None = None  # explicit reference bass note name ("B" in G/B)


@dataclass
class RefCase:
    """One evaluation case: id, tags, ground truth, optional audio spec."""

    id: str
    kind: str  # "synthetic" | "real"
    genre: str
    key: str  # e.g. "C major"
    key_alt: list[str] = field(default_factory=list)  # acceptable alternates (e.g. relative key)
    tempo: float | None = None  # BPM (felt tempo)
    meter: int | None = None
    chords: list[RefChord] = field(default_factory=list)
    # synthetic rendering spec (kind == "synthetic"):
    render: dict | None = None  # {chords: [{tones, bass, start_beat, dur_beats}], bpm, meter}
    # real-song fields (kind == "real"):
    source: str | None = None  # URL
    artist: str | None = None
    checked: str | None = None  # e.g. "hand-checked 2026-09"

    @property
    def duration(self) -> float:
        return max((c.start + c.duration for c in self.chords), default=0.0)


@dataclass
class CaseScore:
    """Metrics for one case."""

    case_id: str
    genre: str
    n_ref: int
    n_detected: int
    chord_accuracy: float  # overlap-weighted (root, quality) agreement
    family_accuracy: float  # root + quality-family (7th/triad tolerance)
    root_accuracy: float  # overlap-weighted root-only agreement
    bass_accuracy: float | None  # where reference states a bass note
    boundary_median: float | None  # |ref boundary − nearest detected| (s)
    boundary_within_250ms: float | None
    tempo_ok: bool | None
    tempo_ratio: float | None  # detected / reference (after octave folding: 1.0 = exact)
    meter_ok: bool | None
    key_ok: bool
    brier: float | None  # mean (confidence − correct)² over ref-covered time
    analysis_seconds: float
    audio_seconds: float


# --------------------------------------------------------------------------- #
#  Chord-symbol parsing (reference side)
# --------------------------------------------------------------------------- #

_SUFFIX_PCS = {
    "": (0, 4, 7), "maj7": (0, 4, 7, 11), "m": (0, 3, 7), "m7": (0, 3, 7, 10),
    "7": (0, 4, 7, 10), "dim": (0, 3, 6), "dim7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10), "aug": (0, 4, 8), "sus4": (0, 5, 7), "sus2": (0, 2, 7),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "maj9": (0, 4, 7, 11, 14 % 12),
}

# MIREX-style extension tolerance: a detected triad under a referenced 7th
# (or vice versa) counts as family-correct but not strictly correct.
_QUALITY_FAMILY = {
    "maj7": "maj", "7": "maj", "maj9": "maj", "maj6": "maj",
    "min7": "min", "min6": "min", "m7b5": "dim", "dim7": "dim", "hdim7": "dim",
    "7sus4": "sus4",
}


def quality_family(q: str) -> str:
    return _QUALITY_FAMILY.get(q, q)


def parse_symbol(symbol: str) -> tuple[int, str, int | None]:
    """'G/B' → (root_pc, quality, bass_pc); 'C' → (0, 'maj', None)."""
    symbol = symbol.strip()
    bass = None
    if "/" in symbol:
        symbol, bass_name = symbol.split("/", 1)
        bass = pc_from_name(bass_name.strip())
    root_name = symbol[0] + ("#" if symbol[1:2] == "#" else "b" if symbol[1:2] == "b" else "")
    root = pc_from_name(root_name)
    suffix = symbol[len(root_name):]
    if suffix not in _SUFFIX_PCS:
        raise ValueError(f"unknown reference suffix {suffix!r} in {symbol!r}")
    quality = {"": "maj", "m": "min", "m7": "min7", "m9": "min9",
               "m11": "min11", "m13": "min13", "m6": "min6",
               "6": "maj6", "maj9": "maj9", "m7b5": "hdim7"}.get(suffix, suffix)
    return root, quality, bass


# --------------------------------------------------------------------------- #
#  Synthetic rendering (ground truth → audio)
# --------------------------------------------------------------------------- #


def _tone(freq: float, dur: float, amp: float = 0.2) -> np.ndarray:
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t)
    fade = int(0.01 * SR)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return amp * wave


def _note(name: str, octave: int, dur: float, amp: float = 0.2) -> np.ndarray:
    midi = 12 * (octave + 1) + pc_from_name(name)
    return _tone(440.0 * 2 ** ((midi - 69) / 12), dur, amp)


def _click(dur: float = 0.03, amp: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(7)
    n = int(SR * dur)
    return amp * rng.standard_normal(n) * np.exp(-np.linspace(0, 60, n))


# Per-beat click emphasis mimicking a drum groove: kick on 1 (and 3), snare
# on the backbeats. Uniform clicks cannot disambiguate meter; this pattern
# can (docs/EVALUATION.md §method).
_GROOVE = {
    2: [1.0, 0.5],
    3: [1.0, 0.5, 0.5],
    4: [1.0, 0.55, 0.75, 0.55],
    5: [1.0, 0.5, 0.6, 0.5, 0.5],
    6: [1.0, 0.5, 0.5, 0.75, 0.5, 0.5],
    7: [1.0, 0.5, 0.5, 0.6, 0.5, 0.5, 0.5],
}


def render_case(case: RefCase) -> np.ndarray:
    """Render a synthetic case: chord tones + bass + optional drum clicks."""
    spec = case.render or {}
    bpm = spec.get("bpm") or case.tempo or 120.0
    meter = spec.get("meter") or case.meter or 4
    with_clicks = bool(spec.get("clicks", True))
    total = case.duration + 1.0
    song = np.zeros(int(SR * total))
    sec_per_beat = 60.0 / bpm

    for rc in spec.get("chords", []):
        start = rc["start_beat"] * sec_per_beat
        dur = rc["dur_beats"] * sec_per_beat
        i0 = int(start * SR)
        seg = np.zeros(int(dur * SR))
        for tone in rc["tones"]:
            seg += _note(tone, 4, dur)
        bass_note = rc.get("bass") or rc["tones"][0]
        # Keyboard-style reinforcement: root position doubles the root an
        # octave up; an INVERTED chord reinforces the sounding bass instead
        # (a pianist playing C/E does not double C below the E) — otherwise
        # the fixture contradicts its own inversion ground truth.
        mid = bass_note if bass_note != rc["tones"][0] else rc["tones"][0]
        seg += _note(mid, 3, dur, amp=0.25)
        seg += _note(bass_note, 2, dur, amp=0.3)
        song[i0:i0 + len(seg)] += seg

    if with_clicks:
        groove = _GROOVE.get(meter, [1.0] + [0.5] * (meter - 1))
        n_beats = int(total / sec_per_beat)
        for b in range(n_beats):
            i0 = int(b * sec_per_beat * SR)
            click = _click(amp=0.6 * groove[b % meter])
            song[i0:i0 + len(click)] += click

    peak = np.abs(song).max() or 1.0
    return (song / peak * 0.9).astype(np.float32)


# --------------------------------------------------------------------------- #
#  Scoring
# --------------------------------------------------------------------------- #


def _detected_timeline(result: AnalysisResult) -> list[tuple[float, float, int, str, int | None]]:
    """[(start, end, root_pc, quality, bass_pc)] for every detected segment."""
    return [(c.start, c.end, c.root_pc, c.quality, c.bass_pc) for c in result.chords]


def _coverage(ref: RefChord, timeline, match) -> float:
    """Fraction of the reference span covered by detected segments passing `match`."""
    r0, r1 = ref.start, ref.start + ref.duration
    covered = 0.0
    for d0, d1, root, quality, bass in timeline:
        lo, hi = max(r0, d0), min(r1, d1)
        if hi <= lo:
            continue
        if match(root, quality, bass):
            covered += hi - lo
    return min(covered / ref.duration, 1.0) if ref.duration > 0 else 0.0


def score_case(case: RefCase, result: AnalysisResult, analysis_seconds: float) -> CaseScore:
    timeline = _detected_timeline(result)
    ref_root, ref_quality, ref_bass = zip(*(parse_symbol(c.symbol) for c in case.chords))

    w = np.array([c.duration for c in case.chords])
    chord_acc = float(np.average([
        _coverage(c, timeline, lambda r, q, b, R=rt, Q=qt: r == R and q == Q)
        for c, rt, qt in zip(case.chords, ref_root, ref_quality)], weights=w))
    family_acc = float(np.average([
        _coverage(c, timeline,
                  lambda r, q, b, R=rt, F=quality_family(qt): r == R and quality_family(q) == F)
        for c, rt, qt in zip(case.chords, ref_root, ref_quality)], weights=w))
    root_acc = float(np.average([
        _coverage(c, timeline, lambda r, q, b, R=rt: r == R)
        for c, rt in zip(case.chords, ref_root)], weights=w))

    bass_idx = [i for i, b in enumerate(ref_bass) if b is not None]
    bass_acc = None
    if bass_idx:
        bw = np.array([case.chords[i].duration for i in bass_idx])
        bass_acc = float(np.average([
            _coverage(case.chords[i], timeline, lambda r, q, b, B=ref_bass[i]: b == B)
            for i in bass_idx], weights=bw))

    ref_bounds = sorted({c.start for c in case.chords} - {0.0})
    det_bounds = [c.start for c in result.chords[1:]]
    b_med = b_within = None
    if ref_bounds and det_bounds:
        dists = np.array([min(abs(rb - db) for db in det_bounds) for rb in ref_bounds])
        b_med = float(np.median(dists))
        b_within = float(np.mean(dists <= 0.25))

    tempo_ok = tempo_ratio = meter_ok = None
    if case.tempo and result.tempo:
        ratio = result.tempo / case.tempo
        for fold in (1.0, 2.0, 0.5):
            if abs(ratio * (1 / fold) - 1.0) <= 0.04:
                tempo_ratio = ratio / fold
                tempo_ok = True
                break
        else:
            tempo_ratio = ratio
            tempo_ok = False
    if case.meter and result.rhythm is not None:
        meter_ok = result.rhythm.meter == case.meter

    tonic, mode = case.key.split()
    from .models import pitch_name

    def key_matches(name: str) -> bool:
        t, m = name.split()
        return pitch_name(result.key.tonic_pc) == t and result.key.mode == m

    key_ok = key_matches(case.key) or any(key_matches(a) for a in case.key_alt)

    # Confidence calibration: per reference chord, coverage-weighted correctness
    # vs. the mean predicted confidence of detected material overlapping it.
    brier_terms: list[tuple[float, float]] = []  # (weight, (conf − correct)²)
    for c, rt, qt in zip(case.chords, ref_root, ref_quality):
        r0, r1 = c.start, c.start + c.duration
        overlaps = [(min(r1, d1) - max(r0, d0), conf)
                    for (d0, d1, r, q, b), conf in
                    zip(timeline, [ch.confidence for ch in result.chords])]
        overlaps = [(ov, conf) for ov, conf in overlaps if ov > 0]
        if not overlaps:
            continue
        correct = _coverage(c, timeline, lambda r, q, b, R=rt, Q=qt: r == R and q == Q)
        conf = sum(ov * conf for ov, conf in overlaps) / sum(ov for ov, _ in overlaps)
        brier_terms.append((c.duration, (conf - correct) ** 2))
    brier = (sum(wt * e for wt, e in brier_terms) / sum(wt for wt, _ in brier_terms)
             if brier_terms else None)

    return CaseScore(
        case_id=case.id, genre=case.genre, n_ref=len(case.chords),
        n_detected=len(result.chords), chord_accuracy=chord_acc,
        family_accuracy=family_acc, root_accuracy=root_acc, bass_accuracy=bass_acc,
        boundary_median=b_med, boundary_within_250ms=b_within,
        tempo_ok=tempo_ok, tempo_ratio=tempo_ratio, meter_ok=meter_ok,
        key_ok=key_ok, brier=brier, analysis_seconds=analysis_seconds,
        audio_seconds=case.duration,
    )


# --------------------------------------------------------------------------- #
#  Runner + CLI
# --------------------------------------------------------------------------- #


def run_case(case: RefCase, work_dir: Path | None = None) -> CaseScore:
    """Analyze one case and score it."""
    if case.kind == "synthetic":
        audio = render_case(case)
        tmp = Path(tempfile.mkdtemp(prefix="harmony_eval_")) if work_dir is None else work_dir
        wav = tmp / f"{case.id}.wav"
        try:
            import soundfile as sf
            sf.write(wav, audio, SR)
            t0 = time.time()
            result = analyze(str(wav), verbose=False)
            return score_case(case, result, time.time() - t0)
        finally:
            if work_dir is None:
                wav.unlink(missing_ok=True)
    elif case.kind == "real":
        if not case.source:
            raise ValueError(f"real case {case.id!r} has no source URL")
        t0 = time.time()
        result = analyze(case.source, verbose=False)
        return score_case(case, result, time.time() - t0)
    raise ValueError(f"unknown case kind {case.kind!r}")


def load_dataset(path: Path) -> list[RefCase]:
    """Load a dataset manifest (JSON list of case dicts)."""
    out: list[RefCase] = []
    for raw in json.loads(Path(path).read_text(encoding="utf-8")):
        chords = [RefChord(**c) for c in raw.get("chords", [])]
        out.append(RefCase(
            id=raw["id"], kind=raw["kind"], genre=raw.get("genre", "unknown"),
            key=raw["key"], key_alt=raw.get("key_alt", []),
            tempo=raw.get("tempo"), meter=raw.get("meter"),
            chords=chords, render=raw.get("render"), source=raw.get("source"),
            artist=raw.get("artist"), checked=raw.get("checked"),
        ))
    return out


def aggregate(scores: list[CaseScore]) -> dict:
    """Dataset-level summary + per-genre buckets."""
    def bucket(rows: list[CaseScore]) -> dict:
        n = len(rows)
        return {
            "n": n,
            "chord_accuracy": round(float(np.mean([s.chord_accuracy for s in rows])), 4) if n else None,
            "family_accuracy": round(float(np.mean([s.family_accuracy for s in rows])), 4) if n else None,
            "root_accuracy": round(float(np.mean([s.root_accuracy for s in rows])), 4) if n else None,
            "bass_accuracy": (lambda v: round(float(np.mean(v)), 4) if v else None)(
                [s.bass_accuracy for s in rows if s.bass_accuracy is not None]),
            "tempo_ok": sum(1 for s in rows if s.tempo_ok) / n if n else None,
            "meter_ok": (lambda v: sum(v) / len(v) if v else None)(
                [s.meter_ok for s in rows if s.meter_ok is not None]),
            "key_ok": sum(1 for s in rows if s.key_ok) / n if n else None,
            "brier": (lambda v: round(float(np.mean(v)), 4) if v else None)(
                [s.brier for s in rows if s.brier is not None]),
            "sec_per_audio_min": round(float(np.mean(
                [s.analysis_seconds / s.audio_seconds * 60 for s in rows
                 if s.audio_seconds > 0])), 2) if n else None,
        }

    genres = sorted({s.genre for s in scores})
    return {
        "overall": bucket(scores),
        "by_genre": {g: bucket([s for s in scores if s.genre == g]) for g in genres},
    }


def report_markdown(scores: list[CaseScore], agg: dict, dataset: str) -> str:
    lines = [
        f"# Evaluation — {dataset}", "",
        f"Cases: {len(scores)} · overall chord accuracy "
        f"{agg['overall']['chord_accuracy']}", "",
        "| case | genre | chord | family | root | bass | key | tempo | meter | brier | s/min audio |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.case_id} | {s.genre} | {s.chord_accuracy:.2f} | {s.family_accuracy:.2f} | {s.root_accuracy:.2f} "
            f"| {'—' if s.bass_accuracy is None else f'{s.bass_accuracy:.2f}'} "
            f"| {'✓' if s.key_ok else '✗'} "
            f"| {'—' if s.tempo_ok is None else ('✓' if s.tempo_ok else '✗')} "
            f"| {'—' if s.meter_ok is None else ('✓' if s.meter_ok else '✗')} "
            f"| {'—' if s.brier is None else f'{s.brier:.3f}'} "
            f"| {s.analysis_seconds / s.audio_seconds * 60:.0f} |")
    lines += ["", "## By genre", "", "| genre | n | chord | family | root | bass | brier |", "|---|---|---|---|---|---|---|"]
    for g, b in agg["by_genre"].items():
        lines.append(
            f"| {g} | {b['n']} | {b['chord_accuracy']} | {b['family_accuracy']} | {b['root_accuracy']} "
            f"| {b['bass_accuracy'] or '—'} | {b['brier'] or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the harmony evaluation dataset")
    parser.add_argument("dataset", help="Path to a dataset manifest JSON")
    parser.add_argument("--out", default=None, help="Output prefix (writes .json and .md)")
    parser.add_argument("--case", default=None, help="Run a single case id")
    parser.add_argument("--fetch", action="store_true",
                        help="Allow real-song cases (yt-dlp fetch); default: synthetic only")
    args = parser.parse_args()

    cases = load_dataset(Path(args.dataset))
    if args.case:
        cases = [c for c in cases if c.id == args.case]
    if not args.fetch:
        skipped = [c.id for c in cases if c.kind == "real"]
        if skipped:
            print(f"skipping real-song cases (use --fetch): {', '.join(skipped)}")
        cases = [c for c in cases if c.kind != "real"]
    if not cases:
        print("nothing to run", file=sys.stderr)
        raise SystemExit(1)

    scores = []
    for case in cases:
        print(f"[{case.kind}] {case.id} …", flush=True)
        try:
            scores.append(run_case(case))
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    agg = aggregate(scores)
    dataset_name = Path(args.dataset).stem
    print(json.dumps(agg, indent=2))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(
            {"dataset": dataset_name, "aggregate": agg,
             "cases": [s.__dict__ | {} for s in scores]}, indent=2, default=str))
        out.with_suffix(".md").write_text(report_markdown(scores, agg, dataset_name))
        print(f"wrote {out.with_suffix('.json')} and {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
