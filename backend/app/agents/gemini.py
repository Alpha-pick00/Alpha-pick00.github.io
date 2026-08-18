from openai import AsyncOpenAI

from ..config import settings
from ..schemas import BulkProposal, SearchResult
from .base import build_bulk_prompt, filter_bulk_options, parse_json_array

# 이 모듈이 담당하는 에이전트 슬롯은 스키마/프론트엔드/테스트 전반에서
# agent="gemini"로 식별된다(파일명·함수명도 그대로) - 하지만 실제로 호출하는
# 모델은 2026-08-16부터 Gemini가 아니라 Groq다(사용자 요청: "deepseek Qwen
# 빼고 싹 다 무료 모델로 바꾸려고 해" - Gemini 프로젝트가 403으로 막혀있기도
# 했다). Groq도 OpenAI 호환 엔드포인트를 제공해서, openai SDK를 base_url만
# 바꿔 그대로 쓴다(agents/deepseek.py와 동일한 패턴).


def _client() -> AsyncOpenAI:
    # max_retries=0 - embeddings.py와 동일한 이유(사용자 요청, 2026-08-15: "너무
    # 느려 더 빠르게"). 실패해도 호출부가 이미 폴백을 갖고 있어 SDK 재시도로
    # 얻는 이득보다 지연 비용이 크다.
    return AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_api_base, max_retries=0)


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": build_bulk_prompt(query, search_results)}],
        )
        options = parse_json_array(response.choices[0].message.content or "")
        options = filter_bulk_options(options, search_results)
        return BulkProposal(agent="gemini", options=options)
    except Exception as exc:
        return BulkProposal(agent="gemini", error=str(exc))
