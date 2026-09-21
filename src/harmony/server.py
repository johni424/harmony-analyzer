"""Web UI for the harmony analyzer.

A self-contained FastAPI app: paste a YouTube link or drop an audio file,
watch the analysis progress, then explore the chord timeline in the
interactive player. Run with:

    harmony-web            (entry point installed by pyproject)
    python -m harmony.server --port 8600
"""
from __future__ import annotations

import argparse
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import report
from .models import AnalysisResult
from .pipeline import analyze

app = FastAPI(title="harmony analyzer", docs_url=None, redoc_url=None)

MIME_MAP = {
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/opus",
    ".webm": "audio/webm",
}
AUDIO_EXTS = set(MIME_MAP)
UPLOAD_LIMIT_MB = 200

YOUTUBE_RE = re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts)")
SPOTIFY_RE = re.compile(r"open\.spotify\.com/(track|album|playlist)/")


@dataclass
class Job:
    id: str
    kind: str  # "url" | "upload"
    stage: str = "queued"  # queued/ingest/features/decode/harmony/rhythm/render/done/error
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    result: AnalysisResult | None = None
    audio_path: str | None = None
    work_dir: Path | None = None


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 40


def _prune_jobs() -> None:
    with JOBS_LOCK:
        if len(JOBS) <= MAX_JOBS:
            return
        finished = sorted(
            (j for j in JOBS.values() if j.finished is not None),
            key=lambda j: j.finished,
        )
        for j in finished[: len(JOBS) - MAX_JOBS]:
            JOBS.pop(j.id, None)


def _run_job(job: Job, source: str) -> None:
    def on_stage(stage: str, done: bool) -> None:
        if done:
            return  # only stage starts are polled; completion is the render step
        job.stage = stage

    try:
        t0 = time.time()
        result = analyze(source, verbose=False, keep_audio=True, on_stage=on_stage)
        job.stage = "render"
        html = report.html_report(result, sharp=False,
                                   audio_src=f"/audio/{job.id}")
        assert job.work_dir is not None
        (job.work_dir / "player.html").write_text(html)
        job.result = result
        job.audio_path = result.audio_path
        job.stage = "done"
        job.finished = time.time()
    except Exception as exc:  # surfaced to the poller
        job.stage = "error"
        job.error = f"{type(exc).__name__}: {exc}"[:500]
        job.finished = time.time()


def _start(job: Job, source: str) -> None:
    threading.Thread(target=_run_job, args=(job, source), daemon=True).start()


def _summary(job: Job) -> dict:
    r = job.result
    return {
        "job_id": job.id,
        "stage": job.stage,
        "error": job.error,
        "title": r.title if r else None,
        "duration": round(r.duration, 1) if r else None,
        "key": r.key.name(sharp=False) if r else None,
        "tempo": round(r.tempo, 1) if r and r.tempo else None,
        "n_chords": len(r.chords) if r else 0,
        "has_audio": job.audio_path is not None,
    }


