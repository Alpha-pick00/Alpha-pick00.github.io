"""ADK(Google Agent Development Kit) 기반 역할 분리형 검색 파이프라인.

정제(Groq) → 검색 → 제안(Qwen·Groq·DeepSeek 병렬, 각자 최선 1개) →
필터링+병합(fusion.dedup 재사용) → 검증(DeepSeek) → 매칭/합성 → 심사(Groq)
순서로 실행된다 — `debate.py`의 run_single_debate/run_single_debate_stream이
이 모듈의 run()/run_stream()을 호출한다. (제안 슬롯 이름은 "gpt"/"groq" -
"gpt" 슬롯은 실제로는 Qwen이 돌지만 리네임 비용이 커서 식별자를 그대로 뒀고,
"groq" 슬롯은 2026-08-18에 실제 쓰는 모델명으로 리네임했다 - 원래 이름은
"gemini"였다.)

SequentialAgent/ParallelAgent는 google-adk 2.6.3 기준 deprecated(대체 예정인
Workflow가 아직 LlmAgent의 sub-agent로 못 쓰여 미완성 상태)이지만, 실제로는
정상 동작함을 스파이크로 검증했다 — Workflow가 성숙하면 마이그레이션 대상.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, AsyncIterator
from urllib.parse import urlsplit

from fetchers import danawa as danawa_fetcher
from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models import LlmResponse
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import TypeAdapter

from . import price_table as price_table_module
from . import search as search_module
from .agents import deepseek as deepseek_module
from .agents import gpt as gpt_module
from .agents import judge as judge_module
from .category import CategoryClassification, classify_category
from .intent import needs_clarification
from .agents.base import (
    NO_CANDIDATE_ERROR,
    build_challenge_prompt,
    build_prompt,
    build_refine_query_prompt,
    filter_candidates,
    format_results_block,
    is_danawa_comparison_page,
    parse_json_array,
)
from .config import settings
from .schemas import (
    AgentCandidate,
    ChallengeResult,
    ChallengeVerdict,
    ClarifyResponse,
    DecideResponse,
    Decision,
    PriceTable,
    Proposal,
    RefinedQuery,
    SearchResult,
)
from fusion.dedup import merge_candidates

logger = logging.getLogger(__name__)

_APP_NAME = "alpha_pick_debate"

# 매 요청 검색 히트 수 — search.py::search()의 max_results 기본값(12)과 동일하게.
_MAX_SEARCH_RESULTS = 12
# 에이전트당 최종 후보 1개(가장 좋은 것 하나)만 제안하게 한다(사용자 요청,
# 2026-08-15: "최종 후보도 각각 5개가 아닌 1개만 추천해주는걸로 하자 가장
# 좋은 거 1개") - 이전엔 에이전트당 최대 5개까지 브레인스토밍해 병합 풀을
# 넓혔지만(최대 15개), 그만큼 judge 심사 대상도 늘어나고 응답에도 서로 다른
# 후보가 여러 줄 노출될 수 있었다. 1로 줄이면 각 에이전트가 처음부터 자기
# 최선의 답 하나만 내고, 병합은 여전히 3개 에이전트가 같은 상품을 골랐는지
# 판단하는 데만 쓰인다.
_MAX_CANDIDATES_PER_AGENT = 1


def _format_price_krw(price_krw: int | None) -> str:
    return f"{price_krw:,}원" if price_krw is not None else ""


def _search_results_from_state(state: dict) -> list[SearchResult]:
    return [SearchResult(**r) for r in state.get("search_results") or []]


def _augment_search_query(query: str, classification: CategoryClassification) -> str:
    """Tavily에 보낼 검색어에 분류된 카테고리를 살짝 얹어, 검색엔진 자체의
    랭킹을 그 카테고리 쪽으로 미세 조정한다. 도메인/결과를 강제로 거르는 게
    아니라 키워드를 하나 더 얹는 완만한 가중치라 — 분류가 틀려도 원래 질의
    키워드는 그대로 남아 있어 결과가 아예 사라지지는 않는다. 반대로 이 보정된
    문자열은 Tavily 호출에만 쓰고, 프롬프트에 넘기는 refined_query 자체는
    건드리지 않는다(propose/judge가 보는 질의는 항상 깨끗한 원문). 분류가
    실패했으면(category=None) 원래 질의를 그대로 둔다."""
    if classification.category is None:
        return query
    return f"{query} {classification.category}"


def _refined_query_text(state: dict) -> str:
    refined = state.get("refined_query")
    if isinstance(refined, dict) and refined.get("query"):
        return refined["query"]
    return state.get("original_query", "")


# ---------------------------------------------------------------------------
# 커스텀(순수 Python) 노드 — ADK LlmAgent가 아니라 직접 상태를 읽고 쓴다.
# (_SearchNode는 예외적으로 내부에서 카테고리 분류를 한 번 호출한다 — 그 노드
# docstring 참고.)
# ---------------------------------------------------------------------------


class _SearchNode(BaseAgent):
    """정제된 질의로 search_module.search()를 호출해 원본 결과 + 프롬프트용
    포맷 텍스트를 상태에 저장한다. 이 섹션의 다른 노드와 달리 Tavily 호출 전에
    카테고리 분류(Groq) 호출이 하나 더 낀다 — 분류 결과를 검색어에 얹어
    검색엔진 랭킹을 카테고리 쪽으로 미세 조정하기 위함(_augment_search_query
    참고). 이 호출은 이 노드 안에서만 쓰고 상태에 저장하지 않는다 — clarify
    단계의 카테고리 분류(debate.py::_extract_clarify_options)는 실제 검색
    결과를 근거로 다시 판별하는 별도 호출이라 더 정확하고, 그 결과와 여기서
    쓰는 값을 굳이 공유할 필요가 없다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        query = _refined_query_text(ctx.session.state)
        classification = await classify_category(query, [])
        search_query = _augment_search_query(query, classification)
        try:
            results = await search_module.search(search_query, max_results=_MAX_SEARCH_RESULTS)
        except Exception:
            logger.exception("검색 실패: %r", search_query)
            results = []

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "search_results": [r.model_dump() for r in results],
                    "search_results_block": format_results_block(results),
                }
            ),
        )


