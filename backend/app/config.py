import os
import secrets

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # openai_api_key는 이제 embeddings.py(검색 캐시 의미 기반 매칭)에서만 쓴다 -
    # "gpt" 에이전트 슬롯 자체는 2026-08-15부터 OpenAI 토큰 소진으로 Qwen(DashScope)
    # 으로 옮겼다(agents/gpt.py 참고 - 파일/함수/agent="gpt" 식별자는 스키마·
    # 프론트엔드·테스트 전반에 걸쳐 있어 그대로 두고, 내부에서 호출하는 모델만
    # 바꿨다). 아래 qwen_api_key가 그 슬롯의 실제 자격증명이다.
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    qwen_api_key: str | None = os.environ.get("QWEN_API_KEY")
    # DashScope는 리전마다 별도 엔드포인트/계정이다 - 이전에 이 프로젝트가 Qwen을
    # 붙였다가 "Model Studio 계정의 과금 플랜 활성화 문제"로 포기한 적이 있는데
    # (agents/deepseek.py 주석 참고), Model Studio는 국제(비중국 본토) DashScope의
    # 제품명이라 기본값을 국제 엔드포인트로 둔다. 중국 본토 계정이면 .env의
    # QWEN_API_BASE를 https://dashscope.aliyuncs.com/compatible-mode/v1 로 바꿀 것.
    qwen_api_base: str = os.environ.get(
        "QWEN_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    deepseek_api_key: str | None = os.environ.get("DEEPSEEK_API_KEY")
    tavily_api_key: str | None = os.environ.get("TAVILY_API_KEY")
    google_merchant_id: str | None = os.environ.get("GOOGLE_MERCHANT_ID")
    google_service_account_file: str | None = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")

    # DashScope(Alibaba Cloud) 기준 범용 성능이 가장 높은 모델 - 필요하면 .env의
    # QWEN_MODEL로 다른 버전(예: qwen-max-latest)으로 바꿀 수 있다.
    qwen_model: str = os.environ.get("QWEN_MODEL", "qwen-max")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    judge_model: str = os.environ.get("JUDGE_MODEL", "claude-sonnet-5")
    deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    google_vision_api_key: str | None = os.environ.get("GOOGLE_VISION_API_KEY")

    # 검색 캐시의 의미 기반(임베딩) 매칭 on/off. openai_api_key는 이제 이 임베딩
    # 조회에서만 쓰이지만, 그것과 별개로 이 기능 자체만 끄고 싶을 때를 위한
    # 스위치를 그대로 둔다.
    semantic_cache_enabled: bool = os.environ.get("SEMANTIC_CACHE_ENABLED", "true").lower() != "false"

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
