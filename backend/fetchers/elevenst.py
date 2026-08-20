"""11번가 오픈API(ProductSearch) 어댑터 - 다나와/Tavily를 대체하는 검색
백엔드(2026-08-20, "11번가 api를 구해서 다나와를 폐기하고 11번가 쪽으로
방향을 틀려고"). 일반(비셀러) 키로 열리는 API는 ProductSearch 하나뿐이다 -
상세설명/원재료명 같은 정보는 이 API에 없다(openapi.11st.co.kr 개발가이드
실측 확인). 검색 결과의 상품명/가격/판매자/리뷰수 정도만 얻을 수 있다.

응답은 EUC-KR로 인코딩된 XML이다. 파이썬 기본 expat 파서는 EUC-KR 같은
멀티바이트 인코딩의 XML 선언(<?xml ... encoding="EUC-KR"?>)을 직접 못 읽는다
(실측: "multi-byte encodings are not supported") - 그래서 바이트를 EUC-KR로
직접 디코딩한 뒤, 선언부만 UTF-8로 바꿔 재인코딩해서 ET.fromstring에 넘긴다.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

BASE_URL = "http://openapi.11st.co.kr/openapi/OpenApiService.tmall"

REQUEST_TIMEOUT = 10.0


class ElevenstApiError(RuntimeError):
    pass


@dataclass
class Product:
    code: str
    name: str
    price: int | None
    sale_price: int | None
    image_url: str | None
    seller_nick: str | None
    detail_url: str | None
    delivery: str | None
    review_count: int | None
    buy_satisfy: int | None
    discount: int | None


@dataclass
class Category:
    name: str
    count: int


@dataclass
class SearchResult:
    total_count: int
    products: list[Product]
    categories: list[Category]


def _text(el: ET.Element | None, tag: str) -> str | None:
    if el is None:
        return None
    value = el.findtext(tag)
    return value.strip() if value else None


def _int(el: ET.Element | None, tag: str) -> int | None:
    text = _text(el, tag)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_product(el: ET.Element) -> Product:
    benefit = el.find("Benefit")
    return Product(
        code=_text(el, "ProductCode") or "",
        name=_text(el, "ProductName") or "",
        price=_int(el, "ProductPrice"),
        sale_price=_int(el, "SalePrice"),
        image_url=_text(el, "ProductImage300") or _text(el, "ProductImage"),
        seller_nick=_text(el, "SellerNick") or _text(el, "Seller"),
        detail_url=_text(el, "DetailPageUrl"),
        delivery=_text(el, "Delivery"),
        review_count=_int(el, "ReviewCount"),
        buy_satisfy=_int(el, "BuySatisfy"),
        discount=_int(benefit, "Discount") if benefit is not None else None,
    )


def _parse_category(el: ET.Element) -> Category:
    return Category(name=_text(el, "CategoryName") or "", count=_int(el, "CategoryPrdCnt") or 0)


def _parse_response(content: bytes) -> SearchResult:
    """순수 함수 - 네트워크 없이 XML 바이트만 파싱한다. 테스트는 전부 이
    함수를 통해서 한다(search_products는 이 함수를 감싸는 네트워크 래퍼일 뿐)."""
    try:
        text = content.decode("euc-kr")
    except UnicodeDecodeError as exc:
        raise ElevenstApiError(f"EUC-KR 디코딩 실패: {exc}") from exc
    text = text.replace('encoding="EUC-KR"', 'encoding="UTF-8"', 1)

    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ElevenstApiError(f"응답 파싱 실패: {exc}") from exc

    error_code = root.findtext(".//ErrorCode") or root.findtext(".//Error/Code")
    if error_code:
        message = root.findtext(".//ErrorMessage") or root.findtext(".//Error/Message") or "알 수 없는 오류"
        raise ElevenstApiError(f"11번가 API 오류 {error_code}: {message}")

    products_el = root.find("Products")
    total_count = _int(products_el, "TotalCount") or 0
    products = [_parse_product(p) for p in root.findall(".//Products/Product")]

    categories = [_parse_category(c) for c in root.findall(".//Categories/Category")]

    return SearchResult(total_count=total_count, products=products, categories=categories)


# 같은 요청 안에서 검색 단계(app.search._elevenst_search, _SearchNode)와 제안
# 단계(adk_pipeline._ElevenstFetchNode)가 refine 제거 이후 같은 질의 문자열로
# 이 API를 각자 독립적으로 불러, 매 요청 11번가 호출이 2번씩 나가고 있었다
# (2026-08-20, LLM/API 비용 점검 중 발견 - 둘 다 page_size=20 기본값을 쓰고,
# 파이프라인상 검색 단계가 끝난 직후 propose_parallel이 바로 이어받는 구조라
# 몇 초 안에 붙어서 일어난다). fetchers.danawa_search._cache(1시간 TTL)와 같은
# 패턴으로 짧은 TTL 캐시를 두면, 그 두 호출을 굳이 상태로 엮지 않고도 두
# 번째 호출이 그냥 캐시를 맞게 만들 수 있다 - 가격 신선도에 미치는 영향은
# danawa_search의 1시간 TTL보다 훨씬 짧아 무시할 만하다.
_RECENT_CACHE_TTL_SEC = 60.0


class _RecentCache:
    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._store: dict[tuple, tuple[float, SearchResult]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: tuple) -> SearchResult | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if expires_at < time.monotonic():
                del self._store[key]
                return None
            return result

    async def set(self, key: tuple, result: SearchResult) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, result)


_recent_cache = _RecentCache(_RECENT_CACHE_TTL_SEC)


async def search_products(
    api_key: str,
    keyword: str,
    page_num: int = 1,
    page_size: int = 20,
    include_categories: bool = False,
    timeout: float = REQUEST_TIMEOUT,
) -> SearchResult:
    """상품검색(ProductSearch) API 1건 비동기 호출. 실패/차단 시 ElevenstApiError.

    동기 httpx.get이 아니라 반드시 비동기로 호출해야 한다 - 호출부
    (adk_pipeline._ElevenstFetchNode)가 propose_parallel(ParallelAgent) 소속이라
    Qwen/Groq/DeepSeek LLM 호출과 같은 이벤트 루프에서 동시 실행되는데, 동기
    호출은 그 응답을 기다리는 동안 이벤트 루프 전체를 막아 다른 동시 호출까지
    지연시킨다.

    같은 (api_key, keyword, page_num, page_size, include_categories) 조합은
    _RECENT_CACHE_TTL_SEC 안에서는 API를 다시 부르지 않고 방금 받은 결과를
    그대로 재사용한다 - 위 _RecentCache 설명 참고."""
    cache_key = (api_key, keyword, page_num, page_size, include_categories)
    cached = await _recent_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "key": api_key,
        "apiCode": "ProductSearch",
        "keyword": keyword,
        "pageNum": str(page_num),
        "pageSize": str(page_size),
    }
    if include_categories:
        params["option"] = "Categories"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(BASE_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ElevenstApiError(f"요청 실패: {exc}") from exc

    result = _parse_response(resp.content)
    await _recent_cache.set(cache_key, result)
    return result