class _DanawaFetchNode(BaseAgent):
    """다나와 실측 가격표를 propose 3개 모델과 나란히(동시에) 조회한다 —
    PRESERVED FROM seungmin/lsm의 run_single_debate_price_table_variant(PART 4-2)를
    ADK 파이프라인으로 포팅(2026-08-16, README "한계점 및 향후 과제" 후속작업).
    같은 ParallelAgent(propose_parallel) 소속이라 gpt/groq/deepseek LlmAgent와
    동시에 실행되므로 지연시간이 추가되지 않는다.

    price_table_module.fetch_price_tables()는 원래도 예외를 던지지 않지만,
    이 노드도 다른 커스텀 노드(_SearchNode 등)와 같은 방어 패턴을 따라 한 번 더
    감싼다 — 다나와 조회가 실패해도 gpt/groq/deepseek 후보만으로 파이프라인이
    계속 진행된다.

    A등급(구매 링크 생성 가능) 최저가 offer가 있는 대표 가격표(pick_primary -
    offer가 가장 많은 페이지) 하나만 골라 다른 슬롯과 같은 모양(raw JSON
    문자열, output_key 컨벤션)으로 danawa_raw에 저장한다 - _FilterMergeNode가
    다른 3개 슬롯과 동일하게 처리해 병합 풀에 합류시킨다. 여러 다나와 페이지가
    있어도 대표 1개만 후보로 올리는 이유: 다른 3개 에이전트도 이미 "각자 최선
    1개"만 제안하도록 되어 있어(_MAX_CANDIDATES_PER_AGENT) 여러 개를 넣어도
    filter_candidates가 어차피 1개로 자른다.

    danawa_tables(전체 가격표, 모든 offer 포함)는 별도로 저장해 run_stream()의
    후처리(enrich_decision/exclude_price_comparison_site_as_final_pick/
    price_table 채우기)에서 그대로 재사용한다 - 이 노드에서 만든 대표 후보
    하나로는 그 후처리들이 필요로 하는 전체 가격표 정보(모든 offer, 다른 pcode
    페이지들)를 담을 수 없다.

    (2026-08-16 하드닝, 그라운딩 회귀 파일럿에서 발견) pick_primary()는
    offer가 가장 많은 페이지를 고를 뿐 query와의 관련성은 전혀 안 본다 -
    "아이폰 16 프로 256GB" 검색에서 실제로 무관한 액세서리(아이패드 케이스,
    판매처가 많아 offer 수만 높음)가 골라져 verified=True로 강제된 채(아래
    _apply_challenge 참고 - danawa 출신 후보는 challenge 검증 자체를 건너뜀)
    최종 추천으로 노출된 사례를 확인했다. enrich_decision이 이미 쓰는
    _product_name_matches(fuzzy 유사도 + 모델/수량 충돌 가드)를 query 자체에도
    적용해, 이름이 안 맞으면 애초에 후보를 만들지 않는다 - danawa_tables(전체
    가격표)는 그대로 보존해 다른 후처리는 영향받지 않는다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        query = _refined_query_text(ctx.session.state)
        results = _search_results_from_state(ctx.session.state)

        tables_dump: list[list] = []
        danawa_raw = "[]"
        try:
            tables = await price_table_module.fetch_price_tables(query, results)
            tables_dump = [[table.model_dump(), raw] for table, raw in tables]
            primary = price_table_module.pick_primary(tables)
            if primary is not None:
                primary_table, raw_result = primary
                if price_table_module._product_name_matches(query, primary_table.product_name or ""):
                    offer = price_table_module.cheapest_linkable_raw_offer(raw_result)
                    if offer is not None:
                        resolved_url = await price_table_module.resolve_purchase_url(offer)
                        if resolved_url is not None:
                            candidate = AgentCandidate(
                                product_name=primary_table.product_name or query,
                                price_krw=offer["price_krw"],
                                retailer=offer["seller"],
                                url=resolved_url,
                            )
                            danawa_raw = json.dumps([candidate.model_dump()])
        except Exception:
            logger.exception("다나와 실측가 조회 실패: %r", query)

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"danawa_tables": tables_dump, "danawa_raw": danawa_raw}
            ),
        )


class _CoupangCheckNode(BaseAgent):
    """challenge 단계에 쿠팡 검색 결과를 독립 교차 확인 신호로 추가한다
    (사용자 요청, 2026-08-16: "그라운딩 성능을 높여줘"). propose_parallel
    소속이라 gpt/groq/deepseek/danawa와 동시 실행되어 지연시간이 추가되지
    않는다. 다나와처럼 가격을 추출해 후보로 올리지는 않는다 - 쿠팡 페이지를
    직접 파싱하지 않고(과거 15개 리테일러를 다나와 하나로 좁힌 이유였던
    "스니펫만으로 파싱하면 엉뚱한 상품/가격이 섞이는 문제"를 재현하지 않기
    위해) Tavily 스니펫만 challenge LLM에게 참고 신호로 넘긴다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        query = _refined_query_text(ctx.session.state)
        results = await search_module.search_coupang(query)
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"coupang_results": [r.model_dump() for r in results]}),
        )


class _NaverCheckNode(BaseAgent):
    """쿠팡(_CoupangCheckNode)과 동일한 패턴의 두 번째 소프트 그라운딩 신호
    (2026-08-16, "다나와 단일 실측 소스에 대한 의존도를 낮추도록") - 다나와
    실측가만 확정 소스이고 쿠팡 하나만으로는 교차 확인 대상이 한 곳뿐이라,
    서로 다른 두 번째 쇼핑몰을 propose_parallel에 같이 태워 challenge가 볼
    참고 자료를 넓힌다. 후보를 만들지 않는 점, 실패해도 조용히 빈 리스트인
    점 모두 쿠팡 노드와 동일."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        query = _refined_query_text(ctx.session.state)
        results = await search_module.search_naver(query)
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"naver_results": [r.model_dump() for r in results]}),
        )


class _FilterMergeNode(BaseAgent):
    """3개 제안 노드 + 다나와 후보의 원시 JSON을 각각 파싱+필터링한 뒤,
    fusion.dedup으로 동일 상품을 병합한다 — 지금까지 어디서도 안 쓰이던
    merge_candidates()가 여기서 처음 실사용된다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        raw_by_agent = {
            "gpt": state.get("gpt_raw"),
            "groq": state.get("groq_raw"),
            "deepseek": state.get("deepseek_raw"),
            "danawa": state.get("danawa_raw"),
        }
        danawa_tables = _danawa_tables_from_state(state)
        merged = await _merge_proposals(raw_by_agent, danawa_tables)
        logger.info(
            "후보 풀: 병합 %d건 (%r)", len(merged), [m["proposed_by"] for m in merged]
        )

        yield Event(author=self.name, actions=EventActions(state_delta={"candidates": merged}))


async def _resolve_comparison_page_item(
    item: dict, danawa_tables: list[tuple[PriceTable, dict]]
) -> dict:
    """item['url']이 다나와 가격비교 페이지(prod.danawa.com/info?pcode=...)면
    같은 propose 라운드에서 _DanawaFetchNode가 이미 페치해 둔 가격표와 pcode로
    대조해 A등급 최저가 구매링크로 바꿔치기한다 - 해석에 성공하면 URL이
    /bridge/ 형태로 바뀌어 뒤이은 filter_candidates()의
    is_danawa_comparison_page 검사를 정상 통과한다. 해석 실패(pcode 불일치,
    A등급 오퍼 없음 등)하면 원본을 그대로 반환해 기존처럼 필터링되게 둔다 -
    안 검증된 값을 지어내지 않는다는 원칙은 그대로 유지."""
    url = item.get("url") or ""
    if not is_danawa_comparison_page(url):
        return item
    resolved = await price_table_module.resolve_danawa_comparison_url(url, danawa_tables)
    if resolved is None:
        return item
    resolved_url, price_krw, retailer = resolved
    return {**item, "url": resolved_url, "price_krw": price_krw, "retailer": retailer}


