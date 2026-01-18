import wikipedia
import logging
from google import genai
from google.genai import types
from src.config import API_KEY, DEFAULT_MODEL

logger = logging.getLogger(__name__)

def get_wiki_content(query: str, lang: str = "ja") -> str:
    """
    Fetches the content of a Wikipedia page.
    """
    wikipedia.set_lang(lang)
    try:
        # Use auto_suggest=False to get more precise results for anime titles
        page = wikipedia.page(query, auto_suggest=False)
        return page.content
    except wikipedia.exceptions.DisambiguationError as e:
        logger.warning(f"Disambiguation error for '{query}': {e.options}")
        # Try to get the first option if it's not a list of suggestions
        if e.options:
            try:
                page = wikipedia.page(e.options[0], auto_suggest=False)
                return page.content
            except Exception:
                raise ValueError(f"Ambiguous search result for '{query}'. Options: {', '.join(e.options[:5])}")
        raise ValueError(f"Ambiguous search result for '{query}'.")
    except wikipedia.exceptions.PageError:
        logger.error(f"Page not found for topic: {query}")
        raise ValueError(f"Wikipedia page not found for '{query}' in language '{lang}'.")
    except Exception as e:
        logger.error(f"Unexpected error fetching Wikipedia content: {e}")
        raise

class ContextGenerator:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        if not API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        self.client = genai.Client(api_key=API_KEY)
        self.model_name = model_name

    def generate_summary(self, raw_text: str, query: str) -> str:
        """
        Uses Gemini to summarize Wikipedia content into a markdown reference.
        """
        prompt = (
            f"以下は、'{query}' に関するWikipediaの生データです。\n\n"
            "このテキストを分析し、文字起こしAIのための「超」簡潔なリファレンスを作成してください。\n"
            "**制約事項:**\n"
            "1. **冒頭の挨拶や説明文（「以下は...です」など）は一切書かないでください。** 出力は必ず `# {query}` の見出しから開始してください。\n"
            "2. **説明は極限まで短くしてください。** 長い文章は不要です。体言止めや箇条書きを活用してください。\n"
            "3. 一般的なスラング（陰キャ、中二病など）の辞書的な定義は不要です。「主人公の属性」程度で十分です。\n\n"
            "**出力フォーマット:**\n"
            "# {作品名}\n\n"
            "## 1. 主要登場人物\n"
            "* **名前** (よみ): 属性・役割（例: 主人公、姉、あだ名は「〇〇」）\n\n"
            "## 2. 用語\n"
            "* **用語**: 簡単な説明\n\n"
            "## 3. 概要\n"
            "* 簡潔なあらすじ（3行以内）\n\n"
            "--- WIKIPEDIA CONTENT START ---\n"
            f"{raw_text}\n"
            "--- WIKIPEDIA CONTENT END ---"
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="あなたはデータ整理のプロです。余計な言葉を一切省き、構造化されたデータのみを出力してください。",
                )
            )
            return response.text or ""
        except Exception as e:
            logger.error(f"Error generating summary with Gemini: {e}")
            raise
