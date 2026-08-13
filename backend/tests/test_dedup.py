from app.schemas import AgentCandidate
from fusion.dedup import merge_candidates

GMARKET_EXHIB_URL = "http://rpp.gmarket.co.kr?exhib=235390"


def _candidate(
    product_name: str,
    price_krw: int | None = None,
    retailer: str | None = "G마켓",
    url: str = GMARKET_EXHIB_URL,
) -> AgentCandidate:
    return AgentCandidate(product_name=product_name, price_krw=price_krw, retailer=retailer, url=url)


def test_same_shared_listing_url_with_conflicting_prices_stays_separate():
    """실제 발견한 케이스: 다이슨 3개 모델이 전부 같은 G마켓 전시 페이지 URL을 공유.
    가격이 서로 크게 달라 상품 상세가 아니라 목록/전시 페이지라는 증거이므로
    병합하지 않고 별개 후보 3개로 유지하며, 전부 shared_url 플래그가 붙어야 한다."""
    entries = [
        ("gpt", _candidate("다이슨 V10 옵틱 + 오토 엠티 독", price_krw=690000)),
        ("gpt", _candidate("다이슨 무선청소기 디지털 슬림(니켈/니켈)", price_krw=351000)),
        ("gpt", _candidate("다이슨 V8 플러피 무선 청소기", price_krw=319000)),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 3
    for candidate in merged:
        assert candidate["flags"]["shared_url"] is True
        assert candidate["flags"]["shared_url_count"] == 3


def test_same_url_identical_price_merges():
    entries = [
        ("gpt", _candidate("무선 마우스", price_krw=12900, url="https://coupang.com/vp/products/1")),
        ("gemini", _candidate("무선 마우스", price_krw=12900, url="https://coupang.com/vp/products/1")),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 1
    assert merged[0]["price_krw"] == 12900
    assert merged[0]["flags"]["shared_url"] is False


def test_same_url_small_price_difference_within_tolerance_merges():
    entries = [
        ("gpt", _candidate("무선 마우스", price_krw=12900, url="https://coupang.com/vp/products/1")),
        ("gemini", _candidate("무선 마우스", price_krw=13200, url="https://coupang.com/vp/products/1")),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 1
    assert merged[0]["flags"]["shared_url"] is False


def test_same_url_one_missing_price_merges_and_adopts_known_price():
    entries = [
        ("gpt", _candidate("무선 마우스", price_krw=None, url="https://coupang.com/vp/products/1")),
        ("gemini", _candidate("무선 마우스", price_krw=12900, url="https://coupang.com/vp/products/1")),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 1
    assert merged[0]["price_krw"] == 12900


def test_same_seller_and_price_but_unrelated_name_stays_separate():
    """(판매처, 가격) 완전 일치만으로 병합하면 우연히 가격이 같은 다른 상품이
    섞일 수 있어, 상품명이 최소한 무관하지 않은지(token_set_ratio>=60) 확인해야 한다."""
    entries = [
        ("gpt", _candidate("쿠쿠 IH 압력밥솥 6인용", price_krw=99000, retailer="11번가", url="https://11st.co.kr/products/1")),
        ("gemini", _candidate("다이슨 슈퍼소닉 헤어드라이어", price_krw=99000, retailer="11번가", url="https://11st.co.kr/products/2")),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 2


def test_tracking_params_only_difference_merges():
    entries = [
        (
            "gpt",
            _candidate(
                "무선 마우스",
                price_krw=12900,
                url="https://coupang.com/vp/products/1?utm_source=fb&utm_medium=cpc",
            ),
        ),
        (
            "gemini",
            _candidate("무선 마우스", price_krw=12900, url="https://coupang.com/vp/products/1/"),
        ),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 1
    assert merged[0]["proposed_by"] == ["gpt", "gemini"]


def test_empty_entries_returns_empty_list():
    assert merge_candidates([]) == []


def test_same_product_different_retailers_picks_cheapest_price_and_matching_url():
    """이름 유사도로 묶인(= URL도 판매처도 다른) 동일 상품 후보들 중, 최종적으로
    보여줄 가격은 최저가여야 하고 그 URL/판매처는 실제로 그 최저가를 파는
    판매처의 것이어야 한다 — 가격 다수결과 URL 다수결을 따로 하면 서로 다른
    판매처의 값이 섞일 수 있다."""
    entries = [
        ("gpt", _candidate("에어팟 프로 2세대", price_krw=259000, retailer="쿠팡", url="https://coupang.com/vp/products/1")),
        ("gemini", _candidate("에어팟 프로 2세대", price_krw=239000, retailer="11번가", url="https://11st.co.kr/products/2")),
        ("deepseek", _candidate("에어팟 프로 2세대", price_krw=259000, retailer="G마켓", url="https://gmarket.co.kr/products/3")),
    ]

    merged = merge_candidates(entries)

    assert len(merged) == 1
    assert merged[0]["price_krw"] == 239000
    assert merged[0]["retailer"] == "11번가"
    assert merged[0]["url"] == "https://11st.co.kr/products/2"
