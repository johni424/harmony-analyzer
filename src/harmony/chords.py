"""Chord recognition: template matching + Viterbi decoding over chroma frames."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Interval structure (semitones above root) and per-tone weights for each
# quality we recognize. The root is weighted 1.3: real chords emphasize their
# root, and this disambiguates identical pitch-class sets (Dm7 vs Fmaj6).
QUALITY_INTERVALS: dict[str, tuple[tuple[int, float], ...]] = {
    "maj": ((0, 1.3), (4, 1.0), (7, 0.8)),
    "min": ((0, 1.3), (3, 1.0), (7, 0.8)),
    "dim": ((0, 1.3), (3, 1.0), (6, 0.7)),
    "aug": ((0, 1.3), (4, 1.0), (8, 0.7)),
    "sus4": ((0, 1.3), (5, 0.9), (7, 0.8)),
    "sus2": ((0, 1.3), (2, 0.9), (7, 0.8)),
    "maj7": ((0, 1.3), (4, 1.0), (7, 0.8), (11, 0.8)),
    "min7": ((0, 1.3), (3, 1.0), (7, 0.8), (10, 0.8)),
    "7": ((0, 1.3), (4, 1.0), (7, 0.8), (10, 0.8)),
    "hdim7": ((0, 1.3), (3, 1.0), (6, 0.8), (10, 0.7)),
    "dim7": ((0, 1.3), (3, 1.0), (6, 0.8), (9, 0.7)),
    "minmaj7": ((0, 1.3), (3, 1.0), (7, 0.8), (11, 0.7)),
    "maj6": ((0, 1.3), (4, 0.9), (7, 0.8), (9, 0.8)),
    "min6": ((0, 1.3), (3, 0.9), (7, 0.8), (9, 0.8)),
    "7sus4": ((0, 1.3), (5, 0.9), (7, 0.8), (10, 0.8)),
}
LEAK = 0.03
N_CHORDQualITIES = len(QUALITY_INTERVALS)


@dataclass
class RawSegment:
    """Frame-index based segment before time snapping."""

    root_pc: int
    quality: str
    start_frame: int
    end_frame: int  # exclusive
    confidence: float


def build_emission_matrix(qualities: list[str] | None = None) -> tuple[np.ndarray, list[tuple[int, str]]]:
    """Return (emission weights, state list).

    Emission matrix E has shape (n_states, 12); rows are L2-normalized so
    that E @ chroma_norm gives cosine similarity per state (L2 normalization
    keeps 4-note qualities competitive with triads).
    """
    if qualities is None:
        qualities = list(QUALITY_INTERVALS)
    states: list[tuple[int, str]] = []
    rows: list[np.ndarray] = []
    for root in range(12):
        for quality in qualities:
            w = np.full(12, LEAK)
            for interval, weight in QUALITY_INTERVALS[quality]:
                w[(root + interval) % 12] += weight
                # Spectral spill: CQT windows leak ~10% amplitude into the
                # neighboring semitone bins. Modeling this stops phantom
                # extensions (e.g. G# leaking from A -> fake minmaj7).
                w[(root + interval - 1) % 12] += 0.12 * weight
                w[(root + interval + 1) % 12] += 0.12 * weight
                # Harmonic spill: real instruments' harmonics paint phantom
                # pitch classes. A played note adds energy a fifth above
                # (+19 st = 3rd harmonic, folds to +7) and a major third
                # above two octaves (+28 st = 5th harmonic, folds to +4).
                # Unmodeled, the 3rd of a triad fakes the 7th (G's B -> F#
                # makes every G look like Gmaj7; measured on real mixes:
                # 3rd harmonic ~0.30 of the fundamental, 5th ~0.12).
                w[(root + interval + 7) % 12] += 0.30 * weight
                w[(root + interval + 4) % 12] += 0.12 * weight
            norm = np.linalg.norm(w)
            if norm == 0:
                norm = 1.0
            rows.append(w / norm)
            states.append((root, quality))
    E = np.vstack(rows)
    return E, states


def _normalize_chroma(chroma: np.ndarray) -> np.ndarray:
    """L2-normalize each frame (cosine scoring); silent frames stay zero."""
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    norms[norms == 0] = 1.0
    return chroma / norms


def viterbi_chords(
    chroma: np.ndarray,
    times: np.ndarray,
    tempo: float | None,
    qualities: list[str] | None = None,
    self_loop_base: float = 0.90,
    max_self_loop: float = 0.965,
) -> list[RawSegment]:
    """Decode the most likely chord sequence with a Viterbi pass.

    Self-loop probability grows with expected segment duration (tempo-aware):
    longer expected chords -> stickier transitions.
    """
    E, states = build_emission_matrix(qualities)
    n_states = len(states)

    # Expected segment length: ~one bar's worth of quarter notes, bounded.
    quarter = 60.0 / tempo if tempo and tempo > 0 else 0.5
    expected_dur = float(np.clip(2 * quarter, 0.5, 4.0))
    frame_dur = float(np.median(np.diff(times))) if len(times) > 1 else 0.023
    frames_per_expected = max(1.0, expected_dur / frame_dur)
    len_bias = min(0.045, 0.045 * np.log1p(frames_per_expected / 20.0) / np.log(2.0))
    self_loop = min(max_self_loop, self_loop_base + len_bias)

    trans = np.full((n_states, n_states), (1.0 - self_loop) / (n_states - 1))
    np.fill_diagonal(trans, self_loop)

    # Rarity prior: in pop/jazz repertoire, triads and 7ths are common while
    # diminished/augmented sonorities are rare. This log-prior tips close
    # calls (G7 vs Bdim on the same chroma) toward the likelier quality.
    _PRIOR = {
        "maj": 0.0, "min": 0.0, "7": -0.03, "maj7": -0.03, "min7": -0.03,
        # Sus sonorities: in pop recordings the "sus note" is usually a sung
        # melody tone (e.g. the 4th over a I chord), not a real suspension.
        # Measured on a real mix: sus labels fired while the sus note sat
        # below 25% relative energy. Keep them clearly rarer than triads.
        "sus4": -0.18, "sus2": -0.18, "maj6": -0.08, "min6": -0.08, "7sus4": -0.2,
        "hdim7": -0.15, "dim": -0.2, "dim7": -0.2, "aug": -0.2, "minmaj7": -0.25,
    }
    log_prior = np.array([_PRIOR.get(q, -0.2) for _, q in states])

    chroma_n = _normalize_chroma(chroma)
    emissions = E @ chroma_n  # (n_states, T)

    # Viterbi
    # Evidence scale: log-emissions are multiplied by this factor so per-frame
    # evidence can outvote transition costs. With cosine emissions bounded in
    # [0,1], log-emission differences are tiny (~0.1 nats) while each chord
    # switch costs 2*log(1/self_loop) ≈ 16 nats — without scaling, Viterbi
    # cannot afford to insert a short correct chord between similar neighbors
    # (measured: C–Am–F–G decoded without Am). 2.0 keeps smoothing effective
    # while letting 10–20 frames of clear evidence win.
    EVIDENCE_SCALE = 2.0
    T = emissions.shape[1]
    log_a = np.log(trans + 1e-12)
    log_e = np.log(emissions + 1e-12) * EVIDENCE_SCALE
    dp = np.full((n_states, T), -np.inf)
    bp = np.zeros((n_states, T), dtype=np.int32)
    dp[:, 0] = log_e[:, 0] + log_prior
    for t in range(1, T):
        # dp[:, t] = log_e[:, t] + prior + max over prev (dp[:, t-1] + log_a)
        scores = dp[:, t - 1][:, None] + log_a  # (n_states, n_states)
        bp[:, t] = np.argmax(scores, axis=0)
        dp[:, t] = log_e[:, t] + log_prior + scores[bp[:, t], np.arange(n_states)]

    # Backtrace
    path = np.zeros(T, dtype=np.int32)
    path[-1] = int(np.argmax(dp[:, -1]))
    for t in range(T - 2, -1, -1):
        path[t] = bp[path[t + 1], t + 1]

    # Per-frame posterior confidence: temperature softmax over the cosine
    # emissions (max-subtracted for numerical stability). Temperature is
    # loose enough that confidences stay meaningfully below 1.0.
    temperature = 0.045
    shifted = emissions - emissions.max(axis=0, keepdims=True)
    exp = np.exp(shifted / temperature)
    posterior = exp / (exp.sum(axis=0, keepdims=True) + 1e-12)

    # Collapse frames into segments.
    segments: list[RawSegment] = []
    run_start = 0
    for t in range(1, T + 1):
        if t == T or path[t] != path[run_start]:
            state_idx = int(path[run_start])
            root, quality = states[state_idx]
            conf = float(posterior[state_idx, run_start:t].mean())
            segments.append(
                RawSegment(
                    root_pc=root,
                    quality=quality,
                    start_frame=run_start,
                    end_frame=t,
                    confidence=conf,
                )
            )
            run_start = t

    return _merge_short_segments(segments, min_duration=0.6)


def _merge_short_segments(segments: list[RawSegment], min_duration: float) -> list[RawSegment]:
    """Merge sub-beat slivers into the preceding segment.

    Transition moments (chord changes) briefly paint the previous chord's
    tail notes, which Viterbi may decode as short wrong chords. Anything
    shorter than `min_duration` seconds is absorbed by its predecessor —
    including a *different* label (the point: kill the sliver, not the
    boundary). Adjacent equal-label segments are then coalesced.
    """
    if not segments:
        return segments
    min_frames = max(2, int(min_duration / 0.023))
    merged = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.end_frame - seg.start_frame < min_frames:
            # Absorb into the previous segment regardless of label.
            prev.end_frame = seg.end_frame
        elif prev.root_pc == seg.root_pc and prev.quality == seg.quality:
            prev.end_frame = seg.end_frame
        else:
            merged.append(seg)
    return merged
