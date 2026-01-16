# JimakuGen

## Project Overview

**JimakuGen** is a Python-based CLI tool designed to generate Japanese subtitles for video files. It leverages the Google Gemini API to transcribe Japanese dialogue, using existing English subtitle tracks as context to improve accuracy (e.g., disambiguating homophones and selecting correct Kanji).

### Key Features
*   **Context-Aware Transcription:** Uses English subtitles to guide the Japanese transcription.
*   **Smart Segmentation:** Splits media into chunks based on silence to preserve dialogue integrity.
*   **Validation & Retry:** Automatically validates generated subtitles for timestamp errors or hallucinations and retries if necessary.
*   **Caching:** Caches transcribed chunks locally in `cache/` to resume interrupted jobs without re-processing.
*   **CLI Interface:** Simple command-line interface for processing videos.

### Architecture
*   **`src/core.py`**: Orchestrates the entire pipeline: extraction, segmentation, caching, and loop control.
*   **`src/transcriber.py`**: Handles interactions with the Google Gemini API (file uploads, content generation).
*   **`src/media_utils.py`**: Wrappers around `ffmpeg` for extracting audio and subtitle tracks.
*   **`src/utils.py`**: Helper functions for timestamp parsing, validation, and time conversion.

## Building and Running

### Prerequisites
*   Python 3.10+
*   `ffmpeg` installed and available in the system PATH.
*   A Google Cloud API key with access to Gemini models.

### Setup
1.  **Environment:** Create and activate a virtual environment.
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # .venv\Scripts\activate   # Windows
    ```
2.  **Dependencies:** Install required packages.
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuration:** Create a `.env` file in the project root.
    ```env
    GOOGLE_API_KEY=your_gemini_api_key
    ```

### Execution
Run the tool directly via the entry point script:
```bash
python main.py <video_file_path> [options]
```

**Common Options:**
*   `--context <file>`: Text file with series-specific terms/names.
*   `--chunk-size <seconds>`: Target duration for audio chunks (default: 90s).
*   `--limit <n>`: Process only the first N chunks (useful for testing).
*   `-o <path>`: Specify output file path.

### Running Tests
The project uses `unittest`. Run all tests with:
```bash
python -m unittest discover tests
```

## Development Conventions

*   **Code Style:** Follows standard Python PEP 8 conventions. Type hinting is used throughout the `src` directory.
*   **Logging:** Uses the standard `logging` library. Verbose output (`DEBUG` level) can be enabled with the `-v` flag.
*   **Error Handling:** The `Transcriber` handles rate limits (`429`) by raising a custom `RateLimitError`. The core loop catches this to stop gracefully.
*   **Testing:** Regression tests are located in `tests/` and use `.ass` fixtures in `tests/fixtures/` with expected outputs in `tests/expected/` to verify subtitle extraction logic.
*   **Dependencies:** Managed via `requirements.txt` and `pyproject.toml`.
