"""Functional harmony analysis: key, roman numerals, devices, and effects."""
from __future__ import annotations

import numpy as np

from .chords import QUALITY_INTERVALS
from .models import Chord, KeyEstimate, pitch_name

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)

# Krumhansl-Kessler key profiles.
_MAJ_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MIN_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Diatonic chord qualities for each scale degree (major key).
_MAJOR_DIATONIC = {0: ("maj", "maj7"), 1: ("min", "min7"), 2: ("min", "min7"), 3: ("maj", "maj7"),
                   4: ("maj", "7"), 5: ("min", "min7"), 6: ("dim", "hdim7")}
_MINOR_DIATONIC = {0: ("min", "min7"), 1: ("dim", "hdim7"), 2: ("maj", "maj7"), 3: ("min", "min7"),
                   4: ("min", "min7"), 5: ("maj", "7"), 6: ("maj", "maj7")}


def detect_key(chords: list[Chord]) -> KeyEstimate:
    """Estimate the global key from duration-weighted chord pitch classes."""
    hist = np.zeros(12)
    for chord in chords:
        if chord.quality == "N":
            continue
        w = np.zeros(12)
        w[chord.root_pc] = 1.0
        for interval, weight in QUALITY_INTERVALS.get(chord.quality, ()):
            w[(chord.root_pc + interval) % 12] += weight
        hist += w * chord.duration

    best = None
    for tonic in range(12):
        for mode, profile in (("major", _MAJ_PROFILE), ("minor", _MIN_PROFILE)):
            # profile_rotated[pc] = profile[(pc - tonic) % 12]
            rotated = np.roll(profile, tonic)
            score = float(np.corrcoef(hist, rotated)[0, 1]) if hist.sum() > 0 else 0.0
            if best is None or score > best[0]:
                best = (score, tonic, mode)
    assert best is not None
    score, tonic, mode = best
    return KeyEstimate(tonic_pc=tonic, mode=mode, confidence=max(0.0, score))


def _diatonic_scale(key: KeyEstimate) -> tuple[int, ...]:
    return MINOR_SCALE if key.mode == "minor" else MAJOR_SCALE


def _degree_of(root_pc: int, key: KeyEstimate) -> tuple[int, int]:
    """Return (degree 0-6, accidental offset -1/0/+1) of a pitch class in the key.

    Exact scale degrees match before chromatic near-misses (F is IV in C,
    not #III).
    """
    scale = _diatonic_scale(key)
    # Pass 1: exact diatonic match wins over any chromatic spelling.
    for degree in range(7):
        if root_pc == (key.tonic_pc + scale[degree]) % 12:
            return degree, 0
    # Tritone pitch: conventionally spelled #IV rather than bV.
    if root_pc == (key.tonic_pc + 6) % 12:
        return 4, 1
    # Pass 2a: flat-side alterations win (Ab -> bVI, Bb -> bVII, Db -> bII)
    # but never for degrees I and V: bI/bV are notational nonsense while
    # the sharp side (#VII leading tone) is the standard spelling.
    for degree in range(7):
        if degree in (0, 4):
            continue
        if root_pc == (key.tonic_pc + scale[degree] - 1) % 12:
            return degree, -1
    # Pass 2b: sharp-side alterations (D# -> #II, G# -> #V).
    for degree in range(7):
        if root_pc == (key.tonic_pc + scale[degree] + 1) % 12:
            return degree, 1
    return 0, (root_pc - key.tonic_pc) % 12  # fallback: treated as altered tonic


_CASE_SUFFIX = {
    "maj": ("U", ""), "min": ("L", ""), "dim": ("L", "°"), "aug": ("U", "+"),
    "maj7": ("U", "maj7"), "min7": ("L", "7"), "7": ("U", "7"), "hdim7": ("L", "ø7"),
    "dim7": ("L", "°7"), "minmaj7": ("L", "maj7"), "maj6": ("U", "6"), "min6": ("L", "6"),
    "sus4": ("U", "sus4"), "sus2": ("U", "sus2"), "7sus4": ("U", "7sus4"),
}
_ROMAN_BASE = ["I", "II", "III", "IV", "V", "VI", "VII"]


