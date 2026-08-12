import asyncio
import logging
import re
from typing import Any, AsyncIterator

from fetchers import danawa, danawa_search

from . import price_table as price_table_module
from . import search as search_module
from .agents import deepseek, gemini, gpt, judge
from .agents.base import NO_CANDIDATE_ERROR
from .config import settings
from .intent import is_bulk_query, needs_clarification
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


async def run_danawa_only_debate(query: str) -> DecideResponse | BulkDecideResponse:
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
    2026-08-11: "한번에 5개 찾아주는거 너무 느린데")로 5에서 줄였다."""
    urls = await price_table_module._search_danawa_urls(query, limit=price_table_module.DANAWA_ONLY_SEARCH_LIMIT)
    danawa_tables = await price_table_module.fetch_price_tables_for_urls(urls)
    return await _finalize_danawa_only(query, danawa_tables)


async def run_danawa_only_debate_stream(query: str) -> AsyncIterator[dict[str, Any]]:
    """run_danawa_only_debate()의 스트리밍 버전 - 사용자 요청(네 번째 라운드,
    2026-08-11: "1개 서치 완료되면 1개 올려줘 먼저"). 후보 3개를 asyncio.gather로
    한꺼번에 기다리는 대신 stream_price_tables_for_urls()로 끝나는 대로 하나씩
    {"type": "candidate", ...} 이벤트로 내보내고, 전부(또는 실패한 나머지를
    빼고) 모이면 run_danawa_only_debate()와 완전히 동일한 로직(_finalize_danawa_only)
    으로 최종 판단을 만들어 {"type": "final", "result": ...}로 내보낸다.

    /decide/danawa-only/stream 전용 - run_debate()에서 자동으로 타지 않는다."""
    urls = await price_table_module._search_danawa_urls(query, limit=price_table_module.DANAWA_ONLY_SEARCH_LIMIT)
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
        result = await _finalize_danawa_only(query, danawa_tables)
    except RuntimeError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    yield {"type": "final", "result": result.model_dump()}


async def _finalize_danawa_only(
    query: str, danawa_tables: list[tuple[Any, danawa.DanawaResult]]
) -> DecideResponse | BulkDecideResponse:
    """run_danawa_only_debate()/run_danawa_only_debate_stream() 공유 로직 -
    이미 페치된 danawa_tables로부터 최종 DecideResponse(단일 상품) 또는
    BulkDecideResponse(애매모호한 검색어 후보 목록)를 만든다."""
    if not danawa_tables:
        raise RuntimeError(f"다나와에서 '{query}'에 대한 가격 정보를 찾지 못했다(검색/실측 모두 실패).")

    if not price_table_module._is_single_product_family(danawa_tables):
        options = await price_table_module.build_ambiguous_options(danawa_tables)
        if not options:
            raise RuntimeError(f"'{query}'는 여러 상품에 걸친 검색어인데, 구매 링크를 만들 수 있는 후보가 없다.")
        return BulkDecideResponse(
            query=query,
            proposals=[],
            decision=BulkDecision(
                options=options,
                reasoning=(
                    f"'{query}'는 서로 다른 상품에 걸친 검색어라 하나로 단정하지 않고, "
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
        reasoning="다나와 실측 최저가(A등급, 구매링크 검증됨) - LLM 미사용, 규칙 기반 선택",
        chosen_agent="danawa",
        price_source="danawa_offer",
    )
    decision = await price_table_module.exclude_price_comparison_site_as_final_pick(decision, [], danawa_tables)

    return DecideResponse(query=query, proposals=[], decision=decision, price_table=table)


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


def _attach_brand_crossfilter(
    facets: list[ClarifyFacet], items: list[danawa_search.DanawaSearchItem]
) -> list[ClarifyFacet]:
    """브랜드 facet과 다른 facet(시리즈/모델 등) 사이의 연관을 상품명에서 직접
    계산해 붙인다(사용자 요청, 2026-08-13: "삼성전자를 누르면 시리즈에 삼성전자에
    관한것만, APPLE을 누르면 아이폰만"). 검색을 다시 하지 않고, 이미 받아온
    items(상품명)만으로 "이 옵션과 이 브랜드가 같은 상품명에 같이 등장하는가"를
    보고 옵션별로 브랜드를 매핑한다 - 그래서 프론트가 브랜드를 고르는 순간
    (그 자체로는 아직 검색을 트리거하지 않는다) 다른 facet의 보이는 옵션만
    즉시 좁혀 보여줄 수 있다."""
    brand_facet = next((f for f in facets if deepseek._BRAND_LABEL_PATTERN.search(f.label)), None)
    if brand_facet is None or len(brand_facet.options) < 2:
        return facets

    normalized_names = [_normalize_for_match(item["product_name"]) for item in items]

    updated = []
    for facet in facets:
        if facet is brand_facet:
            updated.append(facet)
            continue
        by_brand: dict[str, list[str]] = {}
        for brand in brand_facet.options:
            nb = _normalize_for_match(brand)
            relevant = [
                option
                for option in facet.options
                if any(nb in name and _normalize_for_match(option) in name for name in normalized_names)
            ]
            if relevant:
                by_brand[brand] = relevant
        # 모든 브랜드에서 다 그 facet의 옵션 전체가 그대로 나오면 실제로 좁혀주는
        # 게 없으니 매핑을 안 붙인다(쓸모없는 데이터를 응답에 얹지 않는다).
        if by_brand and any(len(v) < len(facet.options) for v in by_brand.values()):
            updated.append(facet.model_copy(update={"options_by_brand": by_brand}))
        else:
            updated.append(facet)
    return updated


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
    facets = _attach_brand_crossfilter(facets, items)
    return ClarifyResponse(query=query, options=ClarifyOptions(facets=facets))


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
