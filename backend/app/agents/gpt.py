from openai import AsyncOpenAI

from ..config import settings
from ..schemas import (
    BrandOption,
    BulkProposal,
    ClarifyOptions,
    SearchResult,
)
from .base import (
    build_brand_price_prompt,
    build_bulk_prompt,
    build_clarify_ask_prompt,
    build_clarify_match_prompt,
    build_clarify_prompt,
    filter_bulk_options,
    is_generic_listing_url,
    parse_json_array,
    parse_json_object,
)


async def propose_bulk(query: str, search_results: list[SearchResult]) -> BulkProposal:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_bulk_prompt(query, search_results)}],
        )
        options = parse_json_array(response.choices[0].message.content or "")
        options = filter_bulk_options(options, search_results)
        return BulkProposal(agent="gpt", options=options)
    except Exception as exc:
        return BulkProposal(agent="gpt", error=str(exc))


async def extract_options(query: str, search_results: list[SearchResult]) -> ClarifyOptions:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_clarify_prompt(query, search_results)}],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        return ClarifyOptions(**data)
    except Exception:
        return ClarifyOptions()


_CLARIFY_MATCH_FALLBACK_REPLY = "지금은 답장을 만들지 못했어요 — 아래 선택지 중에서 골라주시겠어요?"


async def match_clarify_reply(message: str, options: list[str]) -> tuple[str | None, str]:
    """채팅창에 타이핑한 자유 텍스트가 현재 clarify 선택지 중 뭘 가리키는지
    해석하고, 그 결과를 자연스러운 한국어 답장(reply)으로도 함께 받는다 — 봇의
    응답이 고정 문구가 아니라 실제 LLM이 그때그때 생성한 문장이 되도록.
    확신 없으면(또는 호출 자체가 실패하면) matched=None — 호출부는 이걸
    "선택 실패"로 보고 프론트에서 다시 물어봐야 한다(버튼은 항상 그대로 남아있어
    안전한 대체 경로가 있다). 실패 시 reply는 고정 안내 문구로 대체한다."""
    if not options:
        return None, _CLARIFY_MATCH_FALLBACK_REPLY
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_clarify_match_prompt(message, options)}],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        matched = data.get("matched")
        matched = matched if matched in options else None
        reply = data.get("reply") or _CLARIFY_MATCH_FALLBACK_REPLY
        return matched, reply
    except Exception:
        return None, _CLARIFY_MATCH_FALLBACK_REPLY


_CLARIFY_ASK_FALLBACK = "몇 가지 후보를 찾았어요 — 아래에서 골라주시겠어요?"


async def generate_clarify_question(query: str, options: list[str]) -> str:
    """이번 라운드에 물어봐야 할 축(브랜드/제품/용량/개수)의 후보들을 실제
    상담원처럼 자연스러운 한 질문으로 바꾼다 — 프론트가 "브랜드를 선택하면
    좁혀드려요" 같은 고정 라벨 대신 이 문장을 채팅 말풍선으로 보여준다.
    호출 실패 시 고정 안내 문구로 대체한다."""
    if not options:
        return _CLARIFY_ASK_FALLBACK
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[{"role": "user", "content": build_clarify_ask_prompt(query, options)}],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        return data.get("message") or _CLARIFY_ASK_FALLBACK
    except Exception:
        return _CLARIFY_ASK_FALLBACK


async def find_lowest_price(
    query: str, brand: str, search_results: list[SearchResult]
) -> BrandOption | None:
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.gpt_model,
            messages=[
                {"role": "user", "content": build_brand_price_prompt(query, brand, search_results)}
            ],
            response_format={"type": "json_object"},
        )
        data = parse_json_object(response.choices[0].message.content or "")
        if not data.get("product_name"):
            return None
        if is_generic_listing_url(data.get("url", "")):
            return None
        return BrandOption(brand=brand, **data)
    except Exception:
        return None
