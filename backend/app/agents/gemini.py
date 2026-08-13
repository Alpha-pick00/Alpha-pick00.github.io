from google import genai
from google.genai import types

from ..config import settings
from ..schemas import AgentCandidate, AgentCandidates, BulkProposal, SearchResult
from .base import build_bulk_prompt, build_prompt, filter_bulk_options, filter_candidates, parse_json_array

# Gemini는 GPT의 response_format={"type": "json_object"}에 대응하는 기능이
# response_mime_type이다. 지정하지 않으면 코드블록(```json ... ```)으로 감싸는 등
# 형식이 흔들려서 parse_json_object/array의 정규식 파싱이 실패하는 경우가 있었다.
JSON_CONFIG = types.GenerateContentConfig(response_mime_type="application/json")


async def propose(query: str, search_results: list[SearchResult]) -> AgentCandidates:
    """PRESERVED FROM seungmin/lsm - run_single_debate_price_table_variant
    (app.debate)에서만 쓰인다. run_debate()의 실제 LLM 경로는 adk_pipeline이
    담당하며 거기서는 propose 단계가 LlmAgent로 이미 구현돼 있다."""
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_prompt(query, search_results),
            config=JSON_CONFIG,
        )
        items = parse_json_array(response.text or "")
        items = filter_candidates(items)
        return AgentCandidates(agent="gemini", candidates=[AgentCandidate(**i) for i in items])
    except Exception as exc:
        return AgentCandidates(agent="gemini", error=str(exc))


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_bulk_prompt(query, search_results),
            config=JSON_CONFIG,
        )
        options = parse_json_array(response.text or "")
        options = filter_bulk_options(options, search_results)
        return BulkProposal(agent="gemini", options=options)
    except Exception as exc:
        return BulkProposal(agent="gemini", error=str(exc))
