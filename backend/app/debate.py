import asyncio
import logging
import re
from typing import Any, AsyncIterator

from fetchers import danawa, danawa_search

from . import adk_pipeline
from . import price_table as price_table_module
from . import search as search_module
from .agents import deepseek, gemini, gpt, judge
from .agents.base import NO_CANDIDATE_ERROR, is_generic_listing_url
from .category import (
    QUANTITY_RELEVANT_CATEGORIES,
    VOLUME_RELEVANT_CATEGORIES,
    VOLUME_REQUIRES_BEVERAGE_CHECK,
    CategoryClassification,
    classify_category,
)
from .config import settings
from .intent import has_count_spec, has_volume_spec, is_bulk_query, needs_clarification
from .schemas import (
    AgentCandidates,
    BrandOption,
    BrandPriceResponse,
    BulkDecideResponse,
    BulkDecision,
    BulkProposal,
    ClarifyFacet,
    ClarifyOptions,
    ClarifyResponse,
    Decision,
    DecideResponse,
    PriceRange,
    Proposal,
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


def _any_llm_key_configured() -> bool:
    return bool(
        settings.openai_api_key
        or settings.gemini_api_key
        or settings.deepseek_api_key
        or settings.anthropic_api_key
    )


async def run_debate(query: str) -> DecideResponse | BulkDecideResponse | ClarifyResponse:
    if is_bulk_query(query):
        return await run_bulk_debate(query)
    if not _any_llm_key_configured():
        # 임시(로컬 실험용) - LLM 키가 하나도 없으면 /decide 자체를 다나와
        # 전용 규칙 기반 경로로 자동 전환한다. .env에 키를 하나라도 채우고
        # 재시작하면 이 분기를 안 타고 원래 LLM 파이프라인으로 바로 돌아간다.
        # needs_clarification()보다 먼저 검사해야 한다 - run_clarify()는 GPT를
        # 호출하므로, 키가 아예 없을 때 그리로 먼저 새면 실패한다(2026-08-12,
        # needs_clarification()이 짧은 검색어까지 잡도록 넓히면서 드러난 순서
        # 버그 - 이 분기가 없었을 땐 우연히 순서가 안 겹쳤을 뿐이었다).
        return await run_danawa_only_debate(query)
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
    if not _any_llm_key_configured():
        # run_debate()의 "LLM 키가 하나도 없으면 다나와 전용 경로로 자동 전환"과
        # 같은 가드를 스트리밍 경로에도 둔다 - 2026-08 통합 병합으로 프론트가
        # 이제 이 함수(/decide/stream)를 기본 검색 경로로 쓰므로, 이 가드가
        # 없으면 로컬에서 LLM 키 없이 실행할 때 run_single_debate_stream이
        # adk_pipeline을 통해 바로 실패한다 - run_danawa_only_debate_stream()으로
        # 대체해 LLM 키 없이도(다나와 실측 가격만으로) 계속 동작하게 한다.
        async for event in run_danawa_only_debate_stream(query):
            yield event
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


async def run_single_debate_price_table_variant(query: str) -> DecideResponse:
    """PRESERVED FROM seungmin/lsm, NOT currently wired into run_debate() —
    run_debate()'s LLM path calls the ADK-orchestrated run_single_debate()
    (adk_pipeline.py: refine/challenge/extract_pages/judge) instead, per the
    2026-08 통합 decision to keep that as the canonical 'AI 오케스트레이션'.
    This direct asyncio.gather implementation is kept callable and fully
    tested because its PART 4-2 behavior — injecting price_table_module's
    danawa A등급 최저가 candidates directly into the judge's candidate pool
    (build_danawa_candidates/pick_primary/enrich_decision/
    exclude_price_comparison_site_as_final_pick below) — has NOT been ported
    into adk_pipeline.py yet. TODO(follow-up PR): graft that same danawa
    candidate injection into adk_pipeline.py's propose/judge stage, then
    retire this function.
    """
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


async def _search_danawa_urls_with_fallback(
    query: str, base_query: str | None
) -> tuple[list[str], str]:
    """가격 실측용 다나와 URL 검색(사용자 요청, 2026-08-14: "이런식으로 가격
    정보를 찾지 못하는 결과는 없어야해"). AI 상세검색으로 facet을 여러 개
    이어붙인 아주 구체적인 검색어(예: "초코파이 오리온 초코파이 바나나 468g")는
    다나와 검색엔진이 토큰이 많거나 표현이 어색해 결과가 아예 안 나올 수 있다 -
    실제 상품이 없어서가 아니라 검색어 자체의 문제일 수 있다는 뜻이다. query가
    빈손이면 그 조합을 만든 원래(더 넓은) base_query로 한 번 더 시도한다.
    (effective_query, urls) 대신 (urls, effective_query) 순서로 반환 - 호출자가
    이후 _finalize_danawa_only에 "실제로 무엇으로 검색해서 찾았는지"를 넘겨야
    해서다."""
    urls = await price_table_module._search_danawa_urls(query, limit=price_table_module.DANAWA_ONLY_SEARCH_LIMIT)
    if urls:
        return urls, query
    if base_query and base_query.strip() and base_query.strip() != query.strip():
        fallback_urls = await price_table_module._search_danawa_urls(
            base_query, limit=price_table_module.DANAWA_ONLY_SEARCH_LIMIT
        )
        if fallback_urls:
            logger.info(
                "danawa-only fallback: %r found nothing, retried with base_query %r", query, base_query
            )
            return fallback_urls, base_query
    return [], query


async def run_danawa_only_debate(
    query: str, base_query: str | None = None
) -> DecideResponse | BulkDecideResponse:
    """LLM API 비용 절감을 위한 임시 로컬 실험 경로 - gpt/gemini/deepseek
    제안도, judge 최종 결정도 전부 건너뛴다. LLM 호출 0번. 다나와 실측
    가격표(다나와 직접검색만)에서 A등급(구매 링크 생성 가능) offer를
    규칙 기반으로 최종 추천으로 쓴다.

    run_debate()에서 자동으로 타지 않는다 - /decide/danawa-only 전용
    엔드포인트에서만 명시적으로 호출한다. 다나와 데이터가 아예 없거나
    A등급 offer가 없으면(=구매 링크를 만들 수 없으면) RuntimeError를 던진다 -
    "링크 없는 추천은 만들지 않는다" 원칙은 LLM 없이도 동일하게 지킨다.

    속도 최적화(사용자 요청, 두 번째 라운드) - 캐시 안 된 쿼리를 실측해보니
    Tavily 검색 자체가 15~20초로 압도적 병목이었다(다나와 직접검색은
    2~4초, 상세페이지 5건 페치는 3~4초). 이 경로는 LLM 에이전트가 없어서
    Tavily 결과가 다른 어디에도 안 쓰이므로, Tavily를 아예 호출하지
    않고 search_danawa()만으로 pcode를 찾는다 - 후보 수는 줄지만(합집합의
    Tavily 쪽 절반을 잃음) 응답은 몇 배 빨라진다. run_single_debate()(LLM
    경로)는 Tavily 결과를 LLM 에이전트와도 공유해야 해서 그대로 둔다.

    두 갈래(사용자 요청, 세 번째 라운드, 2026-08-11):
    1) 후보들이 같은 상품의 스펙 변형(색상/용량)이면 - 예: "맥북에어 m2" -
       하나를 고르되 pick_primary()(offer가 가장 많은 "풍부한" 페이지)가
       아니라 cheapest_across_tables()(A등급 절대 최저가)로 고른다.
       실측에서 관련도 1위 변형이 이미 가장 쌌는데도(1,307,990원) 풍부함
       기준 때문에 1,669,990원짜리가 나갔던 문제를 이렇게 고친다.
    2) 후보들이 브랜드/모델 자체가 다른 상품들이면(_is_single_product_family
       False) - 예: "노트북" - 하나를 억지로 고르지 않고 BulkDecideResponse
       (기존 '대량구매' 응답과 동일 스키마, 프론트도 그대로 재사용)로 후보를
       가격 오름차순으로 나열해 사용자가 직접 고르게 한다.

    후보 수는 DANAWA_ONLY_SEARCH_LIMIT(3) - 사용자 요청(네 번째 라운드,
    2026-08-11: "한번에 5개 찾아주는거 너무 느린데")로 5에서 줄였다.

    base_query(2026-08-14, "이런식으로 가격 정보를 찾지 못하는 결과는 없어야해") -
    AI 상세검색으로 facet을 여러 개 이어붙인 아주 구체적인 검색어(예: "초코파이
    오리온 초코파이 바나나 468g")는 다나와 검색엔진이 토큰이 많거나 어색해서
    결과가 아예 안 나올 수 있다 - 그러면 그 조합을 만든 원래(더 넓은) 검색어로
    한 번 더 시도한다(_search_danawa_urls_with_fallback 참고)."""
    urls, effective_query = await _search_danawa_urls_with_fallback(query, base_query)
    danawa_tables = await price_table_module.fetch_price_tables_for_urls(urls)
    return await _finalize_danawa_only(effective_query, danawa_tables, original_query=query)


async def run_danawa_only_debate_stream(
    query: str, base_query: str | None = None
) -> AsyncIterator[dict[str, Any]]:
    """run_danawa_only_debate()의 스트리밍 버전 - 사용자 요청(네 번째 라운드,
    2026-08-11: "1개 서치 완료되면 1개 올려줘 먼저"). 후보 3개를 asyncio.gather로
    한꺼번에 기다리는 대신 stream_price_tables_for_urls()로 끝나는 대로 하나씩
    {"type": "candidate", ...} 이벤트로 내보내고, 전부(또는 실패한 나머지를
    빼고) 모이면 run_danawa_only_debate()와 완전히 동일한 로직(_finalize_danawa_only)
    으로 최종 판단을 만들어 {"type": "final", "result": ...}로 내보낸다.

    /decide/danawa-only/stream 전용 - run_debate()에서 자동으로 타지 않는다.

    base_query(2026-08-14) - run_danawa_only_debate() 참고. 여기서도 query가
    아무 결과도 못 찾으면 base_query로 한 번 더 시도해 진짜 빈손으로 끝나는
    경우를 최대한 줄인다."""
    urls, effective_query = await _search_danawa_urls_with_fallback(query, base_query)
    if not urls:
        yield {"type": "error", "message": f"다나와에서 '{query}'에 대한 가격 정보를 찾지 못했다(검색/실측 모두 실패)."}
        return

    danawa_tables: list[tuple[Any, danawa.DanawaResult]] = []
    async for table, raw in price_table_module.stream_price_tables_for_urls(urls):
        danawa_tables.append((table, raw))
        offer = price_table_module.cheapest_linkable_raw_offer(raw)
        # candidate 이벤트에는 구매 URL을 안 채운다(사용자 요청, 2026-08-11:
        # "검색시간을 더 줄일수있나") - resolve_purchase_url()은 2홉 네트워크
        # 요청이고, 그마저도 prod.danawa.com 상세페이지 페치와 같은 도메인
        # 스로틀(0.5초)을 공유해 서로 대기열에 줄을 선다. 어차피 최종 확정
        # 단계(_finalize_danawa_only)에서 필요한 offer(들)만 다시 resolve하므로,
        # 여기서 3개 전부 미리 resolve하면 최종 당첨자 몫은 완전히 중복이고
        # 나머지는 아예 버려지는 순수 낭비였다 - 프론트도 로딩 중 후보 목록은
        # 텍스트로만 보여줄 뿐 클릭 링크로 안 쓴다.
        yield {
            "type": "candidate",
            "product_name": table.product_name,
            "price": f"{offer['price_krw']:,}원" if offer is not None else None,
            "retailer": offer["seller"] if offer is not None else None,
            "url": None,
        }

    try:
        result = await _finalize_danawa_only(effective_query, danawa_tables, original_query=query)
    except RuntimeError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    yield {"type": "final", "result": result.model_dump()}


async def _finalize_danawa_only(
    query: str,
    danawa_tables: list[tuple[Any, danawa.DanawaResult]],
    *,
    original_query: str | None = None,
) -> DecideResponse | BulkDecideResponse:
    """run_danawa_only_debate()/run_danawa_only_debate_stream() 공유 로직 -
    이미 페치된 danawa_tables로부터 최종 DecideResponse(단일 상품) 또는
    BulkDecideResponse(애매모호한 검색어 후보 목록)를 만든다.

    original_query(2026-08-14) - query가 _search_danawa_urls_with_fallback으로
    base_query로 대체된 경우("초코파이 오리온 초코파이 바나나 468g"를 못 찾아
    "초코파이"로 넓혀 찾은 경우), 사용자가 원래 물어본 게 뭐였는지 reasoning에
    솔직하게 남긴다 - 조용히 다른 상품을 최종 추천으로 내밀지 않는다."""
    used_fallback = bool(original_query) and original_query.strip() != query.strip()
    fallback_note = (
        f"'{original_query}'에 정확히 맞는 상품을 찾지 못해 더 넓은 검색어 '{query}'로 찾은 결과입니다. "
        if used_fallback
        else ""
    )

    if not danawa_tables:
        raise RuntimeError(f"다나와에서 '{query}'에 대한 가격 정보를 찾지 못했다(검색/실측 모두 실패).")

    if not price_table_module._is_single_product_family(danawa_tables):
        options = await price_table_module.build_ambiguous_options(danawa_tables)
        if not options:
            raise RuntimeError(f"'{query}'는 여러 상품에 걸친 검색어인데, 구매 링크를 만들 수 있는 후보가 없다.")
        return BulkDecideResponse(
            query=original_query or query,
            proposals=[],
            decision=BulkDecision(
                options=options,
                reasoning=(
                    f"{fallback_note}'{query}'는 서로 다른 상품에 걸친 검색어라 하나로 단정하지 않고, "
                    f"실측 최저가 순으로 후보 {len(options)}개를 보여드립니다."
                ),
            ),
            price_range=_compute_price_range(options),
        )

    best = price_table_module.cheapest_across_tables(danawa_tables)
    if best is None:
        raise RuntimeError(f"'{query}' 가격표는 있지만 구매 링크를 만들 수 있는(A등급) 판매처가 없다.")
    table, raw_result, offer = best

    resolved_url = await price_table_module.resolve_purchase_url(offer)
    if resolved_url is None:
        raise RuntimeError(f"'{table.product_name}' 최저가 판매처({offer['seller']}) 구매 링크 해석에 실패했다.")

    decision = Decision(
        product_name=table.product_name or query,
        price=f"{offer['price_krw']:,}원",
        retailer=offer["seller"],
        url=resolved_url,
        reasoning=f"{fallback_note}다나와 실측 최저가(A등급, 구매링크 검증됨) - LLM 미사용, 규칙 기반 선택",
        chosen_agent="danawa",
        price_source="danawa_offer",
    )
    decision = await price_table_module.exclude_price_comparison_site_as_final_pick(decision, [], danawa_tables)

    return DecideResponse(query=original_query or query, proposals=[], decision=decision, price_table=table)


# check_clarify_facets()의 base_query 재사용 필터링 전용(사용자 요청, 2026-08-13:
# "조금 더 빠르게 검색기능이 되면 좋겠어"). 필터링 결과가 이보다 적으면 표본이
# 너무 좁아 facet 품질이 나빠질 수 있으니, 필터링을 포기하고 base_query의
# 넓은 표본을 그대로 쓴다(추가 검색은 하지 않는다 - 속도가 이 최적화의 목적이라
# 여기서 또 search.danawa.com을 때리면 본전도 못 찾는다).
MIN_FILTERED_CLARIFY_ITEMS = 3


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _filter_items_by_extra_terms(
    items: list[danawa_search.DanawaSearchItem], query: str, base_query: str
) -> list[danawa_search.DanawaSearchItem]:
    """base_query로 얻은(캐시 재사용) 넓은 표본을, 사용자가 그 뒤에 덧붙인
    단어들(예: base_query="핸드폰", query="핸드폰 삼성전자"의 "삼성전자")로
    상품명을 걸러 좁힌다 - 네트워크 요청 없이 순수 로컬 필터링."""
    base_tokens = {_normalize_for_match(t) for t in base_query.split()}
    extra_tokens = [
        _normalize_for_match(t) for t in query.split() if _normalize_for_match(t) not in base_tokens
    ]
    if not extra_tokens:
        return items
    filtered = [
        item
        for item in items
        if all(term in _normalize_for_match(item["product_name"]) for term in extra_tokens)
    ]
    return filtered if len(filtered) >= MIN_FILTERED_CLARIFY_ITEMS else items


def _items_for_brand(brand: str, items: list[danawa_search.DanawaSearchItem]) -> list[str]:
    nb = _normalize_for_match(brand)
    return [item["product_name"] for item in items if nb in _normalize_for_match(item["product_name"])]


async def _enrich_facets_per_brand(
    facets: list[ClarifyFacet], items: list[danawa_search.DanawaSearchItem], query: str
) -> list[ClarifyFacet]:
    """브랜드가 여러 개 섞인 채로 한 번에 facet을 뽑으면, DeepSeek이 각 facet마다
    총 MAX_OPTIONS_PER_FACET(6)개 안에서 모든 브랜드가 경쟁한다 - 다나와 검색
    결과가 특정 브랜드로 치우친 카테고리(예: "핸드폰"의 삼성전자)면, 소수 브랜드
    (APPLE)의 시리즈가 인기순 정렬에서 밀려 상위 6개에 아예 못 들 수 있다
    (사용자 요청, 2026-08-13: "APLLE 을 선택했을때 시리즈 후보가 너무 적어 ...
    다른 질문을 했을때도 이런문제가 없으면"). 그래서 브랜드별로 그 브랜드
    상품명만 모아 별도로(각자 자기 몫의 6개 예산을 온전히 받아) 다시 facet을
    뽑고(asyncio.gather로 병렬), 같은 라벨의 facet에 새 옵션만 합쳐 넣는다.
    라벨을 다시 자유롭게 고르게 두면 같은 개념도 호출마다 "시리즈"/"모델"처럼
    다르게 이름 붙어 병합이 안 되므로, required_labels로 원래 라벨을 그대로 쓰라고
    강제한다(deepseek.extract_facets_from_names 참고). 그래도 안 맞으면(모델이
    지시를 어기면) 그 라벨은 그냥 원래 결과 그대로 둔다 - 실패해도 기존 동작보다
    나빠지지 않는다."""
    brand_facet = next((f for f in facets if deepseek._BRAND_LABEL_PATTERN.search(f.label)), None)
    if brand_facet is None or len(brand_facet.options) < 2:
        return facets

    other_labels = [f.label for f in facets if f is not brand_facet]
    if not other_labels:
        return facets

    try:
        per_brand_facets = await asyncio.gather(
            *(
                deepseek.extract_facets_from_names(
                    query, _items_for_brand(brand, items), required_labels=other_labels
                )
                for brand in brand_facet.options
            )
        )
    except Exception:
        logger.exception("check_clarify_facets: 브랜드별 facet 보강 실패, 원래 결과 그대로 사용")
        return facets

    enriched = []
    for facet in facets:
        if facet is brand_facet:
            enriched.append(facet)
            continue
        merged_options = list(facet.options)
        seen = {_normalize_for_match(o) for o in merged_options}
        for brand_facets in per_brand_facets:
            match = next((f for f in brand_facets if f.label == facet.label), None)
            if match is None:
                continue
            for option in match.options:
                key = _normalize_for_match(option)
                if key not in seen:
                    seen.add(key)
                    merged_options.append(option)
        if merged_options != facet.options:
            enriched.append(facet.model_copy(update={"options": merged_options}))
        else:
            enriched.append(facet)
    return enriched


def _attach_facet_crossfilter(
    facets: list[ClarifyFacet], items: list[danawa_search.DanawaSearchItem]
) -> list[ClarifyFacet]:
    """facet 쌍 전부(브랜드 한정이 아니다) 사이의 연관을 상품명에서 직접 계산해
    붙인다(사용자 요청, 2026-08-13: "삼성전자를 누르면 시리즈에 삼성전자에 관한것만"
    -> 2026-08-14: "시리즈에 초코파이 바나나를 골랐다면 용량에 없는것들은
    선택할수 없게" - 브랜드 특수 케이스였던 걸 모든 facet 쌍으로 일반화했다).
    검색을 다시 하지 않고, 이미 받아온 items(상품명)만으로 "이 두 옵션이 같은
    상품명에 같이 등장하는가"를 모든 (선택 가능한 facet, 대상 facet) 쌍에 대해
    계산한다 - 그래서 프론트가 어느 facet에서든 값을 고르는 순간(그 자체로는
    아직 검색을 트리거하지 않는다) 아직 안 고른 다른 facet들의 보이는 옵션만
    즉시 좁혀 보여줄 수 있다(여러 개를 고르면 교집합은 프론트가 계산한다)."""
    if len(facets) < 2:
        return facets

    normalized_names = [_normalize_for_match(item["product_name"]) for item in items]

    def _relevant(selector_value: str, target_options: list[str]) -> list[str]:
        nv = _normalize_for_match(selector_value)
        return [
            option
            for option in target_options
            if any(nv in name and _normalize_for_match(option) in name for name in normalized_names)
        ]

    updated = []
    for target in facets:
        by_selection: dict[str, list[str]] = {}
        for selector in facets:
            if selector is target:
                continue
            for value in selector.options:
                relevant = _relevant(value, target.options)
                # 이 선택이 target의 옵션을 실제로 좁혀줄 때만(전체가 그대로
                # 나오거나 아예 안 나오면 매핑을 안 붙인다) 쓸모없는 데이터를
                # 응답에 얹지 않는다.
                if relevant and len(relevant) < len(target.options):
                    by_selection[value] = relevant
        updated.append(target.model_copy(update={"options_by_selection": by_selection}) if by_selection else target)
    return updated


# 상세검색 facet을 넓은(거시적) 기준부터 좁은(미시적) 기준 순서로 보여주기 위한
# 우선순위 힌트(사용자 요청, 2026-08-14: "거시적인 선택에서 미시적인 선택으로
# 점차 줄여나가게"). 라벨에 이 키워드가 포함되면 그 순번을 쓴다 - 못 찾은
# 라벨은 맨 뒤로(기존 순서 유지, 정렬은 stable). 실제 좁히기 자체는
# _attach_facet_crossfilter가 순서와 무관하게 다 계산해두므로, 이건 어떤 순서로
# "물어보면" 자연스러운지에 대한 화면 표시 순서일 뿐이다.
_FACET_ORDER_HINTS = [
    "카테고리", "브랜드", "제조사", "시리즈", "모델", "타입", "종류",
    "용량", "무게", "사이즈", "용기형태", "구매유형", "특징", "색상",
]


def _facet_display_order(facet: ClarifyFacet) -> int:
    for i, hint in enumerate(_FACET_ORDER_HINTS):
        if hint in facet.label:
            return i
    return len(_FACET_ORDER_HINTS)


async def check_clarify_facets(query: str, base_query: str | None = None) -> ClarifyResponse:
    """AI 상세검색(2026-08-12 요청) - "음료수"처럼 짧고 애매한 검색어를 다나와
    실제 검색 결과 상품명에 근거해 몇 가지 기준(facet)으로 좁혀나가도록 DeepSeek에게
    물어본다(원래 Qwen으로 붙였다가, Model Studio 계정의 과금 플랜 활성화 문제로
    이미 키가 있고 바로 되는 DeepSeek로 옮겼다). run_danawa_only_debate()/
    run_danawa_only_debate_stream()과는 완전히 분리된 별도 진입점이다 - 그 둘은
    "LLM 호출 0번"이 테스트로 고정된 불변식이라(test_run_danawa_only_debate_never_calls_any_llm)
    여기서 DeepSeek를 부르는 로직을 거기 안에 섞으면 안 된다. 프론트가 이 함수를
    먼저(짧은 쿼리에 한해) 호출해보고, facets가 비어 있으면(=명확한 검색어이거나
    DeepSeek 호출 실패) 그대로 danawa-only 빠른 경로로 진행한다.

    needs_clarification()이 False면 검색조차 하지 않고 즉시 빈 결과를 반환한다 -
    대부분의(구체적인) 검색어는 이 함수를 호출해도 search.danawa.com 요청도,
    DeepSeek 호출도 전혀 없이 즉시 끝난다.

    base_query(2026-08-13, 속도 개선) - 여러 라운드에 걸쳐 좁혀나갈 때(예: "핸드폰"
    -> "핸드폰 삼성전자" -> ...) 프론트가 그 드릴다운의 맨 처음 검색어를 실어 보낸다.
    query 대신 base_query로 검색하면 search.danawa.com의 1시간 캐시(fetchers.
    danawa_search._cache)가 맞을 확률이 높아 10초 Crawl-delay를 건너뛰고, 그 결과를
    query에서 base_query에 없는 단어들로 로컬 필터링해 재사용한다 - 실제 최종
    가격 조회(run_danawa_only_debate*)는 이 캐시/필터링을 안 쓰고 항상 정확한
    검색을 새로 한다."""
    if not needs_clarification(query):
        return ClarifyResponse(query=query, options=ClarifyOptions())

    search_query = base_query if base_query and base_query.strip() else query
    items = await price_table_module._search_danawa_items(
        search_query, limit=price_table_module.CLARIFY_SEARCH_LIMIT
    )
    if base_query and base_query.strip() and base_query.strip() != query.strip():
        items = _filter_items_by_extra_terms(items, query, base_query)
    names = [item["product_name"] for item in items]
    facets = await deepseek.extract_facets_from_names(query, names)
    facets = await _enrich_facets_per_brand(facets, items, query)
    facets = _attach_facet_crossfilter(facets, items)
    facets = sorted(facets, key=_facet_display_order)
    return ClarifyResponse(query=query, options=ClarifyOptions(facets=facets))


def _filter_listing_pages(results: list[SearchResult]) -> list[SearchResult]:
    """검색결과 목록/사이트내검색 페이지(예: search.11st.co.kr/...?kwd=)를 clarify
    추출 대상에서 뺀다. 이런 페이지는 사이드바에 "함께 본 상품"류의 전혀 무관한
    상품이 잔뜩 섞여 있어서, GPT가 그 안 상품명을 죄다 브랜드/제품 옵션으로
    뽑아버리는 문제가 있었다(propose 단계는 filter_candidates에서 이미
    is_generic_listing_url로 걸러왔는데, clarify 추출은 이 필터를 거치지 않고
    있었다). 전부 걸러져도 빈 리스트를 그대로 반환 — 호출부가 "옵션 없음"으로
    안전하게 처리한다."""
    return [r for r in results if not is_generic_listing_url(r.url)]


async def _extract_clarify_options(query: str, results: list[SearchResult]) -> ClarifyResponse | None:
    """검색 결과에서 브랜드/제품/용량/수량을 뽑아본다. 아무것도 못 찾으면 None.
    이미 가져온 검색 결과를 그대로 받아 재검색하지 않는다 — run_single_debate가
    전체 실패했을 때 같은 결과로 이 함수를 다시 시도하는 용도로도 쓰인다.
    카테고리 분류(Gemini)는 옵션 추출(GPT)과 동시에 실행해 지연 시간을 늘리지
    않는다."""
    filtered_results = _filter_listing_pages(results)
    raw, classification = await asyncio.gather(
        gpt.extract_options(query, filtered_results),
        classify_category(query, filtered_results),
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
