# ADR-006: Streamed web player (not audio-embedded HTML)

**Status:** Accepted · **Date:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §5.

## Context

The Timeline Player originally embedded the analyzed audio as a base64 data
URI so a single HTML file works offline. Through the web server this meant
**~100 MB player pages** (391 s of WAV, base64-inflated), slow loads, and
memory pressure in the browser.

## Decision

`report.html_report()` accepts `audio_src`. The web server passes
`/audio/{job_id}`; the player then streams audio over HTTP (Starlette
FileResponse, range requests → `206`) and fetches the same URL for waveform
decoding. The CLI `--html --audio` export keeps base64 embedding so the
single-file offline guarantee holds where it matters.

## Rationale

- 365 KB page instead of ~100 MB (≈275×); instant load, instant seek
  (server-side range requests).
- One template, two audio sources — no forked player code.
- The embedded variant remains the right answer for portability (email,
  USB, no server); the streamed variant is the right answer for the web app.

## Consequences

- Web players require the server (audio 404s after job store eviction).
- MIME mapping matters: `.m4a` must be served as `audio/mp4`
  (Python's `mimetypes` suggests `audio/mp4a-latm`, which Chromium rejects —
  caught in live verification, fixed in `_AUDIO_MIME`/`MIME_MAP`).
