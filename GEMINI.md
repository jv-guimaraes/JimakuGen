# Project Context: Subtitles Experiment

## Overview
This project is a Python-based tool designed to generate Japanese subtitles for video files. It leverages the **Google Gemini API** to transcribe audio, using existing English subtitles embedded in the video file as context to improve accuracy. This approach is particularly useful for anime or other media where English subtitles are available but Japanese subtitles are missing or incomplete.

## Key Features
*   **Smart Segmentation:** Groups dialogue events into manageable chunks based on time gaps to ensure context is preserved.
*   **Context-Aware Transcription:** Extracts audio chunks and sends them to Gemini along with the corresponding English subtitles. This helps the model differentiate between similar-sounding words or infer context that might be ambiguous in audio alone.
*   **Caching:** Caches transcription results to `cache/` to prevent redundant API calls and speed up re-runs.
*   **Format Handling:** extracting English subtitles from `.ass` tracks within `.mkv` files and outputting standard `.srt` files.

## Tech Stack
*   **Language:** Python 3
*   **AI Model:** Google Gemini (specifically `gemini-2.5-flash-preview-09-2025`)
*   **Media Processing:** `ffmpeg` (via `subprocess`) for extracting audio and subtitle tracks.
*   **Dependencies:**
    *   `google-generativeai`: For interacting with the Gemini API.
    *   `pysrt`: For subtitle handling (though the core parsing logic seems custom-implemented for `.ass`).
    *   `python-dotenv`: Listed in requirements, likely for environment management (Note: `load_dotenv()` is not currently called in `main.py`).

## Setup & Configuration

### Prerequisites
1.  **Python 3.x**
2.  **FFmpeg:** Must be installed and accessible in the system PATH.
3.  **Google Cloud API Key:** A valid API key with access to Gemini models.

### Installation
1.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```
2.  Install Python dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Environment Variables
The application requires the `GOOGLE_API_KEY` environment variable to be set.
```bash
export GOOGLE_API_KEY="your_api_key_here"
```
*Note: A `.env` file is ignored by git, but the script currently expects the variable to be present in the environment.*

## Usage
To generate Japanese subtitles for a video file:

```bash
python main.py <path_to_video_file>
```

**Example:**
```bash
python main.py sample/Yofukashi_no_Uta_01.mkv
```

**Output:**
The script generates a new subtitle file in the same directory as the input video, with the extension `.ja.generated.srt`.

## Project Structure
*   `main.py`: The core script containing the workflow logic (file I/O, API interaction).
*   `subtitle_extractor.py`: Module for analyzing video files, selecting the best English subtitle track, and extracting/cleaning dialogue events.
*   `requirements.txt`: Python package dependencies.
*   `cache/`: Directory where intermediate transcription results are stored.
*   `sample/`: Directory containing sample video and subtitle files.
