from app.category import CategoryClassification
from app.debate import (
    _resolved_dimension_count,
    _strip_category_irrelevant_options,
    _strip_resolved_options,
)
from app.schemas import ClarifyOptions


def test_strip_resolved_options_removes_brand_already_in_query():
    """사용자가 이미 브랜드를 골라 재검색했는데, 이번 검색 결과에서도 여러
    브랜드가 다시 뽑히면(옵션 추출은 매번 새로 하는 raw 추출이라 사용자가
    이미 고른 값을 모름) 프론트가 브랜드 선택 단계를 또 보여주는 버그가
    있었다 — 이미 질의에 반영된 브랜드는 옵션 목록에서 제거해야 한다."""
    options = ClarifyOptions(brands=["빙그레", "롯데삼강"], volumes=["70ml", "200ml"], quantities=[])

    stripped = _strip_resolved_options("메로나 빙그레", options)

    assert stripped.brands == []
    assert stripped.volumes == ["70ml", "200ml"]


def test_strip_resolved_options_removes_volume_already_in_query():
    options = ClarifyOptions(brands=[], volumes=["70ml", "200ml"], quantities=["1개", "10개"])

    stripped = _strip_resolved_options("메로나 빙그레 70mL", options)

    assert stripped.volumes == []
    assert stripped.quantities == ["1개", "10개"]


def test_strip_resolved_options_removes_quantity_already_in_query():
    options = ClarifyOptions(brands=[], volumes=[], quantities=["1개", "10개"])

    stripped = _strip_resolved_options("메로나 빙그레 70mL 10개", options)

    assert stripped.quantities == []


def test_strip_resolved_options_keeps_unresolved_dimensions():
    options = ClarifyOptions(brands=["빙그레", "롯데삼강"], volumes=[], quantities=[])

    stripped = _strip_resolved_options("메로나", options)

    assert stripped.brands == ["빙그레", "롯데삼강"]


def test_resolved_dimension_count_counts_brand_and_quantity():
    """'초코파이 해태제과 10개'처럼 브랜드와 개수를 이미 답한 라운드에서는,
    이번 라운드에 검색 결과가 바뀌며 새로 갈리는 제품 라인(products)이 있어도
    2개 축이 이미 풀렸다고 세야 한다 — 이 값이 라운드 상한(_MAX_CLARIFY_ROUNDS)
    도달 여부를 판단하는 근거가 된다."""
    raw_options = ClarifyOptions(
        brands=["해태제과"],
        products=["초코파이 오리지널", "초코파이 다크"],
        volumes=[],
        quantities=[],
    )

    count = _resolved_dimension_count("초코파이 해태제과 10개", raw_options)

    assert count == 2


def test_resolved_dimension_count_ignores_unresolved_product():
    raw_options = ClarifyOptions(
        brands=["빙그레", "롯데삼강"], products=[], volumes=[], quantities=[]
    )

    count = _resolved_dimension_count("메로나", raw_options)

    assert count == 0


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
