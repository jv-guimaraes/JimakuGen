import os
import re
import logging
from typing import TypedDict, Any
from datetime import timedelta
from src.config import CACHE_DIR

logger = logging.getLogger(__name__)

class SubtitleEvent(TypedDict):
    start: float | int
    end: float | int
    text: str

def get_cache_path(video_file: str, start_ms: float | int, end_ms: float | int) -> str:
    base = os.path.basename(video_file)
    os.makedirs(os.path.join(CACHE_DIR, base), exist_ok=True)
    return os.path.join(CACHE_DIR, base, f"{start_ms}_{end_ms}.txt")

def parse_time_to_ms(ts_str: str) -> float:
    ts_str = ts_str.strip().replace(',', '.').replace('s', '')
    parts = ts_str.split(':')
    if len(parts) == 3:
        return (int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000
    elif len(parts) == 2:
        return (int(parts[0]) * 60 + float(parts[1])) * 1000
    else:
        return float(ts_str) * 1000

def ms_to_mm_ss_mmm(ms: float | int) -> str:
    total_seconds = ms / 1000.0
    m = int(total_seconds // 60)
    s = total_seconds % 60
    return f"{m:02}:{s:06.3f}".replace('.', ',')

def ms_to_srt_time(ms: float | int) -> str:
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    return f"{total_seconds // 3600:02}:{(total_seconds % 3600) // 60:02}:{total_seconds % 60:02},{int(ms % 1000):03}"

def remove_japanese_spaces(text: str | None) -> str | None:
    if not text:
        return text
    # Japanese character ranges:
    # Hiragana: \u3040-\u309f
    # Katakana: \u30a0-\u30ff
    # Kanji: \u4e00-\u9fff
    # CJK symbols and punctuation: \u3000-\u303f
    # Full-width alphanumeric: \uff00-\uffef
    jp_range = r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]'
    
    # 1. Remove spaces between two Japanese characters
    text = re.sub(rf'(?<={jp_range})\s+(?={jp_range})', '', text)
    
    # 2. Remove spaces between a Japanese character and common punctuation
    # (including half-width ! ? . , : ;)
    punct = r'[!?.,:;]'
    text = re.sub(rf'(?<={jp_range})\s+(?={punct})', '', text)
    text = re.sub(rf'(?<={punct})\s+(?={jp_range})', '', text)
    
    return text

def parse_timestamps(text: str, offset_ms: float | int) -> list[SubtitleEvent]:
    results: list[SubtitleEvent] = []
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
                    if content: # Ensure content is not None
                        results.append({'start': start_ms, 'end': end_ms, 'text': content})
            except: pass
    return results

def validate_chunk(subs: list[SubtitleEvent], cps_threshold: float = 25.0, min_cps_threshold: float = 0.2, max_duration: float = 10.0) -> bool:
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
