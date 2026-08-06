import json
import re

from ..schemas import SearchResult

_GENERIC_LISTING_URL_PATTERN = re.compile(
    r"(search\?|dsearch\.php|/search\.|Gateway\.[a-z]+\?|[?&](q|query|prdid)=($|&|#))",
    re.IGNORECASE,
)


def is_generic_listing_url(url: str) -> bool:
    """검색/카테고리 목록 페이지처럼 특정 상품 하나를 가리키지 않는 URL인지 판별.
    프롬프트로 LLM에게 피하라고만 하면 종종 무시되므로, 응답을 받은 뒤 코드에서 한 번 더 걸러낸다."""
    return bool(_GENERIC_LISTING_URL_PATTERN.search(url))


NO_CANDIDATE_ERROR = "적절한 상품 후보를 찾지 못했습니다."


def proposal_data_or_error(data: dict) -> dict:
    """product_name이 비어 있거나 url이 일반 목록 페이지면 빈 필드 그대로 두지 말고
    error로 표시한다. 그래야 judge가 내용 없는 제안을 실제 후보처럼 다루지 않는다."""
    if is_generic_listing_url(data.get("url") or ""):
        return {"error": NO_CANDIDATE_ERROR}
    if not (data.get("product_name") or "").strip():
        return {"error": NO_CANDIDATE_ERROR}
    return data


PRICE_CONFIDENCE_GUIDANCE = (
    "price는 검색 결과 텍스트에 그 상품 자체의 가격으로 명확히 숫자가 나와 있을 때만 적으세요. "
    "다른 용량/수량/판촉가와 헷갈리거나 정확한 숫자를 확신할 수 없으면 "
    "실제와 다른 가격을 적느니 price를 빈 문자열로 두세요."
)

PROPOSAL_INSTRUCTIONS = (
    "당신은 쇼핑 후보를 조사해 하나의 상품을 추천하는 에이전트입니다. "
    "아래 검색 결과를 참고해 사용자의 질의에 가장 적합한 상품 하나를 고르고, "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", "reasoning": "..."}\n\n'
    "url은 반드시 아래 검색 결과에 나온 URL을 그대로(수정 없이) 복사해서 쓰세요. "
    "검색 결과에 없는 URL을 새로 만들어내지 마세요. "
    "검색창/카테고리 목록 같은 일반 검색 페이지(예: query= 뒤가 비어있는 URL, "
    "검색 결과 전체 목록 페이지)는 후보에서 아예 제외하세요. "
    "특정 상품 하나를 가리키는 상세 페이지 URL을 가진 항목만 후보로 삼으세요. "
    f"{PRICE_CONFIDENCE_GUIDANCE} "
    "검색 결과가 없거나 적절한 상품을 찾을 수 없으면 모든 필드를 빈 문자열로 두세요."
)


BULK_PROPOSAL_INSTRUCTIONS = (
    "당신은 쇼핑 후보를 조사해 서로 다른 브랜드의 후보를 제안하는 에이전트입니다. "
    "아래 검색 결과를 참고해 사용자가 사려는 상품과 일치하는, 서로 다른 브랜드의 후보를 "
    "최대 {max_options}개까지 찾아 각 브랜드의 최저가로 제시하세요. "
    "반드시 아래 JSON 배열 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '[{{"brand": "...", "product_name": "...", "price": "...", "retailer": "...", "url": "..."}}, ...]\n\n'
    "url은 반드시 아래 검색 결과에 나온 URL을 그대로(수정 없이) 복사해서 쓰세요. "
    "검색 결과에 없는 URL을 새로 만들어내지 마세요. "
    "검색창/카테고리 목록 같은 일반 검색 페이지(예: query= 뒤가 비어있는 URL, "
    "검색 결과 전체 목록 페이지)는 후보에서 아예 제외하세요. "
    "특정 상품 하나를 가리키는 상세 페이지 URL을 가진 항목만 후보로 삼으세요. "
    f"{PRICE_CONFIDENCE_GUIDANCE} "
    "검색 결과에서 적절한 브랜드를 찾을 수 없으면 빈 배열 []을 반환하세요."
)


def _format_results_block(search_results: list[SearchResult]) -> str:
    return (
        "\n".join(f"- {r.title} ({r.url}): {r.snippet}" for r in search_results)
        or "(검색 결과 없음)"
    )


