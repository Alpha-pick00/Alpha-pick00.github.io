"""app/search.py의 그라운딩 소프트 신호 검색(search_coupang/search_naver) 테스트.
네트워크 요청 금지 - _tavily_search를 직접 monkeypatch해서 호출 인자만 검증한다
(실제 httpx 동작은 danawa 어댑터 테스트들처럼 이미 검증된 패턴이라 여기서 다시 안 봄)."""

from __future__ import annotations

import asyncio

import httpx

from app import search as search_module
from app.schemas import SearchResult


def test_search_coupang_scopes_tavily_to_coupang_domain(monkeypatch):
    captured: dict = {}

    async def _fake_tavily_search(query, max_results, domains=None):
        captured["query"] = query
        captured["max_results"] = max_results
        captured["domains"] = domains
        return [SearchResult(title="쿠팡 상품", url="https://coupang.com/vp/products/1", snippet="...")]

    monkeypatch.setattr(search_module, "_tavily_search", _fake_tavily_search)

    results = asyncio.run(search_module.search_coupang("무선 이어폰"))

    assert captured["query"] == "무선 이어폰"
    assert captured["domains"] == search_module.COUPANG_DOMAINS
    assert len(results) == 1
    assert results[0].url == "https://coupang.com/vp/products/1"


def test_search_coupang_returns_empty_list_on_failure(monkeypatch):
    async def _boom(query, max_results, domains=None):
        raise RuntimeError("tavily down")

    monkeypatch.setattr(search_module, "_tavily_search", _boom)

    results = asyncio.run(search_module.search_coupang("무선 이어폰"))

    assert results == []


def test_search_naver_scopes_tavily_to_naver_shopping_domain(monkeypatch):
    captured: dict = {}

    async def _fake_tavily_search(query, max_results, domains=None):
        captured["query"] = query
        captured["max_results"] = max_results
        captured["domains"] = domains
        return [SearchResult(title="네이버 상품", url="https://shopping.naver.com/products/1", snippet="...")]

    monkeypatch.setattr(search_module, "_tavily_search", _fake_tavily_search)

    results = asyncio.run(search_module.search_naver("무선 이어폰"))

    assert captured["query"] == "무선 이어폰"
    assert captured["domains"] == search_module.NAVER_DOMAINS
    assert len(results) == 1
    assert results[0].url == "https://shopping.naver.com/products/1"


def test_search_naver_returns_empty_list_on_failure(monkeypatch):
    async def _boom(query, max_results, domains=None):
        raise RuntimeError("tavily down")

    monkeypatch.setattr(search_module, "_tavily_search", _boom)

    results = asyncio.run(search_module.search_naver("무선 이어폰"))

    assert results == []


def test_search_unrestricted_passes_empty_domains_list(monkeypatch):
    captured: dict = {}

    async def _fake_tavily_search(query, max_results, domains=None):
        captured["query"] = query
        captured["max_results"] = max_results
        captured["domains"] = domains
        return [SearchResult(title="어딘가의 리뷰 글", url="https://example.com/review", snippet="...")]

    monkeypatch.setattr(search_module, "_tavily_search", _fake_tavily_search)

    results = asyncio.run(search_module.search_unrestricted("희귀 상품명"))

    assert captured["query"] == "희귀 상품명"
    assert captured["domains"] == []
    assert len(results) == 1
    assert results[0].url == "https://example.com/review"


def test_search_unrestricted_returns_empty_list_on_failure(monkeypatch):
    async def _boom(query, max_results, domains=None):
        raise RuntimeError("tavily down")

    monkeypatch.setattr(search_module, "_tavily_search", _boom)

    results = asyncio.run(search_module.search_unrestricted("희귀 상품명"))

    assert results == []


def test_tavily_search_filters_out_generic_listing_pages(monkeypatch):
    """다나와 카테고리 목록 페이지처럼 특정 상품 하나를 가리키지 않는 결과는
    propose에게 넘기기 전에 걸러야 한다(2026-08-19 사용자 리포트: "10만원대
    이어폰 추천해줘 했는데 아무것도 안뜨잖아" - "이어폰" 검색 결과가 목록
    페이지로 뒤덮여 propose가 실제 상품을 하나도 못 봤다)."""
    fixture_response = {
        "results": [
            {
                "title": "무선 이어폰 : 다나와 가격비교",
                "url": "https://prod.danawa.com/list?cate=12237349",
                "content": "카테고리 목록",
            },
            {
                "title": "QCY Mini 2 : 다나와 가격비교",
                "url": "https://prod.danawa.com/info?pcode=6833593",
                "content": "39,900원",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture_response)

    real_async_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_async_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(search_module.httpx, "AsyncClient", factory)

    results = asyncio.run(search_module._tavily_search("이어폰", 5))

    assert len(results) == 1
    assert results[0].url == "https://prod.danawa.com/info?pcode=6833593"
