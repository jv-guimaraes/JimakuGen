import os
import sys
import time
import subprocess
import re
import logging
import argparse
import tempfile
import atexit
import shutil
from datetime import timedelta
from google import genai
from google.genai import types
from media_utils import get_best_english_track, get_best_japanese_audio_track, get_dialogue_from_ass, group_events, remove_japanese_spaces

# Configuration
API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_MODEL = "gemini-3-flash-preview"
CACHE_DIR = "cache"

logger = logging.getLogger(__name__)

class RateLimitError(Exception):
    """Custom exception for Gemini rate limits."""
    pass

def setup_logging(verbose=False):
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(LOG_DIR, f"app_{timestamp}.log")
    
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Remove existing handlers to avoid duplicates if re-configured
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger.info(f"Logging initialized. Level: {'DEBUG' if verbose else 'INFO'}, File: {LOG_FILE}")

if not API_KEY:
    # We can't use logger yet if setup_logging hasn't run, but this check is global.
    # We'll print to stderr for immediate feedback.
    print("Error: GOOGLE_API_KEY not found.", file=sys.stderr)
    sys.exit(1)

client = genai.Client(api_key=API_KEY)

def get_cache_path(video_file, start_ms, end_ms):
    base = os.path.basename(video_file)
    os.makedirs(os.path.join(CACHE_DIR, base), exist_ok=True)
    return os.path.join(CACHE_DIR, base, f"{start_ms}_{end_ms}.txt")

def parse_time_to_ms(ts_str):
    ts_str = ts_str.strip().replace(',', '.').replace('s', '')
    parts = ts_str.split(':')
    if len(parts) == 3:
        return (int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000
    elif len(parts) == 2:
        return (int(parts[0]) * 60 + float(parts[1])) * 1000
    else:
        return float(ts_str) * 1000

def ms_to_mm_ss_mmm(ms):
    total_seconds = ms / 1000.0
    m = int(total_seconds // 60)
    s = total_seconds % 60
    return f"{m:02}:{s:06.3f}".replace('.', ',')

def parse_timestamps(text, offset_ms):
    results = []
    for line in text.splitlines():
        line = line.strip().replace('`', '')
        if not line: continue
        match = re.search(r"(\d+[:\d\.,]*)\s*-\s*(\d+[:\d\.,]*)", line)
        if match:
            start_str, end_str = match.groups()
            content = line[match.end():].strip().lstrip(']: ')
            try:
                start_ms = parse_time_to_ms(start_str) + offset_ms
                end_ms = parse_time_to_ms(end_str) + offset_ms
                if content:
                    content = remove_japanese_spaces(content)
                    results.append({'start': start_ms, 'end': end_ms, 'text': content})
            except: pass
    return results

def transcribe_chunk(audio_path, english_context, model_name, series_info=None):
    try:
        sample_file = client.files.upload(file=audio_path)
        while sample_file.state == types.FileState.PROCESSING:
            time.sleep(2)
            sample_file = client.files.get(name=sample_file.name)
        
        prompt_parts = []
        if series_info:
            prompt_parts.append(f"Series Information:\n{series_info}")

        prompt_parts.append(
            "Transcribe the Japanese dialogue accurately. "
            "You MUST use the following timestamp format for EVERY line: [MM:SS,mmm - MM:SS,mmm] Dialogue. "
            "Do not use any other format. Example: [00:01,250 - 00:03,100] こんにちは"
        )
        prompt_parts.append(f"English Context Reference:\n{english_context}")
        
        prompt = "\n\n".join(prompt_parts)
        
        logger.debug(f"--- Prompt sent to Gemini ---\n{prompt}\n-----------------------------")
        
        response = client.models.generate_content(
            model=model_name,
            contents=[sample_file, prompt],
            config=types.GenerateContentConfig(
                system_instruction="You are an expert Japanese media transcriber."
            )
        )
        logger.debug(f"--- Response from Gemini ---\n{response.text}\n----------------------------")
        return response.text
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg:
            raise RateLimitError(err_msg)
        else:
            raise e

def ms_to_srt_time(ms):
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    return f"{total_seconds // 3600:02}:{(total_seconds % 3600) // 60:02}:{total_seconds % 60:02},{int(ms % 1000):03}"

def validate_chunk(subs, cps_threshold=25.0, min_cps_threshold=0.2, max_duration=10.0):
    for sub in subs:
        duration_s = (sub['end'] - sub['start']) / 1000.0
        if duration_s <= 0:
            logger.warning(f"Validation failed: Zero or negative duration for '{sub['text']}'")
            return False
        
        # Check for single line duration exceeding safe limit
        if duration_s > max_duration:
            logger.warning(f"Validation failed: Duration {duration_s:.2f}s exceeds limit {max_duration}s for '{sub['text']}'")
            return False

        text_len = len(sub['text'])
        cps = text_len / duration_s
        
        if cps > cps_threshold:
            logger.warning(f"Validation failed: High CPS ({cps:.2f}) for '{sub['text']}' ({duration_s:.3f}s)")
            return False
            
        if cps < min_cps_threshold:
             logger.warning(f"Validation failed: Low CPS ({cps:.2f}) for '{sub['text']}' ({duration_s:.3f}s)")
             return False
             
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate Japanese subtitles for a video using Gemini.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging (DEBUG level)")
    parser.add_argument("--chunk-size", type=int, default=60, help="Target duration for each chunk in seconds (default: 60)")
    parser.add_argument("--context", help="Path to a text file containing series context (characters, terms, etc.)")
    parser.add_argument("--limit", type=int, help="Limit the number of chunks to process (for testing)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("-o", "--output", help="Output SRT file path (default: <video_name>.ja.generated.srt)")
    args = parser.parse_args()

    setup_logging(args.verbose)
    
    video_file = args.video_file
    
    # Create temporary directory that will be cleaned up on exit
    temp_dir = tempfile.mkdtemp(prefix="subtitles_")
    atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    series_context = None
    if args.context:
        try:
            with open(args.context, 'r', encoding='utf-8') as f:
                series_context = f.read().strip()
            logger.info(f"Loaded series context from {args.context}")
        except Exception as e:
            logger.error(f"Failed to read context file: {e}")
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
    clusters = group_events(events, target_duration=args.chunk_size)
    logger.info(f"Total chunks: {len(clusters)}")
    
    final_subs = []
    stop_processing = False
    for i, cluster in enumerate(clusters):
        if stop_processing:
            break
        if args.limit and i >= args.limit:
            logger.info(f"Limit of {args.limit} chunks reached. Stopping early.")
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
                    raw = transcribe_chunk(audio_chunk, eng_ctx, args.model, series_context)
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
    if args.output:
        output_srt = args.output
    else:
        base, _ = os.path.splitext(video_file)
        output_srt = f"{base}.ja.generated.srt"
    
    with open(output_srt, "w", encoding="utf-8") as f:
        for k, sub in enumerate(final_subs):
            f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")
            
    logger.info(f"Success! Saved to {output_srt}")
    # temp_dir cleanup is handled by atexit

if __name__ == "__main__":
    main()