async def _merge_proposals(
    raw_by_agent: dict[str, str | None],
    danawa_tables: list[tuple[PriceTable, dict]],
) -> list[dict]:
    """3개 제안자의 원시 JSON 텍스트를 각각 파싱한 뒤, 다나와 가격비교 페이지
    URL은 A등급 구매링크로 먼저 해석하고(_resolve_comparison_page_item),
    필터링해 fusion.dedup으로 동일 상품을 병합한다 — 한 제안자의 파싱이
    실패해도 나머지로 진행한다.

    (2026-08-18) 원래는 LLM 호출 없이 테스트 가능한 순수 동기 함수였는데,
    Qwen/Groq/DeepSeek이 다나와 검색 결과에서 고를 수 있는 URL이 사실상 전부
    가격비교 페이지 형태뿐이라(다나와 도메인 단독 검색의 특성상) 해석 없이
    그대로 필터링하면 세 제안자가 후보를 거의 못 만들어 후보 풀이 자주
    0건으로 비고, 그 결과 되묻기(clarify)나 "적절한 상품 후보를 찾지 못했다"
    실패가 대량 발생하는 걸 그라운딩 회귀 파일럿에서 확인했다(50개 중 정직한
    실패인 케이스는 12%뿐, 나머지는 이 문제였다). 해석 자체(resolve_purchase_url)는
    실제로는 네트워크 호출이 없는 순수 문자열 가공이라(price_table.py 참고)
    async로 바꿔도 테스트 비용이 늘지 않는다."""
    entries: list[tuple[str, AgentCandidate]] = []
    for agent_name, raw in raw_by_agent.items():
        if not raw:
            continue
        try:
            items = parse_json_array(raw)
            items = [await _resolve_comparison_page_item(item, danawa_tables) for item in items]
            items = filter_candidates(items, max_items=_MAX_CANDIDATES_PER_AGENT)
            entries.extend((agent_name, AgentCandidate(**item)) for item in items)
        except Exception:
            logger.exception("%s 제안 파싱 실패, 이 제안자는 후보 풀에서 제외", agent_name)

    return merge_candidates(entries)


# Tavily extract 호출 수 상한 — 병합 후보가 많아도 재조회 비용/지연시간을 제한한다.
_MAX_EXTRACT_CANDIDATES = 10


def _urls_to_extract(candidates: list[dict]) -> list[str]:
    """재조회 대상 URL — 병합 후보 중 URL이 있는 것만, 상한선까지만 남긴다."""
    return [c["url"] for c in candidates[:_MAX_EXTRACT_CANDIDATES] if c.get("url")]


def _is_danawa_product_url(url: str | None) -> bool:
    return bool(url) and urlsplit(url).netloc.lower().endswith("danawa.com")


class _ExtractPagesNode(BaseAgent):
    """병합된 후보들의 실제 판매 페이지 원문을 다시 가져와 상태에 저장한다.
    challenge(DeepSeek)는 기존에는 검색 당시 잘린 스니펫(최대 1500자)만 보고
    판단했는데, 여기서 채운 candidate_pages를 함께 주면 지금 이 URL의 실제
    최신 본문을 근거로 재검증할 수 있다 — search.extract()는 원래도 있었지만
    어디서도 쓰이지 않던 함수였다. 개별 URL 조회가 실패해도 그 후보만 스니펫
    기반 검증으로 남고 나머지는 그대로 진행한다(전체를 막지 않음).

    후보 URL은 전부 다나와 검색(Tavily include_domains=danawa.com)에서 나오므로,
    다나와 URL에 한해 fetchers/danawa.py로 직접 재조회해 "가격비교 서비스가
    종료된 상품" 페이지인지도 함께 확인한다(사용자 요청, 2026-08-13: "가격미확인
    되어있는것도 뜨거든... 가격 비교가 중지된 상품이라고 뜨는 이런 경우의 수도
    없애주면"). Tavily extract 텍스트만으로 challenge LLM이 이 패턴을 매번
    알아채리라 보장할 수 없어서, _is_expired_page()로 이미 검증된 판별을
    LLM 판단에 맡기지 않고 여기서 결정적으로 걸러낸다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        candidates: list[dict] = ctx.session.state.get("candidates") or []
        urls = _urls_to_extract(candidates)
        danawa_urls = [u for u in urls if _is_danawa_product_url(u)]

        async def _safe_extract(url: str) -> tuple[str, str | None]:
            try:
                return url, await search_module.extract(url)
            except Exception:
                logger.warning("후보 페이지 재조회 실패: %r", url, exc_info=True)
                return url, None

        async def _check_expired(url: str) -> tuple[str, bool]:
            try:
                result = await danawa_fetcher.fetch_danawa_offers(url)
                return url, result["parse_status"] == "expired"
            except Exception:
                logger.warning("다나와 후보 URL 상태 확인 실패: %r", url, exc_info=True)
                return url, False

        pages: dict[str, str] = {}
        expired_urls: list[str] = []
        if urls:
            extracted, expiry_checked = await asyncio.gather(
                asyncio.gather(*(_safe_extract(u) for u in urls)),
                asyncio.gather(*(_check_expired(u) for u in danawa_urls)),
            )
            pages = {url: text for url, text in extracted if text}
            expired_urls = [url for url, is_expired in expiry_checked if is_expired]

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"candidate_pages": pages, "expired_danawa_urls": expired_urls}),
        )


class _ApplyChallengeNode(BaseAgent):
    """DeepSeek의 검증 결과를 병합된 후보와 매칭해 최종 Proposal 목록을 만든다 —
    URL 우선, 실패 시 인덱스로 폴백(LLM이 순서를 흐트러뜨릴 가능성에 대비)."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        candidates: list[dict] = state.get("candidates") or []
        raw_challenge = state.get("raw_challenge")
        expired_urls = set(state.get("expired_danawa_urls") or [])

        verdicts: list[ChallengeVerdict] = []
        if raw_challenge:
            try:
                verdicts = [ChallengeVerdict(**v) for v in parse_json_array(raw_challenge)]
            except Exception:
                logger.exception("DeepSeek 검증 결과 파싱 실패 — 전부 미검증으로 진행")

        proposals = _apply_challenge(candidates, ChallengeResult(verdicts=verdicts), expired_urls)

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"proposals": [p.model_dump() for p in proposals]}),
        )


