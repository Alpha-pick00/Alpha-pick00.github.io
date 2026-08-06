from google import genai

from ..config import settings
from ..schemas import BulkProposal, Proposal, SearchResult
from .base import (
    build_bulk_prompt,
    build_prompt,
    is_generic_listing_url,
    parse_json_array,
    parse_json_object,
)


async def propose(query: str, search_results: list[SearchResult]) -> Proposal:
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_prompt(query, search_results),
        )
        data = parse_json_object(response.text or "")
        if data.get("url") and is_generic_listing_url(data["url"]):
            data = {}
        return Proposal(agent="gemini", **data)
    except Exception as exc:
        return Proposal(agent="gemini", error=str(exc))


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=build_bulk_prompt(query, search_results),
        )
        options = parse_json_array(response.text or "")
        options = [o for o in options if not is_generic_listing_url(o.get("url", ""))]
        return BulkProposal(agent="gemini", options=options)
    except Exception as exc:
        return BulkProposal(agent="gemini", error=str(exc))
