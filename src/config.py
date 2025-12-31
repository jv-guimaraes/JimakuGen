import os
from pathlib import Path
from dotenv import load_dotenv

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_MODEL = "gemini-2.5-flash"
CACHE_DIR = PROJECT_ROOT / "cache"

# Media Processing Constants
CHUNK_TARGET_SECONDS = 90
MAX_GAP_SECONDS = 2.0