def build_prompt(query: str, search_results: list[SearchResult]) -> str:
    results_block = _format_results_block(search_results)
    return f"{PROPOSAL_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


def build_bulk_prompt(query: str, search_results: list[SearchResult], max_options: int = 5) -> str:
    results_block = _format_results_block(search_results)
    instructions = BULK_PROPOSAL_INSTRUCTIONS.format(max_options=max_options)
    return f"{instructions}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


CLARIFY_INSTRUCTIONS = (
    "당신은 검색 결과에서 실제 판매 중인 상품의 옵션을 추출하는 에이전트입니다. "
    "아래 검색 결과에 등장하는 서로 다른 브랜드, 용량(ml/L 등), 판매 단위(묶음 개수)를 "
    "각각 목록으로 뽑아주세요. 실제로 검색 결과에 나온 값만 사용하고 지어내지 마세요. "
    "찾을 수 없으면 해당 목록을 빈 배열로 두세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"brands": ["..."], "volumes": ["..."], "quantities": ["..."]}'
)


def build_clarify_prompt(query: str, search_results: list[SearchResult]) -> str:
    results_block = _format_results_block(search_results)
    return f"{CLARIFY_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


BRAND_PRICE_INSTRUCTIONS = (
    "당신은 검색 결과에서 특정 브랜드 상품의 최저가를 찾는 에이전트입니다. "
    '아래 검색 결과에서 "{brand}" 브랜드의 상품 중 가장 저렴한 것 하나만 찾아 '
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{{"product_name": "...", "price": "...", "retailer": "...", "url": "..."}}\n\n'
    "url은 반드시 검색 결과에 나온 URL을 그대로(수정 없이) 복사해서 쓰세요. "
    "검색 결과에 없는 URL을 새로 만들어내지 마세요. "
    "검색창/카테고리 목록 같은 일반 검색 페이지(예: query= 뒤가 비어있는 URL, "
    "검색 결과 전체 목록 페이지)는 후보에서 아예 제외하세요. "
    "특정 상품 하나를 가리키는 상세 페이지 URL을 가진 항목만 후보로 삼으세요. "
    f"{PRICE_CONFIDENCE_GUIDANCE} "
    '"{brand}" 브랜드의 상품 상세 페이지가 검색 결과에 없으면 모든 필드를 빈 문자열로 두세요.'
)


def build_brand_price_prompt(query: str, brand: str, search_results: list[SearchResult]) -> str:
    results_block = _format_results_block(search_results)
    instructions = BRAND_PRICE_INSTRUCTIONS.format(brand=brand)
    return f"{instructions}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


PRICE_CONFIRM_INSTRUCTIONS = (
    "당신은 상품 상세 페이지의 전체 본문에서 실제 판매 가격을 확인하는 에이전트입니다. "
    "아래는 특정 상품 페이지 하나의 전체 텍스트입니다. 이 페이지에 실제로 표시된 "
    "최종 판매 가격(할인이 적용된 결제 가격)을 찾아 반드시 아래 JSON 형식으로만 답하세요. "
    "다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"price": "...", "product_name": "..."}\n\n'
    "product_name은 페이지에 나온 정확한 상품명으로 다시 채우세요. "
    "페이지 본문에서 가격을 명확히 찾을 수 없으면 price를 빈 문자열로 두세요."
)


def build_price_confirm_prompt(product_name: str, page_content: str) -> str:
    return (
        f"{PRICE_CONFIRM_INSTRUCTIONS}\n\n"
        f"기존에 파악한 상품명: {product_name}\n\n"
        f"페이지 전체 텍스트:\n{page_content[:6000]}"
    )


def filter_bulk_options(options: list[dict]) -> list[dict]:
    """generic listing URL이거나 브랜드/상품명이 비어 있는 항목은 후보에서 제외한다."""
    return [
        o
        for o in options
        if not is_generic_listing_url(o.get("url") or "")
        and (o.get("brand") or "").strip()
        and (o.get("product_name") or "").strip()
    ]


def parse_json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(match.group(0))


def parse_json_array(text: str) -> list:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in response: {text[:200]!r}")
    return json.loads(match.group(0))
