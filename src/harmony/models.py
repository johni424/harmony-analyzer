"""Core data model for the harmony analyzer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Canonical pitch-class spelling table. Index = pitch class 0-11.
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

PC_TO_SHARP = {name: i for i, name in enumerate(SHARP_NAMES)}
PC_TO_FLAT = {name: i for i, name in enumerate(FLAT_NAMES)}

MAJOR_PROFILE_INTERVALS = (0, 4, 7)
MINOR_PROFILE_INTERVALS = (0, 3, 7)


def pitch_name(pc: int, sharp: bool = True) -> str:
    """Pitch-class number -> note name."""
    return (SHARP_NAMES if sharp else FLAT_NAMES)[pc % 12]


def pc_from_name(name: str) -> int:
    """Note name (with # or b) -> pitch class."""
    name = name.strip()
    if name in PC_TO_SHARP:
        return PC_TO_SHARP[name]
    if name in PC_TO_FLAT:
        return PC_TO_FLAT[name]
    base = name[0].upper()
    table = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    if base not in table:
        raise ValueError(f"Unknown note name: {name!r}")
    pc = table[base]
    for suffix in name[1:]:
        if suffix == "#":
            pc += 1
        elif suffix == "b":
            pc -= 1
        else:
            raise ValueError(f"Unknown accidental {suffix!r} in {name!r}")
    return pc % 12


INVERSION_NAMES = {0: "root position", 1: "1st inversion", 2: "2nd inversion", 3: "3rd inversion"}

# Intervals (semitones above the chord root) for common extension tones.
EXTENSION_INTERVALS = {7: 10, 9: 2, 11: 5, 13: 9}  # intervals for b7, 9, 11, 13


@dataclass
class VoicingInfo:
    """How a chord is actually realized in the audio.

    pitch_set is the set of pitch classes detected as sounding in the segment
    (beyond noise threshold); extensions are those that turn a triad/7th into
    a richer sonority (e.g. 9, 11, 13) judged present with some confidence.
    """

    pitch_classes: frozenset[int]
    bass_pc: Optional[int] = None
    extensions: tuple[int, ...] = ()  # e.g. (9,) or (7, 9)
    register_spread_semitones: float = 0.0  # spread of detected harmonics
    spacing: str = "unknown"  # closed / open / cluster / spread / unknown
    added_notes: tuple[int, ...] = ()  # pitch classes in the audio outside the nominal chord
    confidence: float = 0.0


@dataclass
class Chord:
    """One detected chord segment in the song."""

    start: float  # seconds
    end: float
    root_pc: int
    quality: str  # "maj", "min", "dim", "aug", "maj7", "min7", "7", "hdim7", "dim7", "sus4", ...
    bass_pc: Optional[int] = None  # if != root_pc, chord is inverted (slash chord)
    inversion: int = 0  # 0=root, 1=first, 2=second, 3=third
    confidence: float = 0.0
    voicing: Optional[VoicingInfo] = None
    function: Optional[str] = None  # roman numeral e.g. "vi7"
    role: Optional[str] = None  # e.g. "tonic", "predominant", "dominant"
    effect: Optional[str] = None  # human-readable effect annotation
    # Rhythmic placement (filled by the rhythm stage; None if no beat grid):
    beats: Optional[int] = None  # count of beat onsets that land inside the chord
    beat_fraction: Optional[float] = None  # exact duration in beats (duration / sec_per_beat)
    bar: Optional[int] = None  # 1-based bar number of the chord's first beat
    beat_in_bar: Optional[int] = None  # 1-based position of that beat within its bar
    pushed: bool = False  # chord starts off the beat (anticipation / push)
    human_corrected: bool = False  # label changed by a human (correction interface, roadmap step 3)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def symbol(self, sharp: bool = True) -> str:
        base = pitch_name(self.root_pc, sharp) + _QUALITY_SUFFIX.get(self.quality, self.quality)
        if self.bass_pc is not None and self.bass_pc != self.root_pc:
            base += "/" + pitch_name(self.bass_pc, sharp)
        return base

    @property
    def inversion_name(self) -> str:
        return INVERSION_NAMES.get(self.inversion, "root position")


# Suffix used in chord symbols for each quality.
_QUALITY_SUFFIX = {
    "maj": "",
    "min": "m",
    "dim": "dim",
    "aug": "aug",
    "maj7": "maj7",
    "min7": "m7",
    "7": "7",
    "hdim7": "m7b5",
    "dim7": "dim7",
    "minmaj7": "mMaj7",
    "sus4": "sus4",
    "sus2": "sus2",
    "maj6": "6",
    "min6": "m6",
    "maj9": "maj9",
    "min9": "m9",
    "9": "9",
    "13": "13",
    "min11": "m11",
    "maj13": "maj13",
    "min13": "m13",
    "aug7": "7#5",
    "maj7#11": "maj7#11",
    "7b9": "7b9",
    "7#9": "7#9",
    "7alt": "7alt",
    "7sus4": "7sus4",
    "min7b13": "m7b13",
    "N": "N",  # no chord
}


@dataclass
class KeyEstimate:
    tonic_pc: int
    mode: str  # "major" | "minor"
    confidence: float = 0.0

    def name(self, sharp: bool = True) -> str:
        return f"{pitch_name(self.tonic_pc, sharp)} {self.mode}"


@dataclass
class ConfidenceScores:
    """Per-dimension trust metrics for one analysis (the confidence engine's output).

    Each field is 0.0-1.0. `overall` combines the dimensions; it is NOT a
    probability of correctness — see docs/HARMONIC_MODEL.md §confidence.
    """

    chord: float = 0.0  # chord quality/label evidence strength (mean emission margin)
    bass: float = 0.0  # low-register evidence for the claimed bass/inversion
    inversion: float = 0.0  # how unambiguous each claimed inversion is (root=1)
    voicing: float = 0.0  # pitch-set stability inside segments
    function: float = 0.0  # key-profile fit + diatonic coherence
    rhythm: float = 0.0  # beat-grid coherence (0.0 when no grid was found)
    overall: float = 0.0  # weighted combination of the above


@dataclass
class RhythmInfo:
    """Beat grid + meter estimated from the audio (rhythmic analysis stage).

    beat_times/strengths are parallel lists; downbeats are indices into them.
    meter is beats per bar (4 = 4/4, 3 = 3/4). confidence is the mean
    normalized onset strength at bar starts (grid coherence, 0-1).
    """

    tempo: float  # BPM as estimated (may be half/double the felt tempo)
    meter: int
    beat_times: list[float]
    beat_strengths: list[float]
    downbeats: list[int]
    confidence: float = 0.0

    def bar_beat(self, beat_index: int) -> tuple[int, int]:
        """1-based (bar, beat_in_bar) for a 0-based beat index."""
        return beat_index // self.meter + 1, beat_index % self.meter + 1

    def is_downbeat(self, beat_index: int) -> bool:
        return beat_index % self.meter == 0


@dataclass
class DnaMatch:
    """One recognized progression pattern inside the Harmonic DNA report."""

    name: str  # e.g. "I–V–vi–IV (axis)"
    numerals: tuple[str, ...]  # roman numerals of the matched run
    start: float  # seconds
    end: float
    count: int  # occurrences of this pattern in the song
    annotation: str  # musical effect description


@dataclass
class DnaReport:
    """Harmonic DNA (step 18): the song's identity at progression level."""

    signature: str  # e.g. "I → V → vi → IV (axis)"
    devices: dict[str, int] = field(default_factory=dict)  # e.g. {"borrowed chords": 3}
    matches: list[DnaMatch] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Full analysis output for one song."""

    title: str
    source: str
    duration: float
    key: KeyEstimate
    audio_path: Optional[str] = None  # local audio file, embeddable in the HTML player
    chords: list[Chord] = field(default_factory=list)
    tempo: Optional[float] = None
    notes: list[str] = field(default_factory=list)
    rhythm: Optional[RhythmInfo] = None  # beat grid / meter, if detectable
    confidence: Optional[ConfidenceScores] = None  # per-dimension trust metrics
    dna: Optional[DnaReport] = None  # Harmonic DNA summary (signature progressions)

    def progression_symbols(self, sharp: bool = True) -> list[str]:
        return [c.symbol(sharp) for c in self.chords]