def roman_numeral(chord: Chord, key: KeyEstimate) -> str:
    degree, acc = _degree_of(chord.root_pc, key)
    base = _ROMAN_BASE[degree]
    case, suffix = _CASE_SUFFIX.get(chord.quality, ("U", chord.quality))
    numeral = base.upper() if case == "U" else base.lower()
    prefix = "#" if acc > 0 else ("b" if acc < 0 else "")
    return f"{prefix}{numeral}{suffix}"


def _function_of(degree: int) -> str:
    if degree in (0, 2, 5):
        return "tonic"
    if degree in (1, 3):
        return "predominant"
    if degree in (4, 6):
        return "dominant"
    return "modal color"


def _is_diatonic(chord: Chord, key: KeyEstimate) -> bool:
    degree, acc = _degree_of(chord.root_pc, key)
    if acc != 0:
        return False
    table = _MINOR_DIATONIC if key.mode == "minor" else _MAJOR_DIATONIC
    return chord.quality in table.get(degree, ())


def annotate_functions(chords: list[Chord], key: KeyEstimate) -> None:
    """Attach roman numerals, function roles and effect descriptions in place."""
    for chord in chords:
        chord.function = roman_numeral(chord, key)
        degree, acc = _degree_of(chord.root_pc, key)
        chord.role = _function_of(degree)

    n = len(chords)
    for i, chord in enumerate(chords):
        effects: list[str] = []
        nxt = chords[i + 1] if i + 1 < n else None

        # ---- cadence at the very end of the song ---------------------------
        if i == n - 2 and nxt is not None:
            eff = _cadence_effect(chord, nxt, key)
            if eff:
                effects.append(eff)

        # ---- secondary dominants & tritone subs ----------------------------
        if nxt is not None and chord.quality in ("7", "9", "13", "7b9", "7#9", "maj"):
            target_degree, _ = _degree_of(nxt.root_pc, key)
            down_fifth = (nxt.root_pc - chord.root_pc) % 12 == 5
            semitone_above = (chord.root_pc - nxt.root_pc) % 12 == 1
            if chord.quality in ("7", "9", "13", "7b9", "7#9") and down_fifth and _is_diatonic(nxt, key) and chord.root_pc != key.tonic_pc:
                target_rn = roman_numeral(nxt, key).lower() if nxt.quality in ("min", "min7") else roman_numeral(nxt, key)
                chord.function = f"V7/{target_rn}"
                effects.append(f"secondary dominant — builds tension that resolves into {nxt.symbol()}")
            elif chord.quality == "7" and semitone_above:
                chord.function = f"subV7/{roman_numeral(nxt, key)}"
                effects.append(f"tritone substitution — chromatic, slippery approach to {nxt.symbol()}")

        # ---- borrowed chords (modal mixture) --------------------------------
        if not _is_diatonic(chord, key) and chord.quality != "N":
            borrow = _borrowed_effect(chord, key)
            if borrow:
                effects.append(borrow)

        # ---- inversion & bass-line effects ----------------------------------
        inv_eff = _inversion_effect(chord, key, chords[i - 1] if i > 0 else None)
        if inv_eff:
            effects.append(inv_eff)

        # ---- tonal color ------------------------------------------------------
        color = _QUALITY_COLOR.get(chord.quality)
        if color:
            effects.append(color)

        if effects:
            chord.effect = "; ".join(effects)

    _annotate_bass_line(chords)
    _annotate_pickup(chords)
    _annotate_retake(chords)


_QUALITY_COLOR = {
    "maj7": "maj7 color — warm, dreamy, jazz-inflected",
    "min7": "m7 color — mellow, restrained",
    "7": "dominant 7th — bluesy forward drive",
    "hdim7": "half-diminished — suspenseful, unsettled",
    "dim7": "fully diminished — dramatic, cinematic tension",
    "sus4": "suspended — floating, delays resolution",
    "sus2": "suspended 2nd — open, airy",
    "maj6": "added 6th — bittersweet softening of the triad",
    "min6": "m6 — bittersweet minor color",
    "aug": "augmented — weightless, disoriented",
    "minmaj7": "minor-major 7th — film-noir exotic tension",
}


def _cadence_effect(penult: Chord, final: Chord, key: KeyEstimate) -> str | None:
    t = key.tonic_pc
    if penult.root_pc == (t + 7) % 12 and final.root_pc == t:
        return "authentic cadence (V–I) — full harmonic closure"
    if penult.root_pc == (t + 5) % 12 and final.root_pc == t:
        return "plagal cadence (IV–I) — gentle, hymn-like settling"
    if penult.root_pc == (t + 7) % 12 and final.root_pc == (t + 9) % 12:
        return "deceptive cadence (V–vi) — withholds the ending, surprises the ear"
    if penult.root_pc == (t + 10) % 12 and final.root_pc == t:
        return "backdoor cadence (bVII–I) — rock/blues-flavored resolution"
    if final.root_pc == (t + 7) % 12:
        return "half cadence — ends open on the dominant, unresolved"
    return None


