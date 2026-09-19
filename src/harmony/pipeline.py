"""End-to-end harmony analysis pipeline."""
from __future__ import annotations

import time

import numpy as np

from . import bass, chroma, chords, function, ingest, rhythm, voicing
from .models import AnalysisResult, Chord


def analyze(source: str, verbose: bool = False, keep_audio: bool = False) -> AnalysisResult:
    """Analyze a song from a URL or file path and return the full result.

    keep_audio: if True, the local audio file backing the analysis is
    referenced in the result (AnalysisResult.audio_path) so the HTML player
    can embed it for playback sync.
    """
    t0 = time.time()

    path, title, resolved_source = ingest.resolve(source)
    if verbose:
        print(f"[{time.time() - t0:5.1f}s] loaded: {path}")

    y, sr = chroma.load_audio(path)
    duration = len(y) / sr
    title = ingest.best_title(path, source, title)

    features = chroma.extract_features(y, sr)
    if verbose:
        print(f"[{time.time() - t0:5.1f}s] features: chroma {features.chroma.shape}")

    tempo = None  # beat tracking is optional; template/Viterbi is tempo-adaptive
    raw = chords.viterbi_chords(features.recognition_chroma, features.times, tempo)
    if verbose:
        print(f"[{time.time() - t0:5.1f}s] chord decoding: {len(raw)} segments")

    times = features.times
    chord_objs = [
        Chord(
            start=float(times[s.start_frame]),
            end=float(times[min(s.end_frame, len(times) - 1)]),
            root_pc=s.root_pc,
            quality=s.quality,
            confidence=s.confidence,
        )
        for s in raw
    ]
    _snap_boundaries(chord_objs, features.recognition_chroma, times)

    # Post-processing: inversions, voicing, functional analysis.
    bass.label_inversions(chord_objs, features, times)
    for c in chord_objs:
        c.voicing = voicing.analyze_voicing(c, features, times)
    key = function.detect_key(chord_objs)
    function.annotate_functions(chord_objs, key)

    # Rhythmic analysis: beat grid + meter; chords get bar/beat placement.
    rhythm_info = None
    try:
        rhythm_info = rhythm.analyze_rhythm(y, sr)
    except Exception:
        rhythm_info = None  # non-percussive / rubato material: no grid
    if rhythm_info is not None:
        rhythm.align_chords_to_beats(chord_objs, rhythm_info)

    return AnalysisResult(
        title=title,
        source=resolved_source,
        duration=duration,
        key=key,
        chords=chord_objs,
        tempo=rhythm_info.tempo if rhythm_info else None,
        rhythm=rhythm_info,
        audio_path=path if keep_audio else None,
    )


def _snap_boundaries(chord_objs: list[Chord], chroma: np.ndarray, times: np.ndarray,
                     window: float = 0.3) -> None:
    """Refine segment boundaries to local maxima of chroma flux.

    The Viterbi decoder snaps to its frame grid; the true harmonic change
    often lands a few frames away. Chroma flux (positive spectral change)
    peaks exactly where the harmony changes.
    """
    if len(chord_objs) < 2 or chroma.shape[1] < 3:
        return
    diff = np.diff(chroma, axis=1)
    flux = np.maximum(diff, 0).sum(axis=0)  # flux[i] = change into frame i+1
    frame_dt = float(np.median(np.diff(times)))
    radius = max(1, int(window / frame_dt))

    for i in range(len(chord_objs) - 1):
        boundary_t = chord_objs[i].end
        b_frame = int(round(boundary_t / frame_dt))
        lo = max(1, b_frame - radius)
        hi = min(len(flux), b_frame + radius + 1)
        if hi <= lo:
            continue
        best = lo + int(np.argmax(flux[lo:hi]))
        new_t = float(times[best])
        # Keep the change small and segments non-degenerate.
        if abs(new_t - boundary_t) <= window and new_t - chord_objs[i].start > 0.1 \
                and chord_objs[i + 1].end - new_t > 0.1:
            chord_objs[i].end = new_t
            chord_objs[i + 1].start = new_t
