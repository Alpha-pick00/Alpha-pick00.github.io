from app.debate import _strip_resolved_options
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
