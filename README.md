# Japanese Subtitle Generator (Gemini-based)

This project is a Python-based tool designed to generate Japanese subtitles for video files. It leverages the **Google Gemini API** to transcribe audio, using existing English subtitles embedded in the video file as context to improve accuracy.

This approach is particularly useful for media where English subtitles are available but Japanese subtitles are missing or incomplete, as the English context helps the model differentiate between similar-sounding words and infer correct kanji.

## Key Features

*   **Context-Aware Transcription:** Extracts audio chunks and sends them to Gemini along with the corresponding English subtitles. This helps the model disambiguate audio and produce higher-quality transcriptions.
*   **Smart Segmentation:** Groups dialogue events into manageable chunks (default 60s) based on time gaps, ensuring that conversational context is preserved while staying within model limits.
*   **Automated Track Selection:** Uses `ffprobe` to automatically identify:
    *   The best English subtitle track (prioritizing full dialogue over "Signs & Songs").
    *   The Japanese audio track.
*   **Caching:** Stores transcription results in the `cache/` directory to prevent redundant API calls and speed up subsequent runs.
*   **Clean Output:** Automatically removes unnecessary spaces in the generated Japanese text and outputs standard `.srt` files.
*   **Format Handling:** Handles `.ass` tracks within `.mkv` containers and produces `.ja.srt` files.

## Tech Stack

*   **Language:** Python 3
*   **AI Model:** Google Gemini (defaulting to `gemini-2.5-flash`)
*   **Media Processing:** `ffmpeg` and `ffprobe` for audio extraction and stream analysis.
*   **Dependencies:** `google-genai` for API interaction.

## Setup & Configuration

### Prerequisites

1.  **Python 3.x**
2.  **FFmpeg:** Must be installed and accessible in your system PATH.
3.  **Google Cloud API Key:** A valid API key with access to Gemini models.

### Installation

1.  Clone the repository and navigate to the project directory.
2.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Environment Variables

The application requires the `GOOGLE_API_KEY` environment variable.
```bash
export GOOGLE_API_KEY="your_api_key_here"
```

## Usage

To generate Japanese subtitles for a video file:

```bash
python main.py <path_to_video_file>
```

### Options

*   `-v`, `--verbose`: Enable DEBUG level logging for detailed information.
*   `--chunk-size <seconds>`: Target duration for each transcription chunk (default: 60).
*   `--context <file.txt>`: Provide additional series context (character names, world-building terms) to the model.
*   `--limit <number>`: Limit the number of chunks to process (useful for testing).
*   `--model <model_name>`: Specify which Gemini model to use (default: `gemini-3-flash-preview`).
*   `-o`, `--output <path>`: Custom output path for the generated SRT file (default: `<video_name>.ja.srt`).

### Example

```bash
python main.py samples/movie.mkv --context context.txt
```

The script will generate a file named `movie.ja.srt` in the same directory as the input video.

## Project Structure

*   `main.py`: Entry point for the CLI.
*   `src/`: Core application package containing logic, configuration, and utilities.
*   `cache/`: Stores intermediate transcription results.
*   `logs/`: Detailed execution logs.
*   `tests/`: Regression tests and sample fixtures.

## Development

Run tests to ensure everything is working correctly:
```bash
python -m unittest discover tests
```
