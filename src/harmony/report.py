"""Output formatting: rich terminal table, JSON, Markdown, HTML timeline player."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from .models import AnalysisResult, pitch_name

_TERMINAL_WIDTH = 100


def terminal_report(result: AnalysisResult, sharp: bool = True) -> str:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    import io

    buf = io.StringIO()
    console = Console(file=buf, width=_TERMINAL_WIDTH, no_color=True)

    key_name = result.key.name(sharp)
    console.print(f"[bold]Song:[/bold] {result.title}")
    console.print(f"[bold]Source:[/bold] {result.source}  |  duration {result.duration:.1f}s"
                  + (f"  |  tempo {result.tempo:.0f} bpm" if result.tempo else ""))
    console.print(f"[bold]Key:[/bold] {key_name}  (confidence {result.key.confidence:.2f})")
    console.print()

    table = Table(box=box.SIMPLE_HEAVY, show_lines=False, padding=(0, 1))
    table.add_column("Start", justify="right")
    table.add_column("End", justify="right")
    table.add_column("Chord", style="bold")
    table.add_column("Inv.", justify="center")
    table.add_column("Function")
    table.add_column("Voicing / extensions")
    table.add_column("Conf.", justify="right")
    table.add_column("Effect / commentary")

    for c in result.chords:
        inv = "—" if c.inversion == 0 else f"{c.inversion}{['st','nd','rd'][min(c.inversion - 1, 2)]}"
        ext = ""
        if c.voicing and c.voicing.extensions:
            names = {1: "b9", 2: "9", 3: "#9", 5: "11", 6: "#11", 8: "b13", 9: "13"}
            ext = ", ".join(names.get(e, str(e)) for e in c.voicing.extensions)
        spacing = c.voicing.spacing if c.voicing else ""
        conf = f"{c.confidence:.2f}"
        table.add_row(
            f"{c.start:6.2f}", f"{c.end:6.2f}", c.symbol(sharp),
            inv, c.function or "—",
            f"{ext or '—'} ({spacing})" if ext else spacing,
            conf, (c.effect or "—")[:60],
        )

    console.print(table)
    return buf.getvalue()


def json_report(result: AnalysisResult) -> str:
    def chord_dict(c) -> dict:
        d = {
            "start": round(c.start, 3),
            "end": round(c.end, 3),
            "chord": c.symbol(),
            "root": pitch_name(c.root_pc),
            "quality": c.quality,
            "inversion": c.inversion,
            "inversion_name": c.inversion_name,
            "bass": pitch_name(c.bass_pc) if c.bass_pc is not None else None,
            "roman": c.function,
            "role": c.role,
            "confidence": round(c.confidence, 3),
        }
        if c.voicing:
            d["voicing"] = {
                "pitch_classes": sorted(pitch_name(p) for p in c.voicing.pitch_classes),
                "extensions": list(c.voicing.extensions),
                "spacing": c.voicing.spacing,
                "added_notes": sorted(pitch_name(p) for p in c.voicing.added_notes),
                "confidence": round(c.voicing.confidence, 3),
            }
        if c.bar is not None:
            d["rhythm"] = {
                "bar": c.bar,
                "beat_in_bar": c.beat_in_bar,
                "beats": c.beats,
                "beat_fraction": c.beat_fraction,
                "pushed": c.pushed,
            }
        if c.effect:
            d["effect"] = c.effect
        return d

    payload = {
        "title": result.title,
        "source": result.source,
        "duration": round(result.duration, 3),
        "key": {"name": result.key.name(), "tonic": pitch_name(result.key.tonic_pc),
                "mode": result.key.mode, "confidence": round(result.key.confidence, 3)},
        "tempo": result.tempo,
        "rhythm": _rhythm_dict(result.rhythm),
        "chords": [chord_dict(c) for c in result.chords],
        "notes": result.notes,
    }
    return json.dumps(payload, indent=2)


def _rhythm_dict(r) -> dict | None:
    if r is None:
        return None
    return {
        "tempo": r.tempo,
        "meter": r.meter,
        "confidence": r.confidence,
        "beat_times": r.beat_times,
        "downbeats": r.downbeats,
    }


def markdown_report(result: AnalysisResult, sharp: bool = True) -> str:
    key_name = result.key.name(sharp)
    lines = [
        f"# Harmony analysis — {result.title}",
        "",
        f"- **Key:** {key_name} (confidence {result.key.confidence:.2f})",
        f"- **Source:** {result.source} — {result.duration:.1f}s",
        "",
        "| Start | End | Chord | Inversion | Function | Voicing | Effect |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in result.chords:
        inv = "root" if c.inversion == 0 else f"{c.inversion}{['st','nd','rd'][min(c.inversion - 1, 2)]}"
        ext = ""
        if c.voicing and c.voicing.extensions:
            names = {1: "b9", 2: "9", 3: "#9", 5: "11", 6: "#11", 8: "b13", 9: "13"}
            ext = ", ".join(names.get(e, str(e)) for e in c.voicing.extensions)
        lines.append(
            f"| {c.start:.2f} | {c.end:.2f} | `{c.symbol(sharp)}` | {inv} | {c.function or ''} "
            f"| {ext or '—'} ({c.voicing.spacing if c.voicing else '—'}) | {c.effect or ''} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML Timeline Player
# ---------------------------------------------------------------------------

# Harmonic role -> (css class, css color).
_FN_COLORS = {
    "tonic": ("fn-tonic", "#26a69a"),
    "predominant": ("fn-pred", "#42a5f5"),
    "dominant": ("fn-dom", "#ef6c00"),
    "borrowed": ("fn-borrowed", "#ab47bc"),
    "secondary": ("fn-secondary", "#8d6e63"),
    "unknown": ("fn-other", "#546e7a"),
}


def _fn(role: str | None, effect: str | None) -> str:
    """Classify a chord into one of the timeline color categories."""
    if role in _FN_COLORS:
        return role
    if effect:
        low = effect.lower()
        if "secondary" in low:
            return "secondary"
        if "borrowed" in low:
            return "borrowed"
    return "unknown"


def _color_classes(role: str | None, effect: str | None) -> str:
    return _FN_COLORS.get(_fn(role, effect), _FN_COLORS["unknown"])[0]


# Shared, self-contained interactive player.
# Chord data is injected as JSON; the audio file (if any) is embedded as a
# base64 data URI so the page works standalone in any browser.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — harmony timeline</title>
<style>
:root {
  --bg: #0e1116; --panel: #161c24; --panel2: #1d2530; --line: #263041;
  --text: #e8ecf1; --muted: #8b98a9;
  --tonic: #26a69a; --pred: #42a5f5; --dom: #ef6c00;
  --borrowed: #ab47bc; --secondary: #8d6e63; --other: #546e7a;
  --accent: #4fc3f7;
  --gridline: rgba(255,255,255,.16); --beatline: rgba(255,255,255,.055);
}
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', 'Inter', sans-serif; background: var(--bg);
       color: var(--text); margin: 0; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 24px 20px 48px; }
header h1 { font-size: 1.35rem; margin: 0; letter-spacing: .2px; }
header .meta { color: var(--muted); font-size: .9rem; margin-top: 6px; }
.kbd { border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font-size: .75rem;
       color: var(--muted); background: var(--panel); }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px;
       vertical-align: baseline; }

.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
        padding: 14px; margin-top: 16px; }

/* --- player row --- */
.player { display: flex; align-items: center; gap: 12px; }
.playbtn { width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
           background: var(--accent); color: #06222e; font-size: 1.1rem; display: flex;
           align-items: center; justify-content: center; flex-shrink: 0; }
.playbtn:hover { filter: brightness(1.1); }
.time { font-variant-numeric: tabular-nums; color: var(--muted); font-size: .85rem;
        min-width: 92px; text-align: center; }
.rhud { display: flex; align-items: center; gap: 8px; margin-left: 6px; color: var(--muted);
        font-size: .85rem; font-variant-numeric: tabular-nums; }
#beatdot { width: 11px; height: 11px; border-radius: 50%; background: var(--panel2);
           border: 1px solid var(--line); transition: transform .09s, background .09s, box-shadow .09s; }
#beatdot.pulse { background: var(--accent); transform: scale(1.35); box-shadow: 0 0 8px rgba(79,195,247,.6); }
#beatdot.pulse.down { background: var(--dom); transform: scale(1.5); box-shadow: 0 0 10px rgba(239,108,0,.7); }
#d-rhythm { font-size: .85rem; color: var(--muted); }
.barline { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--gridline); pointer-events: none; }
.beattick { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--beatline); pointer-events: none; }
.barlab { position: absolute; bottom: 4px; font-size: .62rem; color: var(--muted); transform: translateX(3px); }
.speed { margin-left: auto; display: flex; gap: 6px; }
.speed button { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
                border-radius: 6px; padding: 3px 8px; font-size: .75rem; cursor: pointer; }
.speed button.on { color: var(--accent); border-color: var(--accent); }

/* --- waveform --- */
#wavebox { margin-top: 12px; position: relative; height: 64px; cursor: pointer; }
#wavebox canvas { width: 100%; height: 64px; display: block; }
#playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--accent);
            left: 0; pointer-events: none; }
#wave-load { position: absolute; inset: 0; display: flex; align-items: center;
             justify-content: center; color: var(--muted); font-size: .85rem; }

/* --- chord grid --- */
#grid { position: relative; overflow-x: auto; background: var(--panel2);
        border: 1px solid var(--line); border-radius: 10px; margin-top: 12px; }
#grid-inner { position: relative; height: 158px; min-width: 100%; }
.chord { position: absolute; top: 8px; height: 56px; border-radius: 8px; cursor: pointer;
         display: flex; flex-direction: column; align-items: center; justify-content: center;
         border: 1px solid rgba(255,255,255,.16); overflow: hidden; user-select: none; }
.chord .sym { font-weight: 700; font-size: .95rem; text-shadow: 0 1px 2px rgba(0,0,0,.4); }
.chord .sub { font-size: .68rem; opacity: .85; }
.chord:hover { filter: brightness(1.25); }
.chord.now { box-shadow: 0 0 0 2px #fff, 0 0 14px 2px rgba(79,195,247,.45); z-index: 2; }
.ruler { position: absolute; left: 0; right: 0; top: 70px; height: 80px; pointer-events: none; }
.tick { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(255,255,255,.08); }
.ticklab { position: absolute; top: 64px; font-size: .65rem; color: var(--muted);
           transform: translateX(-50%); }

/* --- detail panel --- */
#detail { margin-top: 14px; }
#detail .head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
#detail .big { font-size: 1.6rem; font-weight: 800; }
#detail .roman { font-size: 1.05rem; color: var(--accent); }
#detail .inv { font-size: .9rem; color: #e8a54b; }
#detail .conf { margin-left: auto; font-size: .8rem; color: var(--muted); }
#detail .confbar { display: inline-block; width: 90px; height: 6px; border-radius: 3px;
                   background: var(--panel2); margin-left: 6px; vertical-align: middle; }
#detail .confbar i { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
#detail .effect { margin-top: 6px; color: #c6d2e0; font-size: .92rem; }
#detail .voicerow { margin-top: 10px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
#detail .piano svg { display: block; }
#detail .pcs { font-size: .85rem; color: var(--muted); }
.pchip { display: inline-block; border: 1px solid var(--line); background: var(--panel2);
         border-radius: 5px; padding: 2px 7px; margin-right: 5px; font-size: .8rem; }
.pchip.ext { color: #f0b060; border-color: #7a5a30; }
.pchip.add { color: #cf8fdf; border-color: #6a4a72; }

/* --- table --- */
table { border-collapse: collapse; margin-top: 14px; width: 100%; font-size: .85rem; }
th, td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--panel); }
tr.trow:hover, tr.trow.now { background: var(--panel2); cursor: pointer; }
td.sym { font-weight: 700; }

/* --- export buttons --- */
.exports { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
.exports button { background: var(--panel2); color: var(--text); border: 1px solid var(--line);
                 border-radius: 7px; padding: 5px 12px; font-size: .8rem; cursor: pointer; }
.exports button:hover { border-color: var(--accent); color: var(--accent); }
.nosound { margin-top: 8px; color: var(--muted); font-size: .8rem; }

/* --- transport: start/stop + pause --- */
.pausebtn { width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--line);
            cursor: pointer; background: var(--panel2); color: var(--text); font-size: .95rem;
            display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.pausebtn:disabled { opacity: .35; cursor: default; }
.pausebtn:not(:disabled):hover { border-color: var(--accent); color: var(--accent); }

/* --- theme toggle --- */
.titlerow { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.themebtn { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
            border-radius: 7px; padding: 5px 12px; font-size: .8rem; cursor: pointer; }
.themebtn:hover { border-color: var(--accent); color: var(--accent); }
body.light {
  --bg: #f4f6f9; --panel: #ffffff; --panel2: #eaeff5; --line: #d7dfe8;
  --text: #16202b; --muted: #5f6f80; --wave: #b9c6d4; --accent: #0288d1;
  --gridline: rgba(22,32,43,.22); --beatline: rgba(22,32,43,.07);
}
body.light .chord { border-color: rgba(0,0,0,.2); }

/* --- print / PDF export --- */
#printdoc { display: none; }
@media print {
  @page { size: A4; margin: 14mm; }
  body { background: #fff; color: #111; }
  #app { display: none !important; }
  #printdoc { display: block; font-size: 10.5pt; }
  #printdoc h1 { font-size: 16pt; margin: 0 0 2mm; }
  #printdoc .meta { color: #444; margin-bottom: 4mm; }
  #printdoc .strip { font-size: 12.5pt; font-weight: 600; line-height: 1.65; margin-bottom: 5mm; }
  #printdoc table { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
  #printdoc th, #printdoc td { border: .5pt solid #999; padding: 2.5pt 4pt; text-align: left; }
  #printdoc th { background: #eee; }
  #printdoc tr { page-break-inside: avoid; }
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="titlerow">
      <h1>__TITLE__</h1>
      <button id="theme" class="themebtn" title="Switch light/dark theme">☀ Light</button>
    </div>
    <div class="meta">
      Key: <strong>__KEY__</strong> · __DUR__ · source: __SOURCE__ ·
      __NCHORDS__ chords · __RHYTHM_META__
      <span class="dot" style="background:var(--tonic)"></span>tonic
      <span class="dot" style="background:var(--pred)"></span>predominant
      <span class="dot" style="background:var(--dom)"></span>dominant
      <span class="dot" style="background:var(--borrowed)"></span>borrowed
      <span class="dot" style="background:var(--secondary)"></span>secondary dom
      · <span class="kbd">space</span> play <span class="kbd">←→</span> chord
    </div>
  </header>

  <div class="card">
    <div class="player">
      <button id="btn-start" class="playbtn" title="Start (space)">▶</button>
      <button id="btn-pause" class="pausebtn" title="Pause" disabled>⏸</button>
      <div class="time"><span id="tcur">0:00</span> / <span id="tdur">0:00</span></div>
      <div class="rhud" id="rhudwrap" style="display:none"><span id="beatdot"></span><span id="rhud">—</span></div>
      <div class="speed">
        <button data-r="0.5">0.5×</button><button data-r="1" class="on">1×</button><button data-r="1.5">1.5×</button>
      </div>
    </div>
    <div id="wavebox">
      <canvas id="wave"></canvas>
      <div id="playhead"></div>
      <div id="wave-load">computing waveform…</div>
    </div>
    <div id="grid"><div id="grid-inner"></div></div>
    <div class="nosound" id="nosound" style="display:none">
      No audio embedded — visual navigation only (use ← → or click a chord).
    </div>
  </div>

  <div class="card" id="detail">
    <div class="head">
      <span class="big" id="d-sym">—</span>
      <span class="roman" id="d-roman"></span>
      <span class="inv" id="d-inv"></span>
      <span id="d-rhythm"></span>
      <span class="conf" id="d-conf"></span>
    </div>
    <div class="effect" id="d-effect"></div>
    <div class="voicerow">
      <span class="piano" id="d-piano"></span>
      <span class="pcs" id="d-pcs"></span>
    </div>
  </div>

  <table id="tbl">
    <thead><tr><th>Start</th><th>End</th><th>Chord</th><th>Inversion</th><th>Function</th><th>Conf.</th></tr></thead>
    <tbody></tbody>
  </table>

  <div class="exports">
    <button id="dl-pdf">Export PDF</button>
    <button id="dl-json">Download JSON</button>
    <button id="dl-md">Download Markdown</button>
  </div>
</div>

__PRINTDOC__

<script>
const CHORDS = __CHORDS_JSON__;
const KEY = __KEY_JSON__;
const TITLE = __TITLE_JSON__;
const DURATION = __DURATION__;
const AUDIO_URI = __AUDIO_URI__;   // data URI string, or null
const REPORT_JSON = __REPORT_JSON__;
const REPORT_MD = __REPORT_MD__;
const RHYTHM = __RHYTHM_JSON__;

const $ = (id) => document.getElementById(id);
const fmt = (t) => Math.floor(t/60) + ':' + String(Math.floor(t%60)).padStart(2, '0');

/* ---------- state ---------- */
let audio = null, rafId = null, wavePeak = null, ticking = false;

/* ---------- audio / transport ---------- */
function initAudio() {
  if (!AUDIO_URI) { $('nosound').style.display = ''; renderTransport(); return; }
  audio = new Audio(AUDIO_URI);
  audio.preload = 'auto';
  audio.addEventListener('loadedmetadata', () => { $('tdur').textContent = fmt(audio.duration); });
  audio.addEventListener('play', () => { renderTransport(); startTick(); });
  audio.addEventListener('pause', () => { renderTransport(); stopTick(); });
  audio.addEventListener('ended', () => { renderTransport(); stopTick(); setNow(null); });
  renderTransport();
}
function isPlaying() { return !!(audio && !audio.paused && !audio.ended); }
function renderTransport() {
  const playing = isPlaying();
  $('btn-start').textContent = playing ? '⏹' : '▶';
  $('btn-start').title = playing ? 'Stop — back to 0:00' : 'Start (space)';
  $('btn-pause').disabled = !playing;
}
function startPlayback() {
  if (!audio) { $('nosound').style.display = ''; return; }
  if (audio.ended || audio.currentTime >= (audio.duration || DURATION) - 0.05) audio.currentTime = 0;
  audio.play();
}
function stopPlayback() {
  if (!audio) return;
  audio.pause();
  audio.currentTime = 0;
  $('tcur').textContent = '0:00';
  drawPlayhead(0, true);
  setNow(chordAt(0), false);
}
function togglePause() {
  if (!audio) { $('nosound').style.display = ''; return; }
  if (audio.paused) audio.play(); else audio.pause();
}
function startTick() { if (!ticking) { ticking = true; tick(); } }
function stopTick() { ticking = false; if (rafId) cancelAnimationFrame(rafId); }
function seek(t, andPlay) {
  if (audio) {
    audio.currentTime = Math.max(0, Math.min(t, audio.duration || DURATION));
    if (andPlay) audio.play();
  }
  drawPlayhead(t, true);
  setNow(chordAt(t), true);
}
function tick() {
  if (!audio || !ticking) return;
  drawPlayhead(audio.currentTime, false);
  $('tcur').textContent = fmt(audio.currentTime);
  updateBeatPulse(audio.currentTime);
  setNow(chordAt(audio.currentTime), false);
  rafId = requestAnimationFrame(tick);
}

/* ---------- waveform (decoded locally; no round-trip) ---------- */
function initWave() {
  if (!AUDIO_URI) { $('wave-load').textContent = 'no audio embedded'; return; }
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  fetch(AUDIO_URI).then(r => r.arrayBuffer())
    .then(buf => ctx.decodeAudioData(buf))
    .then(buf => {
      const ch = buf.getChannelData(0);
      const N = 1200, block = Math.floor(ch.length / N), peaks = new Float32Array(N);
      for (let i = 0; i < N; i++) {
        let m = 0;
        for (let j = i * block; j < (i + 1) * block && j < ch.length; j += 16) {
          const v = Math.abs(ch[j]); if (v > m) m = v;
        }
        peaks[i] = m;
      }
      wavePeak = peaks;
      $('wave-load').style.display = 'none';
      drawWave();
    })
    .catch(() => { $('wave-load').textContent = 'waveform unavailable'; });
}
function drawWave() {
  const cv = $('wave'), dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d'); g.scale(dpr, dpr);
  g.clearRect(0, 0, W, H);
  if (!wavePeak) return;
  g.fillStyle = (getComputedStyle(document.body).getPropertyValue('--wave') || '#2c3a4d').trim() || '#2c3a4d';
  const N = wavePeak.length;
  for (let i = 0; i < N; i++) {
    const x = i / N * W, h = Math.max(1, wavePeak[i] * (H * 0.92));
    g.fillRect(x, (H - h) / 2, Math.max(1, W / N - 0.5), h);
  }
}
function drawPlayhead(t, force) {
  const W = $('wavebox').clientWidth;
  $('playhead').style.left = (t / DURATION * W) + 'px';
}
$('wavebox').addEventListener('click', (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  seek((e.clientX - r.left) / r.width * DURATION, false);
});

/* ---------- chord grid ---------- */
function buildGrid() {
  const inner = $('grid-inner');
  const pxPerSec = Math.max(24, 2400 / Math.max(60, DURATION));  // ~scrollable width
  inner.style.width = (DURATION * pxPerSec) + 'px';
  // bar + beat lines under the chord blocks (rhythmic alignment aid)
  if (RHYTHM && RHYTHM.beat_times && RHYTHM.beat_times.length) {
    RHYTHM.beat_times.forEach((t, bi) => {
      if (!RHYTHM.downbeats.includes(bi)) {
        const tick = document.createElement('div');
        tick.className = 'beattick'; tick.style.left = (t * pxPerSec) + 'px';
        inner.appendChild(tick);
      }
    });
    RHYTHM.downbeats.forEach(bi => {
      const t = RHYTHM.beat_times[bi];
      const bar = document.createElement('div');
      bar.className = 'barline'; bar.style.left = (t * pxPerSec) + 'px';
      const lab = document.createElement('div');
      lab.className = 'barlab'; lab.style.left = (t * pxPerSec) + 'px';
      lab.textContent = (bi / RHYTHM.meter + 1).toFixed(0);
      inner.appendChild(bar); inner.appendChild(lab);
    });
  }
  CHORDS.forEach((c, i) => {
    const cls = c.fncls, w = Math.max(14, (c.end - c.start) * pxPerSec - 3);
    const el = document.createElement('div');
    el.className = 'chord ' + cls;
    el.style.left = (c.start * pxPerSec) + 'px';
    el.style.width = w + 'px';
    const conf = c.conf;
    el.style.background = colorOf(cls);
    el.style.opacity = (0.55 + 0.45 * Math.min(1, conf * 2.2)).toFixed(2);
    el.innerHTML = `<span class="sym">${esc(c.symbol)}</span>` +
      `<span class="sub">${esc(c.roman)}${c.inv ? ' · ' + ordInv(c.inv) + ' inv' : ''}</span>`;
    el.title = `${c.symbol} (${c.roman}) — ${c.effect}`;
    el.onclick = () => { selectChord(i); seek(c.start + 0.02, true); };
    el.dataset.i = i;
    inner.appendChild(el);
  });
  // time ruler
  const ruler = document.createElement('div');
  ruler.className = 'ruler';
  const step = DURATION > 240 ? 30 : DURATION > 90 ? 15 : 10;
  for (let t = 0; t <= DURATION; t += step) {
    const tk = document.createElement('div');
    tk.className = 'tick'; tk.style.left = (t * pxPerSec) + 'px';
    const lab = document.createElement('div');
    lab.className = 'ticklab'; lab.style.left = (t * pxPerSec) + 'px';
    lab.textContent = fmt(t);
    ruler.appendChild(tk); ruler.appendChild(lab);
  }
  inner.appendChild(ruler);
}
function colorOf(cls) {
  const map = { 'fn-tonic': 'var(--tonic)', 'fn-pred': 'var(--pred)', 'fn-dom': 'var(--dom)',
                'fn-borrowed': 'var(--borrowed)', 'fn-secondary': 'var(--secondary)',
                'fn-other': 'var(--other)' };
  return map[cls] || 'var(--other)';
}
function chordAt(t) {
  for (let i = 0; i < CHORDS.length; i++)
    if (t >= CHORDS[i].start && t < CHORDS[i].end) return i;
  return null;
}

/* ---------- now-playing / detail ---------- */
let nowIdx = null;
function setNow(i, scroll) {
  if (i === nowIdx) return;
  document.querySelectorAll('.chord.now').forEach(e => e.classList.remove('now'));
  document.querySelectorAll('tr.trow.now').forEach(e => e.classList.remove('now'));
  nowIdx = i;
  if (i === null) { $('tcur').textContent = fmt(audio ? audio.currentTime : 0); return; }
  const el = document.querySelector(`.chord[data-i="${i}"]`);
  if (el) { el.classList.add('now'); if (scroll) el.scrollIntoView({behavior:'smooth', inline:'center', block:'nearest'}); }
  const row = document.querySelector(`tr.trow[data-i="${i}"]`);
  if (row) row.classList.add('now');
  showDetail(i);
}
function selectChord(i) {
  const el = document.querySelector(`.chord[data-i="${i}"]`);
  if (el) el.scrollIntoView({behavior:'smooth', inline:'center', block:'nearest'});
  setNow(i, false);
}
function showDetail(i) {
  const c = CHORDS[i];
  $('d-sym').textContent = c.symbol;
  $('d-roman').textContent = c.roman ? `(${c.roman} · ${c.role})` : '';
  $('d-inv').textContent = c.inv ? c.inv + ' inversion — bass ' + c.bass : '';
  $('d-conf').innerHTML = 'confidence ' + c.conf.toFixed(2) +
    `<span class="confbar"><i style="width:${Math.round(Math.min(1, c.conf * 2.2) * 100)}%"></i></span>`;
  $('d-effect').textContent = c.effect || '';
  $('d-rhythm').textContent = rhythmText(c);
  $('d-piano').innerHTML = pianoSVG(c.pcs, c.root, c.bass);
  const chips = c.pcs.map(p => {
    const isRoot = p === c.root, isBass = p === c.bass;
    const isExt = c.exts.includes(p) && !isChordTone(c, p);
    const cls = isExt ? 'ext' : (c.adds.includes(p) ? 'add' : '');
    const tag = isRoot ? ' (root)' : (isBass && !isRoot ? ' (bass)' : '');
    return `<span class="pchip ${cls}">${p}${tag}</span>`;
  }).join('');
  $('d-pcs').innerHTML = chips || '<span class="pchip">no pitches detected</span>';
}
function isChordTone(c, p) {
  return c.pcs.indexOf(p) >= 0 && !c.adds.includes(p);
}

/* 2-octave piano SVG; keys lit for present pitches, bass key highlighted */
function pianoSVG(pcs, root, bass) {
  const W = 196, H = 64, white = [0,2,4,5,7,9,11];
  // black key pitch class -> white-key boundary it sits on (1 = between 1st/2nd white key)
  const black = {1:1, 3:2, 6:4, 8:5, 10:6};
  const pcSet = pcs.map(pcsIndex);  // pitch-class numbers
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  const ww = W / 14;
  for (let o = 0; o < 2; o++)
    for (let i = 0; i < 7; i++) {
      const pc = white[i], x = (o * 7 + i) * ww;
      const on = pcSet.includes(pc);
      const isBass = bass !== null && pcsIndex(bass) === pc && o === 0;
      s += `<rect x="${x}" y="1" width="${ww - 1}" height="${H - 2}" rx="2"
        fill="${on ? (isBass ? '#4fc3f7' : '#e8ecf1') : '#1d2530'}"
        stroke="#263041"/>`;
    }
  for (let o = 0; o < 2; o++)
    for (const [pc, b] of Object.entries(black)) {
      const p = parseInt(pc), x = (o * 7 + b) * ww - ww * 0.31;
      const on = pcSet.includes(p);
      s += `<rect x="${x}" y="1" width="${ww * 0.62}" height="${H * 0.6}" rx="2"
        fill="${on ? '#4fc3f7' : '#0e1116'}" stroke="#263041"/>`;
    }
  return s + '</svg>';
}
function pcsIndex(p) {
  const N = {C:0,'C#':1,Db:1,D:2,'D#':3,Eb:3,E:4,F:5,'F#':6,Gb:6,G:7,'G#':8,Ab:8,A:9,'A#':10,Bb:10,B:11};
  return N[p] !== undefined ? N[p] : 0;
}
function rhythmText(c) {
  if (c.bar === undefined || c.bar === null) return '';
  let s = 'bar ' + c.bar + ', beat ' + c.beat_in_bar;
  if (c.beat_fraction) s += ' · ' + (c.beat_fraction % 1 ? c.beat_fraction.toFixed(1) : c.beat_fraction) + ' beats';
  if (c.pushed) s += ' · pushed (off-beat entry)';
  return s;
}
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function ordInv(n) { return n + ({1:'st',2:'nd',3:'rd'}[n] || 'th'); }

/* ---------- table ---------- */
function buildTable() {
  const tb = $('tbl').tBodies[0];
  CHORDS.forEach((c, i) => {
    const tr = tb.insertRow(-1);
    tr.className = 'trow'; tr.dataset.i = i;
    [fmt(c.start), fmt(c.end), c.symbol, c.inv ? ordInv(c.inv) + ' inversion' : 'root', c.roman, c.conf.toFixed(2)]
      .forEach(v => { const td = tr.insertCell(-1); td.textContent = v; if (v === c.symbol) td.className = 'sym'; });
    tr.onclick = () => { selectChord(i); seek(c.start + 0.02, true); };
  });
}

/* ---------- exports ---------- */
function dl(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type: 'text/plain'}));
  a.download = name; a.click();
  URL.revokeObjectURL(a.href);
}
$('dl-json').onclick = () => dl(TITLE.replace(/\\W+/g, '_') + '_harmony.json', REPORT_JSON);
$('dl-md').onclick = () => dl(TITLE.replace(/\\W+/g, '_') + '_harmony.md', REPORT_MD);

/* ---------- speed + transport + keyboard ---------- */
$('btn-start').onclick = () => isPlaying() ? stopPlayback() : startPlayback();
$('btn-pause').onclick = () => togglePause();
$('dl-pdf').onclick = () => window.print();
document.querySelectorAll('.speed button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('.speed button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    if (audio) audio.playbackRate = parseFloat(b.dataset.r);
  };
});
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (!CHORDS.length) return;
  if (e.code === 'Space') { e.preventDefault(); isPlaying() ? audio.pause() : startPlayback(); }
  else if (e.key === 'ArrowRight') { const i = Math.min(CHORDS.length - 1, (nowIdx ?? -1) + 1); selectChord(i); seek(CHORDS[i].start + 0.02, false); }
  else if (e.key === 'ArrowLeft') { const i = Math.max(0, (nowIdx ?? 1) - 1); selectChord(i); seek(CHORDS[i].start + 0.02, false); }
});
window.addEventListener('resize', () => { drawWave(); });

/* ---------- beat pulse ---------- */
let lastBeatIdx = -2, pulseTimer = null;
function updateBeatPulse(t) {
  if (!RHYTHM || !RHYTHM.beat_times || !RHYTHM.beat_times.length) return;
  const beats = RHYTHM.beat_times;
  // binary search for the last beat at-or-before t
  let lo = 0, hi = beats.length - 1, j = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (beats[mid] <= t) { j = mid; lo = mid + 1; } else hi = mid - 1; }
  if (j !== lastBeatIdx) {
    lastBeatIdx = j;
    if (j >= 0) {
      const dot = $('beatdot');
      const isDown = RHYTHM.downbeats.includes(j);
      dot.className = 'pulse' + (isDown ? ' down' : '');
      if (pulseTimer) clearTimeout(pulseTimer);
      pulseTimer = setTimeout(() => { dot.className = ''; }, 120);
    }
  }
}

/* ---------- boot ---------- */
function applyTheme(light) {
  document.body.classList.toggle('light', light);
  $('theme').textContent = light ? '🌙 Dark' : '☀ Light';
  try { localStorage.setItem('harmony-theme', light ? 'light' : 'dark'); } catch (e) {}
  drawWave();
}
$('theme').onclick = () => applyTheme(!document.body.classList.contains('light'));
let savedTheme = null; try { savedTheme = localStorage.getItem('harmony-theme'); } catch (e) {}
applyTheme(savedTheme === 'light');

initAudio();
buildGrid();
buildTable();
initWave();
drawPlayhead(0, true);
if (RHYTHM && RHYTHM.beat_times && RHYTHM.beat_times.length) {
  $('rhudwrap').style.display = '';
  $('rhud').textContent = RHYTHM.tempo + ' BPM · ' + RHYTHM.meter + '/4';
}
if (CHORDS.length) { showDetail(0); setNow(chordAt(0), false); }
$('tdur').textContent = fmt(DURATION);
</script>
</body>
</html>"""


