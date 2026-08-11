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
    """product_name이나 url이 비어 있거나, url이 일반 목록 페이지인 후보는
    제외한다. url이 빈 후보를 그대로 통과시키면, 실제로 살 수 있는 페이지가
    없는 후보가 병합/심사까지 흘러가 judge가 존재하지 않는 URL을 스스로
    지어내 채우는 문제가 생긴다 — 근거가 확실하지 않으면 애초에 후보를
    반환하지 말라고 프롬프트에도 적혀 있지만, 코드에서 한 번 더 걸러낸다.
    개수를 억지로 채우지 않고, 유효한 후보만 에이전트가 제시한 선호 순서 그대로
    최대 max_items개까지 남긴다."""
    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        if not url or is_generic_listing_url(url):
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
    "아래 검색 결과를 참고해 사용자의 질의에 적합한 상품 후보를 최대 10개까지, "
    "당신이 가장 적합하다고 판단하는 순서대로 배열에 담아 반환하세요. "
    "근거가 확실한 후보가 1개뿐이면 1개만 반환하세요 — 개수를 채우려고 "
    "억지 후보를 만들어내지 마세요. 같은 상품을 중복해서 넣지 마세요. "
    "질의에 브랜드·용량·개수가 구체적으로 명시돼 있다면(예: '메로나 빙그레 70mL 10개') "
    "그 값과 명확히 일치하는 후보만 남기세요 — 브랜드만 맞고 용량이나 개수가 "
    "다른 상품(예: 70mL를 찾는데 80mL만 있는 상품)은 후보에서 제외하세요. "
    "질의에 명시되지 않은 항목은 자유롭게 골라도 됩니다. "
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


def format_results_block(search_results: list[SearchResult]) -> str:
    return (
        "\n".join(f"- {r.title} ({r.url}): {r.snippet}" for r in search_results)
        or "(검색 결과 없음)"
    )


def build_prompt(query: str, search_results: list[SearchResult]) -> str:
    results_block = format_results_block(search_results)
    return f"{PROPOSAL_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


def build_bulk_prompt(query: str, search_results: list[SearchResult], max_options: int = 5) -> str:
    results_block = format_results_block(search_results)
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
    results_block = format_results_block(search_results)
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
    results_block = format_results_block(search_results)
    instructions = BRAND_PRICE_INSTRUCTIONS.format(brand=brand)
    return f"{instructions}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


REFINE_QUERY_INSTRUCTIONS = (
    "당신은 사용자의 쇼핑 검색어를 실제 쇼핑몰 검색에 더 유리하게 다듬는 에이전트입니다. "
    "질의가 이미 구체적이면(브랜드·모델명·용량 등이 명확하면) 그대로 반환하세요. "
    "모호한 표현(예: '그거', '요즘 유행하는')이 있으면 검색어에서 제거하고, "
    "질의에 이미 암시된 브랜드·스펙·용량이 있다면 명시적인 키워드로 풀어 쓰세요. "
    "검색어에 없는 브랜드나 상품 정보를 새로 지어내지 마세요 — 원래 의미를 벗어나면 안 됩니다. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"query": "..."}'
)


def build_refine_query_prompt(query: str) -> str:
    return f"{REFINE_QUERY_INSTRUCTIONS}\n\n사용자 질의: {query}"


CHALLENGE_INSTRUCTIONS = (
    "당신은 다른 에이전트들이 제안한 쇼핑 후보를 비판적으로 검증하는 에이전트입니다. "
    "아래 후보 목록과 검색 결과를 비교해 각 후보를 두 기준으로 판단하세요: "
    "(1) 그라운딩 — 검색 결과 텍스트에 실제로 나오지 않는 가격/상품 정보를 지어내지 않았는지, "
    "(2) 정체성 일치 — 그 후보가 사용자 질의가 찾는 상품(브랜드·용량·개수를 포함한 스펙)과 "
    "실제로 일치하는지. 특히 질의에 용량이나 개수가 숫자로 구체적으로 적혀 있다면(예: "
    "'70mL 10개') 후보의 용량·개수가 그 숫자와 정확히 같은지 반드시 확인하세요 — "
    "브랜드와 상품명은 맞아도 용량이나 개수가 다르면(예: 70mL를 찾는데 후보가 80mL) "
    "verified를 false로 표시하고 note에 어떤 값이 다른지 적으세요. "
    "애매하거나 확신이 서지 않으면 verified를 false로 남발하지 말고, "
    "명백히 근거가 없거나 질의와 무관한 경우에만 false로 표시하세요. "
    "일부 후보에는 '실제 페이지 재조회 원문'이 함께 제공됩니다 — 이는 검색 당시 "
    "잘린 스니펫보다 더 최신이고 완전한 정보이므로, 스니펫과 내용이 다르면 "
    "재조회 원문을 우선 신뢰해 판단하세요. "
    "반드시 입력된 후보와 같은 개수, 같은 순서로 아래 JSON 배열 형식으로만 답하세요. "
    "다른 텍스트나 코드펜스를 덧붙이지 마세요.\n\n"
    '[{"url": "...", "verified": true, "note": "..."}, ...]\n\n'
    "note는 검증 근거를 한 문장으로 설명하세요(통과든 우려든)."
)


def _format_candidates_block(candidates: list, candidate_pages: dict[str, str] | None = None) -> str:
    candidate_pages = candidate_pages or {}
    lines = []
    for i, c in enumerate(candidates, start=1):
        product_name = getattr(c, "product_name", None) or (c.get("product_name") if isinstance(c, dict) else None)
        price_krw = getattr(c, "price_krw", None) if not isinstance(c, dict) else c.get("price_krw")
        retailer = getattr(c, "retailer", None) if not isinstance(c, dict) else c.get("retailer")
        url = getattr(c, "url", None) if not isinstance(c, dict) else c.get("url")
        reasoning = getattr(c, "reasoning", None) if not isinstance(c, dict) else c.get("reasoning")
        page_text = candidate_pages.get(url) if url else None
        page_block = f"\n    실제 페이지 재조회 원문: {page_text[:2000]}" if page_text else ""
        lines.append(
            f"[{i}] 상품: {product_name} / 가격: {price_krw} / 판매처: {retailer} / "
            f"URL: {url} / 제안 근거: {reasoning}{page_block}"
        )
    return "\n".join(lines) or "(후보 없음)"


def build_challenge_prompt(
    query: str,
    candidates: list,
    search_results: list[SearchResult],
    candidate_pages: dict[str, str] | None = None,
) -> str:
    candidates_block = _format_candidates_block(candidates, candidate_pages)
    results_block = format_results_block(search_results)
    return (
        f"{CHALLENGE_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n"
        f"검증할 후보:\n{candidates_block}\n\n검색 결과:\n{results_block}"
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
