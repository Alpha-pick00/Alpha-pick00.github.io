import asyncio

from app.category import CategoryClassification
from app.debate import (
    _FACET_ORDER_HINTS,
    _attach_facet_crossfilter,
    _build_facet_value_incidence,
    _extract_clarify_options,
    _facet_centrality,
    _facet_resolved,
    _facet_sort_key,
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


# --- 하이퍼그래프 incidence 기반 facet 크로스필터/정렬(2026-08-16) -----------
# _attach_facet_crossfilter가 상품명을 매번 재스캔하는 브루트포스 대신
# _build_facet_value_incidence(facet 값 -> 등장하는 상품 인덱스 집합)의 교집합
# 판정으로 재구성됐다 - 아래는 그 판정이 기존과 동일한 결과를 내는지, 그리고
# incidence 기반 중심성이 _FACET_ORDER_HINTS를 안 건드리고 그 바깥에서만
# 타이브레이커로 쓰이는지 확인한다.


def test_build_facet_value_incidence_maps_values_to_matching_name_indices():
    facets = [_facet("브랜드", ["삼성전자", "APPLE"]), _facet("시리즈", ["갤럭시S25", "아이폰17"])]
    names = ["삼성전자 갤럭시S25 256GB", "APPLE 아이폰17 256GB"]

    incidence = _build_facet_value_incidence(facets, names)

    assert incidence["삼성전자"] == {0}
    assert incidence["apple"] == {1}
    assert incidence["갤럭시s25"] == {0}
    assert incidence["아이폰17"] == {1}


def test_build_facet_value_incidence_empty_set_for_value_with_no_match():
    facets = [_facet("브랜드", ["LG전자"])]
    names = ["삼성전자 갤럭시S25 256GB"]

    incidence = _build_facet_value_incidence(facets, names)

    assert incidence["lg전자"] == set()


def test_attach_facet_crossfilter_matches_existing_symmetric_scenario():
    """tests/test_clarify_facets.py의
    test_check_clarify_facets_attaches_facet_crossfilter_symmetrically와 같은
    시나리오를 check_clarify_facets 전체를 안 거치고 직접 검증 - incidence
    재구성이 기존 결과를 그대로 재현하는지 확인하는 더 빠른 회귀망."""
    facets = [
        _facet("브랜드", ["삼성전자", "APPLE"]),
        _facet("시리즈", ["갤럭시S25", "갤럭시Z 폴드8", "아이폰17", "아이폰17 프로"]),
    ]
    names = [
        "삼성전자 갤럭시S25 256GB",
        "삼성전자 갤럭시Z 폴드8 512GB",
        "APPLE 아이폰17 256GB",
        "APPLE 아이폰17 프로 512GB",
    ]

    updated = _attach_facet_crossfilter(facets, names)

    by_label = {f.label: f for f in updated}
    assert by_label["브랜드"].options_by_selection == {
        "갤럭시S25": ["삼성전자"],
        "갤럭시Z 폴드8": ["삼성전자"],
        "아이폰17": ["APPLE"],
        "아이폰17 프로": ["APPLE"],
    }
    assert by_label["시리즈"].options_by_selection == {
        "삼성전자": ["갤럭시S25", "갤럭시Z 폴드8"],
        "APPLE": ["아이폰17", "아이폰17 프로"],
    }


def test_facet_centrality_averages_option_degrees():
    incidence = {"삼성전자": {0, 1, 2}, "apple": {3}}
    facet = _facet("브랜드", ["삼성전자", "APPLE"])

    assert _facet_centrality(facet, incidence) == 2.0  # (3 + 1) / 2


def test_facet_centrality_zero_for_no_options():
    assert _facet_centrality(_facet("빈축", []), {}) == 0.0


def test_facet_sort_key_ignores_centrality_for_hint_matched_facet():
    """힌트가 잡는 facet("브랜드")은 incidence 내용과 무관하게 중심성을
    아예 안 본다 - 표본이 작을 때 중심성 신호가 불안정해질 위험으로부터
    안전해야 하는 케이스."""
    incidence = {"삼성전자": set(range(100)), "lg전자": set()}
    high_degree = _facet("브랜드", ["삼성전자"])
    low_degree = _facet("브랜드", ["LG전자"])

    assert _facet_sort_key(high_degree, incidence) == _facet_sort_key(low_degree, incidence)
    assert _facet_sort_key(high_degree, incidence)[1] == 0.0


def test_facet_sort_key_orders_hint_unmatched_facets_by_descending_centrality():
    """힌트가 못 잡는 facet들끼리는 incidence 중심성(평균 degree) 내림차순으로
    정렬돼야 한다 - LLM이 낸 임의 순서 대신."""
    incidence = {"넓은값": set(range(10)), "좁은값": {0}}
    broad = _facet("아무거나축", ["넓은값"])
    narrow = _facet("다른아무거나축", ["좁은값"])

    broad_key = _facet_sort_key(broad, incidence)
    narrow_key = _facet_sort_key(narrow, incidence)

    assert broad_key[0] == narrow_key[0] == len(_FACET_ORDER_HINTS)
    assert broad_key < narrow_key  # 중심성이 높을수록(더 넓은 축일수록) 먼저 온다
