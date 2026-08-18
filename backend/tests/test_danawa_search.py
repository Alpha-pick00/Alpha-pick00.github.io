"""B-3b: 다나와 검색 어댑터(search.danawa.com) 테스트. 네트워크 요청 금지
(conftest의 소켓 차단 fixture 적용) - 네트워크 계층 테스트는 httpx.MockTransport로
전송만 갈아끼운다(실제 소켓을 전혀 만들지 않으므로 차단 fixture와 충돌 없음)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fetchers import danawa_search
from fetchers.danawa_search import (
    DanawaSearchBlocked,
    _DomainThrottle,
    parse_category_breakdown,
    parse_search_html,
)

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


def _category_html(name: str, count: int, subs: list[tuple[str, int]]) -> str:
    subs_html = "".join(
        f'<li><a><span class="tit">{sub_name}</span><span class="count">{sub_count:,}</span></a></li>'
        for sub_name, sub_count in subs
    )
    return f"""
    <div class="main_cate_item">
      <div class="mcl_wrap">
        <h4 class="mcl_tit"><a>{name}</a></h4>
        <span class="count">{count:,}</span>
      </div>
      <div class="layer_cate_depth"><ul class="depth_list">{subs_html}</ul></div>
    </div>
    """


def _category_search_html(items_html: str) -> str:
    return (
        "<html><body><div id='SearchOption_CategoryArea' class='main_cate_area'>"
        f"<div class='main_cate_list'>{items_html}</div></div></body></html>"
    )


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


# -- parse_category_breakdown(대분류/중분류 카테고리 집계) -------------------------


def test_parse_category_breakdown_extracts_group_and_subcategory_counts():
    html = _category_search_html(
        _category_html("태블릿/휴대폰", 202586, [("휴대폰 주변용품", 77372), ("휴대폰", 20469)])
        + _category_html("생활/주방", 84602, [("수납/생활잡화", 73201)])
    )
    groups = parse_category_breakdown(html)
    assert [g["name"] for g in groups] == ["태블릿/휴대폰", "생활/주방"]
    assert groups[0]["count"] == 202586
    assert groups[0]["subcategories"] == [
        {"name": "휴대폰 주변용품", "count": 77372},
        {"name": "휴대폰", "count": 20469},
    ]
    assert groups[1]["subcategories"] == [{"name": "수납/생활잡화", "count": 73201}]


def test_parse_category_breakdown_no_result_text_returns_empty():
    html = f"<html><body>{danawa_search.NO_RESULT_TEXT}</body></html>"
    assert parse_category_breakdown(html) == []


def test_parse_category_breakdown_missing_area_returns_empty():
    assert parse_category_breakdown("<html><body>카테고리 영역 없음</body></html>") == []


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


def test_search_danawa_routes_through_relay_when_configured(monkeypatch):
    """DANAWA_SEARCH_RELAY_URL이 설정돼 있으면(2026-08-18: AWS IP가
    search.danawa.com에서 403으로 차단당해 막히지 않은 로컬 회선의 릴레이를
    거쳐가게 함) search.danawa.com을 직접 때리지 않고 그 릴레이 URL로
    요청해야 한다 - 응답 파싱은 그대로다(릴레이가 상태코드/본문을 그대로
    대리 전달하므로)."""
    fixture_html = (FIXTURES / "danawa_search_buds3pro.html").read_text(encoding="utf-8")
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=fixture_html)

    _patch_client(monkeypatch, handler)
    monkeypatch.setattr(danawa_search, "DANAWA_SEARCH_RELAY_URL", "https://relay.example.com")

    items = asyncio.run(danawa_search.search_danawa("릴레이 라우팅 테스트 쿼리", limit=3))

    assert len(items) == 3
    assert len(seen_urls) == 1
    assert seen_urls[0].startswith("https://relay.example.com/danawa-search?query=")
    assert "search.danawa.com" not in seen_urls[0]


def test_search_danawa_uses_direct_url_when_relay_not_configured(monkeypatch):
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=danawa_search.NO_RESULT_TEXT)

    _patch_client(monkeypatch, handler)
    monkeypatch.setattr(danawa_search, "DANAWA_SEARCH_RELAY_URL", None)

    asyncio.run(danawa_search.search_danawa("릴레이 미설정 테스트 쿼리"))

    assert len(seen_urls) == 1
    assert seen_urls[0].startswith("https://search.danawa.com/dsearch.php")


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


def test_search_danawa_categories_shares_cache_with_search_danawa(monkeypatch):
    """search_danawa()와 search_danawa_categories()는 같은 페이지를 한 번만
    받아와야 한다(_fetch_entry 공유) - 둘 다 부르는 실제 호출자
    (app.debate.check_clarify_facets)가 10초 Crawl-delay를 두 번 태우지
    않기 위한 계약."""
    items_html = _item_html("1", "상품1")
    category_html = _category_html("카테고리A", 100, [("서브A", 10), ("서브B", 5)])
    fixture_html = (
        "<html><body>"
        f"<div id='SearchOption_CategoryArea' class='main_cate_area'>"
        f"<div class='main_cate_list'>{category_html}</div></div>"
        f"<ul class='product_list'>{items_html}</ul>"
        "</body></html>"
    )
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text=fixture_html)

    _patch_client(monkeypatch, handler)

    items = asyncio.run(danawa_search.search_danawa("카테고리 공유 테스트 쿼리", limit=3))
    categories = asyncio.run(danawa_search.search_danawa_categories("카테고리 공유 테스트 쿼리"))

    assert len(items) == 1
    assert categories == [
        {
            "name": "카테고리A",
            "count": 100,
            "subcategories": [{"name": "서브A", "count": 10}, {"name": "서브B", "count": 5}],
        }
    ]
    assert call_count == 1


def test_search_danawa_categories_never_fetches_on_its_own(monkeypatch):
    """search_danawa_categories()는 캐시 전용이다 - 같은 query로
    search_danawa()를 먼저 부른 적이 없으면(캐시 미스) 스스로 네트워크
    요청을 내지 않고 조용히 빈 리스트만 반환해야 한다. 그렇지 않으면
    (fetchers.danawa_search.search_danawa만 monkeypatch하는 기존 테스트들처럼)
    이 함수를 호출하는 쪽이 캐시를 우회한 가짜 search_danawa 뒤에서 실제
    네트워크 요청을 새로 내버리는 회귀가 생긴다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("search_danawa_categories가 직접 네트워크 요청을 내면 안 된다")

    _patch_client(monkeypatch, handler)

    categories = asyncio.run(danawa_search.search_danawa_categories("캐시에 없는 쿼리"))
    assert categories == []
