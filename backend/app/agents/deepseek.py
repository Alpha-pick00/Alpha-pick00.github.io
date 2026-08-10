from openai import AsyncOpenAI

from ..config import settings
from ..schemas import AgentCandidate, AgentCandidates, BulkProposal, SearchResult
from .base import (
    build_bulk_prompt,
    build_prompt,
    filter_bulk_options,
    filter_candidates,
    parse_json_array,
)

# DeepSeek은 OpenAI 호환 API라 openai SDK를 base_url만 바꿔서 그대로 쓴다.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=DEEPSEEK_BASE_URL)


async def propose(query: str, search_results: list[SearchResult]) -> AgentCandidates:
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": build_prompt(query, search_results)}],
        )
        items = parse_json_array(response.choices[0].message.content or "")
        items = filter_candidates(items)
        return AgentCandidates(agent="deepseek", candidates=[AgentCandidate(**i) for i in items])
    except Exception as exc:
        return AgentCandidates(agent="deepseek", error=str(exc))


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": build_bulk_prompt(query, search_results)}],
        )
        options = parse_json_array(response.choices[0].message.content or "")
        options = filter_bulk_options(options, search_results)
        return BulkProposal(agent="deepseek", options=options)
    except Exception as exc:
        return BulkProposal(agent="deepseek", error=str(exc))
