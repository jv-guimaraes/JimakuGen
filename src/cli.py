import typer
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from src.config import PROJECT_ROOT, API_KEY, DEFAULT_MODEL
from src.core import process_video
import logging

app = typer.Typer(help="JimakuGen: AI-powered Japanese subtitle generator.")
console = Console()

@app.command()
def config(
    api_key: str = typer.Option(None, "--api-key", help="Google Gemini API Key"),
):
    """
    Configure JimakuGen settings.
    """
    env_path = PROJECT_ROOT / ".env"
    
    if not api_key:
        api_key = Prompt.ask("Enter your Google Gemini API Key", default=API_KEY or "", password=True)
    
    if api_key:
        with open(env_path, "w") as f:
            f.write(f"GOOGLE_API_KEY={api_key}\n")
        console.print(Panel(f"API Key saved to [bold]{env_path}[/bold]", title="Success", border_style="green"))
    else:
        console.print("[red]API Key is required to run JimakuGen.[/red]")

@app.command()
def run(
    video_file: Path = typer.Argument(..., help="Path to the video file", exists=True, file_okay=True, dir_okay=False, readable=True),
    output: Path = typer.Option(None, "--output", "-o", help="Custom output SRT path"),
    context: Path = typer.Option(None, "--context", "-c", help="Path to context file (names, lore, etc.)", exists=True, file_okay=True),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Gemini model to use"),
    chunk_size: int = typer.Option(90, "--chunk-size", help="Target duration for audio chunks in seconds"),
    limit: int = typer.Option(None, "--limit", help="Limit processing to N chunks (for testing)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Keep temporary files after processing"),
):
    """
    Generate Japanese subtitles for a video file.
    """
    if not os.getenv("GOOGLE_API_KEY") and not API_KEY:
        console.print(Panel("Google API Key not found. Please run [bold]jimakugen config[/bold] first.", title="Error", border_style="red"))
        raise typer.Exit(code=1)

    process_video(
        video_file=str(video_file),
        output_path=str(output) if output else None,
        model=model,
        chunk_size=chunk_size,
        context_path=str(context) if context else None,
        limit=limit,
        verbose=verbose,
        keep_temp=keep_temp
    )

@app.command()
def check():
    """
    Check environment and dependencies.
    """
    import shutil
    from src.utils import run_command
    
    console.print("[bold]Checking JimakuGen Environment...[/bold]\n")
    
    # Check FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        console.print(f"[green]✓[/green] FFmpeg found: {ffmpeg_path}")
    else:
        console.print("[red]✗[/red] FFmpeg NOT found. Please install it.")

    # Check FFprobe
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        console.print(f"[green]✓[/green] FFprobe found: {ffprobe_path}")
    else:
        console.print("[red]✗[/red] FFprobe NOT found. Please install it.")

    # Check API Key
    if os.getenv("GOOGLE_API_KEY") or API_KEY:
        console.print("[green]✓[/green] Google API Key configured.")
    else:
        console.print("[red]✗[/red] Google API Key NOT found. Run 'jimakugen config' to set it.")

    # Check Internet / API Access (Optional but nice)
    console.print("\n[dim]To test API connectivity, try running 'jimakugen run' on a small sample.[/dim]")

if __name__ == "__main__":
    app()
