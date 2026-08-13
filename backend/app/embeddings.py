from openai import AsyncOpenAI

from .config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 512


async def embed_query(text: str) -> list[float]:
    """검색 질의를 벡터로 변환한다 — search_cache.find_similar()가 의미 기반
    캐시 매칭에 사용. 512차원으로 줄여 SQLite 저장량을 아낀다."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding
