import asyncio

from . import search as search_module
from .agents import gemini, gpt, judge
from .intent import is_bulk_query, needs_clarification
from .schemas import (
    BrandPriceResponse,
    BulkDecideResponse,
    BulkProposal,
    ClarifyResponse,
    DecideResponse,
    Proposal,
)


async def run_debate(query: str) -> DecideResponse | BulkDecideResponse | ClarifyResponse:
    if is_bulk_query(query):
        return await run_bulk_debate(query)
    if needs_clarification(query):
        return await run_clarify(query)
    return await run_single_debate(query)


async def run_single_debate(query: str) -> DecideResponse:
    try:
        results = await search_module.search(query)
    except Exception:
        results = []

    proposals: list[Proposal] = list(
        await asyncio.gather(
            gpt.propose(query, results),
            gemini.propose(query, results),
        )
    )

    decision = await judge.decide(query, proposals)

    return DecideResponse(query=query, proposals=proposals, decision=decision)


async def run_bulk_debate(query: str) -> BulkDecideResponse:
    try:
        results = await search_module.search(query, max_results=10)
    except Exception:
        results = []

    proposals: list[BulkProposal] = list(
        await asyncio.gather(
            gpt.propose_bulk(query, results),
            gemini.propose_bulk(query, results),
        )
    )

    decision = await judge.organize_options(query, proposals)

    return BulkDecideResponse(query=query, proposals=proposals, decision=decision)


async def run_clarify(query: str) -> DecideResponse | ClarifyResponse:
    try:
        results = await search_module.search(query, max_results=10)
    except Exception:
        results = []

    options = await gpt.extract_options(query, results)

    if not (options.brands or options.volumes or options.quantities):
        return await run_single_debate(query)

    return ClarifyResponse(query=query, options=options)


async def run_brand_price(query: str, brand: str) -> BrandPriceResponse:
    try:
        results = await search_module.search(f"{query} {brand}", max_results=10)
    except Exception:
        results = []

    option = await gpt.find_lowest_price(query, brand, results)

    if option is None:
        return BrandPriceResponse(
            query=query, brand=brand, error=f"'{brand}' 브랜드 상품을 찾지 못했습니다."
        )

    return BrandPriceResponse(query=query, brand=brand, option=option)
