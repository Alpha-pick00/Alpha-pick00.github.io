import asyncio

from app.category import CategoryClassification
from app.debate import (
    _extract_clarify_options,
    _facet_resolved,
    _filter_listing_pages,
    _is_ambiguous_facets,
    _resolved_facet_count,
    _strip_category_irrelevant_options,
    _strip_resolved_facets,
)
from app.schemas import ClarifyFacet, ClarifyOptions, SearchResult


def _facet(label: str, options: list[str]) -> ClarifyFacet:
    return ClarifyFacet(label=label, options=options)


def test_facet_resolved_true_when_option_already_in_query():
    assert _facet_resolved("메로나 빙그레", _facet("브랜드", ["빙그레", "롯데삼강"])) is True


def test_facet_resolved_false_when_no_option_in_query():
    assert _facet_resolved("메로나", _facet("브랜드", ["빙그레", "롯데삼강"])) is False


def test_strip_resolved_facets_removes_brand_already_in_query():
    """사용자가 이미 브랜드를 골라 재검색했는데, 이번 검색 결과에서도 여러
    브랜드가 다시 뽑히면(facet 추출은 매번 새로 하는 raw 추출이라 사용자가
    이미 고른 값을 모름) 프론트가 브랜드 선택 단계를 또 보여주는 버그가
    있었다 — 이미 질의에 반영된 facet은 목록에서 제거해야 한다."""
    facets = [_facet("브랜드", ["빙그레", "롯데삼강"]), _facet("용량", ["70ml", "200ml"])]

    stripped = _strip_resolved_facets("메로나 빙그레", facets)

    assert [f.label for f in stripped] == ["용량"]


def test_strip_resolved_facets_keeps_unresolved_facets():
    facets = [_facet("브랜드", ["빙그레", "롯데삼강"])]

    stripped = _strip_resolved_facets("메로나", facets)

    assert stripped == facets


def test_is_ambiguous_facets_false_when_nothing_found():
    assert _is_ambiguous_facets("메로나", []) is False


def test_is_ambiguous_facets_false_when_single_option_each():
    facets = [_facet("브랜드", ["다이슨"]), _facet("용량", ["500ml"])]
    assert _is_ambiguous_facets("다이슨 청소기", facets) is False


def test_is_ambiguous_facets_true_when_multiple_options_not_yet_in_query():
    facets = [_facet("브랜드", ["다이슨", "삼성"])]
    assert _is_ambiguous_facets("무선청소기", facets) is True


def test_is_ambiguous_facets_false_when_option_already_chosen_in_query():
    """사용자가 이미 브랜드를 골라 검색어에 반영했으면(예: HITL 재검색), 검색
    결과가 여전히 여러 브랜드를 섞어 보여줘도 다시 묻지 않는다."""
    facets = [_facet("브랜드", ["다이슨", "삼성"])]
    assert _is_ambiguous_facets("무선청소기 다이슨", facets) is False


def test_resolved_facet_count_counts_resolved_facets():
    facets = [_facet("브랜드", ["해태제과"]), _facet("제품", ["초코파이 오리지널", "초코파이 다크"])]

    assert _resolved_facet_count("초코파이 해태제과", facets) == 1


def test_resolved_facet_count_ignores_unresolved_facets():
    facets = [_facet("브랜드", ["빙그레", "롯데삼강"])]

    assert _resolved_facet_count("메로나", facets) == 0


def test_filter_listing_pages_removes_site_search_results():
    """search.11st.co.kr/...?kwd=, m.gmarket.co.kr/n/search?keyword= 같은 사이트내
    검색결과 페이지는 clarify 추출 대상에서 뺀다 — 이런 페이지는 사이드바에
    무관한 상품이 잔뜩 섞여 있어 GPT가 그걸 브랜드/제품 옵션으로 잘못 뽑는
    원인이었다."""
    results = [
        SearchResult(
            title="검색결과", url="https://search.11st.co.kr/pc/total-search?kwd=버즈3", snippet="..."
        ),
        SearchResult(
            title="갤럭시 버즈3", url="https://prod.danawa.com/info?pcode=59541506", snippet="..."
        ),
    ]

    filtered = _filter_listing_pages(results)

    assert [r.url for r in filtered] == ["https://prod.danawa.com/info?pcode=59541506"]


def test_filter_listing_pages_keeps_all_when_none_are_listings():
    results = [
        SearchResult(title="a", url="https://www.coupang.com/vp/products/1", snippet="..."),
        SearchResult(title="b", url="https://prod.danawa.com/info?pcode=2", snippet="..."),
    ]

    assert _filter_listing_pages(results) == results


