import asyncio
import logging
import re
from typing import Any, AsyncIterator

from . import adk_pipeline
from . import search as search_module
from .agents import deepseek, gemini, gpt, judge
from .intent import is_bulk_query, needs_clarification
from .schemas import (
    BrandOption,
    BrandPriceResponse,
    BulkDecideResponse,
    BulkProposal,
    ClarifyOptions,
    ClarifyResponse,
    DecideResponse,
    PriceRange,
    SearchResult,
)

logger = logging.getLogger(__name__)


def _price_to_int(price: str) -> int | None:
    digits = re.sub(r"[^\d]", "", price or "")
    return int(digits) if digits else None


def _compute_price_range(options: list[BrandOption]) -> PriceRange | None:
    prices = [n for n in (_price_to_int(o.price) for o in options) if n is not None]
    if not prices:
        return None
    return PriceRange(min=f"{min(prices):,}원", max=f"{max(prices):,}원")


async def run_debate(query: str) -> DecideResponse | BulkDecideResponse | ClarifyResponse:
    if is_bulk_query(query):
        return await run_bulk_debate(query)
    if needs_clarification(query):
        return await run_clarify(query)
    return await run_single_debate(query)


async def run_debate_stream(query: str) -> AsyncIterator[dict[str, Any]]:
    """단일 상품 검색만 단계별 이벤트로 스트리밍한다. bulk/clarify는 흐름 자체가
    다르고(브랜드 목록 선택, 가격대별 정리) 단계를 쪼갤 만한 지점이 마땅치 않아,
    최종 결과 하나만 "final" 이벤트로 보낸다 — 프론트는 이벤트 타입 하나만 보고
    두 경우 다 처리하면 된다."""
    if is_bulk_query(query):
        yield {"type": "final", "result": (await run_bulk_debate(query)).model_dump()}
        return
    if needs_clarification(query):
        yield {"type": "final", "result": (await run_clarify(query)).model_dump()}
        return

    async for event in run_single_debate_stream(query):
        yield event


def _dedupe_case_insensitive(items: list[str]) -> list[str]:
    """검색 결과가 여러 판매처에서 오다 보니 같은 값이 대소문자만 다르게
    뽑히는 경우가 있다("APPLE" vs "Apple") — 실제로는 같은 선택지인데
    사용자에게 중복으로 보여주거나 애매함 판정을 오탐시키지 않도록 정리한다.
    처음 나온 표기를 그대로 유지하고 순서도 보존한다."""
    seen: set[str] = set()
    deduped = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


async def _extract_clarify_options(query: str, results: list[SearchResult]) -> ClarifyResponse | None:
    """검색 결과에서 브랜드/용량/수량을 뽑아본다. 아무것도 못 찾으면 None.
    이미 가져온 검색 결과를 그대로 받아 재검색하지 않는다 — run_single_debate가
    전체 실패했을 때 같은 결과로 이 함수를 다시 시도하는 용도로도 쓰인다."""
    raw = await gpt.extract_options(query, results)
    options = ClarifyOptions(
        brands=_dedupe_case_insensitive(raw.brands),
        volumes=_dedupe_case_insensitive(raw.volumes),
        quantities=_dedupe_case_insensitive(raw.quantities),
    )
    if not (options.brands or options.volumes or options.quantities):
        return None
    return ClarifyResponse(query=query, options=options)


async def run_single_debate(query: str) -> DecideResponse | ClarifyResponse:
    """정제→검색→제안(GPT·Gemini·DeepSeek 병렬)→필터링+병합→검증→매칭→심사
    역할 분리 파이프라인 — 실제 오케스트레이션은 adk_pipeline(ADK SequentialAgent)이
    담당한다. 이 함수는 main.py/run_debate가 기대하는 기존 시그니처를 유지하는
    얇은 래퍼."""
    return await adk_pipeline.run(query)


async def run_single_debate_stream(query: str) -> AsyncIterator[dict[str, Any]]:
    """run_single_debate와 같은 결과를 만들지만, 파이프라인 단계마다(정제/검색/
    제안/검증/심사) NDJSON 이벤트를 흘려보낸다 — adk_pipeline.run_stream이 실제
    오케스트레이션과 이벤트 번역을 담당."""
    async for event in adk_pipeline.run_stream(query):
        yield event


async def run_bulk_debate(query: str) -> BulkDecideResponse | DecideResponse | ClarifyResponse:
    try:
        results = await search_module.search(query, max_results=10)
    except Exception:
        results = []

    proposals: list[BulkProposal] = list(
        await asyncio.gather(
            gpt.propose_bulk(query, results),
            gemini.propose_bulk(query, results),
            deepseek.propose_bulk(query, results),
        )
    )

    decision = await judge.organize_options(query, proposals)

    if len(decision.options) <= 1:
        # is_bulk_query()는 "숫자+단위가 있으면 대량구매성"이라는 근사치
        # 휴리스틱이라, "메로나 빙그레 70mL"처럼 애초에 특정 상품 하나를
        # 가리키는 질의도 걸릴 수 있다(코드 주석에 이미 명시된 한계). 실제로
        # 갈리는 브랜드가 0~1개뿐이면 "여러 브랜드 비교"라는 전제 자체가
        # 성립하지 않으므로, 브랜드별 비교 포맷 대신 단일상품 파이프라인으로
        # 다시 판단한다.
        return await run_single_debate(query)

    price_range = _compute_price_range(decision.options)

    return BulkDecideResponse(
        query=query, proposals=proposals, decision=decision, price_range=price_range
    )


async def run_clarify(query: str) -> DecideResponse | ClarifyResponse:
    try:
        results = await search_module.search(query, max_results=10)
    except Exception:
        results = []

    clarify = await _extract_clarify_options(query, results)
    if clarify is not None:
        return clarify

    return await run_single_debate(query)


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