def _apply_challenge(
    candidates: list[dict], challenge: ChallengeResult, expired_urls: set[str] = frozenset()
) -> list[Proposal]:
    """병합된 후보(merge_candidates 출력 dict)와 검증 결과를 매칭해 Proposal로
    합성하는 순수 함수 — LLM 호출 없이 테스트 가능.

    expired_urls에 속한 후보(다나와가 "가격비교 서비스가 종료된 상품"으로 표시하는
    페이지로 확인됨)는 verified=False로 남기지 않고 아예 결과에서 제외한다 —
    challenge/judge 단계까지 흘려보내면 죽은 링크가 "가격미확인" 카드로 그대로
    노출될 수 있어서다. 후보가 전부 걸러지면 proposals가 빈 리스트가 되는데,
    이는 run_stream()의 기존 "후보 0개" 폴백 체인(clarify → relaxed fallback →
    NO_CANDIDATE_ERROR)이 그대로 처리한다.

    proposed_by에 "danawa"가 섞인 후보(_DanawaFetchNode가 넣은 실측가 - 다른
    에이전트와 병합됐든 단독이든)는 DeepSeek 검증 결과를 안 보고 verified=True로
    강제한다 - 이미 실측 확인된 가격/구매링크를 텍스트 기반 challenge LLM에게
    다시 판단하게 하는 건 불필요하고, verdict가 안 붙으면 verified=None(미검증)
    으로 표시돼 실측 데이터가 오히려 검증 안 된 것처럼 보이는 문제도 막는다.

    가격 신선도(2026-08-19, 사용자 리포트 "실제로 사이트 들어갔을 때는 다른
    가격을 가져오는 문제") - danawa 출신이 아닌 후보(주로 propose 단계 LLM이
    검색 캐시 스니펫을 읽고 추측한 price_krw, 최대 6시간 묵을 수 있음)는
    verdict.refreshed_price_krw가 있으면 그걸로 price를 덮어쓴다. 이 값은 새
    네트워크 호출이 아니라 challenge 직전 _ExtractPagesNode가 이미 라이브로
    재조회해 둔 candidate_pages 원문에서 나온다 - 그동안 그라운딩 검증에만
    쓰이고 버려지던 데이터를 가격 갱신에도 재사용하는 것. danawa 출신 후보는
    원래 가격 자체가 이미 구조화된 실측 스크래핑이라(대신 최대 1시간 캐시)
    텍스트 기반 재추출이 오히려 덜 정확할 수 있어 건드리지 않는다."""
    verdicts_by_url = {v.url: v for v in challenge.verdicts if v.url}

    proposals = []
    for i, candidate in enumerate(candidates):
        url = candidate.get("url")
        if url in expired_urls:
            logger.info("다나와 가격비교 중지 페이지로 확인되어 후보에서 제외: %s", url)
            continue

        proposed_by = candidate.get("proposed_by") or []
        price_krw = candidate.get("price_krw")
        if "danawa" in proposed_by:
            verified: bool | None = True
            challenge_note = "다나와 실측 가격표에서 확인된 A등급(구매 링크 검증됨) 후보"
        else:
            verdict = verdicts_by_url.get(url)
            if verdict is None and i < len(challenge.verdicts):
                verdict = challenge.verdicts[i]
            verified = verdict.verified if verdict else None
            challenge_note = verdict.note if verdict else None
            if verdict is not None and verdict.refreshed_price_krw is not None:
                price_krw = verdict.refreshed_price_krw
                challenge_note = (
                    f"{challenge_note} (재조회 시점 가격으로 갱신됨)"
                    if challenge_note
                    else "재조회 시점 가격으로 갱신됨"
                )

        # 같은 상품이 여러 모델에서 조금씩 다른 문구로 제안되면 reasons가 여러 개
        # 쌓인다 — 전부 이어붙이면 근거가 아니라 벽글이 되므로 최대 2개만 보여준다.
        reasons = (candidate.get("reasons") or [])[:2]
        proposals.append(
            Proposal(
                agent=proposed_by[0] if proposed_by else "gpt",
                product_name=candidate.get("product_name"),
                price=_format_price_krw(price_krw),
                retailer=candidate.get("retailer"),
                url=candidate.get("url"),
                reasoning=" / ".join(reasons) if reasons else None,
                verified=verified,
                challenge_note=challenge_note,
                proposed_by=proposed_by or None,
            )
        )
    return proposals


# ---------------------------------------------------------------------------
# LlmAgent 노드 — 실제 모델 호출은 ADK + LiteLlm이 담당(수동 SDK 호출 없음).
#
# ADK의 SequentialAgent/ParallelAgent는 서브 에이전트 하나가 예외를 던지면
# 파이프라인 전체를 그대로 죽인다 - 이 프로젝트는 이 기본 동작을 그대로
# 쓴다(2026-08-18, 사용자 요청: "AI 모델중에 하나라도 토큰 다쓰면 실행되지
# 않도록 바꿔줘" - "3개중 하나라도 빠지면 결과를 내지 않도록"과 같은 원칙을
# refine/challenge/judge까지 전부 확장). challenge·judge는 on_model_error_callback을
# 아예 등록하지 않아 원래도 실패하면 그대로 예외가 올라갔다(agent.
# canonical_on_model_error_callbacks가 비어있으면 ADK가 원본 예외를 그대로
# raise한다 - base_llm_flow._call_llm_async 참고). refine/propose 2곳만
# "이 모델 하나 없이도 계속 진행"하는 콜백을 등록해뒀었는데(과거엔 모델 하나가
# 죽어도 나머지로 답을 냈다), 이제 둘 다 실패를 그대로 흘려보내 pipeline_failed로
# 처리되게 바꿨다 - run_stream()의 바깥 try/except가 이를 잡아 proposals를
# 빈 채로 두고 기존 clarify/relaxed fallback/NO_CANDIDATE_ERROR 경로로 이어진다.
# ---------------------------------------------------------------------------


def _model_error_fallback_response(text: str) -> LlmResponse:
    """모델 호출이 실패했을 때 성공한 것처럼 대신 흘려보낼 최소 응답 — ADK는 이
    텍스트를 실제 모델 응답과 동일하게 output_key/output_schema 처리 경로로
    흘려보낸다(base_llm_flow._finalize_model_response_event가 이 content를 그대로
    이벤트에 병합)."""
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _skip_refine_if_already_specific(callback_context, llm_request) -> LlmResponse | None:
    """정제(refine)는 파이프라인에서 검색이 시작되기 전에 걸리는 첫 LLM 왕복이라,
    여기를 건너뛰면 그만큼 전체 응답 지연이 그대로 줄어든다(사용자 요청,
    2026-08-15: "순차단계 줄이자"). REFINE_QUERY_INSTRUCTIONS 자체가 "질의가
    이미 구체적이면 그대로 반환하라"고 하므로, 그 판단을 매번 모델에 왕복해
    묻는 대신 이미 있는 needs_clarification() 휴리스틱(브랜드/스펙 없이 짧은
    질의나 "사고싶어"류 모호한 구매의도 문구만 True)으로 로컬에서 먼저 걸러
    낸다. 애매하면(True) 여기서 손대지 않고 실제 정제(Groq)를 그대로 태운다 -
    오탐(정제가 실제로 필요한데 건너뜀)의 대가가 "약간 덜 다듬어진 검색어"
    정도라 위험하지 않다."""
    original_query = callback_context.state.get("original_query", "")
    if not original_query or needs_clarification(original_query):
        return None
    fallback = RefinedQuery(query=original_query)
    return _model_error_fallback_response(fallback.model_dump_json())


