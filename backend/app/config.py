import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    deepseek_api_key: str | None = os.environ.get("DEEPSEEK_API_KEY")
    tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY")

    gpt_model: str = os.environ.get("GPT_MODEL", "gpt-4.1")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    judge_model: str = os.environ.get("JUDGE_MODEL", "claude-sonnet-5")
    deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    google_vision_api_key: str | None = os.environ.get("GOOGLE_VISION_API_KEY")


settings = Settings()