def _borrowed_effect(chord: Chord, key: KeyEstimate) -> str | None:
    parallel = KeyEstimate(tonic_pc=key.tonic_pc, mode="major" if key.mode == "minor" else "minor")
    if _is_diatonic(chord, parallel):
        if key.mode == "major":
            return "borrowed from the parallel minor — darkens the palette (modal mixture)"
        return "borrowed from the parallel major — brightens the minor key"
    if key.mode == "major" and chord.root_pc == (key.tonic_pc + 10) % 12 and chord.quality in ("maj", "maj7"):
        return "bVII (mixolydian borrow) — classic rock/pop color, softens the dominant"
    if chord.root_pc == (key.tonic_pc + 1) % 12 and chord.quality in ("maj", "maj7") and key.mode == "minor":
        return "Neapolitan (bII) — dark, dramatic pre-dominant, often in first inversion"
    return None


def _inversion_effect(chord: Chord, key: KeyEstimate, prev: Chord | None) -> str | None:
    if chord.inversion == 0:
        return None
    if chord.inversion == 1:
        if chord.root_pc == key.tonic_pc and prev is not None and prev.root_pc in ((key.tonic_pc + 5) % 12, (key.tonic_pc + 7) % 12):
            return "1st inversion — bass steps smoothly into the tonic, softening the arrival"
        if chord.root_pc == (key.tonic_pc + 7) % 12 and chord.bass_pc == (key.tonic_pc + 11) % 12:
            return "leading tone in the bass — pulls hard upward toward the tonic"
        return "1st inversion — bass moves by step, keeps the line flowing"
    if chord.inversion == 2:
        return "2nd inversion — unstable, transitional; classic passing or cadential 6/4 feel"
    if chord.inversion == 3:
        return "3rd inversion — the 7th sits in the bass, adding urgency before resolving down"
    return None


def _annotate_bass_line(chords: list[Chord]) -> None:
    """Detect pedal points and stepwise bass runs across consecutive chords."""
    known = [(i, c) for i, c in enumerate(chords) if c.bass_pc is not None]
    i = 0
    while i < len(known) - 2:
        (i0, c0), (i1, c1), (i2, c2) = known[i], known[i + 1], known[i + 2]
        d1 = (c1.bass_pc - c0.bass_pc) % 12
        d2 = (c2.bass_pc - c1.bass_pc) % 12
        s1 = min(d1, 12 - d1)
        s2 = min(d2, 12 - d2)
        if c0.bass_pc == c1.bass_pc == c2.bass_pc:
            for c in (c0, c1, c2):
                c.effect = ((c.effect + "; ") if c.effect else "") + f"pedal point on {pitch_name(c.bass_pc)} — grounds the harmony while chords change"
            i += 3
            continue
        if s1 in (1, 2) and s2 in (1, 2) and d1 < 6 and d2 < 6:
            direction = "ascending" if (d1 + d2) <= 6 else "descending"
            flavor = "builds momentum and lift" if direction == "ascending" else "plaintive, lament-like feel"
            for c in (c0, c1, c2):
                c.effect = ((c.effect + "; ") if c.effect else "") + f"stepwise {direction} bass line — {flavor}"
            i += 3
            continue
        i += 1


def _annotate_pickup(chords: list[Chord]) -> None:
    if len(chords) >= 2:
        durations = sorted(c.duration for c in chords)
        median = durations[len(durations) // 2]
        first = chords[0]
        if first.duration < 0.5 * median:
            first.effect = ((first.effect + "; ") if first.effect else "") + "pickup chord (anacrusis) — leads into the first strong downbeat"


def _annotate_retake(chords: list[Chord]) -> None:
    for i in range(len(chords) - 2):
        a, _b, c = chords[i], chords[i + 1], chords[i + 2]
        if a.symbol() == c.symbol() and a.symbol() != _b.symbol():
            a.effect = ((a.effect + "; ") if a.effect else "") + "harmony immediately retaken — ostinato-like reinforcement"
