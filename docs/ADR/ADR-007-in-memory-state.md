# ADR-007: All state in memory (no database)

**Status:** Accepted · **Date:** 2026-09-21
Master document: [TECHNICAL_SPECIFICATION.md](../TECHNICAL_SPECIFICATION.md) §21 (database — intentionally 🔴 not implemented).

## Context

The web app must track analysis jobs (stage progress, results, audio
artifacts). The canonical architecture keeps the diagram deliberately simple:
ingest → analysis → JSON → Terminal / API / Frontend. The question is where
job state lives.

Options ranged from SQLite through Redis to a full Postgres-backed job
service with an object store for audio.

## Decision

**Everything lives in process memory.** No database, no external cache, no
durable job store:

- `JOBS: dict[str, Job]` in `server.py`, guarded by `JOBS_LOCK`, capped at
  `MAX_JOBS = 40` (finished jobs pruned oldest-first).
- Analysis runs in daemon threads of the uvicorn process — one job, one
  thread.
- Per-job audio and player data go to a per-job directory under the OS temp
  dir. The only durable output is what the user explicitly exports
  (JSON / PDF / standalone HTML).

## Consequences

**Positive**

- Deployment is one command (`harmony-web`) with zero state to manage —
  nothing to migrate, back up, or run as a service.
- Restart is a clean slate; there is no stale-state failure mode.
- Matches the product reality: a result is re-derivable from its source in
  about a minute, so persisting it buys little.

**Negative / accepted limits**

- A server restart clears all jobs — a user mid-analysis loses it.
- Horizontal scaling is impossible: jobs live in one process's memory.
- The results-library idea (list past analyses on the landing page) only
  covers the current process lifetime.

**When to revisit:** the first time persistence or multi-worker scaling
becomes a real requirement. The natural successor is SQLite (single file,
zero service) with the §21 schema sketch in the technical specification —
not a network database.

## Related

- [ADR-006](ADR-006-streamed-web-player.md) — streamed web player (temp-dir
  artifacts are part of the same no-durability stance).
- [ARCHITECTURE.md](../ARCHITECTURE.md) — "In-memory state (by design)".
