# Licensing

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §27.

## The project's own code

Copyright the repository owner (johni424). Choose and add a `LICENSE` file
before public promotion (MIT or Apache-2.0 recommended for a tool that wants
adoption; Apache-2.0 adds patent grant + trademark terms).

## Third-party runtime dependencies

| Package | License | Role |
|---|---|---|
| numpy | BSD-3 | arrays, Viterbi DP |
| scipy | BSD-3 | median filtering |
| librosa | ISC | CQT, HPSS, beat tracking, audio IO |
| soundfile | BSD-2 | audio IO |
| numba | BSD-2 | librosa acceleration |
| typer / rich | MIT | CLI |
| fastapi / starlette | MIT | web service |
| uvicorn | BSD-3 | ASGI server |
| python-multipart | Apache-2.0 | upload handling |
| yt-dlp (external tool) | Unlicense (public domain) | URL → audio |

All are permissive; none impose copyleft on this project.

## The important part: analyzed content

1. **Analysis is transformation, not reproduction.** The tool ingests audio
   the user already has access to and outputs *derived musical facts* (chord
   symbols, roman numerals, voicing descriptions). Harmonic facts are not
   copyrightable; the **audio itself** is.
2. **Private study is broadly legal** (fair use / fair dealing / private-copy
   exceptions in many jurisdictions) — this is the tool's designed posture:
   everything runs locally, nothing is redistributed.
3. **Never redistribute audio.** `.gitignore` excludes `*.wav`, `*.m4a`, and
   audio-embedded player HTML precisely so copyrighted audio cannot leak into
   the repo or releases. Keep it that way.
4. **Redistribution of analyses** (sharing a JSON/MD/PDF of chords) is a
   greyer zone than private analysis but is common practice (chord charts);
   any *commercial* exposure of user-generated analyses needs counsel.
5. **Commercial/hosted deployments must add:** a DMCA/takedown policy, terms
   of service forbidding upload of audio the user has no rights to process,
   and must not persist copyrighted audio longer than the analysis session
   requires (current default: temp dirs, OS-cleaned).
6. **Scale risk:** pulling audio from YouTube via yt-dlp at commercial scale
   violates YouTube ToS regardless of copyright. The sanctioned path for a
   hosted product is a licensed catalog source or user-provided files only.

## Assets in `eval/`

`eval/user_song.m4a` and `eval/user_song_player.html` (embedded audio) are
git-ignored, local-only evaluation artifacts of a copyrighted recording.
The JSON/MD/HTML reports *without* audio are committed as evaluation
evidence — they contain only derived musical data.
