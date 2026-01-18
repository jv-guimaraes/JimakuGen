# JimakuGen

JimakuGen is a CLI tool that generates Japanese subtitles for video files using the Google Gemini API. It improves transcription accuracy by using existing English subtitle tracks as context, helping the model disambiguate homophones and select correct Kanji based on the translation.

## Usage

JimakuGen provides a modern CLI with several commands.

### Configuration
First, set up your API key:
```bash
jimakugen config
# Or manually provide it:
jimakugen config --api-key YOUR_KEY
```

### Checking Environment
Verify that FFmpeg and credentials are set up correctly:
```bash
jimakugen check
```

### Generating Context
Generate a context reference file from Wikipedia to improve transcription accuracy:
```bash
jimakugen context "僕の心のヤバイやつ"
```
This will search Japanese Wikipedia by default and use Gemini to summarize character names and terminology into a Markdown file.

### Generating Subtitles
Run the transcription on a video file:
```bash
jimakugen run video.mkv
```
This will generate `video.ja.srt` in the same directory. You can use the generated context file:
```bash
jimakugen run video.mkv --context boku_no_kokoro_no_yabai_yatsu_context.md
```

### Options for `context`

| Option | Description |
| :--- | :--- |
| `--output, -o <path>` | Custom output path for the markdown file. |
| `--lang <lang>` | Wikipedia language code (default: `ja`). |
| `--model <name>` | Gemini model to use for summarization. |

### Options for `run`

| Option | Description |
| :--- | :--- |
| `--context, -c <file>` | Path to a text file with series specific terms. |
| `--model <name>` | Gemini model to use (default: `gemini-2.5-flash`). |
| `--chunk-size <sec>` | Target duration for audio chunks (default: 90s). |
| `--limit <n>` | Process only the first N chunks (for testing). |
| `--output, -o <path>` | Custom output path. |
| `--verbose, -v` | Enable verbose logging (to file). |
| `--keep-temp` | Keep temporary files (extracted audio/subs). |

Example:
```bash
jimakugen run episode_01.mkv --context context.txt --model gemini-2.5-pro
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
1.  **Extraction**: Uses `ffmpeg` to extract the Japanese audio track and the best available English subtitle track. It filters the subtitle stream to remove non-dialogue elements like "Signs & Songs" to ensure the model focuses on spoken dialogue.
2.  **Segmentation**: Splits the media into chunks (default ~90s), aligning strictly with silence to avoid cutting dialogue. This "chunking" approach reduces the cognitive load on the LLM and enables targeted error recovery.
3.  **Transcription**: Sends the audio chunk along with the corresponding English text to Gemini. The English text serves as both a semantic "ground truth" for meaning and a precise timing reference, allowing the model to generate accurately synchronized Japanese subtitles.
4.  **Validation & Retry**: Each chunk is validated for common LLM errors (e.g., impossible timestamps, extreme reading speeds, or hallucinations). If a chunk fails validation, the tool automatically retries that specific segment.
5.  **Assembly**: Merges the transcribed segments into a final SRT file.

**Caching**: Successful chunks are cached locally in `cache/`. If the process is interrupted or you re-run it, it will skip already transcribed segments.

## Limitations

*   **Hallucinations**: Like all LLM-based tools, the model may hallucinate. Since it uses English text as a guide, it might occasionally generate Japanese dialogue that matches the *meaning* of the English text but does not match the actual spoken audio.
*   **API Quotas**: Processing long videos may hit the Gemini API rate limits on free tiers. The tool handles rate limits by stopping gracefully (or crashing, depending on severity), but cached progress is saved.
*   **Input**: Currently requires a video file with embedded English subtitles. External subtitle files are not yet supported.