# --------------------------------------------------------------------------- #
#  Landing page
# --------------------------------------------------------------------------- #

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>harmony — chord analyzer</title>
<style>
:root {
  --bg: #0e1117; --panel: #161b26; --panel2: #1c2331; --line: #2a3345;
  --text: #e8ecf4; --dim: #8b95a9; --accent: #5eead4; --accent2: #fbbf24;
  --danger: #f87171; --shadow: 0 18px 50px rgba(0,0,0,.45);
}
body.light {
  --bg: #f4f6fb; --panel: #ffffff; --panel2: #eef1f8; --line: #d7dceb;
  --text: #1c2333; --dim: #61708b; --shadow: 0 18px 50px rgba(30,40,80,.14);
}
* { box-sizing: border-box; margin: 0; }
body {
  font: 16px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
  background:
    radial-gradient(900px 420px at 80% -10%, color-mix(in srgb, var(--accent) 9%, transparent), transparent),
    radial-gradient(700px 380px at 10% 110%, color-mix(in srgb, var(--accent2) 7%, transparent), transparent),
    var(--bg);
  color: var(--text); min-height: 100vh;
  display: flex; flex-direction: column; align-items: center;
  transition: background .3s, color .3s;
}
.wrap { width: min(920px, 92vw); margin: 0 auto; }
header { width: 100%; padding: 22px 0; display: flex; justify-content: center; position: relative; }
.theme-btn {
  position: absolute; right: 4vw; top: 22px; border: 1px solid var(--line);
  background: var(--panel); color: var(--dim); border-radius: 10px;
  padding: 8px 12px; cursor: pointer; font-size: 15px;
}
.theme-btn:hover { color: var(--text); border-color: var(--accent); }
.hero { text-align: center; margin: 34px 0 30px; }
.hero h1 { font-size: clamp(30px, 5vw, 46px); letter-spacing: -.02em; }
.hero h1 em { font-style: normal; color: var(--accent); }
.hero p { color: var(--dim); max-width: 560px; margin: 12px auto 0; }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 18px;
  box-shadow: var(--shadow); padding: 26px; margin-bottom: 22px;
}
.tabs { display: flex; gap: 8px; margin-bottom: 18px; }
.tab {
  flex: 1; text-align: center; padding: 10px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--line); color: var(--dim); font-weight: 600; user-select: none;
}
.tab.on { color: var(--text); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
input[type=url] {
  width: 100%; padding: 14px 16px; border-radius: 12px; font-size: 16px;
  border: 1px solid var(--line); background: var(--panel2); color: var(--text); outline: none;
}
input[type=url]:focus { border-color: var(--accent); }
.drop {
  margin-top: 4px; border: 2px dashed var(--line); border-radius: 14px;
  padding: 34px 16px; text-align: center; color: var(--dim); cursor: pointer;
  transition: border-color .2s, background .2s;
}
.drop.on, .drop:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 7%, transparent); }
.drop b { color: var(--text); }
#fileinfo { margin-top: 10px; color: var(--accent); font-size: 14px; min-height: 1.2em; }
.go {
  margin-top: 16px; width: 100%; padding: 14px; border: 0; border-radius: 12px;
  background: linear-gradient(135deg, var(--accent), #3bc9db); color: #06281f;
  font-size: 17px; font-weight: 700; cursor: pointer;
}
.go:disabled { opacity: .45; cursor: not-allowed; }
.hint { margin-top: 12px; color: var(--dim); font-size: 13.5px; text-align: center; }
#progress { display: none; }
.stages { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 18px; }
.st {
  padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line);
  color: var(--dim); font-size: 13px; display: flex; align-items: center; gap: 7px;
}
.st::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--line); }
.st.active { color: var(--text); border-color: var(--accent); }
.st.active::before { background: var(--accent); animation: pulse 1s infinite; }
.st.done { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 50%, transparent); }
.st.done::before { background: var(--accent); }
@keyframes pulse { 50% { opacity: .25; } }
.bar { height: 8px; border-radius: 999px; background: var(--panel2); overflow: hidden; }
.bar i { display: block; height: 100%; width: 4%; border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .5s; }
#plabel { color: var(--dim); font-size: 14px; margin-bottom: 6px; }
#error { display: none; color: var(--danger); margin-top: 12px; white-space: pre-wrap; }
#result { display: none; text-align: center; }
#result .kpi { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin: 16px 0 20px; }
#result .kpi div { background: var(--panel2); border: 1px solid var(--line); border-radius: 12px; padding: 10px 18px; }
#result .kpi b { color: var(--accent); }
.open {
  display: inline-block; padding: 13px 26px; border-radius: 12px; text-decoration: none;
  background: linear-gradient(135deg, var(--accent), #3bc9db); color: #06281f; font-weight: 700;
}
footer { color: var(--dim); font-size: 13px; margin: 8px 0 30px; text-align: center; }
.eq { display: inline-flex; gap: 3px; align-items: flex-end; height: 15px; margin-right: 8px; vertical-align: -2px; }
.eq i { width: 3px; background: var(--accent); border-radius: 2px; animation: eq 1s infinite ease-in-out; }
.eq i:nth-child(1) { height: 60%; animation-delay: 0s; }
.eq i:nth-child(2) { height: 100%; animation-delay: .15s; }
.eq i:nth-child(3) { height: 45%; animation-delay: .3s; }
.eq i:nth-child(4) { height: 80%; animation-delay: .45s; }
@keyframes eq { 50% { transform: scaleY(.35); } }
</style>
</head>
<body>
<header><button class="theme-btn" id="theme" title="Toggle light/dark">🌙</button></header>
<div class="wrap">
  <div class="hero">
    <h1>What are the <em>chords</em> in this song?</h1>
    <p>Paste a YouTube link or drop an audio file. Get the full progression —
       chords, inversions, voicings, harmonic function and the beat grid —
       synced to the music in an interactive player.</p>
  </div>

  <div class="card" id="formcard">
    <div class="tabs">
      <div class="tab on" id="tab_url">YouTube / Spotify link</div>
      <div class="tab" id="tab_file">Upload audio file</div>
    </div>
    <div id="pane_url">
      <input type="url" id="url" placeholder="https://www.youtube.com/watch?v=…" spellcheck="false">
    </div>
    <div id="pane_file" style="display:none">
      <div class="drop" id="drop">
        <b>Drop an audio file</b> here or click to browse<br>
        <span style="font-size:13px">mp3 · m4a · wav · flac · ogg — up to 200 MB</span>
      </div>
      <input type="file" id="file" accept="audio/*,.mp3,.m4a,.wav,.flac,.ogg" style="display:none">
      <div id="fileinfo"></div>
    </div>
    <button class="go" id="go" disabled>Analyze harmony</button>
    <div class="hint">Processing runs locally on this machine — typical song ≈ 30–60 s.</div>
  </div>

  <div class="card" id="progress">
    <div id="plabel">Starting…</div>
    <div class="stages">
      <div class="st" data-st="ingest">audio</div>
      <div class="st" data-st="features">features</div>
      <div class="st" data-st="decode">chords</div>
      <div class="st" data-st="harmony">inversions & voicing</div>
      <div class="st" data-st="rhythm">beat grid</div>
      <div class="st" data-st="render">player</div>
    </div>
    <div class="bar"><i id="barfill"></i></div>
    <div id="error"></div>
  </div>

  <div class="card" id="result">
    <h2 id="rtitle"></h2>
    <div class="kpi" id="rkpi"></div>
    <a class="open" id="ropen" href="#">Open the interactive player →</a>
  </div>

  <footer>harmony analyzer · chords · inversions · voicing · beat grid</footer>
</div>
<script>
"use strict";
const $ = id => document.getElementById(id);
let mode = "url", file = null, jobId = null, timer = null;

// theme ---------------------------------------------------------------------
const saved = localStorage.getItem("harmony-theme");
if (saved === "light") document.body.classList.add("light");
$("theme").textContent = document.body.classList.contains("light") ? "☀️" : "🌙";
$("theme").onclick = () => {
  const light = document.body.classList.toggle("light");
  $("theme").textContent = light ? "☀️" : "🌙";
  localStorage.setItem("harmony-theme", light ? "light" : "dark");
};

// tabs ----------------------------------------------------------------------
$("tab_url").onclick = () => setMode("url");
$("tab_file").onclick = () => setMode("file");
function setMode(m) {
  mode = m;
  $("tab_url").classList.toggle("on", m === "url");
  $("tab_file").classList.toggle("on", m === "file");
  $("pane_url").style.display = m === "url" ? "" : "none";
  $("pane_file").style.display = m === "file" ? "" : "none";
  update();
}

// enable/disable ------------------------------------------------------------
$("url").addEventListener("input", update);
function update() {
  $("go").disabled = mode === "url"
    ? !/^https?:\/\/.+\..+/.test($("url").value.trim())
    : !file;
}

// drag & drop ---------------------------------------------------------------
const drop = $("drop");
drop.onclick = () => $("file").click();
["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add("on");
}));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove("on");
}));
drop.addEventListener("drop", e => {
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});
$("file").addEventListener("change", e => {
  const f = e.target.files[0];
  if (f) setFile(f);
});
function setFile(f) {
  const okExt = /\.(mp3|m4a|mp4|aac|wav|flac|ogg|oga|opus|webm)$/i.test(f.name) || f.type.startsWith("audio/");
  if (!okExt) { $("fileinfo").textContent = "Unsupported file type."; file = null; update(); return; }
  if (f.size > 200 * 1024 * 1024) { $("fileinfo").textContent = "File is larger than 200 MB."; file = null; update(); return; }
  file = f;
  $("fileinfo").textContent = "✓ " + f.name + " (" + (f.size / 1048576).toFixed(1) + " MB)";
  update();
}

