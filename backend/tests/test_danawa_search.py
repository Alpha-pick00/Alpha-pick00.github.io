"""B-3b: 다나와 검색 어댑터(search.danawa.com) 테스트. 네트워크 요청 금지
(conftest의 소켓 차단 fixture 적용) - 네트워크 계층 테스트는 httpx.MockTransport로
전송만 갈아끼운다(실제 소켓을 전혀 만들지 않으므로 차단 fixture와 충돌 없음)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fetchers import danawa_search
from fetchers.danawa_search import DanawaSearchBlocked, _DomainThrottle, parse_search_html

FIXTURES = Path(__file__).parent / "fixtures"


def _item_html(pcode: str, name_inner_html: str, mall_rows: list[tuple[str, int]] | None = None, ad: bool = False) -> str:
    ad_html = '<span class="icon__ad">광고</span>' if ad else ""
    rows_html = "".join(
        f'<li id="productInfoDetail_{pcode}_{i}">{count}몰 VS상품비교 100,000 원 가격정보 더보기 {label}</li>'
        for i, (label, count) in enumerate(mall_rows or [])
    )
    return f"""
    <li class="prod_item">
      {ad_html}
      <a class="btn_view_zoom" data-product-code="{pcode}"></a>
      <p class="prod_name"><a>{name_inner_html}</a></p>
      <div class="prod_pricelist"><ul>{rows_html}</ul></div>
    </li>
    """


def _search_html(items_html: str) -> str:
    return f"<html><body><ul class='product_list'>{items_html}</ul></body></html>"


# -- 실제 fixture(B-2/B-3a에서 확보한 진짜 검색결과 HTML)로 파싱 검증 -----------------


def test_parse_search_html_real_fixture_extracts_pcode_name_and_mall_count():
    html = (FIXTURES / "danawa_search_buds3pro.html").read_text(encoding="utf-8")
    items = parse_search_html(html, limit=5)

    assert len(items) == 5
    assert items[0]["pcode"] == "59537216"
    assert items[0]["product_name"] == "삼성전자 갤럭시 버즈3 프로 SM-R630N"
    assert items[0]["total_mall_count"] == 150  # "정품" 카테고리 행 - "해외구매" 64몰이 아니다


def test_parse_search_html_no_result_fixture_returns_empty():
    html = (FIXTURES / "danawa_search_noresult.html").read_text(encoding="utf-8")
    assert parse_search_html(html) == []


# -- 합성 HTML로 각 규칙을 독립적으로 검증 -----------------------------------------


def test_parse_search_html_name_gets_spaces_around_bold_tags():
    html = _search_html(_item_html("1", "삼성전자<b>갤럭시</b><b>버즈3</b>프로"))
    items = parse_search_html(html)
    assert items[0]["product_name"] == "삼성전자 갤럭시 버즈3 프로"


def test_parse_search_html_dedupes_repeated_pcode_across_items():
    html = _search_html(_item_html("1", "상품A") + _item_html("1", "상품A 중복"))
    items = parse_search_html(html)
    assert len(items) == 1
    assert items[0]["product_name"] == "상품A"


def test_parse_search_html_respects_limit():
    html = _search_html("".join(_item_html(str(i), f"상품{i}") for i in range(5)))
    items = parse_search_html(html, limit=2)
    assert len(items) == 2


def test_parse_search_html_skips_ad_marked_items():
    html = _search_html(_item_html("1", "광고상품", ad=True) + _item_html("2", "정상상품"))
    items = parse_search_html(html)
    assert len(items) == 1
    assert items[0]["pcode"] == "2"


def test_parse_search_html_skips_item_without_data_product_code():
    html = _search_html('<li class="prod_item"><p class="prod_name"><a>이름만있음</a></p></li>' + _item_html("2", "정상상품"))
    items = parse_search_html(html)
    assert len(items) == 1
    assert items[0]["pcode"] == "2"


def test_extract_total_mall_count_picks_genuine_row_not_overseas():
    html = _search_html(_item_html("1", "상품A", mall_rows=[("해외구매", 64), ("정품", 150)]))
    items = parse_search_html(html)
    assert items[0]["total_mall_count"] == 150


def test_extract_total_mall_count_none_without_pricelist():
    html = _search_html('<li class="prod_item"><a class="btn_view_zoom" data-product-code="1"></a><p class="prod_name"><a>상품A</a></p></li>')
    items = parse_search_html(html)
    assert items[0]["total_mall_count"] is None


# -- 도메인별 rate limiter (시간 mock) ---------------------------------------------


def test_domain_throttle_uses_different_intervals_per_domain(monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleep_calls.append(sec)

    fake_now = [1000.0]
    monkeypatch.setattr(danawa_search.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(danawa_search.time, "monotonic", lambda: fake_now[0])

    throttle = _DomainThrottle({"search.danawa.com": 10.0}, 0.5)

    async def run() -> None:
        await throttle.wait("search.danawa.com")  # 최초 호출 - 대기 없음
        fake_now[0] += 2.0
        await throttle.wait("search.danawa.com")  # 10초 중 2초 지남 -> 8초 대기
        await throttle.wait("other.example.com")  # 최초 호출(다른 도메인) - 대기 없음
        fake_now[0] += 0.1
        await throttle.wait("other.example.com")  # 기본 0.5초 중 0.1초 지남 -> 0.4초 대기

    asyncio.run(run())
    assert sleep_calls == pytest.approx([8.0, 0.4])


# -- search_danawa 네트워크 래퍼 (httpx.MockTransport - 실제 소켓 없음) -------------


async def _async_noop(*_args, **_kwargs) -> None:
    return None


_RealAsyncClient = httpx.AsyncClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(**kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(danawa_search._throttle, "wait", _async_noop)
    monkeypatch.setattr(danawa_search.httpx, "AsyncClient", factory)


def test_search_danawa_returns_items_on_200(monkeypatch):
    fixture_html = (FIXTURES / "danawa_search_buds3pro.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture_html)

    _patch_client(monkeypatch, handler)

    items = asyncio.run(danawa_search.search_danawa("테스트 쿼리 200 케이스", limit=3))
    assert len(items) == 3
    assert items[0]["pcode"] == "59537216"


def test_search_danawa_cache_is_not_capped_by_first_callers_limit(monkeypatch):
    """회귀 테스트(2026-08-13: "APLLE 을 선택했을때 시리즈 후보가 너무 적어") -
    같은 query를 먼저 작은 limit(예: 가격표 실측 경로의 3)으로 검색해 캐시해둔
    뒤, 나중에 더 큰 limit(AI 상세검색의 60)으로 같은 query를 검색하면 캐시에
    막혀 3개만 오면 안 된다 - 새 네트워크 요청 없이도 더 많이 돌려줘야 한다."""
    items_html = "".join(_item_html(str(i), f"상품{i}") for i in range(10))
    fixture_html = _search_html(items_html)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text=fixture_html)

    _patch_client(monkeypatch, handler)

    first = asyncio.run(danawa_search.search_danawa("캐시 재사용 테스트 쿼리", limit=3))
    second = asyncio.run(danawa_search.search_danawa("캐시 재사용 테스트 쿼리", limit=8))

    assert len(first) == 3
    assert len(second) == 8
    assert call_count == 1  # 두 번째 호출은 캐시만 썼다 - 네트워크 요청이 다시 나가면 안 된다


def test_search_danawa_raises_on_403(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    _patch_client(monkeypatch, handler)

    with pytest.raises(DanawaSearchBlocked):
        asyncio.run(danawa_search.search_danawa("테스트 쿼리 403 케이스"))


def test_search_danawa_raises_on_429():
    # 429는 403과 동일하게 차단 신호로 취급해야 한다는 것만 별도 확인
    assert 429 in danawa_search._BLOCKED_STATUS_CODES
    assert 403 in danawa_search._BLOCKED_STATUS_CODES


def test_search_danawa_returns_empty_on_connection_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _patch_client(monkeypatch, handler)

    items = asyncio.run(danawa_search.search_danawa("테스트 쿼리 커넥션에러 케이스"))
    assert items == []


def test_search_danawa_no_result_text_returns_empty_without_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<html><body>{danawa_search.NO_RESULT_TEXT}</body></html>")

    _patch_client(monkeypatch, handler)

    items = asyncio.run(danawa_search.search_danawa("테스트 쿼리 결과없음 케이스"))
    assert items == []
