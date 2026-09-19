"""Rhythmic analysis: beat grid, meter/downbeat estimation, chord-beat alignment.

This is the second stage of the analysis: the harmonic stage says *what*
is played and when; this stage says *where in the bar* it happens, so chords
can be reported as "bar 12, beat 2" and the UI can pulse along with the song.
"""
from __future__ import annotations

import numpy as np
import librosa

from .models import Chord, RhythmInfo

HOP = 512  # keep in sync with chroma.py


def analyze_rhythm(y: np.ndarray, sr: int) -> RhythmInfo | None:
    """Estimate tempo, beat grid and meter from the full mix.

    Returns None when the material is not beat-tracked well enough (ambient,
    rubato, non-percussive solo piano with no clear pulse) — callers should
    treat rhythm as 'unknown' rather than guessing.
    """
    # Spectral-flux onset envelope on the percussive-emphasized mix: the
    # percussive component sharpens transients (drums, attacks) without
    # losing the harmonic attacks that mark beats in sparse mixes.
    y_p = librosa.effects.percussive(y)
    oenv = librosa.onset.onset_strength(
        y=y_p, sr=sr, hop_length=HOP, aggregate=np.median
    )

    tempo, beat_times = librosa.beat.beat_track(
        onset_envelope=oenv, sr=sr, hop_length=HOP, units="time", sparse=True
    )
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = np.asarray(beat_times, dtype=float)
    if not np.isfinite(tempo) or tempo <= 0 or len(beat_times) < 8:
        return None

    strengths = _beat_strengths(oenv, beat_times)
    if strengths.size == 0 or float(np.median(strengths)) <= 0:
        return None

    meter, downbeats, coherence = _estimate_meter(beat_times, strengths)
    if meter == 1 and coherence < 0.15:
        return None  # no trustworthy bar structure

    return RhythmInfo(
        tempo=round(tempo, 1),
        meter=meter,
        beat_times=[round(float(t), 3) for t in beat_times],
        beat_strengths=[round(float(s), 4) for s in strengths],
        downbeats=[int(i) for i in downbeats],
        confidence=round(float(coherence), 3),
    )


def _onset_at(oenv: np.ndarray, t: float, sr: int, radius: int = 1) -> float:
    """Onset-envelope value nearest to time t (max within +-radius frames)."""
    frame = int(round(t * sr / HOP))
    lo, hi = max(0, frame - radius), min(len(oenv), frame + radius + 1)
    if hi <= lo:
        return 0.0
    return float(oenv[lo:hi].max())


def _beat_strengths(oenv: np.ndarray, beat_times: np.ndarray) -> np.ndarray:
    return np.array(
        [_onset_at(oenv, t, sr=22050) for t in beat_times], dtype=float
    )


def _estimate_meter(
    beat_times: np.ndarray, strengths: np.ndarray
) -> tuple[int, list[int], float]:
    """Pick the meter whose downbeat grid aligns with the strongest beats.

    For each candidate meter m in 2..7 and each phase offset o in 0..m-1,
    score = mean strength of beats at positions (o, o+m, o+2m, ...) divided
    by the overall mean strength. Rules that keep this honest:

    - a candidate needs at least 3 downbeat samples (sparse meters on short
      excerpts otherwise win by variance)
    - downbeats must be at least 10% stronger than the average beat
      (score >= 1.10), else there is no trustworthy bar structure
    - near-ties resolve to the simplest meter (3/4 doubling is 6/8-like 6,
      not a "genuine" 6)
    """
    n = len(strengths)
    mean = float(strengths.mean())
    if mean <= 0 or n < 8:
        return 1, [], 0.0

    candidates: list[tuple[float, int, int]] = []  # (score, meter, phase)
    for m in (2, 3, 4, 5, 6, 7):
        for o in range(m):
            idx = np.arange(o, n, m)
            if len(idx) < 3:
                continue
            score = float(strengths[idx].mean()) / mean
            candidates.append((score, m, o))
    if not candidates:
        return 1, [], 0.0

    best_score = max(c[0] for c in candidates)
    if best_score < 1.10:
        return 1, [], 0.0  # no meaningful accent hierarchy

    # Simplest meter within 5% of the best score wins.
    candidates.sort(key=lambda c: (c[1], -c[0]))
    for score, m, o in candidates:
        if score >= best_score * 0.95:
            downbeats = list(range(o, n, m))
            lift = score - 1.0
            coherence = float(min(1.0, max(0.0, lift)))
            return m, downbeats, coherence

    score, m, o = max(candidates, key=lambda c: c[0])
    downbeats = list(range(o, n, m))
    return m, downbeats, float(min(1.0, max(0.0, score - 1.0)))


def align_chords_to_beats(
    chords: list[Chord], rhythm: RhythmInfo, tol_beats: float = 0.16
) -> None:
    """Snap chord boundaries to the beat grid and annotate rhythmic placement.

    Fills, per chord: beats (count), beat_fraction (exact length in beats),
    bar / beat_in_bar (position of its first beat), and pushed (True when the
    chord enters off the grid — an anticipation/syncopation).
    """
    if not chords or not rhythm.beat_times:
        return
    beats = np.asarray(rhythm.beat_times, dtype=float)
    spb = 60.0 / max(rhythm.tempo, 1e-6)
    tol = tol_beats * spb

    # --- snap interior boundaries to the nearest beat when close ----------
    for i in range(len(chords) - 1):
        t = chords[i].end
        j = int(np.searchsorted(beats, t))
        cand = [k for k in (j - 1, j) if 0 <= k < len(beats)]
        if not cand:
            continue
        k = min(cand, key=lambda k: abs(beats[k] - t))
        new_t = float(beats[k])
        if abs(new_t - t) <= tol and chords[i].end - chords[i].start > 0.12 \
                and chords[i + 1].end - chords[i + 1].start > 0.12:
            chords[i].end = new_t
            chords[i + 1].start = new_t

    # --- annotate each chord ---------------------------------------------
    for c in chords:
        c.beat_fraction = round(c.duration / spb, 2)
        # first beat at-or-after start (the beat the chord lands on / pushes to)
        j = int(np.searchsorted(beats, c.start - 1e-6))
        prev_idx = j - 1 if j > 0 else 0
        on_beat = j < len(beats) and abs(beats[j] - c.start) <= tol
        if on_beat:
            idx = j
            c.pushed = False
        else:
            idx = prev_idx
            # off-grid entry: it anticipates the next beat
            c.pushed = bool(j < len(beats) and (beats[j] - c.start) <= 0.5 * spb)
        bar, beat = rhythm.bar_beat(idx)
        c.bar, c.beat_in_bar = bar, beat
        # count grid beats that fall inside [start, end): the beat landing
        # exactly on start counts, the one at end belongs to the next chord
        c.beats = int(np.searchsorted(beats, c.end - 1e-6)
                      - np.searchsorted(beats, c.start - 1e-6))
        if c.beats < 0:
            c.beats = 0
