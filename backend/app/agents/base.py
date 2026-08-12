import json
import re

from ..schemas import SearchResult

_GENERIC_LISTING_URL_PATTERN = re.compile(
    r"(search\?|dsearch\.php|/search\.|Gateway\.[a-z]+\?|/list\?cate="
    r"|[?&](q|query|prdid|code)=($|&|#))",
    re.IGNORECASE,
)


def is_generic_listing_url(url: str) -> bool:
    """검색/카테고리 목록 페이지처럼 특정 상품 하나를 가리키지 않는 URL인지 판별.
    프롬프트로 LLM에게 피하라고만 하면 종종 무시되므로, 응답을 받은 뒤 코드에서 한 번 더 걸러낸다."""
    return bool(_GENERIC_LISTING_URL_PATTERN.search(url))


NO_CANDIDATE_ERROR = "적절한 상품 후보를 찾지 못했습니다."


def filter_candidates(items: list, max_items: int = 3) -> list[dict]:
    """product_name이 비어 있거나 url이 일반 목록 페이지인 후보는 제외한다.
    개수를 억지로 채우지 않고, 유효한 후보만 에이전트가 제시한 선호 순서 그대로
    최대 max_items개까지 남긴다."""
    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if is_generic_listing_url(item.get("url") or ""):
            continue
        if not (item.get("product_name") or "").strip():
            continue
        filtered.append(item)
        if len(filtered) >= max_items:
            break
    return filtered


PRICE_CONFIDENCE_GUIDANCE = (
    "price는 검색 결과 텍스트에 그 상품 자체의 가격으로 명확히 숫자가 나와 있을 때만 적으세요. "
    "다른 용량/수량/판촉가와 헷갈리거나 정확한 숫자를 확신할 수 없으면 "
    "실제와 다른 가격을 적느니 price를 빈 문자열로 두세요."
)

PRICE_KRW_GUIDANCE = (
    "price_krw는 검색 결과 텍스트에 그 상품 자체의 가격으로 명확히 숫자가 나와 있을 때만, "
    "쉼표나 '원' 같은 문자 없이 순수 정수로 적으세요. "
    "다른 용량/수량/판촉가와 헷갈리거나 정확한 숫자를 확신할 수 없으면 "
    "실제와 다른 가격을 적느니 price_krw를 null로 두세요."
)

PROPOSAL_INSTRUCTIONS = (
    "당신은 쇼핑 후보를 조사해 상품을 추천하는 에이전트입니다. "
    "아래 검색 결과를 참고해 사용자의 질의에 적합한 상품 후보를 최대 3개까지, "
    "당신이 가장 적합하다고 판단하는 순서대로 배열에 담아 반환하세요. "
    "근거가 확실한 후보가 1개뿐이면 1개만 반환하세요 — 개수를 채우려고 "
    "억지 후보를 만들어내지 마세요. 같은 상품을 중복해서 넣지 마세요. "
    "반드시 아래 JSON 배열 형식으로만 답하세요. 다른 텍스트나 코드펜스를 덧붙이지 마세요.\n\n"
    '[{"product_name": "...", "price_krw": 12900, "retailer": "...", '
    '"url": "...", "reasoning": "..."}, ...]\n\n'
    "url은 반드시 아래 검색 결과에 나온 URL을 그대로(수정 없이) 복사해서 쓰세요. "
    "검색 결과에 없는 URL을 새로 만들어내지 마세요. "
    "검색창/카테고리 목록 같은 일반 검색 페이지(예: query= 뒤가 비어있는 URL, "
    "검색 결과 전체 목록 페이지)는 후보에서 아예 제외하세요. "
    "특정 상품 하나를 가리키는 상세 페이지 URL을 가진 항목만 후보로 삼으세요. "
    f"{PRICE_KRW_GUIDANCE} "
    "검색 결과가 없거나 적절한 상품을 찾을 수 없으면 빈 배열 []을 반환하세요."
)


