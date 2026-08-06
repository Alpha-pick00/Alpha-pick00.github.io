from openai import AsyncOpenAI

from ..config import settings
from ..schemas import BrandOption, BulkProposal, ClarifyOptions, Proposal, SearchResult
from .base import (
    build_brand_price_prompt,
    build_bulk_prompt,
    build_clarify_prompt,
    build_price_confirm_prompt,
    build_prompt,
    is_generic_listing_url,
    parse_json_array,
    parse_json_object,
)


async def propose(query: str, search_results: list[SearchResult]) -> Proposal:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_prompt(query, search_results)}],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        if data.get("url") and is_generic_listing_url(data["url"]):
            data = {}
        return Proposal(agent="gpt", **data)
    except Exception as exc:
        return Proposal(agent="gpt", error=str(exc))


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_bulk_prompt(query, search_results)}],
        )
        options = parse_json_array(response.choices[0].message.content or "")
        options = [o for o in options if not is_generic_listing_url(o.get("url", ""))]
        return BulkProposal(agent="gpt", options=options)
    except Exception as exc:
        return BulkProposal(agent="gpt", error=str(exc))


async def extract_options(query: str, search_results: list[SearchResult]) -> ClarifyOptions:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_clarify_prompt(query, search_results)}],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        return ClarifyOptions(**data)
    except Exception:
        return ClarifyOptions()


async def find_lowest_price(
    query: str, brand: str, search_results: list[SearchResult]
) -> BrandOption | None:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[
                {"role": "user", "content": build_brand_price_prompt(query, brand, search_results)}
            ],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        if not data.get("product_name"):
            return None
        if is_generic_listing_url(data.get("url", "")):
            return None
        return BrandOption(brand=brand, **data)
    except Exception:
        return None
