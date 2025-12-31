# JimakuGen

JimakuGen is a CLI tool that generates Japanese subtitles for video files using the Google Gemini API. It improves transcription accuracy by using existing English subtitle tracks as context, helping the model disambiguate homophones and select correct Kanji based on the translation.

## Usage

Basic usage:
```bash
python main.py video.mkv
```
This will generate `video.ja.srt` in the same directory.

### Options

| Option | Description |
| :--- | :--- |
| `--context <file>` | Path to a text file with series specific terms (names, lore, etc). |
| `--model <name>` | Gemini model to use (default: `gemini-2.5-flash`). |
| `--chunk-size <sec>` | Target duration for audio chunks (default: 90s). |
| `--limit <n>` | Process only the first N chunks (for testing). |
| `-o <path>` | Custom output path. |

Example with a context file:
```bash
python main.py episode_01.mkv --context context.txt
```

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/yourusername/JimakuGen.git
    cd JimakuGen
    ```

2.  Set up the environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # or .venv\Scripts\activate on Windows
    pip install -r requirements.txt
    ```

3.  Configure your API key:
    Create a `.env` file in the root directory (or export the variable):
    ```bash
    GOOGLE_API_KEY=your_gemini_api_key
    ```

## Functionality

JimakuGen automates the following pipeline:
1.  **Extraction**: Uses `ffmpeg` to extract the Japanese audio track and the best available English subtitle track.
2.  **Segmentation**: Splits the media into chunks (default ~90s), aligning strictly with silence to avoid cutting dialogue.
3.  **Transcription**: Sends the audio chunk along with the corresponding English text to Gemini. The English text serves as a "ground truth" for meaning, guiding the model's Japanese transcription.
4.  **Assembly**: Merges the transcribed segments into a final SRT file.

**Caching**: Successful chunks are cached locally in `cache/`. If the process is interrupted or you re-run it, it will skip already transcribed segments.

## Limitations

*   **Hallucinations**: Like all LLM-based tools, the model may hallucinate. Since it uses English text as a guide, it might occasionally generate Japanese dialogue that matches the *meaning* of the English text but does not match the actual spoken audio.
*   **API Quotas**: Processing long videos may hit the Gemini API rate limits on free tiers. The tool handles rate limits by stopping gracefully (or crashing, depending on severity), but cached progress is saved.
*   **Input**: Currently requires a video file with embedded English subtitles. External subtitle files are not yet supported.