def _on_refine_model_error(callback_context, llm_request, error) -> LlmResponse | None:
    """refine의 모델(Groq) 호출이 실패하면 그 실패를 그대로 흘려보낸다(None
    반환) - propose와 동일한 이유(_on_propose_model_error 참고). 원래는
    정제를 포기하고 원본 질의로 폴백해 계속 진행했는데(다듬지 않은
    질의로라도 검색을 계속하는 게 파이프라인을 죽이는 것보다 낫다는 판단),
    2026-08-18(사용자 요청: "AI 모델중에 하나라도 토큰 다쓰면 실행되지
    않도록 바꿔줘") 어떤 모델이든 하나라도 실패하면 정직하게 전체를
    실패시키는 쪽으로 원칙을 통일했다."""
    logger.warning(
        "refine 단계 모델 호출 실패 - 모델 하나라도 실패하면 파이프라인을 그대로 실패시킨다",
        exc_info=error,
    )
    return None


def _on_propose_model_error(callback_context, llm_request, error) -> LlmResponse | None:
    """propose 3개(gpt/groq/deepseek) 중 하나라도 모델 호출에 실패하면 그
    실패를 그대로 흘려보낸다(None 반환) - ADK는 이 콜백이 None을 반환하면
    원래 예외를 그대로 raise한다(base_llm_flow._call_llm_async 참고). 그
    예외는 run_stream()의 바깥 try/except가 잡아 pipeline_failed=True로
    처리하고, proposals가 빈 채로 기존 clarify/relaxed fallback/
    NO_CANDIDATE_ERROR 경로로 이어진다 - 즉 2/3만으로 최종 답을 내지 않는다.

    (2026-08-18, 사용자 요청: "3개중 하나라도 빠지면 결과를 내지 않도록
    해야지 왜 3개를 안쓰고 2개만해서 결과를 내") 원래는 실패한 슬롯만 빈
    배열("[]")로 대체해 나머지 2개로 계속 진행했다 - 3개 모델이 독립적으로
    같은 상품을 골랐는지(proposed_by 합의)가 그라운딩 신뢰도 신호로 쓰이는
    구조라, 2/3만으로 낸 답은 원래 설계한 신뢰도보다 낮은데도 겉보기엔
    구분이 안 됐다. 이제 하나라도 빠지면 아예 정직하게 실패로 처리한다."""
    logger.warning(
        "%s propose 단계 모델 호출 실패 - 3개 전부 성공해야 하므로 파이프라인을 그대로 실패시킨다",
        callback_context.agent_name,
        exc_info=error,
    )
    return None


def _groq_model(model_name: str) -> LiteLlm:
    """Groq는 OpenAI 호환 엔드포인트라 "openai/" 프리픽스 뒤에 api_base/api_key로
    Groq 엔드포인트를 직접 지정한다 - litellm이 groq 프로바이더를 자체 지원하는지에
    기대지 않고 "그냥 OpenAI 호환 엔드포인트"로 취급하는 쪽이 확실하다(agents/gpt.py의
    DashScope 처리와 동일한 접근). num_retries=0 - embeddings.py와 동일한 이유
    (사용자 요청, 2026-08-15: "너무 느려 더 빠르게"): 실패해도 각 단계마다 이미
    폴백(on_model_error_callback 등)이 있어 litellm 내부 재시도로 얻는 이득보다
    지연 비용이 크다."""
    return LiteLlm(
        model=f"openai/{model_name}",
        api_base=settings.groq_api_base,
        api_key=settings.groq_api_key,
        num_retries=0,
    )


def _build_refine_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        return build_refine_query_prompt(ctx.state.get("original_query", ""))

    return LlmAgent(
        name="refine",
        # refine은 2026-08-16부터 Gemini가 아니라 Groq다(사용자 요청: "deepseek
        # Qwen 빼고 싹 다 무료 모델로 바꾸려고 해"). ADK가 output_schema를
        # response_format=json_schema로 요청하는데 propose 쪽 groq_model
        # (groq/compound-mini)은 이를 지원하지 않아, 구조화 출력이 되는 전용
        # 모델(groq_refine_model)을 따로 쓴다(config.py 주석 참고).
        model=_groq_model(settings.groq_refine_model),
        instruction=instruction,
        output_schema=RefinedQuery,
        output_key="refined_query",
        before_model_callback=_skip_refine_if_already_specific,
        on_model_error_callback=_on_refine_model_error,
    )


def _build_propose_agent(name: str, model) -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        results = _search_results_from_state(ctx.state)
        return build_prompt(query, results)

    return LlmAgent(
        name=name,
        model=model,
        instruction=instruction,
        output_key=f"{name}_raw",
        on_model_error_callback=_on_propose_model_error,
    )


def _build_challenge_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        candidates = ctx.state.get("candidates") or []
        results = _search_results_from_state(ctx.state)
        candidate_pages = ctx.state.get("candidate_pages") or {}
        coupang_results = [SearchResult(**r) for r in ctx.state.get("coupang_results") or []]
        naver_results = [SearchResult(**r) for r in ctx.state.get("naver_results") or []]
        return build_challenge_prompt(query, candidates, results, candidate_pages, coupang_results, naver_results)

    return LlmAgent(
        name="challenge",
        model=LiteLlm(model=f"deepseek/{settings.deepseek_model}", num_retries=0),
        instruction=instruction,
        output_key="raw_challenge",
    )


def _judge_eligible_proposals(proposals: list[Proposal]) -> list[Proposal]:
    """DeepSeek 검증에서 명확히 우려(verified=False)로 표시된 후보는 judge에게
    아예 보여주지 않는다 — 예전에는 참고 정보로만 주고 LLM이 그래도 우려 후보를
    고를 수 있는 구조였다. 단, 전부 우려로 표시된 경우(검증 자체가 과도하게
    엄격했을 가능성)에는 예외적으로 전체 목록을 그대로 넘긴다 — 하나도 못
    고르는 것보다는 최선의 후보라도 고르는 게 낫다."""
    eligible = [p for p in proposals if p.verified is not False]
    return eligible or proposals


