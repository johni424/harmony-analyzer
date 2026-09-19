"""harmony — chord progression, voicing and inversion analyzer."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import report
from .pipeline import analyze

app = typer.Typer(help="Analyze chord progressions, voicings and inversions in songs.")
console = Console()
err = Console(stderr=True)


@app.command()
def analyze_cmd(
    source: str = typer.Argument(..., help="YouTube/Spotify URL or path to an audio file."),
    json_out: Path = typer.Option(None, "--json", help="Write JSON report to this file."),
    md_out: Path = typer.Option(None, "--md", help="Write Markdown report to this file."),
    html_out: Path = typer.Option(None, "--html", help="Write interactive HTML timeline to this file."),
    audio: bool = typer.Option(False, "--audio", help="Embed the audio in the HTML player for playback sync (bigger file)."),
    flats: bool = typer.Option(False, "--flats", help="Use flat spellings (Bb, Eb) instead of sharps."),
    quiet: bool = typer.Option(False, "--quiet", help="Only write the report files, don't print the table."),
) -> None:
    """Analyze a song and print / save the harmony report."""
    sharp = not flats
    try:
        result = analyze(source, verbose=not quiet, keep_audio=audio)
    except Exception as exc:  # typer catches SystemExit separately
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1)

    if not quiet:
        console.print(report.terminal_report(result, sharp=sharp))

    if json_out:
        json_out.write_text(report.json_report(result))
        if not quiet:
            console.print(f"[green]wrote[/green] {json_out}")
    if md_out:
        md_out.write_text(report.markdown_report(result, sharp=sharp))
        if not quiet:
            console.print(f"[green]wrote[/green] {md_out}")
    if html_out:
        html_out.write_text(report.html_report(result, sharp=sharp))
        if not quiet:
            console.print(f"[green]wrote[/green] {html_out}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
