import os
import sys
import time
import logging
from pathlib import Path

logger = logging.getLogger("subtitle_generator")

def setup_logging(verbose=False, console_output=True):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    LOG_DIR = PROJECT_ROOT / "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(LOG_DIR, f"app_{timestamp}.log")
    
    # Always capture everything in the root logger (and thus the file)
    root_level = logging.DEBUG
    
    # Remove existing handlers to avoid duplicates if re-configured
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    handlers = []
    
    # File Handler: Always DEBUG
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    handlers.append(file_handler)

    # Console Handler: Optional, level depends on 'verbose'
    if console_output:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        handlers.append(stream_handler)

    logging.basicConfig(
        level=root_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers
    )
    
    # Silence noise from dependencies
    for logger_name in ["google.genai", "google_genai", "httpx", "google.api_core", "google.auth", "urllib3"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    logger.info(f"Logging initialized. File: {LOG_FILE}")
