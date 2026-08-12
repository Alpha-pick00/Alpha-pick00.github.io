"""다나와 실시간 자동완성(fetchers/danawa_autocomplete.py) 테스트. 네트워크 요청
금지(conftest의 소켓 차단 fixture) - httpx.MockTransport로 전송만 갈아끼운다."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fetchers import danawa_autocomplete
from fetchers.danawa_autocomplete import _parse_jsonp, autocomplete_danawa


# -- _parse_jsonp: 순수 함수, 네트워크 없음 ----------------------------------------


def test_parse_jsonp_extracts_keywords_from_real_shape():
    # 2026-08-11 실측(www.danawa.com/globaljs/.../searchAutocompleteResult.json.php)에서
    # 그대로 받은 응답 형태.
    text = 'akc({"keyword":[{"keyword":"맥북에어","code":""},{"keyword":"맥북에어 m2","code":""}]});'
    assert _parse_jsonp(text) == ["맥북에어", "맥북에어 m2"]


def test_parse_jsonp_skips_entries_without_keyword():
    text = 'akc({"keyword":[{"keyword":"","code":""},{"keyword":"정상값","code":""}]});'
    assert _parse_jsonp(text) == ["정상값"]


def test_parse_jsonp_returns_empty_on_malformed_json():
    assert _parse_jsonp("akc(not valid json);") == []


def test_parse_jsonp_returns_empty_when_no_parens():
    assert _parse_jsonp("") == []


def test_parse_jsonp_returns_empty_when_keyword_field_missing():
    assert _parse_jsonp("akc({});") == []


def test_parse_jsonp_returns_empty_when_top_level_is_not_an_object():
    # 실측(2026-08-11): 쿼리가 깨진 인코딩으로 들어가는 등 비정상 입력에는
    # {"keyword":[...]}가 아니라 배열 등 다른 형태가 오기도 했다(AttributeError로
    # 500이 났던 실제 버그의 회귀 테스트).
    assert _parse_jsonp("akc([]);") == []


# -- autocomplete_danawa: 네트워크 래퍼 (httpx.MockTransport - 실제 소켓 없음) --------

_RealAsyncClient = httpx.AsyncClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(**kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), headers=kwargs.get("headers"))

    async def _async_noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(danawa_autocomplete._throttle, "wait", _async_noop)
    monkeypatch.setattr(danawa_autocomplete.httpx, "AsyncClient", factory)


def test_autocomplete_danawa_returns_keywords_on_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='akc({"keyword":[{"keyword":"노트북","code":""}]});')

    _patch_client(monkeypatch, handler)

    keywords = asyncio.run(autocomplete_danawa("노트"))
    assert keywords == ["노트북"]


def test_autocomplete_danawa_sends_referer_header(monkeypatch):
    # 실측(2026-08-11): Referer 없이 부르면 403 - 이 헤더가 반드시 붙어야 한다.
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["referer"] = request.headers.get("referer")
        return httpx.Response(200, text='akc({"keyword":[]});')

    _patch_client(monkeypatch, handler)

    asyncio.run(autocomplete_danawa("아무거나"))
    assert captured["referer"] == "https://www.danawa.com/"


def test_autocomplete_danawa_returns_empty_on_403(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    _patch_client(monkeypatch, handler)

    assert asyncio.run(autocomplete_danawa("차단됨")) == []


def test_autocomplete_danawa_returns_empty_on_connection_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _patch_client(monkeypatch, handler)

    assert asyncio.run(autocomplete_danawa("커넥션에러")) == []


def test_autocomplete_danawa_returns_empty_for_blank_prefix():
    assert asyncio.run(autocomplete_danawa("   ")) == []


def test_autocomplete_danawa_respects_limit(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        items = ",".join(f'{{"keyword":"후보{i}","code":""}}' for i in range(10))
        return httpx.Response(200, text=f'akc({{"keyword":[{items}]}});')

    _patch_client(monkeypatch, handler)

    keywords = asyncio.run(autocomplete_danawa("후보", limit=3))
    assert len(keywords) == 3
