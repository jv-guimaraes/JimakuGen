import os
import sys
import time
import subprocess
import re
import logging
import argparse
from datetime import timedelta
from google import genai
from google.genai import types
from media_utils import get_best_english_track, get_best_japanese_audio_track, get_dialogue_from_ass, group_events, remove_japanese_spaces

# Configuration
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-2.5-flash"
CACHE_DIR = "cache"
TEMP_DIR = "/home/jv/.gemini/tmp/cf85e6b8eae3ab12e125ebbeb2537e9d8c4c791de7f2b489ef18d1b6052de1fb"

logger = logging.getLogger(__name__)

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

def transcribe_chunk(audio_path, english_context, series_info=None):
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
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[sample_file, prompt],
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert Japanese media transcriber."
                )
            )
            logger.debug(f"--- Response from Gemini ---\n{response.text}\n----------------------------")
            return response.text
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg and attempt < max_retries - 1:
                # Try to extract "retry in 19.739s"
                match = re.search(r"retry in (\d+\.?\d*)s", err_msg)
                if match:
                    wait_time = float(match.group(1)) + 1.0 # Add 1s buffer
                else:
                    wait_time = 60 # Default fallback
                
                logger.warning(f"Rate limited (429). Waiting {wait_time:.2f}s before retry...")
                time.sleep(wait_time)
            else:
                raise e

def ms_to_srt_time(ms):
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    return f"{total_seconds // 3600:02}:{(total_seconds % 3600) // 60:02}:{total_seconds % 60:02},{int(ms % 1000):03}"

def main():
    parser = argparse.ArgumentParser(description="Generate Japanese subtitles for a video using Gemini.")
    parser.add_argument("video_file", help="Path to the input video file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging (DEBUG level)")
    parser.add_argument("--chunk-size", type=int, default=60, help="Target duration for each chunk in seconds (default: 60)")
    parser.add_argument("--context", help="Path to a text file containing series context (characters, terms, etc.)")
    parser.add_argument("--limit", type=int, help="Limit the number of chunks to process (for testing)")
    args = parser.parse_args()

    setup_logging(args.verbose)
    
    video_file = args.video_file
    os.makedirs(TEMP_DIR, exist_ok=True)
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

    temp_ass = os.path.join(TEMP_DIR, "temp_eng.ass")
    cmd_extract_sub = ["ffmpeg", "-y", "-i", video_file, "-map", f"0:{track_index}", temp_ass]
    logger.debug(f"Extracting subtitles command: {' '.join(cmd_extract_sub)}")
    subprocess.run(cmd_extract_sub, capture_output=True)
    
    events = get_dialogue_from_ass(temp_ass)
    clusters = group_events(events, target_duration=args.chunk_size)
    logger.info(f"Total chunks: {len(clusters)}")
    
    final_subs = []
    for i, cluster in enumerate(clusters):
        if args.limit and i >= args.limit:
            logger.info(f"Limit of {args.limit} chunks reached. Stopping early.")
            break

        start_ms = cluster[0]['start'] - 700
        if start_ms < 0: start_ms = 0
        end_ms = cluster[-1]['end'] + 700
        
        cache_path = get_cache_path(video_file, start_ms, end_ms)
        
        if os.path.exists(cache_path):
            logger.info(f"[{i+1}/{len(clusters)}] Using cached transcription ({cache_path})")
            with open(cache_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        else:
            logger.info(f"[{i+1}/{len(clusters)}] Transcribing...")
            audio_chunk = os.path.join(TEMP_DIR, f"chunk_{i}.m4a")
            duration_s = (end_ms - start_ms) / 1000.0
            cmd_extract_audio = ["ffmpeg", "-y", "-ss", str(timedelta(milliseconds=start_ms)), "-i", video_file,
                           "-map", f"0:{audio_index}", "-t", str(duration_s), "-vn", "-c:a", "aac", "-b:a", "128k", audio_chunk]
            logger.debug(f"Extracting audio chunk {i} command: {' '.join(cmd_extract_audio)}")
            subprocess.run(cmd_extract_audio, capture_output=True)
            
            eng_ctx = "\n".join([f"[{ms_to_mm_ss_mmm(e['start'] - start_ms)} - {ms_to_mm_ss_mmm(e['end'] - start_ms)}] {e['text']}" for e in cluster])
            
            try:
                raw = transcribe_chunk(audio_chunk, eng_ctx, series_context)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(raw)
            except Exception as e:
                logger.error(f"Error in chunk {i}: {e}")
                continue
            finally:
                if os.path.exists(audio_chunk): os.remove(audio_chunk)
        
        final_subs.extend(parse_timestamps(raw, start_ms))

    output_srt = video_file.replace(".mkv", ".ja.generated.srt")
    with open(output_srt, "w", encoding="utf-8") as f:
        for k, sub in enumerate(final_subs):
            f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")
            
    logger.info(f"Success! Saved to {output_srt}")
    if os.path.exists(temp_ass): os.remove(temp_ass)

if __name__ == "__main__":
    main()