def _skip_judge_if_single_candidate(callback_context, llm_request) -> LlmResponse | None:
    """검증을 통과한 제안이 정확히 1개면 그 사이에서 "고를" 게 없다 - judge(Claude,
    약 5초) 호출을 건너뛰고 그 하나를 그대로 채택한다(사용자 요청, 2026-08-15:
    "너무 느려 더 빠르게" - 에이전트당 최종 후보 1개 + dedup 병합 + verified=False
    탈락을 거치고 나면, 특히 지금처럼 일부 에이전트 토큰이 소진된 상황에서는
    실제로 이 경우가 자주 나온다). _build_decision()이 judge의 raw product_name/
    price/retailer보다 url로 찾은 실제 proposal(matched)의 그라운딩된 값을
    우선하므로, 여기서는 url만 정확히 일치시키면 나머지 필드는 자동으로 검증된
    값으로 채워진다 - reasoning만 이 함수가 직접 채운다.

    후보가 0개거나 2개 이상이면 원래대로 judge를 그대로 태운다 - 0개는 "고를
    필요 없음"이 아니라 "아무것도 못 찾음"이라 judge의 완화된 자유 추론이 여전히
    의미 있고, 2개 이상은 진짜 비교/심사가 필요하다."""
    proposals = [Proposal(**p) for p in (callback_context.state.get("proposals") or [])]
    eligible = _judge_eligible_proposals(proposals)
    if len(eligible) != 1:
        return None
    only = eligible[0]
    if not (only.product_name and only.price and only.retailer and only.url):
        return None
    verdict = judge_module.JudgeVerdict(
        product_name=only.product_name,
        price=only.price,
        retailer=only.retailer,
        url=only.url,
        reasoning=f"다른 유효한 제안이 없어 {only.agent}의 후보를 그대로 채택했습니다.",
    )
    return _model_error_fallback_response(verdict.model_dump_json())


def _build_judge_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        proposals = [Proposal(**p) for p in (ctx.state.get("proposals") or [])]
        return judge_module.build_judge_prompt(query, _judge_eligible_proposals(proposals))

    return LlmAgent(
        name="judge",
        # judge는 2026-08-16부터 Claude가 아니라 Groq(openai/gpt-oss-120b)다
        # (사용자 요청: "deepseek Qwen 빼고 싹 다 무료 모델로 바꾸려고 해" -
        # Anthropic엔 상시 무료 API 티어가 없다). propose 쪽 groq 슬롯도 같은
        # gpt-oss 계열이지만(2026-08-18부터 120b 공유 - config.py 주석 참고),
        # judge는 계속 120b를 쓴다 - Groq 카탈로그에 구조화 출력(json_schema)을
        # 지원하는 모델이 gpt-oss 계열뿐이라 propose·judge가 완전히 다른 계보를
        # 쓰긴 어렵다.
        model=_groq_model(settings.groq_judge_model),
        instruction=instruction,
        output_schema=judge_module.JudgeVerdict,
        output_key="raw_decision",
        before_model_callback=_skip_judge_if_single_candidate,
    )


def _build_pipeline() -> SequentialAgent:
    gpt_raw = "gpt"
    groq_raw = "groq"
    deepseek_raw = "deepseek"

    propose_parallel = ParallelAgent(
        name="propose",
        sub_agents=[
            # "gpt" 슬롯은 2026-08-15부터 Qwen(DashScope)이 담당한다(사용자 요청:
            # "GPT 토큰이 더 이상 없어서 Qwen 성능 제일 좋은 걸로 바꿔줘") - openai/
            # 프리픽스 대신, DashScope의 OpenAI 호환 엔드포인트를 api_base로 직접
            # 지정한다. litellm이 dashscope 프로바이더를 자체적으로 지원하는지에
            # 기대지 않고, "그냥 OpenAI 호환 엔드포인트"로 취급하는 쪽이 확실하다
            # (agents/gpt.py의 openai SDK+base_url 방식과 동일한 접근). name/
            # output_key는 그대로 "gpt"라 스키마의 AgentName 리터럴이나 이 파일
            # 다른 곳의 "gpt" 참조를 안 건드린다.
            _build_propose_agent(
                gpt_raw,
                LiteLlm(
                    model=f"openai/{settings.qwen_model}",
                    api_base=settings.qwen_api_base,
                    api_key=settings.qwen_api_key,
                    num_retries=0,
                ),
            ),
            # 이 슬롯은 2026-08-16부터 Groq가 담당한다(사용자 요청: "deepseek
            # Qwen 빼고 싹 다 무료 모델로 바꾸려고 해" - Gemini 프로젝트가
            # 403으로 막혀있기도 했다). name/output_key는 원래 "gemini"였지만
            # 2026-08-18("Gemini 이제 안쓰니까 이름 제대로 바꿔서 코드 반영해")
            # 실제 쓰는 모델명을 따라 "groq"로 리네임했다(스키마 AgentName,
            # 프론트엔드, 테스트 전반의 참조도 함께 바꿨다).
            _build_propose_agent(groq_raw, _groq_model(settings.groq_model)),
            _build_propose_agent(
                deepseek_raw, LiteLlm(model=f"deepseek/{settings.deepseek_model}", num_retries=0)
            ),
            # 다나와 A등급 실측가 - 2026-08-16, PRESERVED FROM seungmin/lsm의
            # run_single_debate_price_table_variant(PART 4-2)를 라이브 ADK
            # 파이프라인으로 포팅(README "한계점 및 향후 과제" 후속작업). LLM이
            # 아니라 커스텀 BaseAgent지만 같은 ParallelAgent 소속이라 gpt/groq/
            # deepseek와 동시에 실행된다(지연시간 추가 없음).
            _DanawaFetchNode(name="danawa"),
            # 쿠팡 교차 확인(2026-08-16, "그라운딩 성능을 높여줘") - 후보를 만들지
            # 않고 challenge 단계의 참고 신호만 채운다. 같은 ParallelAgent 소속이라
            # 지연시간이 추가되지 않는다.
            _CoupangCheckNode(name="coupang_check"),
            # 네이버쇼핑 교차 확인(2026-08-16, "다나와 단일 실측 소스에 대한
            # 의존도를 낮추도록") - 쿠팡과 같은 소프트 신호 패턴의 두 번째 소스.
            _NaverCheckNode(name="naver_check"),
        ],
    )

    return SequentialAgent(
        name="single_debate_pipeline",
        sub_agents=[
            _build_refine_agent(),
            _SearchNode(name="search"),
            propose_parallel,
            _FilterMergeNode(name="filter_merge"),
            _ExtractPagesNode(name="extract_pages"),
            _build_challenge_agent(),
            _ApplyChallengeNode(name="apply_challenge"),
            _build_judge_agent(),
        ],
    )


_runner: InMemoryRunner | None = None


def _get_runner() -> InMemoryRunner:
    global _runner
    if _runner is None:
        _runner = InMemoryRunner(agent=_build_pipeline(), app_name=_APP_NAME)
    return _runner


_STAGE_AFTER = {
    "refine": "searching",
    "search": "proposing",
    "filter_merge": "challenging",
    "apply_challenge": "judging",
}

_decide_result_adapter = TypeAdapter(DecideResponse | ClarifyResponse)


