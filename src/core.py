import os
import sys
import shutil
import logging
import argparse
import tempfile
import subprocess
from datetime import timedelta

from src.config import DEFAULT_MODEL, CACHE_DIR
from src.logger import setup_logging
from src.utils import get_cache_path, ms_to_mm_ss_mmm, parse_timestamps, ms_to_srt_time, validate_chunk
from src.media_utils import get_best_english_track, get_best_japanese_audio_track, get_dialogue_from_ass, group_events
from src.transcriber import Transcriber, RateLimitError

logger = logging.getLogger(__name__)

def process_video(video_file, output_path=None, model=DEFAULT_MODEL, chunk_size=60, context_path=None, limit=None, verbose=False):
    setup_logging(verbose)
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="subtitles_")
    logger.debug(f"Created temporary directory: {temp_dir}")
    
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        series_context = None
        if context_path:
            try:
                with open(context_path, 'r', encoding='utf-8') as f:
                    series_context = f.read().strip()
                logger.info(f"Loaded series context from {context_path}")
            except Exception as e:
                logger.error(f"Failed to read context file: {e}")
                return

        # Initialize Transcriber
        try:
            transcriber = Transcriber()
        except ValueError as e:
            logger.error(str(e))
            return

        best_track = get_best_english_track(video_file)
        if best_track is None:
            logger.error("No English track found.")
            return
        
        track_index = best_track['index']
        logger.info(f"Selected subtitle track index {track_index} (Score: {best_track['score']:.1f}, Frames: {best_track['frames']})")
        
        audio_track = get_best_japanese_audio_track(video_file)
        audio_index = audio_track['index'] if audio_track else "a:0"
        if audio_track:
            logger.info(f"Selected audio track index {audio_index} (Score: {audio_track['score']})")
        else:
            logger.warning("No Japanese audio track found, defaulting to first audio stream.")

        temp_ass = os.path.join(temp_dir, "temp_eng.ass")
        cmd_extract_sub = ["ffmpeg", "-y", "-i", video_file, "-map", f"0:{track_index}", temp_ass]
        logger.debug(f"Extracting subtitles command: {' '.join(cmd_extract_sub)}")
        subprocess.run(cmd_extract_sub, capture_output=True)
        
        events = get_dialogue_from_ass(temp_ass)
        clusters = group_events(events, target_duration=chunk_size)
        logger.info(f"Total chunks: {len(clusters)}")
        
        final_subs = []
        stop_processing = False
        for i, cluster in enumerate(clusters):
            if stop_processing:
                break
            if limit and i >= limit:
                logger.info(f"Limit of {limit} chunks reached. Stopping early.")
                break

            start_ms = cluster[0]['start'] - 700
            if start_ms < 0: start_ms = 0
            end_ms = cluster[-1]['end'] + 700
            
            cache_path = get_cache_path(video_file, start_ms, end_ms)
            
            retries = 0
            max_retries = 3
            while retries < max_retries:
                raw = None
                if os.path.exists(cache_path):
                    logger.info(f"[{i+1}/{len(clusters)}] Using cached transcription ({cache_path})")
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        raw = f.read()
                else:
                    logger.info(f"[{i+1}/{len(clusters)}] Transcribing... (Attempt {retries + 1})")
                    audio_chunk = os.path.join(temp_dir, f"chunk_{i}.m4a")
                    duration_s = (end_ms - start_ms) / 1000.0
                    cmd_extract_audio = ["ffmpeg", "-y", "-ss", str(timedelta(milliseconds=start_ms)), "-i", video_file,
                                   "-map", f"0:{audio_index}", "-t", str(duration_s), "-vn", "-c:a", "aac", "-b:a", "128k", audio_chunk]
                    logger.debug(f"Extracting audio chunk {i} command: {' '.join(cmd_extract_audio)}")
                    subprocess.run(cmd_extract_audio, capture_output=True)
                    
                    eng_ctx = "\n".join([f"[{ms_to_mm_ss_mmm(e['start'] - start_ms)} - {ms_to_mm_ss_mmm(e['end'] - start_ms)}] {e['text']}" for e in cluster])
                    
                    try:
                        raw = transcriber.transcribe_chunk(audio_chunk, eng_ctx, model, series_context)
                        with open(cache_path, 'w', encoding='utf-8') as f:
                            f.write(raw)
                    except RateLimitError as e:
                        logger.warning(f"Rate limit hit at chunk {i}. Stopping further processing as requested.")
                        stop_processing = True
                        break
                    except Exception as e:
                        logger.error(f"Error in chunk {i}: {e}")
                        retries += 1
                        continue
                    finally:
                        if os.path.exists(audio_chunk): os.remove(audio_chunk)
                
                if raw:
                    chunk_subs = parse_timestamps(raw, start_ms)
                    if validate_chunk(chunk_subs):
                        final_subs.extend(chunk_subs)
                        break
                    else:
                        logger.warning(f"Chunk {i} validation failed. Retrying...")
                        if os.path.exists(cache_path):
                            os.remove(cache_path)
                        retries += 1
            else:
                 if not stop_processing:
                    logger.error(f"Chunk {i} failed after {max_retries} retries. Skipping.")

        # Determine output path
        if output_path:
            output_srt = output_path
        else:
            base, _ = os.path.splitext(video_file)
            output_srt = f"{base}.ja.generated.srt"
        
        with open(output_srt, "w", encoding="utf-8") as f:
            for k, sub in enumerate(final_subs):
                f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")
                
        logger.info(f"Success! Saved to {output_srt}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.debug(f"Cleaned up temporary directory: {temp_dir}")

def run_cli():
    parser = argparse.ArgumentParser(description="Generate Japanese subtitles for a video using Gemini.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging (DEBUG level)")
    parser.add_argument("--chunk-size", type=int, default=60, help="Target duration for each chunk in seconds (default: 60)")
    parser.add_argument("--context", help="Path to a text file containing series context (characters, terms, etc.)")
    parser.add_argument("--limit", type=int, help="Limit the number of chunks to process (for testing)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("-o", "--output", help="Output SRT file path (default: <video_name>.ja.generated.srt)")
    args = parser.parse_args()

    process_video(
        video_file=args.video_file,
        output_path=args.output,
        model=args.model,
        chunk_size=args.chunk_size,
        context_path=args.context,
        limit=args.limit,
        verbose=args.verbose
    )
