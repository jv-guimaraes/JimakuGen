import os
import shutil
import logging
import tempfile
from datetime import timedelta
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.panel import Panel
from rich.console import Console

from src.config import DEFAULT_MODEL, CACHE_DIR, CHUNK_TARGET_SECONDS, AUDIO_PADDING_MS, MAX_RETRIES
from src.logger import setup_logging
from src.utils import get_cache_path, ms_to_mm_ss_mmm, parse_timestamps, ms_to_srt_time, validate_chunk, SubtitleEvent
from src.media_utils import MediaProcessor, get_dialogue_from_ass, group_events
from src.transcriber import Transcriber, RateLimitError

logger = logging.getLogger(__name__)
console = Console()

class SubtitleJob:
    def __init__(self, video_file: str, output_path: str | None = None, model: str = DEFAULT_MODEL, chunk_size: int = CHUNK_TARGET_SECONDS, context_path: str | None = None, limit: int | None = None, keep_temp: bool = False, verbose: bool = False):
        self.video_file = video_file
        self.output_path = output_path or self._default_output_path()
        self.model = model
        self.chunk_size = chunk_size
        self.context_path = context_path
        self.limit = limit
        self.keep_temp = keep_temp
        self.verbose = verbose
        
        self.temp_dir = tempfile.mkdtemp(prefix="jimakugen_")
        self.media = MediaProcessor()
        self.transcriber = Transcriber()
        self.series_context = self._load_context()
        
        self.final_subs: list[SubtitleEvent] = []
        self.stop_requested = False

    def _default_output_path(self) -> str:
        base, _ = os.path.splitext(self.video_file)
        return f"{base}.ja.srt"

    def _load_context(self) -> str | None:
        if not self.context_path:
            return None
        try:
            with open(self.context_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Failed to read context file: {e}")
            return None

    def cleanup(self):
        if self.keep_temp:
            logger.info(f"Temporary directory kept at: {self.temp_dir}")
        else:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.debug(f"Cleaned up temporary directory: {self.temp_dir}")

    def run(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            
            if not self.media.is_valid_media(self.video_file):
                logger.error(f"Invalid media file: {self.video_file}")
                console.print(f"[bold red]Error:[/bold red] '{self.video_file}' is not a valid media file or cannot be read.")
                return

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
                disable=self.verbose
            ) as setup_progress:
                task_id = setup_progress.add_task("Initializing...", total=None)

                # 1. Track Selection
                setup_progress.update(task_id, description="Selecting tracks...")
                best_sub = self.media.get_best_subtitle_track(self.video_file)
                best_audio = self.media.get_best_audio_track(self.video_file)

                if not best_sub:
                    setup_progress.stop()
                    logger.error("No suitable English subtitle track found.")
                    console.print("[bold red]Error:[/bold red] No suitable English subtitle track found in the video.")
                    return

                if not best_audio:
                    setup_progress.stop()
                    logger.error("No audio track found.")
                    console.print("[bold red]Error:[/bold red] No audio track found in the video.")
                    return

                audio_index = best_audio['index']
                
                # 2. Subtitle Extraction & Grouping
                setup_progress.update(task_id, description="Extracting subtitles...")
                temp_ass = os.path.join(self.temp_dir, "extracted.ass")
                try:
                    self.media.extract_subtitles(self.video_file, best_sub['index'], temp_ass)
                except Exception as e:
                    setup_progress.stop()
                    logger.error(f"Failed to extract subtitles: {e}")
                    console.print(f"[bold red]Error:[/bold red] Failed to extract subtitles with FFmpeg.")
                    return
                
                events = get_dialogue_from_ass(temp_ass)
                if not events:
                    setup_progress.stop()
                    logger.error("No dialogue events found in extracted subtitles.")
                    console.print("[bold red]Error:[/bold red] No dialogue events found. The subtitle track might be empty or incompatible.")
                    return

                clusters = group_events(events, target_duration=self.chunk_size)
                total_chunks = len(clusters)
                if self.limit:
                    total_chunks = min(total_chunks, self.limit)
                
                # 3. Show Summary Panel
                if not self.verbose:
                    def fmt_track(track):
                        if not track: return "None"
                        parts = [f"#{track['index']}"]
                        if track.get('lang'): parts.append(f"[{track['lang']}]")
                        if track.get('title'): parts.append(f"({track['title']})")
                        return " ".join(parts)

                    console.print() # Ensure clean line
                    summary_text = (
                        f"  [bold]Input:[/bold]    {os.path.basename(self.video_file)}\n"
                        f"  [bold]Output:[/bold]   {os.path.basename(self.output_path)}\n"
                        f"  [bold]Model:[/bold]    {self.model}\n"
                        f"  [bold]Audio:[/bold]    {fmt_track(best_audio)}\n"
                        f"  [bold]Context:[/bold]  {fmt_track(best_sub)} (Score: {best_sub['score']:.1f})\n"
                        f"  [bold]Workload:[/bold] {total_chunks} Chunks"
                    )
                    console.print(Panel(summary_text, title="Job Summary", expand=False, border_style="cyan"))

                logger.info(f"Selected Subtitle Track: {best_sub['index']} (Score: {best_sub['score']:.1f})")
                logger.info(f"Selected Audio Track: {audio_index}")
                logger.info(f"Total chunks to process: {total_chunks}")
            
            # 4. Main Processing Loop
            for i, cluster in enumerate(clusters):
                if self.stop_requested: break
                if self.limit is not None and i >= self.limit:
                    logger.info(f"Limit of {self.limit} chunks reached.")
                    break

                # Use a spinner for the active task if not verbose
                if not self.verbose:
                    with console.status(f"Processing Chunk {i+1}/{total_chunks}...") as status:
                        chunk_subs = self._process_chunk(i, cluster, audio_index, total_chunks, status)
                else:
                    chunk_subs = self._process_chunk(i, cluster, audio_index, total_chunks)

                if chunk_subs:
                    self.final_subs.extend(chunk_subs)

            # 5. Save Results
            if self.final_subs:
                self._save_srt()
                if self.stop_requested:
                    logger.warning(f"Processing stopped early. Partial results saved to {self.output_path}")
                else:
                    logger.info(f"Success! Saved to {self.output_path}")
                    if not self.verbose:
                        console.print(f"[green]✓[/green] Subtitles saved to: [bold]{self.output_path}[/bold]")
            else:
                logger.error("No subtitles were generated.")
                console.print("[bold yellow]Warning:[/bold yellow] No subtitles were generated. Check the audio track and model output.")

        except Exception as e:
            logger.exception("An unexpected error occurred during the transcription job.")
            console.print(f"[bold red]Critical Error:[/bold red] {e}")
            if self.verbose:
                console.print_exception()
        finally:
            self.cleanup()

    def _process_chunk(self, index: int, cluster: list[SubtitleEvent], audio_index: int | str, total_chunks: int, status_spinner=None) -> list[SubtitleEvent] | None:
        start_ms = max(0, cluster[0]['start'] - AUDIO_PADDING_MS)
        end_ms = cluster[-1]['end'] + AUDIO_PADDING_MS
        timestamp = ms_to_mm_ss_mmm(start_ms).split(',')[0] # Get mm:ss
        chunk_label = f"Chunk {index+1:02d}/{total_chunks:02d}"
        
        cache_path = get_cache_path(self.video_file, start_ms, end_ms)
        
        for attempt in range(MAX_RETRIES):
            raw_text = None
            from_cache = False
            
            if os.path.exists(cache_path):
                logger.debug(f"[{index+1}/{total_chunks}] Using cache")
                if not self.verbose:
                    console.print(f"[{timestamp}] {chunk_label}: [dim]Using Cache[/dim]")
                
                with open(cache_path, 'r', encoding='utf-8') as f:
                    raw_text = f.read()
                from_cache = True
            else:
                action = "Transcribing" if attempt == 0 else "Retrying"
                logger.debug(f"[{index+1}/{total_chunks}] {action} (Attempt {attempt + 1})")
                
                if status_spinner:
                    status_spinner.update(f"{action} {chunk_label} ({timestamp})...")

                audio_chunk = os.path.join(self.temp_dir, f"chunk_{index}.m4a")
                
                try:
                    self.media.extract_audio_chunk(self.video_file, audio_index, start_ms, end_ms, audio_chunk)
                    eng_ctx = "\n".join([f"[{ms_to_mm_ss_mmm(e['start'] - start_ms)} - {ms_to_mm_ss_mmm(e['end'] - start_ms)}] {e['text']}" for e in cluster])
                    
                    raw_text = self.transcriber.transcribe_chunk(audio_chunk, eng_ctx, self.model, self.series_context)
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(raw_text)
                except RateLimitError:
                    logger.warning(f"Rate limit hit at chunk {index}. Stopping.")
                    if not self.verbose:
                         console.print(f"[{timestamp}] {chunk_label}: [bold red]Rate Limit Hit[/bold red]")
                    self.stop_requested = True
                    return None
                except Exception as e:
                    logger.error(f"Error in chunk {index}: {e}")
                    if not self.verbose:
                        console.print(f"[{timestamp}] {chunk_label}: [bold red]Error: {e}[/bold red]")
                    self.stop_requested = True
                    return None
                finally:
                    if os.path.exists(audio_chunk): os.remove(audio_chunk)

            if raw_text:
                subs = parse_timestamps(raw_text, start_ms)
                if validate_chunk(subs):
                    if not self.verbose and not from_cache:
                         console.print(f"[{timestamp}] {chunk_label}: [green]Transcribed[/green]")
                    return subs
                else:
                    logger.warning(f"Validation failed for chunk {index}. Retrying...")
                    if not self.verbose:
                        console.print(f"[{timestamp}] {chunk_label}: [yellow]Validation Failed (Retrying)[/yellow]")
                    if os.path.exists(cache_path): os.remove(cache_path)
        
        logger.error(f"Chunk {index} failed after {MAX_RETRIES} attempts.")
        if not self.verbose:
            console.print(f"[{timestamp}] {chunk_label}: [bold red]Failed[/bold red]")
        return None

    def _save_srt(self):
        try:
            with open(self.output_path, "w", encoding="utf-8") as f:
                for k, sub in enumerate(self.final_subs):
                    f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")
        except PermissionError:
            logger.error(f"Permission denied when writing to {self.output_path}")
            console.print(f"[bold red]Error:[/bold red] Permission denied when writing to [bold]{self.output_path}[/bold]")
        except Exception as e:
            logger.error(f"Failed to save subtitles: {e}")
            console.print(f"[bold red]Error:[/bold red] Failed to save subtitles to {self.output_path}: {e}")

def process_video(video_file: str, **kwargs) -> None:
    verbose = kwargs.get('verbose', False)
    # Enable console logging if verbose is True, otherwise disable it to use Rich
    setup_logging(verbose, console_output=verbose)
    job = SubtitleJob(video_file, **kwargs)
    job.run()