def _print_document(result: AnalysisResult, sharp: bool) -> str:
    """Print-optimized section (used by the browser's Save-as-PDF export):
    the full progression strip plus a table with chords, inversions, voicing."""
    rows = []
    for c in result.chords:
        inv = "root" if c.inversion == 0 else \
            f"{c.inversion}{['st', 'nd', 'rd'][min(c.inversion - 1, 2)]} inv"
        ext = pcs = adds = spacing = place = ""
        if c.voicing:
            names = {1: "b9", 2: "9", 3: "#9", 5: "11", 6: "#11", 8: "b13", 9: "13"}
            ext = ", ".join(names.get(e, str(e)) for e in c.voicing.extensions)
            pcs = " ".join(sorted(pitch_name(p, sharp) for p in c.voicing.pitch_classes))
            adds = " ".join(sorted(pitch_name(p, sharp) for p in c.voicing.added_notes))
            spacing = c.voicing.spacing
        if c.bar is not None:
            place = f"bar {c.bar}, beat {c.beat_in_bar}"
            if c.pushed:
                place += " (pushed)"
        rows.append(
            f"<tr><td>{c.start:.2f}</td><td>{c.end:.2f}</td>"
            f"<td><b>{_esc_html(c.symbol(sharp))}</b></td>"
            f"<td>{_esc_html(c.function or '')}</td><td>{inv}</td>"
            f"<td>{place}</td>"
            f"<td>{_esc_html(c.effect or '')}</td>"
            f"<td>{pcs}</td><td>{ext or '—'}</td><td>{adds}</td>"
            f"<td>{spacing}</td><td>{c.confidence:.2f}</td></tr>"
        )
    strip = " → ".join(_esc_html(c.symbol(sharp)) for c in result.chords)
    return (
        '<div id="printdoc">'
        f"<h1>{_esc_html(result.title)}</h1>"
        f'<div class="meta">{_esc_html(result.key.name(sharp))} · {result.duration:.0f}s · '
        f"{_esc_html(result.source)} · {len(result.chords)} chords"
        + (f" · {result.rhythm.tempo:.0f} BPM · {result.rhythm.meter}/4" if result.rhythm else "")
        + " — harmony &amp; rhythm analysis: progression, inversions, voicing, bar placement</div>"
        f'<div class="strip">{strip}</div>'
        "<table><thead><tr><th>Start</th><th>End</th><th>Chord</th><th>Function</th>"
        "<th>Inversion</th><th>Position</th><th>Effect</th><th>Voicing</th><th>Ext.</th>"
        "<th>Color tones</th><th>Spacing</th><th>Conf.</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</div>"
    )