// submit --------------------------------------------------------------------
$("go").onclick = async () => {
  $("go").disabled = true;
  $("error").style.display = "none";
  try {
    let res;
    if (mode === "url") {
      res = await fetch("/api/jobs/url", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: $("url").value.trim() }),
      });
    } else {
      const fd = new FormData();
      fd.append("file", file);
      res = await fetch("/api/jobs/file", { method: "POST", body: fd });
    }
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail || res.statusText;
      throw new Error(detail);
    }
    const j = await res.json();
    jobId = j.job_id;
    showProgress();
    timer = setInterval(poll, 1000);
  } catch (err) {
    $("go").disabled = false;
    showError(err.message);
  }
};

// progress ------------------------------------------------------------------
const STAGES = ["ingest", "features", "decode", "harmony", "rhythm", "render"];
function showProgress() {
  $("formcard").style.display = "none";
  $("progress").style.display = "";
  $("result").style.display = "none";
  setBar("queued");
}
function setBar(stage) {
  const idx = STAGES.indexOf(stage);
  const pct = stage === "done" ? 100 : stage === "queued" ? 4 : Math.round(((idx + 1) / (STAGES.length + 1)) * 96);
  $("barfill").style.width = pct + "%";
  $("plabel").textContent = stage === "queued" ? "Queued…"
    : stage === "done" ? "Done"
    : "Analyzing — " + stage + "…";
  document.querySelectorAll(".st").forEach(el => {
    const i = STAGES.indexOf(el.dataset.st);
    el.classList.toggle("done", i < idx || stage === "done");
    el.classList.toggle("active", i === idx);
  });
}
async function poll() {
  if (!jobId) return;
  let j;
  try {
    const res = await fetch("/api/jobs/" + jobId);
    if (!res.ok) throw new Error("lost track of the job (server restarted?)");
    j = await res.json();
  } catch (err) {
    clearInterval(timer); timer = null; showError(err.message); $("go").disabled = false; return;
  }
  setBar(j.stage);
  if (j.stage === "error") {
    clearInterval(timer); timer = null;
    showError(j.error || "analysis failed");
    $("go").disabled = false;
  } else if (j.stage === "done") {
    clearInterval(timer); timer = null;
    showResult(j);
  }
}
function showError(msg) {
  $("error").textContent = "⚠ " + msg;
  $("error").style.display = "";
}

