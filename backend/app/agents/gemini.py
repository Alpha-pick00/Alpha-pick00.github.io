from openai import AsyncOpenAI

from ..config import settings
from ..schemas import AgentCandidate, AgentCandidates, BulkProposal, SearchResult
from .base import build_bulk_prompt, build_prompt, filter_bulk_options, filter_candidates, parse_json_array

# 이 모듈이 담당하는 에이전트 슬롯은 스키마/프론트엔드/테스트 전반에서
# agent="gemini"로 식별된다(파일명·함수명도 그대로) - 하지만 실제로 호출하는
# 모델은 2026-08-16부터 Gemini가 아니라 Groq다(사용자 요청: "deepseek Qwen
# 빼고 싹 다 무료 모델로 바꾸려고 해" - Gemini 프로젝트가 403으로 막혀있기도
# 했다). Groq도 OpenAI 호환 엔드포인트를 제공해서, openai SDK를 base_url만
# 바꿔 그대로 쓴다(agents/deepseek.py와 동일한 패턴).


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_api_base)


async def propose(query: str, search_results: list[SearchResult]) -> AgentCandidates:
    """PRESERVED FROM seungmin/lsm - run_single_debate_price_table_variant
    (app.debate)에서만 쓰인다. run_debate()의 실제 LLM 경로는 adk_pipeline이
    담당하며 거기서는 propose 단계가 LlmAgent로 이미 구현돼 있다."""
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": build_prompt(query, search_results)}],
        )
        items = parse_json_array(response.choices[0].message.content or "")
        items = filter_candidates(items)
        return AgentCandidates(agent="gemini", candidates=[AgentCandidate(**i) for i in items])
    except Exception as exc:
        return AgentCandidates(agent="gemini", error=str(exc))


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
