import os

# Configuration
API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_MODEL = "gemini-2.0-flash-exp"
CACHE_DIR = "cache"

# Media Processing Constants
CHUNK_TARGET_SECONDS = 60
MAX_GAP_SECONDS = 2.0