def html_report(result: AnalysisResult, sharp: bool = True) -> str:
    """Standalone interactive Timeline Player (audio-embedded when available)."""
    chords_data = []
    for c in result.chords:
        vc = c.voicing
        chords_data.append({
            "start": round(c.start, 3),
            "end": round(c.end, 3),
            "symbol": c.symbol(sharp),
            "roman": c.function or "",
            "role": c.role or "",
            "inv": c.inversion,
            "bass": pitch_name(c.bass_pc, sharp) if c.bass_pc is not None else None,
            "conf": round(c.confidence, 2),
            "effect": c.effect or "",
            "root": pitch_name(c.root_pc, sharp),
            "bar": c.bar,
            "beat_in_bar": c.beat_in_bar,
            "beats": c.beats,
            "beat_fraction": c.beat_fraction,
            "pushed": c.pushed,
            "pcs": sorted(pitch_name(p, sharp) for p in vc.pitch_classes) if vc else [],
            "exts": [pitch_name(c.root_pc + i, sharp) for i in (vc.extensions if vc else ())],
            "adds": sorted(pitch_name(p, sharp) for p in vc.added_notes) if vc else [],
            "fncls": _color_classes(c.role, c.effect),
        })

    audio_uri = None
    if result.audio_path:
        p = Path(result.audio_path)
        if p.exists():
            mime = _audio_mime(p)
            audio_uri = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    report_json = json_report(result)
    report_md = markdown_report(result, sharp)

    html = _HTML_TEMPLATE
    for k, v in {
        "__TITLE__": _esc_html(result.title),
        "__KEY__": _esc_html(result.key.name(sharp)),
        "__DUR__": f"{result.duration:.0f}s",
        "__SOURCE__": _esc_html(result.source),
        "__NCHORDS__": str(len(result.chords)),
        "__CHORDS_JSON__": json.dumps(chords_data, ensure_ascii=False),
        "__KEY_JSON__": json.dumps({"name": result.key.name(sharp), "conf": round(result.key.confidence, 2)}),
        "__TITLE_JSON__": json.dumps(result.title, ensure_ascii=False),
        "__DURATION__": f"{max(0.001, result.duration):.3f}",
        "__AUDIO_URI__": json.dumps(audio_uri),
        "__REPORT_JSON__": json.dumps(report_json),
        "__REPORT_MD__": json.dumps(report_md),
        "__PRINTDOC__": _print_document(result, sharp),
        "__RHYTHM_JSON__": json.dumps(_rhythm_dict(result.rhythm)),
        "__RHYTHM_META__": (
            f"{result.rhythm.tempo:.0f} BPM · {result.rhythm.meter}/4"
            if result.rhythm else "no beat grid"
        ),
    }.items():
        html = html.replace(k, v)
    return html


def _esc_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# Browsers are picky about audio container mime types in data URIs
# (e.g. Python reports .m4a as audio/mp4a-latm, which Chromium rejects).
_AUDIO_MIME = {
    ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".mp4": "audio/mp4",
    ".aac": "audio/aac", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".flac": "audio/flac", ".webm": "audio/webm",
}


def _audio_mime(p: Path) -> str:
    mime = _AUDIO_MIME.get(p.suffix.lower()) \
        or mimetypes.guess_type(str(p))[0] \
        or "audio/mpeg"
    return mime if mime.startswith("audio/") else "audio/mpeg"
