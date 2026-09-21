# API

**Status:** v1.0 · **Last updated:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](TECHNICAL_SPECIFICATION.md) §7.

Base URL (default): `http://127.0.0.1:8600` · Start: `harmony-web` or
`python -m harmony.server --port 8600`.

No authentication. Localhost single-user posture — do not expose without the
hardening in spec §26. All responses are JSON unless stated otherwise.

## Job lifecycle

```
POST /api/jobs/url | /api/jobs/file   → 202 {"job_id": "<12 hex>"}
GET  /api/jobs/{job_id}               → { stage: ... }   (poll every ~1 s)
stage: queued → ingest → features → decode → harmony → rhythm → render → done
                                                    ↘ error ({"error": msg})
GET  /player/{job_id}                 → text/html (Timeline Player)
GET  /audio/{job_id}                  → audio stream (Range supported)
```

Job ids are random; the store is in-memory (max 40, finished jobs pruned
LRU) — players/summaries do not survive a server restart.

## Endpoints

### `GET /`
Landing page (HTML). Tabs: URL input, drag & drop upload; live stage
progress; result card linking to the player.

### `GET /healthz`
`{"ok": true}` — liveness probe.

### `POST /api/jobs/url`
Body: `{"url": "https://www.youtube.com/watch?v=…"}`

- Accepts YouTube (`youtube.com/watch`, `youtu.be`, `youtube.com/shorts`) and
  Spotify (`open.spotify.com/track/…`) URLs. Spotify tracks are resolved via
  oEmbed metadata then searched on YouTube.
- `202 Accepted` → `{"job_id": "…"}`
- `422` empty URL or non-YouTube/Spotify source.

### `POST /api/jobs/file`
Multipart form, field `file`. Extensions: `.mp3 .m4a .mp4 .aac .wav .flac
.ogg .oga .opus .webm`; limit **200 MB** (enforced while streaming, 1 MiB
chunks).

- `202 Accepted` → `{"job_id": "…"}`
- `413` file exceeds limit · `422` unsupported extension.

### `GET /api/jobs/{job_id}`
Progress + summary:

```json
{
  "job_id": "fa69d2647c08",
  "stage": "done",
  "error": null,
  "title": "Jesus At The Mention Of Your Name - Donnie McClurkin",
  "duration": 391.5,
  "key": "f major",
  "tempo": 112.3,
  "n_chords": 184,
  "has_audio": true
}
```

`title/duration/key/tempo/n_chords` are `null`/`0` until `done`. `404` for
unknown ids.

### `GET /player/{job_id}`
The interactive Timeline Player (HTML). Web players reference audio via
`/audio/{job_id}` (streamed — [ADR-006](ADR/ADR-006-streamed-web-player.md)).
`404` unknown job · `409` player not rendered yet.

### `GET /audio/{job_id}`
Serves the analyzed audio with `FileResponse` (Starlette range-request
support → `206 Partial Content`, enabling instant seeking). Mime by extension
(`.m4a → audio/mp4`, `.wav → audio/wav`, …). `404` no audio · `410` file was
cleaned up.

## Error model

| Status | Meaning |
|---|---|
| 202 | job accepted, poll `/api/jobs/{id}` |
| 404 | unknown job id |
| 409 | job exists but player not rendered yet |
| 410 | audio file cleaned up |
| 413 | upload exceeds 200 MB |
| 422 | malformed input (empty/blocked URL, unsupported file type) |

Worker exceptions never crash the server: the job transitions to
`stage: "error"` and `error` carries `"{ExceptionType}: {message}"` truncated
to 500 chars. Rhythm-stage failures are contained inside the pipeline (the
analysis completes without a beat grid).
