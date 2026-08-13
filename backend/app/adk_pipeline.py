"""ADK(Google Agent Development Kit) 기반 역할 분리형 검색 파이프라인.

정제(Gemini) → 검색 → 제안(GPT·Gemini·DeepSeek 병렬, 각자 최선 1개) →
필터링+병합(fusion.dedup 재사용) → 검증(DeepSeek) → 매칭/합성 → 심사(Claude)
순서로 실행된다 — `debate.py`의 run_single_debate/run_single_debate_stream이
이 모듈의 run()/run_stream()을 호출한다.

SequentialAgent/ParallelAgent는 google-adk 2.6.3 기준 deprecated(대체 예정인
Workflow가 아직 LlmAgent의 sub-agent로 못 쓰여 미완성 상태)이지만, 실제로는
정상 동작함을 스파이크로 검증했다 — Workflow가 성숙하면 마이그레이션 대상.
"""

from __future__ import annotations

import asyncio
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

from . import search as search_module
from .agents import gpt as gpt_module
from .agents import judge as judge_module
from .category import CategoryClassification, classify_category
from .intent import has_count_spec, has_volume_spec, needs_clarification
from .agents.base import (
    NO_CANDIDATE_ERROR,
    build_challenge_prompt,
    build_prompt,
    build_refine_query_prompt,
    filter_candidates,
    format_results_block,
    parse_json_array,
)
from .config import settings
from .schemas import (
    AgentCandidate,
    ChallengeResult,
    ChallengeVerdict,
    ClarifyOptions,
    ClarifyResponse,
    DecideResponse,
    Decision,
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
# (_SearchNode는 예외적으로 내부에서 Gemini 분류를 한 번 호출한다 — 그 노드
# docstring 참고.)
# ---------------------------------------------------------------------------


class _SearchNode(BaseAgent):
    """정제된 질의로 search_module.search()를 호출해 원본 결과 + 프롬프트용
    포맷 텍스트를 상태에 저장한다. 이 섹션의 다른 노드와 달리 Tavily 호출 전에
    카테고리 분류(Gemini) 호출이 하나 더 낀다 — 분류 결과를 검색어에 얹어
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


class _FilterMergeNode(BaseAgent):
    """3개 제안 노드의 원시 JSON을 각각 파싱+필터링한 뒤, fusion.dedup으로
    동일 상품을 병합한다 — 지금까지 어디서도 안 쓰이던 merge_candidates()가
    여기서 처음 실사용된다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        raw_by_agent = {
            "gpt": state.get("gpt_raw"),
            "gemini": state.get("gemini_raw"),
            "deepseek": state.get("deepseek_raw"),
        }
        merged = _merge_proposals(raw_by_agent)
        logger.info(
            "후보 풀: 병합 %d건 (%r)", len(merged), [m["proposed_by"] for m in merged]
        )

        yield Event(author=self.name, actions=EventActions(state_delta={"candidates": merged}))


def _merge_proposals(raw_by_agent: dict[str, str | None]) -> list[dict]:
    """3개 제안자의 원시 JSON 텍스트를 각각 파싱+필터링한 뒤 fusion.dedup으로
    동일 상품을 병합하는 순수 함수 — 한 제안자의 파싱이 실패해도 나머지로
    진행한다(LLM 호출 없이 테스트 가능)."""
    entries: list[tuple[str, AgentCandidate]] = []
    for agent_name, raw in raw_by_agent.items():
        if not raw:
            continue
        try:
            items = parse_json_array(raw)
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
    NO_CANDIDATE_ERROR)이 그대로 처리한다."""
    verdicts_by_url = {v.url: v for v in challenge.verdicts if v.url}

    proposals = []
    for i, candidate in enumerate(candidates):
        url = candidate.get("url")
        if url in expired_urls:
            logger.info("다나와 가격비교 중지 페이지로 확인되어 후보에서 제외: %s", url)
            continue
        verdict = verdicts_by_url.get(url)
        if verdict is None and i < len(challenge.verdicts):
            verdict = challenge.verdicts[i]

        proposed_by = candidate.get("proposed_by") or []
        # 같은 상품이 여러 모델에서 조금씩 다른 문구로 제안되면 reasons가 여러 개
        # 쌓인다 — 전부 이어붙이면 근거가 아니라 벽글이 되므로 최대 2개만 보여준다.
        reasons = (candidate.get("reasons") or [])[:2]
        proposals.append(
            Proposal(
                agent=proposed_by[0] if proposed_by else "gpt",
                product_name=candidate.get("product_name"),
                price=_format_price_krw(candidate.get("price_krw")),
                retailer=candidate.get("retailer"),
                url=candidate.get("url"),
                reasoning=" / ".join(reasons) if reasons else None,
                verified=verdict.verified if verdict else None,
                challenge_note=verdict.note if verdict else None,
                proposed_by=proposed_by or None,
            )
        )
    return proposals


# ---------------------------------------------------------------------------
# LlmAgent 노드 — 실제 모델 호출은 ADK + LiteLlm이 담당(수동 SDK 호출 없음).
#
# ADK의 SequentialAgent/ParallelAgent는 서브 에이전트 하나가 예외를 던지면
# 파이프라인 전체를 그대로 죽인다(예: propose 3개 중 Gemini 하나만 API 오류가
# 나도 GPT·DeepSeek가 이미 만들어둔 결과까지 전부 버려지고 "후보를 찾지 못했다"로
# 끝남 — 실제로 겪은 장애: Gemini 프로젝트가 일시적으로 403을 뱉었을 때 검색
# 전체가 죽었다). on_model_error_callback으로 모델 호출 실패를 가로채, 그 모델만
# 빈 결과로 대체하고 나머지 파이프라인은 계속 진행하게 한다.
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
    이미 구체적이면 그대로 반환하라"고 하므로, 그 판단을 Gemini에 매번 왕복해
    묻는 대신 이미 있는 needs_clarification() 휴리스틱(브랜드/스펙 없이 짧은
    질의나 "사고싶어"류 모호한 구매의도 문구만 True)으로 로컬에서 먼저 걸러
    낸다. 애매하면(True) 여기서 손대지 않고 실제 Gemini 정제를 그대로 태운다 -
    오탐(정제가 실제로 필요한데 건너뜀)의 대가가 "약간 덜 다듬어진 검색어"
    정도라 위험하지 않다."""
    original_query = callback_context.state.get("original_query", "")
    if not original_query or needs_clarification(original_query):
        return None
    fallback = RefinedQuery(query=original_query)
    return _model_error_fallback_response(fallback.model_dump_json())


