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
    "아래 검색 결과를 참고해 사용자의 질의에 적합한 상품 후보를 최대 5개까지, "
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
    "아래 검색 결과에 등장하는 서로 다른 브랜드, 제품/모델명, 용량(ml/L 등), "
    "판매 단위(묶음 개수)를 각각 목록으로 뽑아주세요. "
    "products는 브랜드가 아니라 그 브랜드 안에서, 사용자가 질의한 상품과 같은 "
    "종류의 서로 다른 제품 라인/모델명입니다 (예: 질의가 '빙그레 아이스크림'이면 "
    "브랜드 '빙그레' 안에 '메로나', '비비빅', '투게더'처럼 서로 다른 아이스크림이 "
    "섞여 있는 경우). 검색 결과 페이지에 사이드바 추천/함께 본 상품처럼 질의와 "
    "다른 종류의 상품(예: 이어폰을 찾는데 냉장고·모니터·시계가 섞여 있는 경우)이 "
    "함께 나오더라도, 그런 무관한 카테고리 상품은 products에 절대 넣지 마세요 — "
    "질의와 같은 종류의 상품만 뽑으세요. 한 브랜드에 제품이 하나뿐이면 products는 "
    "빈 배열로 두세요 — 브랜드명과 똑같은 값을 억지로 넣지 마세요. "
    "실제로 검색 결과에 나온 값만 사용하고 지어내지 마세요. "
    "찾을 수 없으면 해당 목록을 빈 배열로 두세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"brands": ["..."], "products": ["..."], "volumes": ["..."], "quantities": ["..."]}'
)


def build_clarify_prompt(query: str, search_results: list[SearchResult]) -> str:
    results_block = format_results_block(search_results)
    return f"{CLARIFY_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


CLARIFY_MATCH_INSTRUCTIONS = (
    "당신은 쇼핑 검색을 도와주는 챗봇입니다. 사용자가 채팅창에 자유롭게 입력한 "
    "문장이 아래 선택지 중 어떤 것을 가리키는지 판단하고, 그 결과를 사용자에게 "
    "짧고 자연스러운 한국어로 답장하세요. "
    "matched는 선택지 목록에 있는 문자열과 정확히 동일한 값이거나 null입니다. "
    "\"제일 싼 걸로\", \"그거 말고 다른 거\" 같은 간접적인 표현이어도 의미상 가장 "
    "맞는 선택지를 고르세요. 여러 개와 애매하게 겹치거나 선택지와 전혀 무관한 "
    "말이면 matched를 null로 두세요. 목록에 없는 새 값을 만들어내지 마세요. "
    "reply는 실제 챗봇과 대화하듯 한두 문장으로 쓰세요 — matched를 찾았으면 "
    "그 선택을 자연스럽게 확인하는 말을, null이면 다시 골라달라고 선택지를 "
    "참고해 부드럽게 안내하는 말을 쓰세요. 매번 같은 문구를 기계적으로 반복하지 "
    "말고 사용자가 입력한 표현에 맞춰 조금씩 다르게 표현하세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"matched": "..." 또는 null, "reply": "..."}'
)


def build_clarify_match_prompt(message: str, options: list[str]) -> str:
    options_block = "\n".join(f"- {o}" for o in options)
    return f"{CLARIFY_MATCH_INSTRUCTIONS}\n\n사용자 입력: {message}\n\n선택지:\n{options_block}"


CLARIFY_ASK_INSTRUCTIONS = (
    "당신은 쇼핑을 도와주는 챗봇입니다. 사용자가 검색한 상품 중 아래 후보들 중 "
    "어떤 걸 찾는지 확인이 필요합니다. 후보 목록을 그대로 나열하거나 \"~를 "
    "선택하세요\" 같은 딱딱한 안내문 대신, 실제 상담원이 대화하듯 자연스러운 "
    "한두 문장으로 물어보세요 — 후보 중 몇 가지를 예시로 자연스럽게 언급해도 "
    "좋습니다. 매번 표현을 다르게 해서 기계적으로 반복하지 마세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"message": "..."}'
)


def build_clarify_ask_prompt(query: str, options: list[str]) -> str:
    options_block = "\n".join(f"- {o}" for o in options)
    return f"{CLARIFY_ASK_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n후보:\n{options_block}"


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
    results_block = format_results_block(search_results)
    instructions = BRAND_PRICE_INSTRUCTIONS.format(brand=brand)
    return f"{instructions}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


# 완전 일치 후보가 하나도 없을 때의 폴백 경로(2026-08-15, "적절한 상품 후보를
# 찾지 못하면 다시 fallback해서 feedback 구조로 돌아가서 가장 관련성 높은
# 상품을 추천해주는 시스템") - PROPOSAL_INSTRUCTIONS/CLARIFY_INSTRUCTIONS는
# 브랜드/스펙이 정확히 일치하지 않으면 후보를 아예 비워서 반환하도록 요구한다
# (그라운딩 - 존재하지 않는 상품을 지어내지 않기 위함). 이 프롬프트는 딱 그
# 엄격함만 완화해 "정확히 일치하진 않아도 검색 결과 중 가장 관련성 높은 것
# 하나"를 고르게 한다 - 여전히 실제로 검색 결과에 있는 상품만 골라야 하고
# (지어내기는 금지), 왜 완벽히 일치하지 않는지를 reasoning에 반드시 밝히게
# 해서 UI가 "낮은 확신" 캐비어로 그대로 보여줄 수 있게 한다.
RELAXED_PICK_INSTRUCTIONS = (
    "당신은 쇼핑 검색을 돕는 에이전트입니다. 아래 검색 결과 중 사용자 질의와 "
    "정확히 일치하는 상품이 없더라도, 실망시키지 않도록 그나마 가장 관련성 "
    "높은 상품 하나를 대신 추천해야 합니다. "
    "실제로 검색 결과에 나온 상품만 고르세요 - 존재하지 않는 상품을 지어내지 "
    "마세요. product_name/price/retailer/url은 그 검색 결과에 있는 값을 "
    "그대로 옮기세요. "
    "reasoning에는 반드시 이 상품이 질의와 정확히 일치하지 않는 이유(예: "
    "브랜드는 다르지만 같은 종류의 상품, 또는 용량/사양이 다름)를 솔직하게 "
    "먼저 밝히고, 그럼에도 가장 관련성 높다고 판단한 근거를 이어서 쓰세요. "
    "검색 결과 전체에 사용자가 찾는 것과 아예 다른 카테고리 상품만 있어서 "
    "추천할 만한 게 정말 하나도 없으면, 모든 필드를 빈 문자열로 두세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", "reasoning": "..."}'
)


def build_relaxed_pick_prompt(query: str, search_results: list[SearchResult]) -> str:
    results_block = format_results_block(search_results)
    return f"{RELAXED_PICK_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n검색 결과:\n{results_block}"


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
