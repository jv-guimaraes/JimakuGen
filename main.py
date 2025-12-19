import os
import sys
import time
import json
import subprocess
import re
from datetime import timedelta
import google.generativeai as genai

# Configuration
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-2.5-flash-preview-09-2025"
CHUNK_TARGET_SECONDS = 60
MAX_GAP_SECONDS = 2.0
CACHE_DIR = "cache"
TEMP_DIR = "/home/jv/.gemini/tmp/cf85e6b8eae3ab12e125ebbeb2537e9d8c4c791de7f2b489ef18d1b6052de1fb"

if not API_KEY:
    print("Error: GOOGLE_API_KEY not found.")
    sys.exit(1)

genai.configure(api_key=API_KEY)

def get_cache_path(video_file, start_ms, end_ms):
    base = os.path.basename(video_file)
    os.makedirs(os.path.join(CACHE_DIR, base), exist_ok=True)
    return os.path.join(CACHE_DIR, base, f"{start_ms}_{end_ms}.txt")

def clean_ass_text(text):
    text = re.sub(r'\{{.*?\}}', '', text)
    text = text.replace(r'\N', ' ')
    text = text.replace(r'\n', ' ')
    return text.strip()

def parse_ass_time(ts_str):
    parts = ts_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_cc = parts[2].split('.')
    s = int(s_cc[0])
    cc = int(s_cc[1])
    return (h * 3600 + m * 60 + s) * 1000 + cc * 10

def get_dialogue_from_ass(ass_path):
    dialogue_events = []
    with open(ass_path, 'r', encoding='utf-8', errors='ignore') as f:
        in_events = False
        format_cols = []
        for line in f:
            line = line.strip()
            if not line: continue
            if line.startswith('[Events]'):
                in_events = True
                continue
            if in_events:
                if line.startswith('Format:'):
                    format_cols = [c.strip() for c in line[7:].split(',')]
                    continue
                if line.startswith('Dialogue:'):
                    parts = line[9:].split(',', len(format_cols) - 1)
                    event = dict(zip(format_cols, parts))
                    style = event.get('Style', '').lower()
                    text = clean_ass_text(event.get('Text', ''))
                    if text and style in ['default', 'alt', 'italics']:
                        if not any(x in style for x in ['op', 'ed', 'song', 'sign', 'title']):
                            start_ms = parse_ass_time(event['Start'])
                            end_ms = parse_ass_time(event['End'])
                            dialogue_events.append({'start': start_ms, 'end': end_ms, 'text': text})
    return dialogue_events

def get_best_english_track(input_file):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=title,language", "-of", "json", input_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not result.stdout: return None
    data = json.loads(result.stdout)
    tracks = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "subtitle":
            tags = stream.get("tags", {})
            lang = tags.get("language", "").lower()
            title = tags.get("title", "").lower()
            if lang in ["eng", "en"]:
                score = 0
                if "dialogue" in title: score += 10
                if "signs" in title or "song" in title: score -= 5
                tracks.append((stream["index"], score))
    if not tracks: return None
    return sorted(tracks, key=lambda x: x[1], reverse=True)[0][0]

def group_events(events):
    clusters = []
    if not events: return clusters
    current_cluster = [events[0]]
    for i in range(1, len(events)):
        prev = events[i-1]
        curr = events[i]
        gap = (curr['start'] - prev['end']) / 1000.0
        duration = (curr['end'] - current_cluster[0]['start']) / 1000.0
        if duration > CHUNK_TARGET_SECONDS and gap > MAX_GAP_SECONDS:
            clusters.append(current_cluster)
            current_cluster = [curr]
        else:
            current_cluster.append(curr)
    if current_cluster: clusters.append(current_cluster)
    return clusters

