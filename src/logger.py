import os
import sys
import time
import logging

logger = logging.getLogger("subtitle_generator")

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