def _build_decision(state: dict, proposals: list[Proposal]) -> Decision | None:
    """judge(LLM)는 raw_decision에 자기 나름의 product_name/price/retailer/url을
    자유 텍스트로 다시 쓸 수 있는데, 후보 목록에 없는 값을 지어낼 위험이 있다
    (실제로 url이 빈 후보를 골랐을 때 judge가 그럴듯한 URL을 스스로 채워 넣는
    사례를 확인했다). raw.url로 실제 후보(matched)를 찾은 뒤에는, 검증을 거친
    matched의 값(그라운딩된 데이터)을 우선하고 raw는 matched에 값이 없을 때만
    보충으로 쓴다 — reasoning만은 judge가 직접 작성하는 문장이라 그대로 쓴다."""
    raw = state.get("raw_decision")
    if not raw or not proposals:
        return None

    url = raw.get("url")
    matched = next((p for p in proposals if p.url and p.url == url), None) or proposals[0]

    return Decision(
        product_name=matched.product_name or raw.get("product_name") or "",
        price=matched.price or raw.get("price") or "",
        retailer=matched.retailer or raw.get("retailer") or "",
        url=matched.url or raw.get("url") or "",
        reasoning=raw.get("reasoning") or "",
        chosen_agent=matched.agent,
        verified=matched.verified,
    )


async def _verify_relaxed_verdict(
    query: str, verdict: judge_module.JudgeVerdict, search_results: list[SearchResult]
) -> bool | None:
    """relaxed fallback이 고른 verdict를 정상 propose 후보와 동일한 DeepSeek
    challenge 기준으로 그라운딩 재검증한다(2026-08-16 하드닝 - "구매링크를
    안띄워주는거야" 버그의 근본 원인이 바로 이 경로였다: challenge/CMPNYC_MAP
    검증을 전부 우회한 채 Qwen 단독 판단을 그대로 최종 응답으로 내보냈다).
    쿠팡·네이버쇼핑 참고 신호도 정상 challenge와 동일하게 함께 준다. 검증
    자체가 실패(API 오류·파싱 실패)하면 None(미검증)을 반환한다 - 검증 인프라
    장애 때문에 이미 찾은 유일한 후보를 버리지 않는다."""
    candidate = {
        "product_name": verdict.product_name,
        "price_krw": verdict.price,
        "retailer": verdict.retailer,
        "url": verdict.url,
        "reasoning": verdict.reasoning,
    }
    coupang_task = search_module.search_coupang(query)
    naver_task = search_module.search_naver(query)
    coupang_results, naver_results = await asyncio.gather(coupang_task, naver_task)
    verdicts = await deepseek_module.challenge_candidates(
        query, [candidate], search_results, None, coupang_results, naver_results
    )
    if not verdicts:
        return None
    match = next((v for v in verdicts if v.url == verdict.url), verdicts[0])
    return match.verified


async def _pick_and_verify_relaxed(
    query: str, search_results: list[SearchResult]
) -> tuple[judge_module.JudgeVerdict, bool | None] | None:
    """한 라운드(주어진 검색 결과 기준)의 relaxed pick + challenge 재검증을
    묶은 헬퍼. verified=False로 명백히 우려 표시되면 그 후보는 폐기하고
    None을 돌려줘(호출부가 다음 라운드로 넘어가거나 완전히 포기하게) - "낮은
    확신"과 "명백히 틀림"은 다르게 취급한다(challenge의 기존 원칙과 동일:
    애매하면 false 남발 금지, 명백할 때만 false)."""
    verdict = await gpt_module.pick_most_relevant(query, search_results)
    if verdict is None:
        return None
    verified = await _verify_relaxed_verdict(query, verdict, search_results)
    if verified is False:
        logger.info("relaxed fallback 후보가 challenge 검증에서 탈락 — 폐기: %r", verdict.url)
        return None
    return verdict, verified


async def _relaxed_fallback_decision(query: str, search_results: list[SearchResult]) -> Decision | None:
    """적절한 후보를 하나도 못 찾았을 때의 폴백(2026-08-15, "적절한 상품 후보를
    찾지 못하면 다시 fallback해서 feedback 구조로 돌아가서 가장 관련성 높은
    상품을 추천해주는 시스템으로 가고 싶어" - 완전 재검색 루프(끝없이 검색어를
    넓혀가는 것)와 단순 1회 재시도의 중간): 최대 두 라운드만 시도하고 그래도
    없으면 정직하게 포기한다(NO_CANDIDATE_ERROR).

    1라운드 - 이미 가져온 검색 결과 그대로, gpt.pick_most_relevant로 완벽히
    일치하지 않아도 가장 관련성 높은 것을 고르게 한 뒤, DeepSeek challenge로
    다시 검증한다(2026-08-16 하드닝). 검색 자체는 다시 안 하므로 비용이
    거의 없다.

    2라운드(1라운드가 후보를 아예 못 찾았거나 challenge에서 명백히 탈락했을
    때만) - 질의를 앞 2단어로 넓혀 한 번만 재검색한 뒤 같은 기준으로 다시
    시도한다. 넓힌 질의가 원래 질의와 같으면(이미 짧은 질의라 넓힐 게 없으면)
    똑같은 검색을 반복하는 낭비이므로 건너뛴다."""
    picked = await _pick_and_verify_relaxed(query, search_results)
    used_broadened = False
    if picked is None:
        tokens = query.split()
        broadened_query = " ".join(tokens[:2]) if len(tokens) > 2 else query
        if broadened_query != query:
            try:
                broadened_results = await search_module.search(broadened_query)
            except Exception:
                broadened_results = []
            picked = await _pick_and_verify_relaxed(query, broadened_results)
            used_broadened = True
    if picked is None:
        return None
    verdict, verified = picked
    if not verdict.product_name:
        return None

    reasoning = verdict.reasoning
    if used_broadened:
        reasoning = f"'{query}'로는 적절한 상품을 찾지 못해 검색 범위를 넓혀 찾았습니다. {reasoning}"
    if verified is not True:
        reasoning = f"{reasoning} (참고: 교차 검증을 통과하지 못한 낮은 확신의 답변입니다.)"
    return Decision(
        product_name=verdict.product_name,
        price=verdict.price,
        retailer=verdict.retailer,
        url=verdict.url,
        reasoning=reasoning,
        chosen_agent="gpt",
        verified=verified,
    )


def _danawa_tables_from_state(state: dict) -> list[tuple[PriceTable, dict]]:
    return [(PriceTable(**t), raw) for t, raw in (state.get("danawa_tables") or [])]