// result --------------------------------------------------------------------
function showResult(j) {
  $("progress").style.display = "none";
  $("result").style.display = "";
  $("rtitle").textContent = j.title || "Untitled";
  const kpis = [
    ["Key", j.key], ["Tempo", j.tempo ? j.tempo + " BPM" : null],
    ["Chords", j.n_chords], ["Length", j.duration ? fmt(j.duration) : null],
  ].filter(k => k[1]);
  $("rkpi").innerHTML = kpis.map(k => "<div>" + k[0] + ": <b>" + k[1] + "</b></div>").join("");
  $("ropen").href = "/player/" + j.job_id;
}
function fmt(sec) {
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m + ":" + String(s).padStart(2, "0");
}
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/jobs/url")
async def create_job_url(payload: dict) -> JSONResponse:
    """Start an analysis job from a YouTube/Spotify URL ({"url": …})."""
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, "empty URL")
    if not (YOUTUBE_RE.search(url) or SPOTIFY_RE.search(url)):
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Only YouTube and Spotify links are supported "
            "(or switch to the file upload tab).",
        )
    work = Path(tempfile.gettempdir()) / "harmony_web" / uuid.uuid4().hex[:12]
    work.mkdir(parents=True, exist_ok=True)
    job = Job(id=uuid.uuid4().hex[:12], kind="url", work_dir=work)
    _register(job)
    _start(job, url)
    return JSONResponse({"job_id": job.id}, status_code=HTTPStatus.ACCEPTED)


@app.post("/api/jobs/file")
async def create_job_file(file: UploadFile = File(...)) -> JSONResponse:
    """Start an analysis job from an uploaded audio file (multipart field: file)."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"Unsupported file type {ext!r} — audio files only.",
        )
    work = Path(tempfile.gettempdir()) / "harmony_web" / uuid.uuid4().hex[:12]
    work.mkdir(parents=True, exist_ok=True)
    dest = work / f"upload{ext}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > UPLOAD_LIMIT_MB * 1024 * 1024:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                    "File exceeds the 200 MB limit.")
            out.write(chunk)
    job = Job(id=uuid.uuid4().hex[:12], kind="upload", work_dir=work)
    _register(job)
    _start(job, str(dest))
    return JSONResponse({"job_id": job.id}, status_code=HTTPStatus.ACCEPTED)


def _register(job: Job) -> None:
    with JOBS_LOCK:
        JOBS[job.id] = job
    _prune_jobs()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "No such job.")
    return _summary(job)


@app.get("/player/{job_id}", response_class=HTMLResponse)
def player(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if job is None or job.work_dir is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "No such job.")
    path = job.work_dir / "player.html"
    if not path.exists():
        raise HTTPException(HTTPStatus.CONFLICT, "Player not ready yet.")
    return FileResponse(path, media_type="text/html")


@app.get("/audio/{job_id}")
def audio(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if job is None or job.audio_path is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "No audio for this job.")
    path = Path(job.audio_path)
    if not path.exists():
        raise HTTPException(HTTPStatus.GONE, "Audio file was cleaned up.")
    return FileResponse(path, media_type=MIME_MAP.get(path.suffix.lower(), "application/octet-stream"),
                        filename=path.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="harmony analyzer web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