def parse_time_to_ms(ts_str):
    ts_str = ts_str.strip().replace(',', '.').replace('s', '')
    parts = ts_str.split(':')
    if len(parts) == 3:
        return (int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000
    elif len(parts) == 2:
        return (int(parts[0]) * 60 + float(parts[1])) * 1000
    else:
        return float(ts_str) * 1000

def parse_timestamps(text, offset_ms):
    results = []
    for line in text.splitlines():
        line = line.strip().replace('`', '')
        if not line: continue
        match = re.search(r"(\d+[:\d\.]*)\s*-\s*(\d+[:\d\.]*)", line)
        if match:
            start_str, end_str = match.groups()
            content = line[match.end():].strip().lstrip(']: ')
            try:
                start_ms = parse_time_to_ms(start_str) + offset_ms
                end_ms = parse_time_to_ms(end_str) + offset_ms
                if content:
                    results.append({'start': start_ms, 'end': end_ms, 'text': content})
            except: pass
    return results

def transcribe_chunk(audio_path, english_context):
    sample_file = genai.upload_file(path=audio_path)
    while sample_file.state.name == "PROCESSING":
        time.sleep(2)
        sample_file = genai.get_file(sample_file.name)
    
    model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction="You are an expert Japanese media transcriber.")
    prompt = f"Transcribe the Japanese dialogue accurately. Format: [start_seconds - end_seconds] Dialogue\n\nEnglish Context Reference:\n{english_context}"
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = model.generate_content([sample_file, prompt])
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
                
                print(f"Rate limited (429). Waiting {wait_time:.2f}s before retry...")
                time.sleep(wait_time)
            else:
                raise e

def ms_to_srt_time(ms):
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    return f"{total_seconds // 3600:02}:{(total_seconds % 3600) // 60:02}:{total_seconds % 60:02},{int(ms % 1000):03}"

def main(video_file):
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    track_index = get_best_english_track(video_file)
    if track_index is None: return print("No English track.")
    
    temp_ass = os.path.join(TEMP_DIR, "temp_eng.ass")
    subprocess.run(["ffmpeg", "-y", "-i", video_file, "-map", f"0:{track_index}", temp_ass], capture_output=True)
    
    events = get_dialogue_from_ass(temp_ass)
    clusters = group_events(events)
    print(f"Total chunks: {len(clusters)}")
    
    final_subs = []
    for i, cluster in enumerate(clusters):
        start_ms = cluster[0]['start'] - 700
        if start_ms < 0: start_ms = 0
        end_ms = cluster[-1]['end'] + 700
        
        cache_path = get_cache_path(video_file, start_ms, end_ms)
        
        if os.path.exists(cache_path):
            print(f"[{i+1}/{len(clusters)}] Using cached transcription ({cache_path})")
            with open(cache_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        else:
            print(f"[{i+1}/{len(clusters)}] Transcribing...")
            audio_chunk = os.path.join(TEMP_DIR, f"chunk_{i}.m4a")
            duration_s = (end_ms - start_ms) / 1000.0
            subprocess.run(["ffmpeg", "-y", "-ss", str(timedelta(milliseconds=start_ms)), "-i", video_file,
                           "-t", str(duration_s), "-vn", "-c:a", "aac", "-b:a", "128k", audio_chunk], capture_output=True)
            
            eng_ctx = "\n".join([f"[{ (e['start'] - start_ms)/1000.0 :.1f}s] {e['text']}" for e in cluster])
            
            try:
                raw = transcribe_chunk(audio_chunk, eng_ctx)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(raw)
            except Exception as e:
                print(f"Error in chunk {i}: {e}")
                continue
            finally:
                if os.path.exists(audio_chunk): os.remove(audio_chunk)
        
        final_subs.extend(parse_timestamps(raw, start_ms))

    output_srt = video_file.replace(".mkv", ".ja.generated.srt")
    with open(output_srt, "w", encoding="utf-8") as f:
        for k, sub in enumerate(final_subs):
            f.write(f"{k+1}\n{ms_to_srt_time(sub['start'])} --> {ms_to_srt_time(sub['end'])}\n{sub['text']}\n\n")
            
    print(f"Success! Saved to {output_srt}")
    if os.path.exists(temp_ass): os.remove(temp_ass)

if __name__ == "__main__":
    if len(sys.argv) > 1: main(sys.argv[1])