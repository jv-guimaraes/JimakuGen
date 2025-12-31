import json
import re
import subprocess
import logging
from typing import Any
from src.config import CHUNK_TARGET_SECONDS, MAX_GAP_SECONDS
from src.utils import SubtitleEvent

logger = logging.getLogger(__name__)

def clean_ass_text(text: str) -> str:
    # If the text contains drawing commands (starts with \p1, \p2 etc inside tags), treat as non-dialogue
    if re.search(r'\\p[1-9]', text):
        return ""
    text = re.sub(r'\{.*?\}', '', text)
    text = text.replace(r'\N', ' ')
    text = text.replace(r'\n', ' ')
    return text.strip()

def parse_ass_time(ts_str: str) -> int:
    parts = ts_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_cc = parts[2].split('.')
    s = int(s_cc[0])
    cc = int(s_cc[1])
    return (h * 3600 + m * 60 + s) * 1000 + cc * 10

def is_mostly_english(text: str) -> bool:
    if not text: return False
    # Remove common punctuation and numbers
    text = re.sub(r'[0-9\W_]+', '', text)
    if not text: return False
    
    # Count ASCII characters
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return (ascii_count / len(text)) > 0.8

def get_dialogue_from_ass(ass_path: str) -> list[SubtitleEvent]:
    dialogue_events: list[SubtitleEvent] = []
    logger.debug(f"Parsing ASS file: {ass_path}")
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
                    
                    # Blacklist styles that are definitely non-dialogue
                    if any(x in style for x in ['op', 'ed', 'song', 'sign', 'title', 'credit']):
                        continue
                        
                    # Heuristic: Filter out lines with hardcoded positioning (signs, songs, typesetting)
                    # Standard dialogue usually relies on default margins/alignment.
                    if r'\pos' in event.get('Text', '') or r'\move' in event.get('Text', ''):
                        continue

                    if text and is_mostly_english(text):
                        start_ms = parse_ass_time(event['Start'])
                        end_ms = parse_ass_time(event['End'])
                        # Explicitly cast to match SubtitleEvent structure
                        dialogue_events.append({'start': start_ms, 'end': end_ms, 'text': text})
    logger.debug(f"Found {len(dialogue_events)} dialogue events")
    return dialogue_events

def get_best_english_track(input_file: str) -> dict[str, Any] | None:
    # Retrieve stream info including number of frames if available
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=title,language,NUMBER_OF_FRAMES", "-of", "json", input_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFprobe failed: {e}")
        return None
        
    if not result.stdout: return None
    data = json.loads(result.stdout)
    
    candidates = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "subtitle":
            tags = stream.get("tags", {})
            lang = tags.get("language", "").lower()
            title = tags.get("title", "").lower()
            
            # Estimate event count
            frames = 0
            if "NUMBER_OF_FRAMES" in tags:
                try: frames = int(tags["NUMBER_OF_FRAMES"])
                except: pass
            
            # Score the track
            score = 0
            if lang in ["eng", "en"]: score += 10
            elif lang in ["jpn", "ja"]: score += 5  # Allow 'jpn' tracks as candidates (often full subs)
            
            if "dialogue" in title or "full" in title: score += 5
            if "sign" in title or "song" in title: score -= 10
            
            # Prioritize higher frame counts (proxy for dialogue quantity)
            # Normalize frame count to a score bonus (e.g. 400 frames = +20 points)
            score += (frames / 20)
            
            candidates.append({
                'index': stream["index"],
                'score': score,
                'frames': frames,
                'tags': tags
            })
            logger.debug(f"Track candidate: Index={stream['index']}, Lang={lang}, Title='{title}', Frames={frames}, Score={score}")
            
    if not candidates: return None
    # Sort by score descending
    best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
    logger.debug(f"Best track selected: Index={best['index']} (Score: {best['score']})")
    return best

def get_best_japanese_audio_track(input_file: str) -> dict[str, Any] | None:
    # Retrieve stream info
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=title,language", "-of", "json", input_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFprobe failed: {e}")
        return None
        
    if not result.stdout: return None
    data = json.loads(result.stdout)
    
    candidates = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            tags = stream.get("tags", {})
            lang = tags.get("language", "").lower()
            title = tags.get("title", "").lower()
            
            score = 0
            if lang in ["jpn", "ja"]: score += 10
            elif "japanese" in title: score += 5
            
            candidates.append({
                'index': stream["index"],
                'score': score,
                'tags': tags
            })
            logger.debug(f"Audio candidate: Index={stream['index']}, Lang={lang}, Title='{title}', Score={score}")
            
    if not candidates: return None
    # Sort by score descending, then by index to pick the first one if scores are equal
    best = sorted(candidates, key=lambda x: (x['score'], -x['index']), reverse=True)[0]
    logger.debug(f"Best audio selected: Index={best['index']} (Score: {best['score']})")
    return best

def group_events(events: list[SubtitleEvent], target_duration: float = CHUNK_TARGET_SECONDS) -> list[list[SubtitleEvent]]:
    clusters = []
    if not events: return clusters
    current_cluster = [events[0]]
    for i in range(1, len(events)):
        prev = events[i-1]
        curr = events[i]
        gap = (curr['start'] - prev['end']) / 1000.0
        duration = (curr['end'] - current_cluster[0]['start']) / 1000.0
        if duration > target_duration and gap > MAX_GAP_SECONDS:
            clusters.append(current_cluster)
            current_cluster = [curr]
        else:
            current_cluster.append(curr)
    if current_cluster: clusters.append(current_cluster)
    logger.debug(f"Grouped {len(events)} events into {len(clusters)} chunks")
    return clusters
