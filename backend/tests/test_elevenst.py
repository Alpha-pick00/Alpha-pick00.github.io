"""11번가 오픈API(ProductSearch) 어댑터 테스트. 네트워크 요청 금지(conftest의
소켓 차단 fixture 적용) - 네트워크 계층 테스트는 httpx.MockTransport로 전송만
갈아끼운다(실제 소켓 없음, test_danawa_search.py와 동일 패턴)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fetchers import elevenst
from fetchers.elevenst import ElevenstApiError, _parse_response, search_products


def _xml(inner: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="EUC-KR"?><ProductSearchResponse>' + inner + "</ProductSearchResponse>"
    ).encode("euc-kr")


def _product_xml(
    code: str,
    name: str,
    price: int,
    sale_price: int,
    discount: int | None = None,
    detail_url: str = "http://www.11st.co.kr/products/1",
    seller_nick: str = "테스트샵",
    review_count: int = 10,
) -> str:
    benefit = f"<Benefit><Discount>{discount}</Discount></Benefit>" if discount is not None else ""
    return (
        "<Product>"
        f"<ProductCode>{code}</ProductCode>"
        f"<ProductName><![CDATA[{name}]]></ProductName>"
        f"<ProductPrice>{price}</ProductPrice>"
        f"<SalePrice>{sale_price}</SalePrice>"
        f"<ProductImage300><![CDATA[https://cdn.011st.com/img/{code}.webp]]></ProductImage300>"
        f"<SellerNick><![CDATA[{seller_nick}]]></SellerNick>"
        f"<DetailPageUrl><![CDATA[{detail_url}]]></DetailPageUrl>"
        "<Delivery><![CDATA[무료]]></Delivery>"
        f"<ReviewCount>{review_count}</ReviewCount>"
        "<BuySatisfy>96</BuySatisfy>"
        f"{benefit}"
        "</Product>"
    )


# -- _parse_response (순수 파싱, 네트워크 없음) --------------------------------


def test_parse_response_maps_product_fields():
    xml = _xml(
        "<Products><TotalCount>1</TotalCount>" + _product_xml("123", "펩시콜라 355ml", 22300, 19800, discount=2500) + "</Products>"
    )

    result = _parse_response(xml)

    assert result.total_count == 1
    assert len(result.products) == 1
    p = result.products[0]
    assert p.code == "123"
    assert p.name == "펩시콜라 355ml"
    assert p.price == 22300
    assert p.sale_price == 19800
    assert p.discount == 2500
    assert p.seller_nick == "테스트샵"
    assert p.detail_url == "http://www.11st.co.kr/products/1"
    assert p.review_count == 10


def test_parse_response_handles_multiple_products():
    xml = _xml(
        "<Products><TotalCount>2</TotalCount>"
        + _product_xml("1", "상품A", 1000, 900)
        + _product_xml("2", "상품B", 2000, 1800)
        + "</Products>"
    )

    result = _parse_response(xml)

    assert [p.code for p in result.products] == ["1", "2"]


def test_parse_response_no_discount_leaves_discount_none():
    xml = _xml("<Products><TotalCount>1</TotalCount>" + _product_xml("1", "상품", 1000, 900) + "</Products>")

    result = _parse_response(xml)

    assert result.products[0].discount is None


def test_parse_response_empty_products():
    xml = _xml("<Products><TotalCount>0</TotalCount></Products>")

    result = _parse_response(xml)

    assert result.total_count == 0
    assert result.products == []


def test_parse_response_parses_categories():
    xml = _xml(
        "<Products><TotalCount>0</TotalCount></Products>"
        '<Categories><Category><CategoryName><![CDATA[음료]]></CategoryName>'
        "<CategoryPrdCnt>1234</CategoryPrdCnt></Category></Categories>"
    )

    result = _parse_response(xml)

    assert len(result.categories) == 1
    assert result.categories[0].name == "음료"
    assert result.categories[0].count == 1234


def test_parse_response_error_code_raises():
    xml = _xml("<Error><Code>600</Code><Message><![CDATA[잘못된 키입니다.]]></Message></Error>")

    with pytest.raises(ElevenstApiError):
        _parse_response(xml)


def test_parse_response_euckr_roundtrip_korean_text():
    xml = _xml(
        "<Products><TotalCount>1</TotalCount>" + _product_xml("1", "삼성전자 갤럭시 버즈3 프로", 249000, 199000) + "</Products>"
    )

    result = _parse_response(xml)

    assert result.products[0].name == "삼성전자 갤럭시 버즈3 프로"


# -- search_products 네트워크 래퍼 (httpx.MockTransport - 실제 소켓 없음) ------

_RealAsyncClient = httpx.AsyncClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(**kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(elevenst.httpx, "AsyncClient", factory)


def test_search_products_returns_parsed_result(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        xml = _xml("<Products><TotalCount>1</TotalCount>" + _product_xml("1", "펩시 355ml", 22300, 19800) + "</Products>")
        return httpx.Response(200, content=xml)

    _patch_client(monkeypatch, handler)

    result = asyncio.run(search_products("test-key", "펩시 355ml", page_size=5))

    assert result.total_count == 1
    assert result.products[0].name == "펩시 355ml"
    assert "apiCode=ProductSearch" in captured["url"]
    assert "key=test-key" in captured["url"]


def test_search_products_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"internal error")

    _patch_client(monkeypatch, handler)

    with pytest.raises(ElevenstApiError):
        asyncio.run(search_products("test-key", "쿼리"))


# -- 짧은 TTL 재사용 캐시 (2026-08-20, "검색 단계와 propose 단계가 같은 질의로 -----
# 11번가를 매 요청 2번씩 부르고 있었다" 회귀 방지) -------------------------------


def test_search_products_reuses_cached_result_for_identical_request(monkeypatch):
    """같은 (키, 키워드, 페이지, 페이지크기, 카테고리여부) 조합으로 다시
    부르면 네트워크를 다시 타지 않고 직전 결과를 그대로 재사용해야 한다 -
    _SearchNode와 _ElevenstFetchNode가 refine 제거 이후 같은 질의로 각자
    독립 호출하던 중복을 여기서 흡수한다."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        xml = _xml("<Products><TotalCount>1</TotalCount>" + _product_xml("1", "중복호출테스트 상품", 1000, 900) + "</Products>")
        return httpx.Response(200, content=xml)

    _patch_client(monkeypatch, handler)

    first = asyncio.run(search_products("dup-key", "중복호출테스트", page_size=20))
    second = asyncio.run(search_products("dup-key", "중복호출테스트", page_size=20))

    assert calls == 1
    assert first.products[0].name == "중복호출테스트 상품"
    assert second.products[0].name == "중복호출테스트 상품"


def test_search_products_does_not_reuse_cache_across_different_keywords(monkeypatch):
    """캐시 키에 키워드가 포함돼야 한다 - 다른 검색어까지 같은 결과를
    돌려주면 완전히 다른 상품이 잘못 재사용된다."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        xml = _xml("<Products><TotalCount>0</TotalCount></Products>")
        return httpx.Response(200, content=xml)

    _patch_client(monkeypatch, handler)

    asyncio.run(search_products("dup-key", "키워드구분테스트A", page_size=20))
    asyncio.run(search_products("dup-key", "키워드구분테스트B", page_size=20))

    assert calls == 2
