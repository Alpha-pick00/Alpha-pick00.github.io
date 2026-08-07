import os
import secrets

from dotenv import load_dotenv

load_dotenv()


class Settings:
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    deepseek_api_key: str | None = os.environ.get("DEEPSEEK_API_KEY")
    tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY")
    google_merchant_id: str | None = os.environ.get("GOOGLE_MERCHANT_ID")
    google_service_account_file: str | None = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")

    gpt_model: str = os.environ.get("GPT_MODEL", "gpt-4.1")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    judge_model: str = os.environ.get("JUDGE_MODEL", "claude-sonnet-5")
    deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    google_vision_api_key: str | None = os.environ.get("GOOGLE_VISION_API_KEY")

    # 소셜 로그인 (Google Client ID는 프론트엔드 VITE_GOOGLE_CLIENT_ID로만 쓰임 —
    # access_token으로 유저 정보를 조회하는 방식이라 백엔드는 client id가 필요 없다)
    kakao_client_id: str | None = os.environ.get("KAKAO_CLIENT_ID")
    kakao_client_secret: str | None = os.environ.get("KAKAO_CLIENT_SECRET")
    naver_client_id: str | None = os.environ.get("NAVER_CLIENT_ID")
    naver_client_secret: str | None = os.environ.get("NAVER_CLIENT_SECRET")

    # 세션(JWT) 서명 키. 지정하지 않으면 프로세스 시작 시 무작위로 생성되는데,
    # 이 경우 서버가 재시작될 때마다 기존 로그인 세션이 전부 무효화된다.
    # 실제 배포 시에는 반드시 .env에 고정값을 넣을 것 (예: python -c "import secrets; print(secrets.token_hex(32))").
    session_secret_key: str = os.environ.get("SESSION_SECRET_KEY") or secrets.token_hex(32)


settings = Settings()
