"""Ingest audio from YouTube/Spotify links or local files."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SPOTIFY_RE = re.compile(r"open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)")
YOUTUBE_RE = re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts)")


def classify_source(source: str) -> str:
    if SPOTIFY_RE.search(source):
        return "spotify"
    if YOUTUBE_RE.search(source):
        return "youtube"
    return "file"


def _ytdlp_cmd() -> list[str]:
    """Command prefix for yt-dlp: global binary if present, else venv module."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def _spfc(api: str, sp_id: str) -> str:
    """Fetch a Spotify oEmbed payload (no auth needed)."""
    import json
    import urllib.request

    url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/{api}/{sp_id}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _spotify_search_youtube(title: str, author: str) -> str:
    """Find a YouTube URL for a track by searching with yt-dlp."""
    query = f"ytsearch1:{author} {title} audio"
    out = subprocess.run(
        [*_ytdlp_cmd(), "--print", "url", "--no-download", query],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"Could not find a YouTube source for {title!r}: {out.stderr.strip()[:300]}")
    return out.stdout.strip().splitlines()[0]


def resolve(source: str) -> tuple[str, str, str]:
    """Return (audio_path, title, resolved_source_kind) for a user input."""
    kind = classify_source(source)

    if kind == "file":
        path = Path(source).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No such file: {source}")
        return str(path), path.stem, "file"

    if kind == "youtube":
        vid_title, canonical_url = _ytdlp_metadata(source)
        return _ytdlp_download(source, title=None), vid_title, canonical_url or source

    # Spotify: resolve metadata via oEmbed, then search YouTube for audio.
    match = SPOTIFY_RE.search(source)
    kind_, sp_id = match.group(1), match.group(2)  # type: ignore[union-attr]
    if kind_ != "track":
        raise ValueError(
            "Only individual Spotify tracks are supported for analysis "
            "(albums/playlists: iterate tracks yourself)."
        )
    meta = _spfc("track", sp_id)
    title = str(meta.get("title", "spotify track"))
    yt_url = _spotify_search_youtube(title, str(meta.get("provider_name", "")))
    path = _ytdlp_download(yt_url, title=title)
    return path, title, f"spotify (via youtube)"


def _ytdlp_metadata(url: str) -> tuple[str | None, str | None]:
    """Best-effort fetch of a video's title (and canonical URL) via yt-dlp."""
    try:
        out = subprocess.run(
            [*_ytdlp_cmd(), "--no-playlist", "--skip-download",
             "--print", "%(title)s\t%(webpage_url)s", url],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            fields = out.stdout.strip().splitlines()[0].split("\t")
            title = fields[0].strip()
            if title in ("", "NA", "null"):
                title = None
            page = fields[1].strip() if len(fields) > 1 else None
            return title, page
    except Exception:
        pass
    return None, None


def best_title(audio_path: str, source: str, resolved_title: str | None) -> str:
    """Human-facing song title: resolved metadata, else the filename stem."""
    if resolved_title and resolved_title not in ("youtube audio", "spotify track"):
        return resolved_title
    return Path(audio_path).stem


def _ytdlp_download(url: str, title: str | None) -> str:
    out_dir = Path(tempfile.gettempdir()) / "harmony_analyzer"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / "%(id)s.%(ext)s")
    cmd = [
        *_ytdlp_cmd(),
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "wav",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "-o", out_tmpl,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr.strip()[:500]}")
    # yt-dlp prints the output file when --print is not used; find newest wav.
    wavs = sorted(out_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    if not wavs:
        raise RuntimeError("yt-dlp produced no audio file")
    return str(wavs[-1])
