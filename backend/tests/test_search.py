"""app/search.py의 쿠팡 교차 확인 검색(search_coupang) 테스트. 네트워크 요청
금지 - _tavily_search를 직접 monkeypatch해서 호출 인자만 검증한다(실제 httpx
동작은 danawa 어댑터 테스트들처럼 이미 검증된 패턴이라 여기서 다시 안 봄)."""

from __future__ import annotations

import asyncio

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