def _on_refine_model_error(callback_context, llm_request, error) -> LlmResponse:
    """refine의 Gemini 호출이 실패하면 정제를 포기하고 원본 질의를 그대로 쓴다 —
    다듬지 않은 질의로라도 검색을 계속하는 게 파이프라인 전체를 죽이는 것보다
    낫다."""
    logger.warning("refine 단계 모델 호출 실패, 원본 질의로 폴백", exc_info=error)
    original_query = callback_context.state.get("original_query", "")
    fallback = RefinedQuery(query=original_query)
    return _model_error_fallback_response(fallback.model_dump_json())


def _on_propose_model_error(callback_context, llm_request, error) -> LlmResponse:
    """propose 3개 중 하나가 실패하면 그 모델의 후보를 빈 배열로 대체한다 —
    _merge_proposals가 파싱 실패/누락을 이미 각 에이전트 단위로 건너뛰도록 돼
    있으므로, 나머지 2개 모델의 후보만으로 정상 진행된다."""
    logger.warning(
        "%s propose 단계 모델 호출 실패, 이 모델 없이 진행", callback_context.agent_name, exc_info=error
    )
    return _model_error_fallback_response("[]")


def _build_refine_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        return build_refine_query_prompt(ctx.state.get("original_query", ""))

    return LlmAgent(
        name="refine",
        model=settings.gemini_model,  # 네이티브 Gemini — LiteLlm 불필요
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
        return build_challenge_prompt(query, candidates, results, candidate_pages)

    return LlmAgent(
        name="challenge",
        model=LiteLlm(model=f"deepseek/{settings.deepseek_model}"),
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


def _build_judge_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        proposals = [Proposal(**p) for p in (ctx.state.get("proposals") or [])]
        return judge_module.build_judge_prompt(query, _judge_eligible_proposals(proposals))

    return LlmAgent(
        name="judge",
        model=LiteLlm(model=f"anthropic/{settings.judge_model}"),
        instruction=instruction,
        output_schema=judge_module.JudgeVerdict,
        output_key="raw_decision",
    )


def _build_pipeline() -> SequentialAgent:
    gpt_raw = "gpt"
    gemini_raw = "gemini"
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
                ),
            ),
            _build_propose_agent(gemini_raw, settings.gemini_model),
            _build_propose_agent(deepseek_raw, LiteLlm(model=f"deepseek/{settings.deepseek_model}")),
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
    )


