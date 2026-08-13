import re

from openai import AsyncOpenAI

from ..config import settings
from ..schemas import AgentCandidate, AgentCandidates, BulkProposal, ClarifyFacet, SearchResult
from .base import (
    build_bulk_prompt,
    build_facet_clarify_prompt,
    build_facet_clarify_prompt_for_labels,
    build_prompt,
    filter_bulk_options,
    filter_candidates,
    parse_json_array,
    parse_json_object,
)

# DeepSeek은 OpenAI 호환 API라 openai SDK를 base_url만 바꿔서 그대로 쓴다.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=DEEPSEEK_BASE_URL)


async def propose(query: str, search_results: list[SearchResult]) -> AgentCandidates:
    """PRESERVED FROM seungmin/lsm - run_single_debate_price_table_variant
    (app.debate)에서만 쓰인다. run_debate()의 실제 LLM 경로는 adk_pipeline이
    담당하며 거기서는 propose 단계가 LlmAgent로 이미 구현돼 있다."""
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": build_prompt(query, search_results)}],
        )
        items = parse_json_array(response.choices[0].message.content or "")
        items = filter_candidates(items)
        return AgentCandidates(agent="deepseek", candidates=[AgentCandidate(**i) for i in items])
    except Exception as exc:
        return AgentCandidates(agent="deepseek", error=str(exc))


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = _client()
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": build_bulk_prompt(query, search_results)}],
        )
        options = parse_json_array(response.choices[0].message.content or "")
        options = filter_bulk_options(options, search_results)
        return BulkProposal(agent="deepseek", options=options)
    except Exception as exc:
        return BulkProposal(agent="deepseek", error=str(exc))


MAX_FACETS = 4
MAX_OPTIONS_PER_FACET = 6
# "브랜드"/"제조사" 기준은 사용자 요청(2026-08-12: "브랜드가 2,3개 정도만 뜨는데
# ... 찾기 기능도 있었으면")으로 다른 기준보다 훨씬 넓게 보여준다 - 프론트에
# 검색으로 걸러볼 수 있는 입력창을 붙였으니(SearchResults.tsx) 잘라내기 상한을
# 낮게 둘 이유가 없다.
MAX_BRAND_OPTIONS = 15
_BRAND_LABEL_PATTERN = re.compile(r"브랜드|제조사")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _sort_by_popularity(options: list[str], product_names: list[str]) -> list[str]:
    """LLM이 알려준 순서를 믿지 않고, 실제 상품명 목록에서 각 값이 몇 번
    등장하는지(부분 문자열 포함) 직접 세어 내림차순으로 다시 정렬한다 -
    "인기순 정렬" 요청(2026-08-12)의 실제 근거가 LLM의 자기 진술이 아니라
    검색 결과 자체가 되도록. 동률(count 같음)이면 원래 순서를 유지한다
    (sort는 stable)."""
    normalized_names = [_normalize(n) for n in product_names]
    counts = {
        option: sum(1 for name in normalized_names if _normalize(option) in name)
        for option in options
    }
    return sorted(options, key=lambda o: counts[o], reverse=True)


async def extract_facets_from_names(
    query: str, product_names: list[str], required_labels: list[str] | None = None
) -> list[ClarifyFacet]:
    """다나와 검색 결과 상품명 목록만 보고, 검색어를 좁혀나갈 수 있는 기준(facet)을
    뽑아낸다(AI 상세검색, 2026-08-12 - 원래 Qwen으로 붙였다가 Model Studio 계정
    쪽 과금 플랜 활성화 문제로 이미 키가 있고 바로 되는 DeepSeek로 옮겼다).
    실패하거나(API 오류, JSON 파싱 실패 등) 아무 기준도 못 찾으면 조용히 빈
    리스트를 반환한다 - 호출자(app.debate.check_clarify_facets)가 "상세검색이
    필요 없다"와 동일하게 취급해 그대로 원래 검색 경로로 넘어간다.

    required_labels(2026-08-13, app.debate._enrich_facets_per_brand 전용) - 주어지면
    라벨을 자유롭게 고르게 두지 않고 정확히 이 라벨들만 쓰라고 프롬프트로 강제한다.
    브랜드별로 상품명을 좁혀 다시 부를 때, 매 호출마다 같은 개념을 "시리즈"/"모델"처럼
    다르게 이름 붙이면 나중에 라벨로 병합할 수 없어서다 - 그래도 모델이 지시를 어기고
    다른 라벨을 낼 수 있으니, 응답에서도 required_labels에 없는 라벨은 걸러낸다."""
    if not product_names:
        return []
    try:
        client = _client()
        prompt = (
            build_facet_clarify_prompt_for_labels(query, product_names, required_labels)
            if required_labels
            else build_facet_clarify_prompt(query, product_names)
        )
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": prompt}],
        )
        data = parse_json_object(response.choices[0].message.content or "")
        allowed_labels = set(required_labels) if required_labels else None
        facets: list[ClarifyFacet] = []
        for label, options in (data.get("facets") or {}).items():
            if allowed_labels is not None and str(label) not in allowed_labels:
                continue
            if not isinstance(options, list):
                continue
            cleaned = [str(o).strip() for o in options if str(o).strip()]
            if not cleaned:
                continue
            if allowed_labels is None and len(set(cleaned)) < 2:
                # 값이 하나뿐인 기준(예: "핸드폰" 검색에 "카테고리: 스마트폰")은
                # 골라도 아무것도 안 좁혀지니 물어볼 이유가 없다(사용자 요청,
                # 2026-08-13: "카테고리에 스마트폰은 있으면 안되고"). required_labels가
                # 있는 브랜드별 재추출에서는 적용 안 한다 - 그 브랜드가 그 기준에서
                # 값이 하나뿐이어도(예: APPLE 시리즈가 1개), 다른 브랜드 값과 합쳐질
                # 옵션이라 여전히 쓸모 있다.
                continue
            cleaned = _sort_by_popularity(cleaned, product_names)
            cap = MAX_BRAND_OPTIONS if _BRAND_LABEL_PATTERN.search(str(label)) else MAX_OPTIONS_PER_FACET
            facets.append(ClarifyFacet(label=str(label), options=cleaned[:cap]))
        return facets[:MAX_FACETS]
    except Exception:
        return []
