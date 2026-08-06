from google import genai
from google.genai import types

from ..config import settings
from ..schemas import BulkProposal, Proposal, SearchResult
from .base import (
    build_bulk_prompt,
    build_prompt,
    filter_bulk_options,
    parse_json_array,
    parse_json_object,
    proposal_data_or_error,
)

# Gemini는 GPT의 response_format={"type": "json_object"}에 대응하는 기능이
# response_mime_type이다. 지정하지 않으면 코드블록(```json ... ```)으로 감싸는 등
# 형식이 흔들려서 parse_json_object/array의 정규식 파싱이 실패하는 경우가 있었다.
JSON_CONFIG = types.GenerateContentConfig(response_mime_type="application/json")


async def propose(query: str, search_results: list[SearchResult]) -> Proposal:
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_prompt(query, search_results),
            config=JSON_CONFIG,
        )
        data = parse_json_object(response.text or "")
        data = proposal_data_or_error(data)
        return Proposal(agent="gemini", **data)
    except Exception as exc:
        return Proposal(agent="gemini", error=str(exc))


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
