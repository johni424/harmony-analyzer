"""Correction interface (production roadmap step 3).

Musicians see what the analyzer got wrong and can fix it — e.g. the analyzer
said ``F`` but the musician hears ``F/A``. Corrections are first-class
analysis data, not throwaway UI state:

    correction → canonical analysis document → ground-truth case
               → evaluation dataset → engine improvement

Design decisions (kept consistent with the ADRs):
- **In-memory corrections, on the job** (ADR-007): a correction lives on the
  server's ``Job`` and on the corrected analysis document; a restart loses
  corrections, exactly like analyses themselves. A ``dataset case`` export is
  the durable artifact, and it is deliberately the *same format* the
  evaluation harness already consumes.
- **Schema-protected:** the corrected document must pass the frozen contract
  (step 20) — a correction may change labels, never the schema.
- **Provenance kept:** every corrected chord records what the engine said
  before, so future training data distinguishes engine labels from human ones.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import schema as schema_mod
from .models import pc_from_name

# "Fmaj7/A" -> root "F", suffix "maj7", bass "A" (suffix may be empty).
_SYMBOL_RE = re.compile(r"^([A-G][#b]?)([a-zA-Z0-9#b]*)(?:/([A-G][#b]?))?$")


@dataclass
class ChordCorrection:
    """One human edit of one detected chord segment."""

    index: int  # index into analysis["chords"]
    original_symbol: str  # what the engine said (provenance)
    new_symbol: str  # what the musician says is correct
    corrected_at: float = field(default_factory=time.time)
    note: str | None = None  # optional free-text comment


def parse_symbol_strict(symbol: str) -> tuple[int, str, int | None]:
    """Strict root/suffix/bass parse for user input.

    Root and bass must be real note names; the suffix is validated against the
    engine's symbol vocabulary (the same grammar the frozen schema enforces).
    Returns (root_pc, quality, bass_pc).
    """
    m = _SYMBOL_RE.match(symbol.strip())
    if not m:
        raise ValueError(
            f"{symbol!r} is not a chord symbol — use Root[Quality][/Bass], e.g. Fmaj7/A")
    root_name, suffix, bass_name = m.group(1), m.group(2), m.group(3)
    root = pc_from_name(root_name)
    quality = {
        "": "maj", "m": "min", "M": "maj", "maj7": "maj7", "M7": "maj7",
        "m7": "min7", "7": "7", "dim": "dim", "dim7": "dim7", "m7b5": "hdim7",
        "ø": "hdim7", "aug": "aug", "+": "aug", "sus4": "sus4", "sus2": "sus2",
        "6": "maj6", "m6": "min6", "maj9": "maj9", "m9": "min9", "9": "9",
        "13": "13", "m11": "min11", "maj13": "maj13", "m13": "min13",
        "7sus4": "7sus4", "7#5": "aug7", "7b9": "7b9", "7#9": "7#9",
        "7alt": "7alt", "mMaj7": "minmaj7",
    }.get(suffix)
    if quality is None:
        raise ValueError(f"unknown quality suffix {suffix!r} in {symbol!r}")
    bass = pc_from_name(bass_name) if bass_name else None
    return root, quality, bass


def apply_correction(analysis_doc: dict, correction: ChordCorrection) -> dict:
    """Apply one correction to a canonical analysis document (in place) and
    validate the result against the frozen schema.

    Raises ValueError for bad user input (bad index/symbol) and
    jsonschema.ValidationError if the corrected document violates the contract
    (e.g. an inversion without a stated bass).
    """
    chords = analysis_doc.get("chords")
    if not chords:
        raise ValueError("analysis document has no chords to correct")
    i = correction.index
    if not (0 <= i < len(chords)):
        raise ValueError(f"chord index {i} out of range (0..{len(chords) - 1})")

    root, quality, bass = parse_symbol_strict(correction.new_symbol)
    chord = chords[i]
    inversion = 0
    if bass is not None:
        from .bass import _inversion_from_bass

        inversion = _inversion_from_bass(root, quality, bass)
        if inversion == 0:
            # Bass is not a chord tone for this quality — keep the user's bass
            # as color but do not claim a phantom inversion. Root position,
            # bass annotated (the schema allows bass != root only with
            # inversion > 0, so drop to the root pitch class instead).
            bass = None

    from .models import pitch_name

    chord["root"] = pitch_name(root)
    chord["quality"] = quality
    chord["bass"] = pitch_name(bass) if bass is not None else None
    chord["inversion"] = inversion
    chord["inversion_name"] = {
        0: "root position", 1: "1st inversion",
        2: "2nd inversion", 3: "3rd inversion"}[inversion]
    # Rebuild the display symbol in sharp spelling (schema grammar).
    from .models import _QUALITY_SUFFIX

    chord["chord"] = (pitch_name(root) + _QUALITY_SUFFIX.get(quality, quality)
                      + (f"/{pitch_name(bass)}" if bass is not None else ""))
    chord["human_corrected"] = True

    errors = schema_mod.validate_payload(analysis_doc)
    if errors:
        # Do not leave the doc half-edited.
        raise ValueError("correction rejected: " + "; ".join(errors[:3]))
    return analysis_doc


def to_dataset_case(doc_id: str, doc: dict, corrections: list[ChordCorrection],
                    genre: str = "user-corrected", source: str | None = None) -> dict:
    """Export a corrected analysis as a ground-truth case in the *exact* format
    ``evaluation.load_dataset`` consumes — corrections become the timed chord
    reference, with roman numerals taken from the engine's functional layer.

    Timing/boundaries are inherited from the analysis (the human verified the
    labels, not necessarily every boundary), which the harness treats as a
    normal timed reference.
    """
    corrected = {c.index: c for c in corrections}
    chords_out = []
    t = 0.0
    for i, ch in enumerate(doc["chords"]):
        duration = round(float(ch["end"]) - float(ch["start"]), 3)
        symbol = ch["chord"]
        c = corrected.get(i)
        chords_out.append({
            "symbol": symbol,
            "start": round(float(ch["start"]), 3),
            "duration": duration,
            "bass": ch.get("bass"),
            "roman": ch.get("roman"),
            "n_corrections": 1 if c else 0,
        })
        t = ch["start"] + duration
    key_name = doc["key"]["name"]
    return {
        "id": f"corrected_{doc_id}",
        "kind": "synthetic",  # analyzed from audio we do not redistribute
        "genre": genre,
        "key": key_name,
        "tempo": doc.get("tempo"),
        "meter": (doc.get("rhythm") or {}).get("meter"),
        "source": source,
        "checked": (f"human-corrected {time.strftime('%Y-%m-%d')}: "
                    f"{len(corrected)}/{len(doc['chords'])} chords edited"),
        "chords": chords_out,
    }
