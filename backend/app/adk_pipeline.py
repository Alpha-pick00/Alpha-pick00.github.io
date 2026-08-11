"""ADK(Google Agent Development Kit) 기반 역할 분리형 검색 파이프라인.

정제(Gemini) → 검색 → 제안(GPT·Gemini·DeepSeek 병렬, 각자 최대 10개) →
필터링+병합(fusion.dedup 재사용) → 검증(DeepSeek) → 매칭/합성 → 심사(Claude)
순서로 실행된다 — `debate.py`의 run_single_debate/run_single_debate_stream이
이 모듈의 run()/run_stream()을 호출한다.

SequentialAgent/ParallelAgent는 google-adk 2.6.3 기준 deprecated(대체 예정인
Workflow가 아직 LlmAgent의 sub-agent로 못 쓰여 미완성 상태)이지만, 실제로는
정상 동작함을 스파이크로 검증했다 — Workflow가 성숙하면 마이그레이션 대상.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator, AsyncIterator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import TypeAdapter

from . import search as search_module
from .agents import judge as judge_module
from .intent import has_count_spec, has_volume_spec
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
_MAX_CANDIDATES_PER_AGENT = 10


def _format_price_krw(price_krw: int | None) -> str:
    return f"{price_krw:,}원" if price_krw is not None else ""


def _search_results_from_state(state: dict) -> list[SearchResult]:
    return [SearchResult(**r) for r in state.get("search_results") or []]


def _refined_query_text(state: dict) -> str:
    refined = state.get("refined_query")
    if isinstance(refined, dict) and refined.get("query"):
        return refined["query"]
    return state.get("original_query", "")


# ---------------------------------------------------------------------------
# 커스텀(순수 Python) 노드 — LLM 호출 없이 상태만 읽고 쓴다.
# ---------------------------------------------------------------------------


class _SearchNode(BaseAgent):
    """정제된 질의로 search_module.search()를 호출해 원본 결과 + 프롬프트용
    포맷 텍스트를 상태에 저장한다."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        query = _refined_query_text(ctx.session.state)
        try:
            results = await search_module.search(query, max_results=_MAX_SEARCH_RESULTS)
        except Exception:
            logger.exception("검색 실패: %r", query)
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


class _ApplyChallengeNode(BaseAgent):
    """DeepSeek의 검증 결과를 병합된 후보와 매칭해 최종 Proposal 목록을 만든다 —
    URL 우선, 실패 시 인덱스로 폴백(LLM이 순서를 흐트러뜨릴 가능성에 대비)."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        candidates: list[dict] = state.get("candidates") or []
        raw_challenge = state.get("raw_challenge")

        verdicts: list[ChallengeVerdict] = []
        if raw_challenge:
            try:
                verdicts = [ChallengeVerdict(**v) for v in parse_json_array(raw_challenge)]
            except Exception:
                logger.exception("DeepSeek 검증 결과 파싱 실패 — 전부 미검증으로 진행")

        proposals = _apply_challenge(candidates, ChallengeResult(verdicts=verdicts))

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"proposals": [p.model_dump() for p in proposals]}),
        )


def _apply_challenge(candidates: list[dict], challenge: ChallengeResult) -> list[Proposal]:
    """병합된 후보(merge_candidates 출력 dict)와 검증 결과를 매칭해 Proposal로
    합성하는 순수 함수 — LLM 호출 없이 테스트 가능."""
    verdicts_by_url = {v.url: v for v in challenge.verdicts if v.url}

    proposals = []
    for i, candidate in enumerate(candidates):
        verdict = verdicts_by_url.get(candidate.get("url"))
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
# ---------------------------------------------------------------------------


def _build_refine_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        return build_refine_query_prompt(ctx.state.get("original_query", ""))

    return LlmAgent(
        name="refine",
        model=settings.gemini_model,  # 네이티브 Gemini — LiteLlm 불필요
        instruction=instruction,
        output_schema=RefinedQuery,
        output_key="refined_query",
    )


def _build_propose_agent(name: str, model) -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        results = _search_results_from_state(ctx.state)
        return build_prompt(query, results)

    return LlmAgent(name=name, model=model, instruction=instruction, output_key=f"{name}_raw")


def _build_challenge_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        candidates = ctx.state.get("candidates") or []
        results = _search_results_from_state(ctx.state)
        return build_challenge_prompt(query, candidates, results)

    return LlmAgent(
        name="challenge",
        model=LiteLlm(model=f"deepseek/{settings.deepseek_model}"),
        instruction=instruction,
        output_key="raw_challenge",
    )


def _build_judge_agent() -> LlmAgent:
    def instruction(ctx: ReadonlyContext) -> str:
        query = _refined_query_text(ctx.state)
        proposals = [Proposal(**p) for p in (ctx.state.get("proposals") or [])]
        return judge_module.build_judge_prompt(query, proposals)

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
            _build_propose_agent(gpt_raw, LiteLlm(model=f"openai/{settings.gpt_model}")),
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
    raw = state.get("raw_decision")
    if not raw or not proposals:
        return None

    url = raw.get("url")
    matched = next((p for p in proposals if p.url and p.url == url), None) or proposals[0]

    return Decision(
        product_name=raw.get("product_name") or matched.product_name or "",
        price=raw.get("price") or matched.price or "",
        retailer=raw.get("retailer") or matched.retailer or "",
        url=raw.get("url") or matched.url or "",
        reasoning=raw.get("reasoning") or "",
        chosen_agent=matched.agent,
    )


def _is_ambiguous(query: str, options: ClarifyOptions) -> bool:
    """브랜드/용량/개수 중 하나라도 2개 이상이면 사용자에게 물어볼 만큼 애매하다고
    본다 — 0~1개뿐이면 고를 게 없으니 그대로 진행.

    단, 검색 결과가 완전히 못 걸러내더라도(예: "70mL 10개"로 좁혔는데도 검색
    결과에 30개입 페이지가 섞여 나옴) 사용자가 Human-in-the-loop으로 이미 답한
    기준은 다시 안 묻는다 — 질의 텍스트에 이미 용량/개수 스펙이 있으면 그
    차원은 애매함 판정에서 제외한다. 브랜드도 후보 중 하나가 이미 질의에
    문자 그대로 들어있으면 같은 이유로 제외한다."""
    brand_resolved = any(b.casefold() in query.casefold() for b in options.brands)
    volume_resolved = has_volume_spec(query)
    quantity_resolved = has_count_spec(query)

    return (
        (len(options.brands) > 1 and not brand_resolved)
        or (len(options.volumes) > 1 and not volume_resolved)
        or (len(options.quantities) > 1 and not quantity_resolved)
    )


async def run_stream(query: str) -> AsyncIterator[dict[str, Any]]:
    """run()과 같은 결과를 만들지만, 단계마다 NDJSON 이벤트를 흘려보낸다 —
    debate.py::run_single_debate_stream이 그대로 재노출."""
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
                if clarify is not None and _is_ambiguous(query, clarify.options):
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
        raise RuntimeError(NO_CANDIDATE_ERROR)

    decision = _build_decision(final_state, proposals)
    if decision is None:
        raise RuntimeError(NO_CANDIDATE_ERROR)

    result = DecideResponse(query=query, proposals=proposals, decision=decision)
    yield {"type": "final", "result": result.model_dump()}


async def run(query: str) -> DecideResponse | ClarifyResponse:
    result_dict = None
    async for event in run_stream(query):
        if event["type"] == "final":
            result_dict = event["result"]
    if result_dict is None:
        raise RuntimeError(NO_CANDIDATE_ERROR)
    return _decide_result_adapter.validate_python(result_dict)
