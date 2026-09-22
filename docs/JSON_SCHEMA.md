# Canonical JSON Schema

**Status:** v1.0 · **Last updated:** 2026-09-22
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §20.
**Frozen machine-checkable form:** [`schemas/harmony-analysis.schema.json`](../schemas/harmony-analysis.schema.json)
(draft 2020-12, `harmony/schema.py` validates against it; `/api/v1/schema`
serves it; `tests/test_schema.py` enforces it). This page is the human
reference for the same contract.
Emitted by `report.json_report(result)`. The Markdown and HTML (player)
reports derive from the same `AnalysisResult`; the web summary
(`/api/jobs/{id}`) is a reduced projection.

## Top level

```json
{
  "title": "Jesus At The Mention Of Your Name - Donnie McClurkin",
  "source": "https://www.youtube.com/watch?v=Eyoqqnfi7dg",
  "duration": 391.5,
  "key":     { … KeyEstimate … },
  "tempo":   112.3,
  "rhythm":  { … | null … },
  "chords":  [ … Chord … ],
  "notes":   []
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | resolved metadata title, else file stem |
| `source` | string | original input (URL or file path); YouTube sources are canonicalized |
| `duration` | number (s) | from the decoded waveform |
| `tempo` | number \| null | BPM; `null` when no beat grid. May be half/double the felt tempo |
| `notes` | string[] | engine notices (reserved) |

## `key`

```json
{ "name": "F major", "tonic": "F", "mode": "major", "confidence": 0.87 }
```

`mode` ∈ `major | minor`; `confidence` = Pearson correlation against KK
profiles (0–1, scale-free). One global key per analysis (spec §15).

## `rhythm` (top level, `null` when no trustworthy grid)

```json
{
  "tempo": 112.3, "meter": 4,
  "beat_times":   [0.0, 0.535, …],
  "beat_strengths": [0.412, 0.208, …],
  "downbeats": [0, 4, 8, …],
  "confidence": 0.69
}
```

`beat_times`/`beat_strengths` are parallel lists (seconds / onset-envelope
strength). `downbeats` are **indices into `beat_times`**. `meter` ∈ 2–7 beats
per bar. `confidence` = downbeat-strength lift clamped to [0, 1].

## `chords[]`

Always present: `start, end, chord, root, quality, inversion, inversion_name,
roman, role, confidence`. Conditionally present: `bass`, `voicing`, `rhythm`,
`effect`.

```json
{
  "start": 33.0, "end": 35.0,
  "chord": "Bb7/D",
  "root": "Bb", "quality": "7",
  "inversion": 1, "inversion_name": "1st inversion",
  "bass": "D",
  "roman": "IV7", "role": "predominant",
  "confidence": 0.04,
  "voicing": {
    "pitch_classes": ["A", "Bb", "D", "F"],
    "extensions": [],
    "spacing": "closed",
    "added_notes": ["A"],
    "confidence": 0.7
  },
  "rhythm": {
    "bar": 15, "beat_in_bar": 4,
    "beats": 3, "beat_fraction": 3.5, "pushed": false
  },
  "effect": "1st inversion — bass moves by step, keeps the line flowing; dominant 7th — bluesy forward drive"
}
```

| Field | Type | Invariant |
|---|---|---|
| `start`, `end` | number (s) | `end > start`; segments non-overlapping; neighbor boundaries identical |
| `chord` | string | `Root[Quality][/Bass]`, sharp spelling (e.g. `Bb7/D`, `Fm6/C`, `N` = no chord) |
| `root` | string | pitch-class name (sharp spelling in JSON) |
| `quality` | string | one of the 15 in HARMONIC_MODEL §1 |
| `inversion` | int 0–3 | 0 = root position |
| `inversion_name` | string | `root position / 1st / 2nd / 3rd inversion` |
| `bass` | string \| null | sounding bass pc; **`null`** when ambiguous or non-chord-tone — never a speculative label |
| `roman` | string \| null | e.g. `IV7`, `V7/vi`, `subV7/VI7`, `bVII` |
| `role` | string | `tonic / predominant / dominant / modal color` |
| `confidence` | number 0–1 | softmax posterior mean; **not comparable across songs** (spec §19) |
| `voicing.extensions` | int[] | semitone intervals above root (9 → 2, 11 → 5, 13 → 9) |
| `voicing.spacing` | string | `single note / cluster / closed / open / spread` |
| `voicing.pitch_classes` | string[] | sorted note names of sounding pcs (threshold-gated) |
| `voicing.added_notes` | string[] | sounding pcs that are neither chord tones nor claimed extensions |
| `rhythm.*` | object \| absent | present **iff** a beat grid exists; `bar`/`beat_in_bar` 1-based; `pushed` = off-grid entry |
| `effect` | string \| absent | `; `-joined plain-language device explanations |

## Invariants (machine-checkable)

1. `inversion > 0` ⇒ `bass` != null and `bass` is a chord tone ≠ root.
2. `rhythm` (per chord) present for all chords or none — never mixed.
3. Segments tile the analyzed span: `chords[i].end == chords[i+1].start`.
4. Every `roman` is consistent with `root`/`quality` under the reported `key`.
5. `voicing.pitch_classes` ⊇ chord tones of the detected quality above the
   energy threshold (superset relation is threshold-dependent by design).
