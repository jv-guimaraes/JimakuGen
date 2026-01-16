import json
import re
import logging
from typing import Any, TypedDict
from datetime import timedelta
import pysubs2
from src.config import CHUNK_TARGET_SECONDS, MAX_GAP_SECONDS
from src.utils import SubtitleEvent, run_command

logger = logging.getLogger(__name__)

class TrackInfo(TypedDict):
    index: int | str
    score: float
    lang: str
    title: str
    frames: int

def clean_ass_text(text: str) -> str:
    """
    Cleans ASS text by removing drawing commands, override tags, and normalizing whitespace.
    """
    if re.search(r'\\p[1-9]', text):
        return ""
    text = re.sub(r'\{.*?\}', '', text)
    text = text.replace(r'\N', ' ').replace(r'\n', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def is_mostly_english(text: str) -> bool:
    if not text: return False
    text = re.sub(r'[0-9\W_]+', '', text)
    if not text: return False
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return (ascii_count / len(text)) > 0.8

def get_dialogue_from_ass(ass_path: str) -> list[SubtitleEvent]:
    dialogue_events: list[SubtitleEvent] = []
    logger.debug(f"Parsing ASS file with pysubs2: {ass_path}")
    
    stats = {
        'total': 0,
        'style': 0,
        'pos': 0,
        'drawing': 0,
        'empty': 0,
        'non_english': 0,
        'kept': 0
    }

    try:
        subs = pysubs2.load(ass_path, encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load ASS file {ass_path}: {e}")
        return []

    for i, event in enumerate(subs):
        stats['total'] += 1
        style = event.style.lower()
        text_raw = event.text
        
        # 1. Style Blacklist
        if any(x in style for x in ['op', 'ed', 'song', 'sign', 'title', 'credit', 'note']):
            logger.debug(f"Line {i+1}: Skipped due to style '{style}' - '{text_raw}'")
            stats['style'] += 1
            continue
            
        # 2. Typesetting Tags (pos, move, fad, fade)
        if any(x in text_raw for x in [r'\pos', r'\move', r'\fad', r'\fade']):
            logger.debug(f"Line {i+1}: Skipped due to typesetting tags - '{text_raw}'")
            stats['pos'] += 1
            continue

        clean_text = clean_ass_text(text_raw)
        
        # 3. Drawing commands
        if not clean_text and re.search(r'\\p[1-9]', text_raw):
             logger.debug(f"Line {i+1}: Skipped due to drawing commands - '{text_raw}'")
             stats['drawing'] += 1
             continue

        if not clean_text:
             logger.debug(f"Line {i+1}: Skipped (empty after cleaning) - '{text_raw}'")
             stats['empty'] += 1
             continue
             
        if not is_mostly_english(clean_text):
            logger.debug(f"Line {i+1}: Skipped (non-English) - '{clean_text}'")
            stats['non_english'] += 1
            continue

        dialogue_events.append({
            'start': event.start,
            'end': event.end,
            'text': clean_text
        })
        stats['kept'] += 1

    logger.debug(f"ASS Parse Stats: {stats}")
    return dialogue_events

class MediaProcessor:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def get_best_subtitle_track(self, video_file: str) -> dict[str, Any] | None:
        cmd = [self.ffprobe_path, "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=title,language,NUMBER_OF_FRAMES", "-of", "json", video_file]
        try:
            result = run_command(cmd)
            data = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"FFprobe failed for subtitles: {e}")
            return None
            
        candidates = []
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "subtitle":
                tags = stream.get("tags", {})
                lang = tags.get("language", "").lower()
                title = tags.get("title", "").lower()
                
                frames = 0
                if "NUMBER_OF_FRAMES" in tags:
                    try: frames = int(tags["NUMBER_OF_FRAMES"])
                    except: pass
                
                score = 0
                if lang in ["eng", "en"]: score += 10
                elif lang in ["jpn", "ja"]: score += 5
                
                if "dialogue" in title or "full" in title: score += 5
                if "sign" in title or "song" in title: score -= 10
                score += (frames / 20)
                
                candidates.append({
                    'index': stream["index"],
                    'score': score,
                    'frames': frames,
                    'lang': lang,
                    'title': title
                })
                
        if not candidates: return None
        return sorted(candidates, key=lambda x: x['score'], reverse=True)[0]

    def get_best_audio_track(self, video_file: str) -> dict[str, Any] | None:
        cmd = [self.ffprobe_path, "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=title,language", "-of", "json", video_file]
        try:
            result = run_command(cmd)
            data = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"FFprobe failed for audio: {e}")
            return None
            
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
                    'lang': lang,
                    'title': title
                })
                
        if not candidates: return None
        return sorted(candidates, key=lambda x: (x['score'], -x['index']), reverse=True)[0]

    def extract_subtitles(self, video_file: str, track_index: int, output_ass: str) -> None:
        cmd = [self.ffmpeg_path, "-y", "-i", video_file, "-map", f"0:{track_index}", output_ass]
        run_command(cmd)

    def extract_audio_chunk(self, video_file: str, audio_index: int | str, start_ms: int, end_ms: int, output_file: str) -> None:
        duration_s = (end_ms - start_ms) / 1000.0
        cmd = [
            self.ffmpeg_path, "-y", 
            "-ss", str(timedelta(milliseconds=start_ms)), 
            "-i", video_file,
            "-map", f"0:{audio_index}", 
            "-t", str(duration_s), 
            "-vn", "-c:a", "aac", "-b:a", "128k", 
            output_file
        ]
        run_command(cmd)

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