async def _relaxed_fallback_decision(query: str, search_results: list[SearchResult]) -> Decision | None:
    """적절한 후보를 하나도 못 찾았을 때의 폴백(2026-08-15, "적절한 상품 후보를
    찾지 못하면 다시 fallback해서 feedback 구조로 돌아가서 가장 관련성 높은
    상품을 추천해주는 시스템으로 가고 싶어" - 완전 재검색 루프(끝없이 검색어를
    넓혀가는 것)와 단순 1회 재시도의 중간): 최대 두 라운드만 시도하고 그래도
    없으면 정직하게 포기한다(NO_CANDIDATE_ERROR).

    1라운드 - 이미 가져온 검색 결과 그대로, gpt.pick_most_relevant로 완벽히
    일치하지 않아도 가장 관련성 높은 것을 고르게 한다(브랜드/스펙 그라운딩만
    완화 - 존재하지 않는 상품을 지어내는 건 여전히 금지). 검색 자체는 다시
    안 하므로 비용이 거의 없다.

    2라운드(1라운드가 그마저도 못 찾았을 때만 - 즉 검색 결과 자체가 질의와
    아예 무관했을 때) - 질의를 앞 2단어로 넓혀 한 번만 재검색한 뒤 같은 완화
    기준으로 다시 시도한다. 넓힌 질의가 원래 질의와 같으면(이미 짧은 질의라
    넓힐 게 없으면) 똑같은 검색을 반복하는 낭비이므로 건너뛴다."""
    verdict = await gpt_module.pick_most_relevant(query, search_results)
    used_broadened = False
    if verdict is None:
        tokens = query.split()
        broadened_query = " ".join(tokens[:2]) if len(tokens) > 2 else query
        if broadened_query != query:
            try:
                broadened_results = await search_module.search(broadened_query)
            except Exception:
                broadened_results = []
            verdict = await gpt_module.pick_most_relevant(query, broadened_results)
            used_broadened = True
    if verdict is None or not verdict.product_name:
        return None

    reasoning = verdict.reasoning
    if used_broadened:
        reasoning = f"'{query}'로는 적절한 상품을 찾지 못해 검색 범위를 넓혀 찾았습니다. {reasoning}"
    return Decision(
        product_name=verdict.product_name,
        price=verdict.price,
        retailer=verdict.retailer,
        url=verdict.url,
        reasoning=reasoning,
        chosen_agent="gpt",
    )


