import asyncio
import logging
import re
from typing import Any, AsyncIterator

from . import search as search_module
from .agents import deepseek, gemini, gpt, judge
from .agents.base import NO_CANDIDATE_ERROR
from .intent import is_bulk_query, needs_clarification
from .schemas import (
    AgentCandidates,
    BrandOption,
    BrandPriceResponse,
    BulkDecideResponse,
    BulkProposal,
    ClarifyResponse,
    DecideResponse,
    PriceRange,
    Proposal,
    SearchResult,
)

logger = logging.getLogger(__name__)


def _format_price_krw(price_krw: int | None) -> str:
    return f"{price_krw:,}원" if price_krw is not None else ""


def _top_proposal(agent_candidates: AgentCandidates) -> Proposal:
    """에이전트가 배열로 낸 후보 중 1순위(선호도 최상위) 하나만 골라 기존
    Proposal 형태로 맞춘다 — 프론트엔드가 에이전트당 정확히 1행을 기대하므로
    응답 스키마는 그대로 두고, 병합 전 전체 배열은 fusion 모듈에서만 쓴다."""
    if agent_candidates.error is not None:
        return Proposal(agent=agent_candidates.agent, error=agent_candidates.error)
    if not agent_candidates.candidates:
        return Proposal(agent=agent_candidates.agent, error=NO_CANDIDATE_ERROR)
    top = agent_candidates.candidates[0]
    return Proposal(
        agent=agent_candidates.agent,
        product_name=top.product_name,
        price=_format_price_krw(top.price_krw),
        retailer=top.retailer,
        url=top.url,
        reasoning=top.reasoning,
    )


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


async def _extract_clarify_options(query: str, results: list[SearchResult]) -> ClarifyResponse | None:
    """검색 결과에서 브랜드/용량/수량을 뽑아본다. 아무것도 못 찾으면 None.
    이미 가져온 검색 결과를 그대로 받아 재검색하지 않는다 — run_single_debate가
    전체 실패했을 때 같은 결과로 이 함수를 다시 시도하는 용도로도 쓰인다."""
    options = await gpt.extract_options(query, results)
    if not (options.brands or options.volumes or options.quantities):
        return None
    return ClarifyResponse(query=query, options=options)


async def run_single_debate(query: str) -> DecideResponse | ClarifyResponse:
    try:
        results = await search_module.search(query)
    except Exception:
        results = []

    agent_candidates: list[AgentCandidates] = list(
        await asyncio.gather(
            gpt.propose(query, results),
            gemini.propose(query, results),
            deepseek.propose(query, results),
        )
    )
    logger.info(
        "candidate pool sizes for %r: %s",
        query,
        {ac.agent: len(ac.candidates) for ac in agent_candidates},
    )
    proposals = [_top_proposal(ac) for ac in agent_candidates]

    if all(p.error is not None for p in proposals):
        # 세 에이전트가 전부 특정 상품 후보를 못 찾았다 — "아이스크림"처럼 카테고리
        # 자체가 너무 넓은 질의일 때 흔하다(검색 결과가 상품 상세 페이지가 아니라
        # 목록/카테고리 페이지뿐이라 URL 기준 필터를 못 통과함). 완전 실패로 끝내는
        # 대신, 같은 검색 결과에서 브랜드만이라도 뽑아 되물어본다 — 특정 상품 URL을
        # 찾는 것보다 브랜드명이 텍스트에 스치듯 언급됐는지 보는 게 기준이 훨씬
        # 관대해서 성공률이 높다.
        clarify = await _extract_clarify_options(query, results)
        if clarify is not None:
            return clarify
        raise RuntimeError(NO_CANDIDATE_ERROR)

    decision = await judge.decide(query, proposals)

    return DecideResponse(query=query, proposals=proposals, decision=decision)


async def run_single_debate_stream(query: str) -> AsyncIterator[dict[str, Any]]:
    """run_single_debate와 같은 결과를 만들지만, 검색/각 에이전트 완료/심사 단계마다
    이벤트를 내보낸다. 세 에이전트는 asyncio.gather로 한꺼번에 기다리지 않고
    as_completed로 먼저 끝나는 순서대로 흘려보내, 사용자가 셋 다 끝날 때까지
    기다리지 않고 진행 상황을 볼 수 있게 한다."""
    yield {"type": "status", "stage": "searching"}
    try:
        results = await search_module.search(query)
    except Exception:
        results = []

    yield {"type": "status", "stage": "proposing"}

    tasks = [
        asyncio.create_task(gpt.propose(query, results)),
        asyncio.create_task(gemini.propose(query, results)),
        asyncio.create_task(deepseek.propose(query, results)),
    ]
    agent_candidates: list[AgentCandidates] = []
    for task in asyncio.as_completed(tasks):
        ac = await task
        agent_candidates.append(ac)
        yield {"type": "proposal", "proposal": _top_proposal(ac).model_dump()}

    logger.info(
        "candidate pool sizes for %r: %s",
        query,
        {ac.agent: len(ac.candidates) for ac in agent_candidates},
    )

    proposals = [_top_proposal(ac) for ac in agent_candidates]

    if all(p.error is not None for p in proposals):
        # run_single_debate와 동일한 카테고리-질의 완화 처리 — 주석은 그쪽 참고.
        clarify = await _extract_clarify_options(query, results)
        if clarify is not None:
            yield {"type": "final", "result": clarify.model_dump()}
            return
        raise RuntimeError(NO_CANDIDATE_ERROR)

    yield {"type": "status", "stage": "judging"}
    decision = await judge.decide(query, proposals)

    result = DecideResponse(query=query, proposals=proposals, decision=decision)
    yield {"type": "final", "result": result.model_dump()}


async def run_bulk_debate(query: str) -> BulkDecideResponse:
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