BULK_PROPOSAL_INSTRUCTIONS = (
    "당신은 쇼핑 후보를 조사해 서로 다른 브랜드의 후보를 제안하는 에이전트입니다. "
    "아래 검색 결과를 참고해 사용자가 사려는 상품과 일치하는, 서로 다른 브랜드의 후보를 "
    "최대 {max_options}개까지 찾아 각 브랜드의 최저가로 제시하세요. "
    "반드시 아래 JSON 배열 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '[{{"brand": "...", "product_name": "...", "price": "...", "retailer": "...", "url": "...", '
    '"reasoning": "...", "delivery_note": "..."}}, ...]\n\n'
    "reasoning은 이 브랜드에서 왜 이 상품을 최저가 후보로 골랐는지 한두 문장으로 설명하세요. "
    "delivery_note는 검색 결과 텍스트에 로켓배송/당일출고/익일배송처럼 배송 소요 정보가 "
    "명시적으로 나와 있을 때만 그 표현을 그대로 적고, 없으면 빈 문자열로 두세요(지어내지 마세요). "
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


FACET_CLARIFY_INSTRUCTIONS = (
    "당신은 애매한 쇼핑 검색어를 몇 가지 기준(facet)으로 좁혀나가도록 돕는 에이전트입니다. "
    "사용자 질의가 여러 종류의 서로 다른 상품을 아우르는 넓은 카테고리 검색어라면"
    "(예: '음료수', '과자'), 아래 다나와 검색 결과 상품명들에 실제로 등장하는 정보를 "
    "바탕으로 사용자가 선택해 좁혀나갈 수 있는 기준을 최대 4개까지 뽑아주세요. 기준의 "
    "예시: 카테고리, 제조사, 브랜드, 시리즈, 모델, 용량, 용기형태, 특징 - 이 상품군에 "
    "실제로 의미 있는 기준만 고르세요(예: 전자기기류는 시리즈/모델/용량이, 식음료/생활용품류는 "
    "용기형태/특징이 더 유의미할 수 있습니다). '브랜드'나 '제조사' 기준은 상품명에 실제로 등장하는 서로 다른 "
    "브랜드를 최대 15개까지(적으면 있는 만큼만) 뽑고, 그 외 기준은 최대 6개까지 뽑아주세요. "
    "각 기준 안에서는 상품명 목록에 더 많이 등장하는(더 인기 있는) 값부터 먼저 오도록 "
    "순서대로 나열하세요. 상품명 전부가 사실상 같은 값 하나뿐인 기준(예: '핸드폰'을 "
    "검색했는데 카테고리가 전부 '스마트폰'인 경우)은 골라도 아무것도 안 좁혀지니 "
    "만들지 마세요 - 최소 서로 다른 값 2개 이상 있는 기준만 포함하세요. "
    "검색어가 이미 충분히 구체적인 상품 하나를 가리키고 있어 더 좁힐 필요가 없으면 "
    '빈 객체 {"facets": {}}를 반환하세요. '
    "실제로 아래 상품명들에 나온 값만 사용하고 지어내지 마세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트나 코드펜스를 덧붙이지 마세요.\n\n"
    '{"facets": {"카테고리": ["...", "..."], "브랜드": ["...", "..."]}}'
)


def build_facet_clarify_prompt(query: str, product_names: list[str]) -> str:
    names_block = "\n".join(f"- {n}" for n in product_names) or "(검색 결과 없음)"
    return f"{FACET_CLARIFY_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n다나와 검색 결과 상품명:\n{names_block}"


def build_facet_clarify_prompt_for_labels(
    query: str, product_names: list[str], labels: list[str]
) -> str:
    """브랜드별 facet 보강(app.debate._enrich_facets_per_brand, 2026-08-13:
    "APLLE 을 선택했을때 시리즈 후보가 너무 적어") 전용 - 브랜드 하나로 이미
    좁힌 상품명만 다시 보여주고, 라벨은 자유롭게 고르게 두지 않고 이미 정해진
    라벨 그대로만 쓰라고 강제한다. 안 그러면 같은 개념도 호출마다 "시리즈"/
    "모델"처럼 다르게 이름 붙여서, 나중에 라벨로 병합할 때 못 맞춘다."""
    names_block = "\n".join(f"- {n}" for n in product_names) or "(검색 결과 없음)"
    labels_block = ", ".join(labels)
    instructions = (
        "당신은 이미 특정 브랜드로 좁혀진 상품명 목록에서, 정해진 기준(facet)별로 "
        f"선택지를 뽑는 에이전트입니다. 반드시 다음 라벨만 그대로 써서 답하세요(새 "
        f"라벨을 만들거나 이름을 바꾸지 마세요): {labels_block}. 각 라벨마다 아래 "
        "상품명들에 실제로 등장하는 서로 다른 값을 최대 6개까지, 더 많이 등장하는 "
        "값부터 먼저 오도록 뽑으세요. 그 라벨에 해당하는 값이 상품명에 없으면 그 "
        "라벨은 아예 빼세요(빈 배열 넣지 마세요). 실제로 상품명에 나온 값만 쓰고 "
        "지어내지 마세요. 반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트나 "
        "코드펜스를 덧붙이지 마세요.\n\n"
        f'{{"facets": {{"{labels[0] if labels else "..."}": ["...", "..."]}}}}'
    )
    return f"{instructions}\n\n사용자 질의: {query}\n\n다나와 검색 결과 상품명:\n{names_block}"


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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def filter_bulk_options(options: list[dict], search_results: list[SearchResult]) -> list[dict]:
    """generic listing URL이거나 브랜드/상품명이 비어 있는 항목은 후보에서 제외한다.
    또한 brand가 실제로 그 url의 검색 결과(제목+본문)에 등장하지 않으면 제외한다 —
    검색 결과가 여러 개일 때 LLM이 다른 후보의 브랜드명을 엉뚱한 url에 붙이는
    매핑 오류가 가끔 있어, 응답을 받은 뒤 코드에서 한 번 더 근거를 확인한다."""
    url_text = {r.url: _normalize(r.title + r.snippet) for r in search_results}
    filtered = []
    for o in options:
        url = o.get("url") or ""
        brand = (o.get("brand") or "").strip()
        product_name = (o.get("product_name") or "").strip()
        if is_generic_listing_url(url) or not brand or not product_name:
            continue
        haystack = url_text.get(url)
        if haystack is not None and _normalize(brand) not in haystack:
            continue
        filtered.append(o)
    return filtered


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