def test_strip_category_irrelevant_options_removes_volume_but_keeps_quantity_for_fashion():
    """패션의류는 mL/L/kg 같은 용량 스펙은 무의미하지만, '양말 3족'·'정장 2벌'처럼
    수량(묶음 개수)은 여전히 실제 구매 기준으로 쓰인다 — 용량만 빼고 수량은
    남긴다."""
    options = ClarifyOptions(brands=["나이키"], volumes=["270mm"], quantities=["1족", "3족"])

    stripped = _strip_category_irrelevant_options(
        CategoryClassification(category="패션의류/잡화"), options
    )

    assert stripped.brands == ["나이키"]
    assert stripped.volumes == []
    assert stripped.quantities == ["1족", "3족"]


def test_strip_category_irrelevant_options_keeps_quantity_for_books():
    """도서는 '권'이 개수 단위 패턴에 포함돼 있을 만큼 수량이 실제 구매
    기준이다 — 용량 축만 없을 뿐 수량은 남아야 한다."""
    options = ClarifyOptions(brands=[], volumes=["500ml"], quantities=["1권", "10권"])

    stripped = _strip_category_irrelevant_options(
        CategoryClassification(category="도서/음반/DVD"), options
    )

    assert stripped.volumes == []
    assert stripped.quantities == ["1권", "10권"]


def test_strip_category_irrelevant_options_removes_both_for_travel():
    """여행 상품은 숙박/인원 단위라 용량·수량 4축 어디에도 안 걸린다 — 유일하게
    수량 축까지 통째로 빠지는 카테고리."""
    options = ClarifyOptions(brands=["하나투어"], volumes=["500ml"], quantities=["2개"])

    stripped = _strip_category_irrelevant_options(
        CategoryClassification(category="국내여행/해외여행"), options
    )

    assert stripped.volumes == []
    assert stripped.quantities == []


def test_strip_category_irrelevant_options_keeps_volume_for_beverage():
    options = ClarifyOptions(brands=["삼다수"], volumes=["500ml", "2L"], quantities=["6개", "12개"])

    stripped = _strip_category_irrelevant_options(
        CategoryClassification(category="식품", is_beverage=True), options
    )

    assert stripped.volumes == ["500ml", "2L"]
    assert stripped.quantities == ["6개", "12개"]


def test_strip_category_irrelevant_options_removes_volume_but_keeps_quantity_for_non_beverage_food():
    """식품 중에서도 음료가 아니면(정육·과자·조미료 등) 용량 축은 무의미하다 —
    수량(묶음 개수)은 음료가 아닌 식품에도 여전히 의미 있는 축이라 그대로 둔다."""
    options = ClarifyOptions(brands=["오뚜기"], volumes=["500g", "1kg"], quantities=["1개", "3개"])

    stripped = _strip_category_irrelevant_options(
        CategoryClassification(category="식품", is_beverage=False), options
    )

    assert stripped.volumes == []
    assert stripped.quantities == ["1개", "3개"]


def test_strip_category_irrelevant_options_keeps_all_when_classification_failed():
    """Gemini 분류 자체가 실패하면(category=None) 어느 카테고리인지 모르니
    안전하게 기존 동작대로 축을 그대로 둔다 — 잘못 숨기는 것보다 한 번 더
    물어보는 편이 낫다."""
    options = ClarifyOptions(brands=["나이키"], volumes=["270mm"], quantities=["1개"])

    stripped = _strip_category_irrelevant_options(CategoryClassification(), options)

    assert stripped.volumes == ["270mm"]
    assert stripped.quantities == ["1개"]


# --- _extract_clarify_options (2026-08-16부터 facet 기반, check_clarify_facets와
# 같은 추출 파이프라인 공유) ---------------------------------------------------


def _search_result(title: str, url: str) -> SearchResult:
    return SearchResult(title=title, url=url, snippet=title)


def test_extract_clarify_options_returns_facets_not_fixed_axes(monkeypatch):
    async def _fake_extract_facets(query, names, required_labels=None):
        return [ClarifyFacet(label="용량", options=["500ml", "1L"])]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    results = [_search_result("생수 500ml", "https://prod.danawa.com/info?pcode=1")]

    response = asyncio.run(_extract_clarify_options("생수", results))

    assert response is not None
    assert response.options.facets == [ClarifyFacet(label="용량", options=["500ml", "1L"])]
    assert response.options.brands == []


def test_extract_clarify_options_returns_none_when_no_facets_found(monkeypatch):
    async def _fake_extract_facets(query, names, required_labels=None):
        return []

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    results = [_search_result("생수 500ml", "https://prod.danawa.com/info?pcode=1")]

    assert asyncio.run(_extract_clarify_options("생수", results)) is None


def test_extract_clarify_options_returns_none_when_facet_already_resolved_in_query(monkeypatch):
    """이미 질의에 반영된 facet만 뽑히면(_strip_resolved_facets 이후 빈 리스트)
    다시 묻지 않는다."""
    async def _fake_extract_facets(query, names, required_labels=None):
        return [ClarifyFacet(label="용량", options=["500ml"])]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    results = [_search_result("생수 500ml", "https://prod.danawa.com/info?pcode=1")]

    assert asyncio.run(_extract_clarify_options("생수 500ml", results)) is None
