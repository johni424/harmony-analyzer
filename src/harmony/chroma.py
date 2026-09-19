"""Audio feature extraction for the harmony analyzer.

Produces:
- a time-pitch-class matrix ("chroma") for chord recognition
- a bass-weighted chroma for inversion detection
- a normalized log-frequency magnitude matrix for voicing analysis
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import librosa

TARGET_SR = 22050
HOP = 512  # ~23ms at 22050 Hz
N_OCTAVES = 7


@dataclass
class Features:
    chroma: np.ndarray  # (12, T) pitch-class energy over time
    recognition_chroma: np.ndarray  # (12, T) mid-register weighted, for chord decoding
    bass_chroma: np.ndarray  # (12, T) low-register pitch-class energy
    cqt_norm: np.ndarray  # (84, T) per-bin CQT magnitudes, normalized per frame
    times: np.ndarray  # (T,) frame times in seconds
    tempo: float | None


def load_audio(path: str) -> tuple[np.ndarray, int]:
    y, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    return y, sr


def extract_features(y: np.ndarray, sr: int, tempo: float | None = None) -> Features:
    """Compute chroma, bass chroma and normalized CQT from a mono waveform."""
    # Suppress percussive content: analyze the harmonic component mostly.
    y_h, y_p = librosa.effects.hpss(y)
    y = y_h + 0.25 * y_p  # keep a small percussive bleed for realism

    fmin = librosa.note_to_hz("C1")  # 32.7 Hz
    # 3 bins per semitone: with only 12 bins/octave the CQT filter bandwidth
    # at low-mid frequencies is as wide as a semitone, so notes leak heavily
    # into their neighbors (B3 -> C4). Higher-Q filters + max-folding give
    # sharp pitch peaks.
    bpo = 36
    cqt = np.abs(
        librosa.cqt(y, sr=sr, fmin=fmin, n_bins=N_OCTAVES * bpo, bins_per_octave=bpo, hop_length=HOP)
    )

    # Deconvolve the CQT point-spread function. A pure note produces a peak
    # with +-1 subbin skirts at ~50% of the peak (measured; intrinsic to
    # librosa's filter shape, not fixable with more bins). Sharpening with
    # a [-0.5, 1, -0.5] kernel in the sub-bin domain cancels that skirt so
    # a played A no longer fakes a G#/A# (which produced phantom minmaj7
    # chords). Notes genuinely a semitone apart merely dim slightly.
    cqt = np.clip(
        cqt - 0.5 * np.roll(cqt, 1, axis=0) - 0.5 * np.roll(cqt, -1, axis=0),
        0.0,
        None,
    )
    # Zero the roll artifacts at the frequency edges.
    cqt[0] = 0.0
    cqt[-1] = 0.0

    cqt = cqt.reshape(N_OCTAVES * 12, bpo // 12, cqt.shape[1]).max(axis=1)
    times = librosa.frames_to_time(np.arange(cqt.shape[1]), sr=sr, hop_length=HOP)

    # NOTE: deliberately NO harmonic-residual subtraction here. In polyphonic
    # music a "3rd harmonic bin" (root + 19 semitones) is also where a
    # genuinely played note sits; subtracting the fundamental's energy
    # destroys real chord tones (e.g. a loud G2 bass erases a played D4).

    # ---- chroma (pitch-class energy, all octaves) --------------------------
    chroma = np.zeros((12, cqt.shape[1]))
    for oct_idx in range(N_OCTAVES):
        chroma += cqt[oct_idx * 12 : (oct_idx + 1) * 12]

    # ---- recognition chroma (bass octave down-weighted, not excluded) ------
    # The bass carries the root, so it must be present for the decoder, but
    # a full-weight bass fundamental re-roots every chord to the bass note.
    octave_weights = np.array([0.35, 0.55, 0.85, 1.0, 1.0, 0.7, 0.3])
    recognition_chroma = np.zeros((12, cqt.shape[1]))
    for oct_idx in range(N_OCTAVES):
        recognition_chroma += octave_weights[oct_idx] * cqt[oct_idx * 12 : (oct_idx + 1) * 12]

    def _time_median(m: np.ndarray, k: int = 5) -> np.ndarray:
        """Median filter over time: kills frame spikes (splatter, transients)."""
        from scipy.signal import medfilt

        return np.vstack([medfilt(row, kernel_size=k) for row in m])

    recognition_chroma = _time_median(recognition_chroma)

    # ---- bass chroma (octaves C2-B3, low register where roots/bass sit) ---
    bass_chroma = np.zeros((12, cqt.shape[1]))
    for oct_idx in range(1, 3):  # C2-B2 and C3-B3
        bass_chroma += cqt[oct_idx * 12 : (oct_idx + 1) * 12]

    # ---- per-frame normalized CQT (robust against overall loudness) -------
    norms = np.linalg.norm(cqt, axis=0, keepdims=True)
    norms[norms == 0] = 1.0
    cqt_norm = cqt / norms

    return Features(
        chroma=chroma,
        recognition_chroma=recognition_chroma,
        bass_chroma=bass_chroma,
        cqt_norm=cqt_norm,
        times=times,
        tempo=tempo,
    )
