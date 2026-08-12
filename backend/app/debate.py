import asyncio
import logging
import re
from typing import Any, AsyncIterator

from . import adk_pipeline
from . import search as search_module
from .agents import deepseek, gemini, gpt, judge
from .category import (
    QUANTITY_RELEVANT_CATEGORIES,
    VOLUME_RELEVANT_CATEGORIES,
    VOLUME_REQUIRES_BEVERAGE_CHECK,
    CategoryClassification,
    classify_category,
)
from .intent import has_count_spec, has_volume_spec, is_bulk_query, needs_clarification
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


def _strip_resolved_options(query: str, options: ClarifyOptions) -> ClarifyOptions:
    """이미 질의 텍스트에 반영된 차원(브랜드/제품/용량/개수)은 옵션 목록에서
    제거한다. 이걸 안 하면, 사용자가 브랜드를 골라 재검색해도 이번 라운드
    검색 결과에서 브랜드가 다시 여러 개로 뽑힐 수 있어(옵션 추출은 매번 검색
    결과를 새로 보고 하는 raw 추출이라 사용자가 이미 고른 값을 모름) 프론트가
    "옵션이 2개 이상"이라는 이유만으로 이미 답한 선택 단계를 또 보여주게 된다.
    다만 이건 텍스트 매칭 기반의 보조 방어선이고, 실제로 같은 단계가 다시
    뜨지 않는다는 보장은 프론트의 resolvedSteps 추적(Hero.tsx)이 한다 — 여긴
    라운드마다 프론트에 내려주는 옵션 자체를 최대한 깔끔하게 정리해두는 역할."""
    brand_resolved = any(b.casefold() in query.casefold() for b in options.brands)
    product_resolved = any(p.casefold() in query.casefold() for p in options.products)
    return ClarifyOptions(
        brands=[] if brand_resolved else options.brands,
        products=[] if product_resolved else options.products,
        volumes=[] if has_volume_spec(query) else options.volumes,
        quantities=[] if has_count_spec(query) else options.quantities,
    )


_MAX_CLARIFY_ROUNDS = 2
# 브랜드/제품/용량/개수 4축 중 2개가 이미 질의 텍스트에 반영됐으면(=사용자가
# Human-in-the-loop을 2라운드 이상 거쳤으면) 더 묻지 않고 바로 propose/challenge/
# judge 파이프라인으로 넘긴다. 라운드마다 검색 결과가 바뀌면서 이전엔 안 갈리던
# 축(예: 브랜드+개수까지 정했는데 이번 라운드엔 제품 라인이 새로 갈림)이 뒤늦게
# 애매해지는 경우가 있는데, 이걸 그대로 다 물어보면 사용자는 몇 라운드나 답했는데도
# 계속 새 선택 화면이 뜨는 것처럼 느껴진다 — 남은 후보를 좁히는 건 그 시점부턴
# judge가 근거(그라운딩/검증)로 판단하게 맡긴다.


def _resolved_dimension_count(query: str, raw_options: ClarifyOptions) -> int:
    """이번 라운드에 새로 뽑힌 옵션 중 이미 질의 텍스트에 반영된(=사용자가 이미
    답한) 축이 몇 개인지 센다. _strip_resolved_options와 같은 텍스트 매칭 판정을
    쓰되, 스트리핑 전에 호출해야 한다(스트리핑 후엔 이미 다 비워져 있어 셀 수 없음)."""
    brand_resolved = any(b.casefold() in query.casefold() for b in raw_options.brands)
    product_resolved = any(p.casefold() in query.casefold() for p in raw_options.products)
    volume_resolved = has_volume_spec(query)
    quantity_resolved = has_count_spec(query)
    return sum([brand_resolved, product_resolved, volume_resolved, quantity_resolved])


def _strip_category_irrelevant_options(
    classification: CategoryClassification, options: ClarifyOptions
) -> ClarifyOptions:
    """분류된 카테고리에서 용량/수량 축이 무의미하면 그 옵션은 clarify에서 아예
    빼서, 사용자가 해당 없는 선택지 중 하나를 억지로 골라 상품 매핑이 틀어지는
    걸 막는다. 용량과 수량은 서로 다른 카테고리 집합에 걸리는 독립된 축이라
    각각 따로 판단한다(예: 도서는 수량('권')은 의미 있어도 용량은 없음). 분류
    자체가 실패했으면(category=None) 안전하게 기존 동작대로 축을 그대로 둔다.

    '식품'은 그 안에서도 편차가 커서 대분류만으로는 부족하다 — 음료(생수/커피·차
    등)만 용량이 핵심 스펙이고, 정육·과자·조미료 같은 나머지 식품은 용량 축
    자체가 무의미하다. 그래서 식품이면서 음료가 아닌 경우에는 용량만 추가로
    빼고 수량은 그대로 둔다(수량은 음료가 아닌 식품에도 여전히 의미 있는 축)."""
    category = classification.category
    if category is None:
        return options

    volume_relevant = category in VOLUME_RELEVANT_CATEGORIES
    if category in VOLUME_REQUIRES_BEVERAGE_CHECK and not classification.is_beverage:
        volume_relevant = False
    quantity_relevant = category in QUANTITY_RELEVANT_CATEGORIES

    return ClarifyOptions(
        brands=options.brands,
        products=options.products,
        volumes=options.volumes if volume_relevant else [],
        quantities=options.quantities if quantity_relevant else [],
    )


async def _extract_clarify_options(query: str, results: list[SearchResult]) -> ClarifyResponse | None:
    """검색 결과에서 브랜드/제품/용량/수량을 뽑아본다. 아무것도 못 찾으면 None.
    이미 가져온 검색 결과를 그대로 받아 재검색하지 않는다 — run_single_debate가
    전체 실패했을 때 같은 결과로 이 함수를 다시 시도하는 용도로도 쓰인다.
    카테고리 분류(Gemini)는 옵션 추출(GPT)과 동시에 실행해 지연 시간을 늘리지
    않는다."""
    raw, classification = await asyncio.gather(
        gpt.extract_options(query, results),
        classify_category(query, results),
    )
    options = ClarifyOptions(
        brands=_dedupe_case_insensitive(raw.brands),
        products=_dedupe_case_insensitive(raw.products),
        volumes=_dedupe_case_insensitive(raw.volumes),
        quantities=_dedupe_case_insensitive(raw.quantities),
    )
    if _resolved_dimension_count(query, options) >= _MAX_CLARIFY_ROUNDS:
        return None
    options = _strip_resolved_options(query, options)
    options = _strip_category_irrelevant_options(classification, options)
    if not (options.brands or options.products or options.volumes or options.quantities):
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
