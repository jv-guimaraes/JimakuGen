import time
import logging
from google import genai
from google.genai import types, errors
from src.config import API_KEY, POLLING_INTERVAL_SECONDS

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
        file_name = None
        try:
            sample_file = self.client.files.upload(file=audio_path)
            file_name = sample_file.name
            if not file_name:
                raise ValueError("Failed to upload file: No name returned.")

            while sample_file.state == types.FileState.PROCESSING:
                time.sleep(POLLING_INTERVAL_SECONDS)
                sample_file = self.client.files.get(name=file_name)
            
            if sample_file.state == types.FileState.FAILED:
                raise ValueError(f"File processing failed: {sample_file.name}")

            prompt_parts = []
            if series_info:
                prompt_parts.append(f"Series Information:\n{series_info}")

            prompt_parts.append(
                "Transcribe the Japanese speech accurately. "
                "Ignore non-verbal sounds such as grunts, screams, heavy breathing, laughter, or background noise. "
                "Only transcribe spoken Japanese words. "
                "You MUST use the following timestamp format for EVERY line: [MM:SS,mmm - MM:SS,mmm] Dialogue. "
                "Example: [00:01,250 - 00:03,100] こんにちは"
            )
            prompt_parts.append(f"English Context Reference:\n{english_context}")
            
            prompt = "\n\n".join(prompt_parts)
            
            logger.debug(f"--- Prompt sent to Gemini ---\n{prompt}\n-----------------------------")
            
            response = self.client.models.generate_content(
                model=model_name,
                contents=[sample_file, prompt],
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert Japanese media transcriber.",
                    media_resolution="MEDIA_RESOLUTION_HIGH",
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT",
                            threshold="BLOCK_NONE",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH",
                            threshold="BLOCK_NONE",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_NONE",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_NONE",
                        ),
                    ]
                )
            )
            logger.debug(f"--- Response from Gemini ---\n{response.text}\n----------------------------")
            return response.text or ""
        
        except errors.ClientError as e:
            # 429 is usually ClientError in this SDK
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning(f"Gemini API rate limit exceeded: {e}")
                raise RateLimitError(str(e))
            logger.error(f"Gemini Client Error: {e}")
            raise e
        except errors.APIError as e:
            logger.error(f"Gemini API Error: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in transcribe_chunk: {e}")
            raise e
        finally:
            if file_name:
                try:
                    self.client.files.delete(name=file_name)
                    logger.debug(f"Deleted remote file: {file_name}")
                except Exception as e:
                    logger.warning(f"Failed to delete remote file {file_name}: {e}")
