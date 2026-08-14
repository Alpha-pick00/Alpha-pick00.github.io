from openai import AsyncOpenAI

from .config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 512


async def embed_query(text: str) -> list[float]:
    """검색 질의를 벡터로 변환한다 — search_cache.find_similar()가 의미 기반
    캐시 매칭에 사용. 512차원으로 줄여 SQLite 저장량을 아낀다.

    max_retries=0(사용자 요청, 2026-08-15: "너무 느려 더 빠르게") - 호출부
    (app.search.search)가 이미 실패 시 Tavily로 안전하게 폴백하므로, OpenAI SDK
    기본 재시도(2회, 지수 백오프)는 살릴 이유가 없다. 크레딧 소진처럼 재시도해도
    똑같이 실패할 오류(429 insufficient_quota)에 매 검색 호출마다 ~1.3초씩
    허비하고 있었다 - 낭비될 뿐 아니라 실제 정상 응답이 와야 할 자리를 계속
    지연시켰다."""
    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding
