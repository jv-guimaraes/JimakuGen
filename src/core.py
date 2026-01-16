import os
import shutil
import logging
import argparse
import tempfile
from datetime import timedelta

from src.config import DEFAULT_MODEL, CACHE_DIR, CHUNK_TARGET_SECONDS, AUDIO_PADDING_MS, MAX_RETRIES
from src.logger import setup_logging
from src.utils import get_cache_path, ms_to_mm_ss_mmm, parse_timestamps, ms_to_srt_time, validate_chunk, SubtitleEvent
from src.media_utils import MediaProcessor, get_dialogue_from_ass, group_events
from src.transcriber import Transcriber, RateLimitError

logger = logging.getLogger(__name__)

class SubtitleJob:
    def __init__(self, video_file: str, output_path: str | None = None, model: str = DEFAULT_MODEL, chunk_size: int = CHUNK_TARGET_SECONDS, context_path: str | None = None, limit: int | None = None, keep_temp: bool = False):
        self.video_file = video_file
        self.output_path = output_path or self._default_output_path()
        self.model = model
        self.chunk_size = chunk_size
        self.context_path = context_path
        self.limit = limit
        self.keep_temp = keep_temp
        
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
            
            # 1. Track Selection
            best_sub = self.media.get_best_subtitle_track(self.video_file)
            if not best_sub:
                logger.error("No suitable English subtitle track found.")
                return

            best_audio = self.media.get_best_audio_track(self.video_file)
            audio_index = best_audio['index'] if best_audio else "a:0"
            
            logger.info(f"Selected Subtitle Track: {best_sub['index']} (Score: {best_sub['score']:.1f})")
            logger.info(f"Selected Audio Track: {audio_index}")

            # 2. Subtitle Extraction & Grouping
            temp_ass = os.path.join(self.temp_dir, "extracted.ass")
            self.media.extract_subtitles(self.video_file, best_sub['index'], temp_ass)
            
            events = get_dialogue_from_ass(temp_ass)
            clusters = group_events(events, target_duration=self.chunk_size)
            logger.info(f"Total chunks to process: {len(clusters)}")

            # 3. Main Processing Loop
            for i, cluster in enumerate(clusters):
                if self.stop_requested: break
                if self.limit is not None and i >= self.limit:
                    logger.info(f"Limit of {self.limit} chunks reached.")
                    break

                chunk_subs = self._process_chunk(i, cluster, audio_index, len(clusters))
                if chunk_subs:
                    self.final_subs.extend(chunk_subs)

            # 4. Save Results
            if self.final_subs:
                self._save_srt()
                if self.stop_requested:
                    logger.warning(f"Processing stopped early. Partial results saved to {self.output_path}")
                else:
                    logger.info(f"Success! Saved to {self.output_path}")
            else:
                logger.error("No subtitles were generated.")

        finally:
            self.cleanup()

    def _process_chunk(self, index: int, cluster: list[SubtitleEvent], audio_index: int | str, total_chunks: int) -> list[SubtitleEvent] | None:
        start_ms = max(0, cluster[0]['start'] - AUDIO_PADDING_MS)
        end_ms = cluster[-1]['end'] + AUDIO_PADDING_MS
        
        cache_path = get_cache_path(self.video_file, start_ms, end_ms)
        
        for attempt in range(MAX_RETRIES):
            raw_text = None
            if os.path.exists(cache_path):
                logger.info(f"[{index+1}/{total_chunks}] Using cache")
                with open(cache_path, 'r', encoding='utf-8') as f:
                    raw_text = f.read()
            else:
                logger.info(f"[{index+1}/{total_chunks}] Transcribing (Attempt {attempt + 1})")
                audio_chunk = os.path.join(self.temp_dir, f"chunk_{index}.m4a")
                
                try:
                    self.media.extract_audio_chunk(self.video_file, audio_index, start_ms, end_ms, audio_chunk)
                    eng_ctx = "\n".join([f"[{ms_to_mm_ss_mmm(e['start'] - start_ms)} - {ms_to_mm_ss_mmm(e['end'] - start_ms)}] {e['text']}" for e in cluster])
                    
                    raw_text = self.transcriber.transcribe_chunk(audio_chunk, eng_ctx, self.model, self.series_context)
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(raw_text)
                except RateLimitError:
                    logger.warning(f"Rate limit hit at chunk {index}. Stopping.")
                    self.stop_requested = True
                    return None
                except Exception as e:
                    logger.error(f"Error in chunk {index}: {e}")
                    self.stop_requested = True
                    return None
                finally:
                    if os.path.exists(audio_chunk): os.remove(audio_chunk)

            if raw_text:
                subs = parse_timestamps(raw_text, start_ms)
                if validate_chunk(subs):
                    return subs
                else:
                    logger.warning(f"Validation failed for chunk {index}. Retrying...")
                    if os.path.exists(cache_path): os.remove(cache_path)
        
        logger.error(f"Chunk {index} failed after {MAX_RETRIES} attempts.")
        return None

    def _save_srt(self):
        with open(self.output_path, "w", encoding="utf-8") as f:
            for k, sub in enumerate(self.final_subs):
                f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")

def process_video(video_file: str, **kwargs) -> None:
    verbose = kwargs.pop('verbose', False)
    setup_logging(verbose)
    job = SubtitleJob(video_file, **kwargs)
    job.run()

def run_cli() -> None:
    parser = argparse.ArgumentParser(description="JimakuGen: Generate Japanese subtitles for a video using Gemini.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_TARGET_SECONDS, help="Chunk size in seconds")
    parser.add_argument("--context", help="Path to context file")
    parser.add_argument("--limit", type=int, help="Limit number of chunks")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model")
    parser.add_argument("-o", "--output", help="Output SRT path")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temp files")
    args = parser.parse_args()

    process_video(
        video_file=args.video_file,
        output_path=args.output,
        model=args.model,
        chunk_size=args.chunk_size,
        context_path=args.context,
        limit=args.limit,
        verbose=args.verbose,
        keep_temp=args.keep_temp
    )