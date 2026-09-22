"""Harmonic DNA engine (step 18): the song's identity at progression level.

Condenses the roman-numeral progression into:

- a **signature** — the most characteristic recurring progression, named when
  it matches a well-known pattern (the "axis" I–V–vi–IV, the 50s doo-wop
  I–vi–IV–V, the Andalusian descent, the circle-of-fifths sequence …)
- **devices** — counts of the compositional devices the function engine found
  (secondary dominants, modal mixture, pedal points, cadences, inversions …)
- **matches** — every recognized named pattern with occurrence counts and the
  time span of its first appearance

Operates on the already-annotated chord list; recomputes the plain roman
numeral per chord (the function field may carry "V7/ii"-style secondary
labels, which would break pattern matching).
"""
from __future__ import annotations

import re
from collections import Counter

from .function import roman_numeral
from .models import AnalysisResult, Chord, DnaMatch, DnaReport, KeyEstimate

# Keep only the numeral core: "Imaj7" -> "I", "v7" -> "v", "bVII" -> "bVII".
_TOKEN_RE = re.compile(r"^([#b]?[IViv]+)")

# Named progressions in *normalized* tokens. Case carries quality (uppercase
# major, lowercase minor), prefix carries the accidental. Tokens are compared
# literally, so any mode transposes for free (roman numerals are key-relative).
_PATTERNS: dict[str, tuple[tuple[str, ...], str]] = {
    "axis progression": (
        ("I", "V", "vi", "IV"),
        "the defining pop loop — tonic, dominant, relative minor, subdominant",
    ),
    "axis rotation (vi–IV–I–V)": (
        ("vi", "IV", "I", "V"),
        "axis loop starting on the relative minor — melancholy resolving upward",
    ),
    "axis rotation (IV–I–V–vi)": (
        ("IV", "I", "V", "vi"),
        "axis loop starting on the subdominant — warm, rolling",
    ),
    "axis rotation (V–vi–IV–I)": (
        ("V", "vi", "IV", "I"),
        "axis loop starting on the dominant — keeps arriving home",
    ),
    "doo-wop changes": (
        ("I", "vi", "IV", "V"),
        "the 1950s ballad loop — nostalgic, cyclical warmth",
    ),
    "jazz ii–V–I": (
        ("ii", "V", "I"),
        "the engine of jazz standards — predominant into dominant into rest",
    ),
    "classic rock loop": (
        ("I", "IV", "V", "IV"),
        "blues-derived three-chord rock",
    ),
    "mixolydian rock loop": (
        ("I", "bVII", "IV"),
        "flat-VII keeps the dominant soft and gritty",
    ),
    "aeolian epic loop": (
        ("i", "bVI", "bVII"),
        "minor lift — the cinematic minor-key anthem loop",
    ),
    "Andalusian descent": (
        ("i", "bVII", "bVI", "V"),
        "flamenco descent — dramatic walk down to the dominant",
    ),
    "harmonic minor cadence": (
        ("i", "iv", "V"),
        "minor with a raised leading tone — tension before resolution",
    ),
    "Pachelbel ground": (
        ("I", "V", "vi", "iii", "IV"),
        "the canon progression — descending sequence of calm certainty",
    ),
    "circle-of-fifths descent": (
        ("iii", "vi", "ii", "V", "I"),
        "fifths sequence — relentless forward pull to the tonic",
    ),
    "extended jazz loop": (
        ("I", "vi", "ii", "V"),
        "I–vi–ii–V — the long circle used by standards and musicals",
    ),
    "backdoor ascent": (
        ("bVI", "bVII", "I"),
        "bVI–bVII–I — bright, anthemic rise into the tonic",
    ),
}


def analyze(chords: list[Chord], key: KeyEstimate) -> DnaReport:
    """Extract the Harmonic DNA report from an annotated chord list."""
    tokens: list[str] = []
    chord_idx: list[int] = []  # chord index behind each token
    for i, c in enumerate(chords):
        if c.quality == "N":
            continue
        m = _TOKEN_RE.match(roman_numeral(c, key))
        if m:
            tokens.append(m.group(1))
            chord_idx.append(i)

    matches = _find_patterns(tokens, chord_idx, chords)
    devices = _device_summary(chords)
    signature = _signature(tokens, matches)
    return DnaReport(signature=signature, devices=devices, matches=matches)


def _find_patterns(
    tokens: list[str], chord_idx: list[int], chords: list[Chord]
) -> list[DnaMatch]:
    """Find every named pattern; count non-overlapping occurrences."""
    matches: list[DnaMatch] = []
    for name, (pattern, annotation) in _PATTERNS.items():
        n = len(pattern)
        count = 0
        first: tuple[int, int] | None = None  # token-index span of first match
        i = 0
        while i + n <= len(tokens):
            if tuple(tokens[i : i + n]) == pattern:
                if first is None:
                    first = (i, i + n)
                count += 1
                i += n  # non-overlapping
            else:
                i += 1
        if count and first is not None:
            c0, c1 = chord_idx[first[0]], chord_idx[first[1] - 1]
            matches.append(
                DnaMatch(
                    name=name,
                    numerals=pattern,
                    start=float(chords[c0].start),
                    end=float(chords[c1].end),
                    count=count,
                    annotation=annotation,
                )
            )
    # Most frequent first; ties broken by longer pattern, then earlier.
    matches.sort(key=lambda m: (-m.count, -len(m.numerals), m.start))
    return matches


def _signature(tokens: list[str], matches: list[DnaMatch]) -> str:
    """One line naming what the song is harmonically made of."""
    if matches:
        best = matches[0]
        return f"{' → '.join(best.numerals)} — {best.name}"
    # No named pattern: report the most frequent recurring 3-gram, else 2-gram,
    # else the opening progression.
    for n in (3, 2):
        if len(tokens) >= n:
            grams = Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
            gram, count = grams.most_common(1)[0]
            if count >= 2:
                return f"{' → '.join(gram)} — recurring loop (song-specific)"
    if tokens:
        return f"{' → '.join(tokens[:4])} — opening progression"
    return "—"


def _device_summary(chords: list[Chord]) -> dict[str, int]:
    """Count compositional devices, per chord presence, most-used first."""
    keywords = (
        ("secondary dominant", "secondary dominants"),
        ("tritone substitution", "tritone substitutions"),
        ("borrowed", "borrowed chords (modal mixture)"),
        ("pedal point", "pedal points"),
        ("stepwise", "stepwise bass motion"),
        ("cadence", "cadences"),
        ("neapolitan", "Neapolitan chords"),
        ("suspended", "suspensions resolving"),
    )
    devices: Counter[str] = Counter()
    for c in chords:
        text = (c.effect or "").lower()
        for kw, label in keywords:
            if kw in text:
                devices[label] += 1
        if c.inversion:
            devices["inversions used"] += 1
        if c.pushed:
            devices["off-beat (pushed) entries"] += 1
        if c.voicing and c.voicing.extensions:
            devices["extended voicings (9/11/13)"] += 1
        if c.quality in ("sus4", "sus2", "7sus4"):
            devices["suspended sonorities"] += 1
    return dict(sorted(devices.items(), key=lambda kv: -kv[1]))
