import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY")

    gpt_model: str = os.environ.get("GPT_MODEL", "gpt-4.1")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    judge_model: str = os.environ.get("JUDGE_MODEL", "claude-sonnet-5")


settings = Settings()