def _is_ambiguous(query: str, options: ClarifyOptions) -> bool:
    """브랜드/제품/용량/개수 중 하나라도 2개 이상이면 사용자에게 물어볼 만큼
    애매하다고 본다 — 0~1개뿐이면 고를 게 없으니 그대로 진행.

    단, 검색 결과가 완전히 못 걸러내더라도(예: "70mL 10개"로 좁혔는데도 검색
    결과에 30개입 페이지가 섞여 나옴) 사용자가 Human-in-the-loop으로 이미 답한
    기준은 다시 안 묻는다 — 질의 텍스트에 이미 용량/개수 스펙이 있으면 그
    차원은 애매함 판정에서 제외한다. 브랜드·제품도 후보 중 하나가 이미 질의에
    문자 그대로 들어있으면 같은 이유로 제외한다."""
    brand_resolved = any(b.casefold() in query.casefold() for b in options.brands)
    product_resolved = any(p.casefold() in query.casefold() for p in options.products)
    volume_resolved = has_volume_spec(query)
    quantity_resolved = has_count_spec(query)

    return (
        (len(options.brands) > 1 and not brand_resolved)
        or (len(options.products) > 1 and not product_resolved)
        or (len(options.volumes) > 1 and not volume_resolved)
        or (len(options.quantities) > 1 and not quantity_resolved)
    )


async def run_stream(query: str, skip_clarify: bool = False) -> AsyncIterator[dict[str, Any]]:
    """run()과 같은 결과를 만들지만, 단계마다 NDJSON 이벤트를 흘려보낸다 —
    debate.py::run_single_debate_stream이 그대로 재노출.

    skip_clarify(2026-08 통합 병합) - 프론트의 SearchContext.runTurn이 이미
    브랜드/facet/고정축 선택으로 한 라운드를 좁혀온 후속 턴이면 True로 넘어온다
    (main.py의 DecideRequest.skip_intent_check). 이게 없으면 검색 직후
    _is_ambiguous()가 이번 라운드에도 남아있는 다른 축(예: 브랜드는 답했는데
    용량이 여러 개)을 또 clarify로 멈춰세워, 사용자가 이미 몇 라운드나 답했는데도
    계속 새 선택 화면이 뜨는 재질문 버그가 생긴다 - True면 이 조기 종료를 건너뛰고
    바로 propose/challenge/judge까지 진행한다(완전히 후보가 0개면 아래의
    안전망 clarify는 skip_clarify와 무관하게 그대로 동작한다)."""
    from .debate import _extract_clarify_options  # 지연 임포트 — 순환 참조 방지

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
                if clarify is not None and not skip_clarify and _is_ambiguous(query, clarify.options):
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

    proposals = [Proposal(**p) for p in (final_state.get("proposals") or [])]

    if not proposals:
        search_results = _search_results_from_state(final_state)
        clarify = await _extract_clarify_options(query, search_results)
        if clarify is not None:
            yield {"type": "final", "result": clarify.model_dump()}
            return
        fallback_decision = await _relaxed_fallback_decision(query, search_results)
        if fallback_decision is not None:
            result = DecideResponse(query=query, proposals=[], decision=fallback_decision)
            yield {"type": "final", "result": result.model_dump()}
            return
        raise RuntimeError(NO_CANDIDATE_ERROR)

    decision = _build_decision(final_state, proposals)
    if decision is None:
        fallback_decision = await _relaxed_fallback_decision(query, _search_results_from_state(final_state))
        if fallback_decision is not None:
            result = DecideResponse(query=query, proposals=proposals, decision=fallback_decision)
            yield {"type": "final", "result": result.model_dump()}
            return
        raise RuntimeError(NO_CANDIDATE_ERROR)

    result = DecideResponse(query=query, proposals=proposals, decision=decision)
    yield {"type": "final", "result": result.model_dump()}


async def run(query: str, skip_clarify: bool = False) -> DecideResponse | ClarifyResponse:
    result_dict = None
    async for event in run_stream(query, skip_clarify=skip_clarify):
        if event["type"] == "final":
            result_dict = event["result"]
    if result_dict is None:
        raise RuntimeError(NO_CANDIDATE_ERROR)
    return _decide_result_adapter.validate_python(result_dict)
