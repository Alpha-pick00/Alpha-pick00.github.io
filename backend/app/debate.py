import asyncio
import logging
import re

from . import price_table as price_table_module
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


async def run_single_debate(query: str) -> DecideResponse:
    try:
        results = await search_module.search(query)
    except Exception:
        results = []

    # 다나와 페치는 LLM 3개와 asyncio.gather로 동시 실행한다 - 순차로 붙이면
    # 그만큼 응답이 느려진다. price_table_module.fetch_price_tables는 무슨
    # 일이 있어도 예외를 던지지 않고 실패 시 빈 리스트를 반환하므로, 이
    # gather 자체가 실패해서 본 파이프라인이 막히는 일은 없다.
    gpt_result, gemini_result, deepseek_result, danawa_tables = await asyncio.gather(
        gpt.propose(query, results),
        gemini.propose(query, results),
        deepseek.propose(query, results),
        price_table_module.fetch_price_tables(query, results),
    )
    agent_candidates: list[AgentCandidates] = [gpt_result, gemini_result, deepseek_result]
    logger.info(
        "candidate pool sizes for %r: %s",
        query,
        {ac.agent: len(ac.candidates) for ac in agent_candidates},
    )
    proposals = [_top_proposal(ac) for ac in agent_candidates]

    # PART 4-2: 다나와 A등급 최저가 후보를 judge의 선택지 풀에 직접 추가한다
    # (판매처+가격 매칭에 의존하지 않는 경로 - LLM이 고른 상품과 다나와 페이지가
    # 애초에 다른 상품이라 매칭이 실패하는 절반가량의 쿼리에서도 다나와 데이터가
    # 후보로는 정상적으로 노출된다). DecideResponse.proposals(응답에 노출되는
    # 필드)에는 넣지 않는다 - 프론트엔드가 "에이전트 3개" 레이아웃을 가정할 수
    # 있어, judge에게 넘기는 후보 풀만 넓히고 노출 스키마는 그대로 둔다.
    danawa_proposals = await price_table_module.build_danawa_candidates(danawa_tables, agent_candidates)

    decision = await judge.decide(query, proposals + danawa_proposals)
    if decision.chosen_agent == "danawa":
        decision.price_source = "danawa_offer"

    primary = price_table_module.pick_primary(danawa_tables)
    price_table = None
    if primary is not None:
        table, raw_result = primary
        price_table = table
        decision = await price_table_module.enrich_decision(decision, raw_result)

    decision = await price_table_module.exclude_price_comparison_site_as_final_pick(
        decision, proposals, danawa_tables
    )

    return DecideResponse(query=query, proposals=proposals, decision=decision, price_table=price_table)


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
