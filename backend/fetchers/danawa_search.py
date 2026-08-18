"""다나와 통합검색(search.danawa.com)에서 쿼리로 pcode를 직접 찾는 어댑터.

B-3a 실측으로 확정된 전제 두 가지:
  1) 검색결과에 임베드된 div.prod_pricelist는 판매처 목록이 아니라 카테고리
     (정품/해외구매/중고)별 최저가 요약 1줄씩이다. bridge_url도 없어서 이걸로
     구매 링크를 만들 수 없다 - 그래서 이 모듈은 pcode/상품명/총 몰 수만
     뽑고, 실제 판매처 가격표는 여전히 fetchers.danawa.fetch_danawa_offers()가
     상세페이지를 따로 페치해서 얻는다.
  2) search.danawa.com/robots.txt가 Crawl-delay: 10을 명시한다. 이건 서비스
     전체 상한(시간당 360건)을 만드는 값이라 런타임 경로로 쓰기 어렵다 -
     그래서 run_single_debate 등 파이프라인 어디에도 이 모듈을 연결하지
     않는다(B-3c). B-4 오프라인 측정 전용이다.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TypedDict
from urllib.parse import quote, urlsplit

import asyncio

import httpx
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_DOMAIN = "search.danawa.com"
REQUEST_TIMEOUT = 5.0
MAX_RETRIES = 1  # 403은 이 예산과 무관하게 즉시 포기 - fetchers.danawa와 동일 정책

# robots.txt(search.danawa.com)에 명시된 값. 절대 낮추지 않는다 - 지키지 않으면
# 시간당 360건이라는 서비스 전체 상한을 넘겨 차단 위험을 스스로 키우는 셈이다.
SEARCH_CRAWL_DELAY_SEC = 10.0
DEFAULT_DOMAIN_INTERVAL_SEC = 0.5  # search.danawa.com 외 도메인 기본값(prod.danawa.com은 fetchers.danawa 쪽에서 이미 0.5초로 관리)
DOMAIN_INTERVALS_SEC: dict[str, float] = {
    SEARCH_DOMAIN: SEARCH_CRAWL_DELAY_SEC,
}

# 검색결과 구성(어떤 상품이 몇 위인지)은 개별 상품 가격보다 덜 바뀐다고 보고
# fetchers.danawa의 상품 페이지 캐시(20분)보다 길게 잡는다.
SEARCH_CACHE_TTL_SEC = 60 * 60

NO_RESULT_TEXT = "검색결과가 없습니다"
SEARCH_URL_TEMPLATE = "https://search.danawa.com/dsearch.php?query={query}"


class DanawaSearchBlocked(RuntimeError):
    """403/429를 만났을 때만 던진다 - 그 외 실패(타임아웃, 파싱 실패, 결과
    없음)는 전부 빈 리스트로 조용히 처리한다는 계약을 유지한다.

    이건 의도적으로 "예외 없이 빈 리스트 반환" 원칙의 유일한 예외다: 차단을
    빈 리스트로 삼키면 배치 호출자가 "진짜로 상품이 없다"와 "막혔다"를
    구분할 수 없어서, B-4처럼 "403/429 시 즉시 전체 중단"이 요구되는
    호출자가 안전하게 멈출 방법이 없어진다."""

    def __init__(self, status_code: int, query: str) -> None:
        super().__init__(f"danawa search blocked (HTTP {status_code}) for query={query!r}")
        self.status_code = status_code
        self.query = query


class DanawaSearchItem(TypedDict):
    pcode: str
    product_name: str
    # "정품" 카테고리 행의 "N몰" 숫자(등록된 판매처 수 집계). 못 찾으면 None.
    # 상세페이지 결과(fetchers.danawa.DanawaResult)에 병합하는 경로는 아직 없다.
    total_mall_count: int | None


class DanawaSubCategory(TypedDict):
    name: str
    count: int


class DanawaCategoryGroup(TypedDict):
    name: str
    count: int
    subcategories: list[DanawaSubCategory]


def _has_class(tag: str, class_name: str) -> str:
    """BeautifulSoup의 `tag.class_name` CSS 선택자와 동일한(토큰 단위) class
    매칭을 XPath로 표현한다. `contains(@class, ...)`만 쓰면 예를 들어
    class="prod_item_ad"도 "prod_item"에 잘못 걸릴 수 있어 양옆에 공백을
    덧붙인 뒤 대조한다."""
    return f".//{tag}[contains(concat(' ', normalize-space(@class), ' '), ' {class_name} ')]"


def _text_with_spaces(el) -> str:
    """BeautifulSoup의 get_text(' ', strip=True)와 동일한 효과 - <b> 같은
    강조 태그로 텍스트 조각이 나뉘어 있어도 조각 사이에 공백을 넣어 합친다
    (B-2 실측: 안 하면 "삼성전자갤럭시버즈3프로"처럼 토큰이 붙어버린다)."""
    return " ".join(t.strip() for t in el.xpath(".//text()") if t.strip())


def _extract_total_mall_count(item_li) -> int | None:
    """li.prod_item 안 div.prod_pricelist에서 "정품" 카테고리 행만 골라 "N몰"
    숫자를 뽑는다. 한 상품에 정품/해외구매/중고 행이 섞여 나올 수 있어(B-3a
    실측) "정품"이 명시된 행이 아니면 무시한다."""
    pricelists = item_li.xpath(_has_class("div", "prod_pricelist"))
    if not pricelists:
        return None
    for row in pricelists[0].xpath(".//li[starts-with(@id, 'productInfoDetail_')]"):
        text = _text_with_spaces(row)
        if "정품" not in text:
            continue
        match = re.search(r"(\d+)\s*몰", text)
        if match:
            return int(match.group(1))
    return None


def parse_search_html(html: str, limit: int = 5) -> list[DanawaSearchItem]:
    """네트워크 없이 순수하게 검색결과 HTML만 파싱한다(parse_danawa_html과 같은
    패턴 - 테스트는 전부 이 함수를 통해서 한다).

    BeautifulSoup 대신 lxml.html을 직접 쓴다 - "노트북"처럼 결과가 많은
    쿼리는 검색결과 페이지가 5MB를 넘는데, BeautifulSoup의 트리 구성
    오버헤드만으로 5.8초가 걸리는 걸 실측했다(lxml 직접 파싱은 0.3초).
    사용자가 "검색 하나에 15초"라고 보고한 지연의 실제 원인이었다."""
    if NO_RESULT_TEXT in html:
        return []

    doc = lxml_html.fromstring(html)
    items: list[DanawaSearchItem] = []
    seen_pcodes: set[str] = set()

    for li in doc.xpath(_has_class("li", "prod_item")):
        if len(items) >= limit:
            break
        # 방어 코드 - 정적 HTML의 li.prod_item에는 파워쇼핑 광고가 원래 섞이지
        # 않는다는 걸 B-2/B-3a에서 확인했지만(<template> 안에만 있음), 혹시
        # 모를 구조 변경에 대비해 남겨둔다.
        if li.xpath(_has_class("span", "icon__ad")):
            continue

        name_links = li.xpath(_has_class("p", "prod_name") + "/a")
        if not name_links:
            continue
        # <b> 강조 태그로 토큰이 사이 공백 없이 붙어버리는 문제(B-2 실측) -
        # separator를 반드시 줘야 "삼성전자갤럭시버즈3프로"가 아니라
        # "삼성전자 갤럭시 버즈3 프로"로 나온다.
        product_name = _text_with_spaces(name_links[0])
        if not product_name:
            continue

        code_els = li.xpath(".//*[@data-product-code]")
        pcode = code_els[0].get("data-product-code") if code_els else None
        if not pcode or pcode in seen_pcodes:
            continue
        seen_pcodes.add(pcode)

        items.append(
            {
                "pcode": pcode,
                "product_name": product_name,
                "total_mall_count": _extract_total_mall_count(li),
            }
        )

    return items


def _parse_count(text: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else None


def parse_category_breakdown(html: str) -> list[DanawaCategoryGroup]:
    """검색결과 페이지에 함께 내려오는 실측 카테고리 집계(대분류별 건수 +
    중분류별 건수, div#SearchOption_CategoryArea)를 파싱한다.

    B-3d 실측(2026-08-18, 사용자 리포트 "샤오미로 검색하면 AI 상세검색
    카테고리에 휴대폰이 안 나온다") - li.prod_item 상품명 표본(parse_search_html,
    최대 90개)은 다나와 검색 순위 상위에 쏠려 있어서, 특정 대분류 상품이 표본에
    아예 안 걸리면 그 카테고리는 영원히 못 본다(실측: "샤오미" 상위 40개가 전부
    생활가전/액세서리라 휴대폰이 하나도 없었다 - 실제로는 다나와에 있다,
    "샤오미 스마트폰"으로 검색하면 바로 나온다). 이 집계는 표본이 아니라 다나와
    자체 카테고리 색인(대분류당 수만 건 단위)이라 표본 편향에서 자유롭다."""
    if NO_RESULT_TEXT in html:
        return []

    doc = lxml_html.fromstring(html)
    groups: list[DanawaCategoryGroup] = []

    for item_el in doc.xpath(_has_class("div", "main_cate_item")):
        wraps = item_el.xpath(_has_class("div", "mcl_wrap"))
        if not wraps:
            continue
        name_links = wraps[0].xpath(_has_class("h4", "mcl_tit") + "/a")
        count_spans = wraps[0].xpath(_has_class("span", "count"))
        if not name_links or not count_spans:
            continue
        name = _text_with_spaces(name_links[0])
        count = _parse_count(count_spans[0].text_content())
        if not name or count is None:
            continue

        subcategories: list[DanawaSubCategory] = []
        for li in item_el.xpath(_has_class("ul", "depth_list") + "/li"):
            sub_titles = li.xpath(_has_class("span", "tit"))
            sub_counts = li.xpath(_has_class("span", "count"))
            if not sub_titles or not sub_counts:
                continue
            sub_name = _text_with_spaces(sub_titles[0])
            sub_count = _parse_count(sub_counts[0].text_content())
            if not sub_name or sub_count is None:
                continue
            subcategories.append({"name": sub_name, "count": sub_count})

        groups.append({"name": name, "count": count, "subcategories": subcategories})

    return groups


# ---------------------------------------------------------------------------
# 네트워크 계층 - TTL 캐시 + 도메인별(값이 다른) 요청 간격 제한.
# fetchers.danawa의 동일 패턴을 따르되, search.danawa.com만 10초로 분리한다.
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    items: list[DanawaSearchItem]
    categories: list[DanawaCategoryGroup]
    expires_at: float


class _TTLCache:
    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._store: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> _CacheEntry | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                del self._store[key]
                return None
            return entry

    async def set(
        self, key: str, items: list[DanawaSearchItem], categories: list[DanawaCategoryGroup]
    ) -> None:
        async with self._lock:
            self._store[key] = _CacheEntry(
                items=items, categories=categories, expires_at=time.monotonic() + self._ttl
            )


class _DomainThrottle:
    """도메인별로 다른 간격을 줄 수 있는 요청 간격 제한기. search.danawa.com은
    10초(robots.txt Crawl-delay), 그 외 도메인은 기본값을 쓴다."""

    def __init__(self, intervals: dict[str, float], default_interval: float) -> None:
        self._intervals = intervals
        self._default = default_interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, domain: str) -> None:
        interval = self._intervals.get(domain, self._default)
        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last.get(domain)
            if last is not None:
                remaining = interval - (now - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last[domain] = time.monotonic()


_cache = _TTLCache(SEARCH_CACHE_TTL_SEC)
_throttle = _DomainThrottle(DOMAIN_INTERVALS_SEC, DEFAULT_DOMAIN_INTERVAL_SEC)


def _normalize_query(query: str) -> str:
    return " ".join(query.split()).lower()


_BLOCKED_STATUS_CODES = {403, 429}


async def _fetch_html(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response | None, str | None]:
    """(response, error) 반환. 403/429는 재시도하지 않고 즉시 포기 -
    fetchers.danawa와 동일 정책(429는 여기서 새로 추가 - 차단 신호라는 점은
    403과 같다)."""
    last_error: str | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        if resp.status_code in _BLOCKED_STATUS_CODES:
            return resp, str(resp.status_code)
        if resp.status_code >= 400:
            last_error = f"HTTP {resp.status_code}"
            continue
        return resp, None

    return None, last_error


# search_danawa()의 캐시는 query만 키로 쓰고 limit은 안 쓴다 - 호출자마다 필요한
# 개수가 다르다(가격표 실측 경로는 3~5개, AI 상세검색은 30개 이상). limit도 캐시
# 키에 넣으면, 먼저 작은 limit으로 호출한 쪽이 캐시해둔 뒤 나중에 큰 limit으로
# 같은 query를 부른 호출자가 그 적은 개수에 그대로 발이 묶인다(2026-08-13 실측 -
# "APPLE을 선택했을때 시리즈 후보가 너무 적어"의 원인 중 하나였다: clarify가 이미
# 캐시해둔 걸 재사용할 때 원래 요청보다 표본이 부족했다). 그래서 항상 이 상한까지
# 파싱해서 캐시하고, 호출자별 limit은 캐시에서 슬라이스만 한다 - 페이지에 이보다
# 적게 있으면 파싱이 자연히 그만큼만 끝나므로(HTML에 없는 걸 만들어내지 않는다) 손해가 없다.
SEARCH_PAGE_PARSE_LIMIT = 90


async def search_danawa(query: str, limit: int = 5) -> list[DanawaSearchItem]:
    """다나와 통합검색에서 쿼리 하나로 pcode 최대 limit개를 찾는다.

    403/429(DanawaSearchBlocked)를 빼면 예외를 던지지 않는다 - 그 외 실패는
    빈 리스트로 반환한다(fetchers.danawa의 "본 파이프라인을 절대 막지
    않는다" 원칙과 동일).
    """
    cache_key = _normalize_query(query)
    cached = await _cache.get(cache_key)
    if cached is not None:
        return cached.items[:limit]

    url = SEARCH_URL_TEMPLATE.format(query=quote(query))
    domain = urlsplit(url).netloc.lower()

    await _throttle.wait(domain)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp, error = await _fetch_html(client, url)
    except DanawaSearchBlocked:
        raise
    except Exception:  # noqa: BLE001 - 차단 신호(위)를 빼면 무슨 일이 있어도 예외를 던지지 않는다
        logger.exception("danawa search request crashed: %s", query)
        return []

    if resp is not None and resp.status_code in _BLOCKED_STATUS_CODES:
        raise DanawaSearchBlocked(resp.status_code, query)

    if resp is None or error is not None:
        logger.info("danawa search fetch failed: %s (%s)", query, error)
        return []

    items = parse_search_html(resp.text, limit=SEARCH_PAGE_PARSE_LIMIT)
    categories = parse_category_breakdown(resp.text)
    await _cache.set(cache_key, items, categories)
    return items[:limit]


async def search_danawa_categories(query: str) -> list[DanawaCategoryGroup]:
    """같은 검색결과 페이지에서 얻은 카테고리 집계(대분류/중분류별 건수)를
    반환한다 - 이 함수 스스로는 절대 네트워크 요청을 내지 않는다(캐시 전용).
    반드시 같은 query로 search_danawa()를 먼저 호출해 캐시를 채워둔 뒤
    불러야 한다(app.debate.check_clarify_facets가 items를 먼저 가져온
    뒤에만 이 함수를 부르는 식으로 이 순서를 지킨다) - 캐시에 없으면(아직
    안 불렀거나, 만료됐거나, search_danawa 자체가 실패해 캐시되지 않았으면)
    조용히 빈 리스트를 반환한다. 이 함수가 스스로 다시 요청을 낸다면
    search_danawa()가 이미 낸 요청과 별개로 10초 Crawl-delay를 한 번 더
    태우게 되므로 절대 그렇게 하지 않는다."""
    cached = await _cache.get(_normalize_query(query))
    return cached.categories if cached is not None else []