async def _finalize_with_danawa(
    decision: Decision,
    proposals: list[Proposal],
    danawa_tables: list[tuple[PriceTable, dict]],
) -> tuple[Decision, PriceTable | None]:
    """judge(또는 relaxed fallback)가 고른 decision을 다나와 실측 데이터로
    후처리한다 - PRESERVED FROM seungmin/lsm의 run_single_debate_price_table_variant
    PART 4-2/4-3과 동일한 순서(debate.py 260-273줄)를 ADK 파이프라인으로 포팅.
    danawa_tables가 비어있으면(다나와 조회 실패/결과 없음) 세 호출 모두
    안전하게 아무것도 안 하고 decision을 그대로 돌려준다.

    1) judge가 실제로 danawa 후보를 골랐으면 price_source를 danawa_offer로 표시.
    2) pick_primary(offer가 가장 많은 페이지)를 응답의 price_table로 채운다 -
       지금까지 ADK 파이프라인은 이 필드를 항상 null로 냈다.
    3) enrich_decision - judge가 고른 상품명이 다나와 페이지와 이름이 맞으면
       실측 가격/판매처/URL로 덮어쓴다(이름이 안 맞으면 손대지 않음).
    4) exclude_price_comparison_site_as_final_pick - 최종 URL이 다나와
       가격비교 페이지 자체면(judge가 실수로 그렇게 골랐을 때) 실제 구매
       URL로 치환하거나 다른 제안으로 넘긴다."""
    if decision.chosen_agent == "danawa":
        decision.price_source = "danawa_offer"

    primary = price_table_module.pick_primary(danawa_tables)
    price_table: PriceTable | None = None
    if primary is not None:
        table, raw_result = primary
        price_table = table
        decision = await price_table_module.enrich_decision(decision, raw_result)

    decision = await price_table_module.exclude_price_comparison_site_as_final_pick(
        decision, proposals, danawa_tables
    )
    return decision, price_table


async def run_stream(query: str, skip_clarify: bool = False) -> AsyncIterator[dict[str, Any]]:
    """run()과 같은 결과를 만들지만, 단계마다 NDJSON 이벤트를 흘려보낸다 —
    debate.py::run_single_debate_stream이 그대로 재노출.

    skip_clarify(2026-08 통합 병합) - 프론트의 SearchContext.runTurn이 이미
    브랜드/facet/고정축 선택으로 한 라운드를 좁혀온 후속 턴이면 True로 넘어온다
    (main.py의 DecideRequest.skip_intent_check). 이게 없으면 검색 직후
    debate._is_ambiguous_facets()가 이번 라운드에도 남아있는 다른 facet(예:
    브랜드는 답했는데 용량이 여러 개)을 또 clarify로 멈춰세워, 사용자가 이미
    몇 라운드나 답했는데도 계속 새 선택 화면이 뜨는 재질문 버그가 생긴다 -
    True면 이 조기 종료를 건너뛰고 바로 propose/challenge/judge까지 진행한다
    (완전히 후보가 0개면 아래의 안전망 clarify는 skip_clarify와 무관하게
    그대로 동작한다)."""
    from .debate import _extract_clarify_options, _is_ambiguous_facets  # 지연 임포트 — 순환 참조 방지

    runner = _get_runner()
    session_id = str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name=_APP_NAME, user_id="anonymous", session_id=session_id, state={"original_query": query}
    )

    yield {"type": "status", "stage": "refining"}

    pipeline_failed = False
    gen = runner.run_async(
        user_id="anonymous",
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    )
    try:
        async for event in gen:
            # search도 우리가 직접 만든 커스텀 노드라 이벤트 모양을 확실히 안다.
            # 검색 직후 브랜드/용량/개수가 애매하면(Human-in-the-loop) 제안 단계로
            # 넘어가기 전에 여기서 파이프라인을 실제로 멈춘다 — 제안/검증/심사는
            # 아예 실행되지 않는다(만들어놓고 버리는 게 아니라 애초에 안 돈다).
            if event.author == "search" and event.actions and event.actions.state_delta:
                search_results = [
                    SearchResult(**r) for r in event.actions.state_delta.get("search_results") or []
                ]
                clarify = await _extract_clarify_options(query, search_results)
                if (
                    clarify is not None
                    and not skip_clarify
                    and _is_ambiguous_facets(query, clarify.options.facets)
                ):
                    await gen.aclose()
                    yield {"type": "final", "result": clarify.model_dump()}
                    return

            # apply_challenge는 우리가 직접 만든 커스텀 노드라 이 이벤트의
            # state_delta 형태를 확실히 안다(LlmAgent의 output_key 이벤트 형태는
            # 검증되지 않아 의존하지 않음 — 최종 상태는 아래에서 get_session()으로
            # 한 번에 확정해서 읽는다). 후보를 먼저 보여준 뒤 judging 단계로 넘어가야
            # 하므로 proposal 이벤트를 status보다 먼저 yield한다.
            if event.author == "apply_challenge" and event.actions and event.actions.state_delta:
                for proposal in event.actions.state_delta.get("proposals") or []:
                    yield {"type": "proposal", "proposal": proposal}

            next_stage = _STAGE_AFTER.get(event.author)
            if next_stage:
                yield {"type": "status", "stage": next_stage}
    except Exception:
        logger.exception("ADK 파이프라인 실행 실패: %r", query)
        pipeline_failed = True

    final_session = await runner.session_service.get_session(
        app_name=_APP_NAME, user_id="anonymous", session_id=session_id
    )
    final_state: dict = dict(final_session.state) if final_session else {}
    if pipeline_failed:
        final_state.setdefault("proposals", [])

    danawa_tables = _danawa_tables_from_state(final_state)
    proposals = [Proposal(**p) for p in (final_state.get("proposals") or [])]

    if not proposals:
        search_results = _search_results_from_state(final_state)
        clarify = await _extract_clarify_options(query, search_results)
        if clarify is not None:
            yield {"type": "final", "result": clarify.model_dump()}
            return
        fallback_decision = await _relaxed_fallback_decision(query, search_results)
        if fallback_decision is not None:
            fallback_decision, price_table = await _finalize_with_danawa(fallback_decision, [], danawa_tables)
            result = DecideResponse(
                query=query, proposals=[], decision=fallback_decision, price_table=price_table
            )
            yield {"type": "final", "result": result.model_dump()}
            return
        raise RuntimeError(NO_CANDIDATE_ERROR)

    decision = _build_decision(final_state, proposals)
    if decision is None:
        fallback_decision = await _relaxed_fallback_decision(query, _search_results_from_state(final_state))
        if fallback_decision is not None:
            fallback_decision, price_table = await _finalize_with_danawa(
                fallback_decision, proposals, danawa_tables
            )
            result = DecideResponse(
                query=query, proposals=proposals, decision=fallback_decision, price_table=price_table
            )
            yield {"type": "final", "result": result.model_dump()}
            return
        raise RuntimeError(NO_CANDIDATE_ERROR)

    decision, price_table = await _finalize_with_danawa(decision, proposals, danawa_tables)
    result = DecideResponse(query=query, proposals=proposals, decision=decision, price_table=price_table)
    yield {"type": "final", "result": result.model_dump()}


async def run(query: str, skip_clarify: bool = False) -> DecideResponse | ClarifyResponse:
    result_dict = None
    async for event in run_stream(query, skip_clarify=skip_clarify):
        if event["type"] == "final":
            result_dict = event["result"]
    if result_dict is None:
        raise RuntimeError(NO_CANDIDATE_ERROR)
    return _decide_result_adapter.validate_python(result_dict)
