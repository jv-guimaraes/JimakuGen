import time
import logging
from google import genai
from google.genai import types
from src.config import API_KEY

logger = logging.getLogger(__name__)

class RateLimitError(Exception):
    """Custom exception for Gemini rate limits."""
    pass

class Transcriber:
    def __init__(self) -> None:
        if not API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        self.client = genai.Client(api_key=API_KEY)

    def transcribe_chunk(self, audio_path: str, english_context: str, model_name: str, series_info: str | None = None) -> str:
        try:
            sample_file = self.client.files.upload(file=audio_path)
            file_name = sample_file.name
            if not file_name:
                raise ValueError("Failed to upload file: No name returned.")

            while sample_file.state == types.FileState.PROCESSING:
                time.sleep(2)
                sample_file = self.client.files.get(name=file_name)
            
            prompt_parts = []
            if series_info:
                prompt_parts.append(f"Series Information:\n{series_info}")

            prompt_parts.append(
                "Transcribe the Japanese dialogue accurately. "
                "You MUST use the following timestamp format for EVERY line: [MM:SS,mmm - MM:SS,mmm] Dialogue. "
                "Do not use any other format. Example: [00:01,250 - 00:03,100] こんにちは"
            )
            prompt_parts.append(f"English Context Reference:\n{english_context}")
            
            prompt = "\n\n".join(prompt_parts)
            
            logger.debug(f"--- Prompt sent to Gemini ---\n{prompt}\n-----------------------------")
            
            response = self.client.models.generate_content(
                model=model_name,
                contents=[sample_file, prompt],
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert Japanese media transcriber."
                )
            )
            logger.debug(f"--- Response from Gemini ---\n{response.text}\n----------------------------")
            return response.text or ""
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg:
                raise RateLimitError(err_msg)
            else:
                raise e
