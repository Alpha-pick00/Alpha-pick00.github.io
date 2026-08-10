"""네트워크 호출 없이 고정 HTML 픽스처(scripts/probe_danawa.py로 실측한 실제
다나와 페이지)만으로 파싱 로직을 검증한다. fetch_danawa_offers()(네트워크
래퍼)는 여기서 전혀 부르지 않는다 — parse_danawa_html()만 테스트한다."""

from pathlib import Path

from fetchers.danawa import (
    MAX_VALID_PRICE,
    normalize_seller,
    parse_danawa_html,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_all_ten_offers_parsed_pcode_1151074():
    html = _load_fixture("danawa_offers_1151074.html")
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1151074", html)

    assert result["parse_status"] == "ok"
    assert len(result["offers"]) == 10
    sellers = {o["seller"] for o in result["offers"]}
    assert "쿠팡" in sellers
    assert "11번가" in sellers


def test_all_ten_offers_parsed_pcode_59537216():
    html = _load_fixture("danawa_offers_59537216.html")
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=59537216", html)

    assert result["parse_status"] == "ok"
    assert len(result["offers"]) == 10


def test_prices_are_integers_without_comma_or_won():
    html = _load_fixture("danawa_offers_1151074.html")
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1151074", html)

    coupang_offer = next(o for o in result["offers"] if o["seller"] == "쿠팡")
    assert coupang_offer["price_krw"] == 23000
    assert isinstance(coupang_offer["price_krw"], int)
    for offer in result["offers"]:
        assert isinstance(offer["price_krw"], int)


def test_delivery_text_is_separate_from_price():
    html = _load_fixture("danawa_offers_1151074.html")
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1151074", html)

    coupang_offer = next(o for o in result["offers"] if o["seller"] == "쿠팡")
    # 배송비는 price_krw에 합쳐지지 않고 delivery_text라는 별도 필드로 빠져야 한다.
    assert coupang_offer["price_krw"] == 23000
    assert "delivery_text" in coupang_offer
    assert coupang_offer["delivery_text"] != coupang_offer["price_krw"]


def test_seller_normalization():
    assert normalize_seller("쿠팡") == "쿠팡"
    assert normalize_seller("쿠팡 로켓배송") == "쿠팡"
    assert normalize_seller("coupang") == "쿠팡"
    assert normalize_seller("11번가") == "11번가"
    assert normalize_seller("g마켓") == "G마켓"
    # 매핑에 없는 3rd-party 셀러명은 원문 그대로 통과해야 한다(이마트몰/신세계몰처럼
    # 서로 다른 실제 판매처를 섣불리 합치면 안 되므로).
    assert normalize_seller("이마트몰") == "이마트몰"
    assert normalize_seller("newgods1") == "newgods1"


def test_expired_page_returns_expired_status_without_exception():
    html = _load_fixture("danawa_expired_31162997.html")
    result = parse_danawa_html("https://prod.danawa.com/info/?pcode=31162997", html)

    assert result["parse_status"] == "expired"
    assert result["offers"] == []
    assert result["product_name"] is None


def test_li_without_logo_is_skipped_not_raised():
    html = """
    <html><body>
    <ul class="list__mall-price">
      <li class="list-item">
        <div class="box__logo"><img src="x.png" alt="쿠팡"></div>
        <div class="box__price"><div class="sell-price"><span class="text__num">10,000</span></div></div>
        <a class="link__full-cover" href="/bridge/loadingBridge.html?cmpnyc=TP40F"></a>
      </li>
      <li class="list-item">
        <!-- 로고도 text__logo도 없는 비정상 슬롯(광고 등으로 추정) -->
        <div class="box__price"><div class="sell-price"><span class="text__num">9,000</span></div></div>
      </li>
    </ul>
    </body></html>
    """
    result = parse_danawa_html("https://example.test/x", html)

    assert result["parse_status"] == "partial"
    assert len(result["offers"]) == 1
    assert result["offers"][0]["seller"] == "쿠팡"


def test_invalid_prices_are_filtered_out():
    html = f"""
    <html><body>
    <ul class="list__mall-price">
      <li class="list-item">
        <div class="box__logo"><img src="x.png" alt="쿠팡"></div>
        <div class="box__price"><div class="sell-price"><span class="text__num">0</span></div></div>
        <a class="link__full-cover" href="/bridge/loadingBridge.html?cmpnyc=A"></a>
      </li>
      <li class="list-item">
        <div class="box__logo"><img src="x.png" alt="11번가"></div>
        <div class="box__price"><div class="sell-price"><span class="text__num">{MAX_VALID_PRICE + 1:,}</span></div></div>
        <a class="link__full-cover" href="/bridge/loadingBridge.html?cmpnyc=B"></a>
      </li>
      <li class="list-item">
        <div class="box__logo"><img src="x.png" alt="G마켓"></div>
        <div class="box__price"><div class="sell-price"><span class="text__num">12,900</span></div></div>
        <a class="link__full-cover" href="/bridge/loadingBridge.html?cmpnyc=C"></a>
      </li>
    </ul>
    </body></html>
    """
    result = parse_danawa_html("https://example.test/x", html)

    assert result["parse_status"] == "partial"
    assert len(result["offers"]) == 1
    assert result["offers"][0]["seller"] == "G마켓"
    assert result["offers"][0]["price_krw"] == 12900


def test_bridge_url_is_stored_and_no_network_call_happens():
    html = _load_fixture("danawa_offers_1151074.html")
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1151074", html)

    coupang_offer = next(o for o in result["offers"] if o["seller"] == "쿠팡")
    assert coupang_offer["bridge_url"] is not None
    assert "bridge/loadingBridge.html" in coupang_offer["bridge_url"]
    # 파이프라인에서 자동으로 채워지면 안 되는 필드들 — STEP 3 전까지는 항상 None.
    assert coupang_offer["resolved_url"] is None
    assert coupang_offer["product_id"] is None
    # 이 테스트는 parse_danawa_html()만 호출했다 — httpx를 import조차 하지 않았으므로
    # 네트워크 요청이 발생할 여지가 구조적으로 없다.
