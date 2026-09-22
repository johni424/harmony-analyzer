# Evaluation datasets

Two layers, one format (JSON manifest of case dicts — see
`harmony/evaluation.py::load_dataset`):

- **`synthetic.json`** — cases rendered to audio at eval time from exact
  specs. Ground truth is the spec itself; hermetic and license-free.
- **`real_songs.json`** — hand-checked references. Audio is fetched on
  demand (yt-dlp) into a temp dir and **never committed**. Every entry
  carries a `checked` provenance note; timed chord references exist only
  where beat-positions were verified, otherwise key/tempo/meter are scored
  sequence-level.

```bash
.venv/bin/harmony-eval datasets/synthetic.json --out eval/synthetic   # offline
.venv/bin/harmony-eval datasets/real_songs.json --fetch               # needs yt-dlp
```

Case fields: `id`, `kind` (`synthetic|real`), `genre`, `key`, `key_alt`
(acceptable alternates, e.g. the relative minor), `tempo`, `meter`,
`chords` (`symbol`/`start`/`duration`/`bass` — the timed ground truth),
`render` (synthetic only: chord tones, bass, beat positions, groove clicks),
`source`/`artist`/`checked` (real only). Metrics and the current baseline:
[docs/EVALUATION.md](../docs/EVALUATION.md).
