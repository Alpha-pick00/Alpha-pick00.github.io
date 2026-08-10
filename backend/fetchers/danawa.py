"""다나와 상품 페이지를 "가격 데이터 소스"로 쓰는 어댑터.

다나와는 최종 추천 대상이 아니다(수수료 0) — 상품 페이지 하나에 판매처별
가격표(ul.list__mall-price)가 정적 HTML로 통째로 들어있다는 걸 이용해,
쿠팡/SSG처럼 직접 페치가 막힌 판매처의 가격까지 간접적으로 확보하는 데 쓴다.
구조는 scripts/probe_danawa.py의 STEP 1 실측으로 확정했다.

설계상 중요한 제약(STEP 2 지시서):
- 판매처 각각의 bridge_url(다나와 중계 URL)은 저장만 하고 절대 페치하지
  않는다. fetch_danawa_offers()는 다나와 상품 페이지 1번만 페치한다.
- resolve_outlink()는 최종 추천으로 확정된 offer 1건에 대해서만, 파이프라인이
  아니라 호출자가 명시적으로 불러야 한다(STEP 3에서 연결 예정, 이 파일은
  함수만 제공하고 어디서도 자동 호출하지 않는다).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 5.0
MAX_CONCURRENCY = 3
PER_DOMAIN_INTERVAL_SEC = 0.5
MAX_RETRIES = 1  # 403은 이 재시도 예산과 무관하게 즉시 포기(아래 _fetch_html 참고)
CACHE_TTL_SEC = 20 * 60

MIN_VALID_PRICE = 1
MAX_VALID_PRICE = 10_000_000

BRIDGE_TARGET_PATTERN = re.compile(r'goLink\("([^"]+)"\)')

# 원문(raw_seller)에 배송사/부가 문구가 붙는 명백한 동일 판매처 변형만
# 정규화한다. 이마트몰/신세계몰/SSG.COM처럼 실제로 다나와가 서로 다른
# 행(다른 link_pcode, 다른 가격일 수 있음)으로 취급하는 것들은 섣불리
# 합치지 않는다 — STEP 1 실측에서 이 셋이 같은 상품 페이지에 별도 행으로
# 동시에 나온 걸 확인했다.
SELLER_ALIASES: dict[str, str] = {
    "쿠팡": "쿠팡",
    "쿠팡 로켓배송": "쿠팡",
    "쿠팡로켓배송": "쿠팡",
    "coupang": "쿠팡",
    "11번가": "11번가",
    "11st": "11번가",
    "g마켓": "G마켓",
    "지마켓": "G마켓",
    "gmarket": "G마켓",
    "옥션": "옥션",
    "auction": "옥션",
    "ssg.com": "SSG",
    "ssg": "SSG",
}

# STEP 3에서 쿠팡 파트너스 제휴 링크를 만들 때 쓸 상품 식별자 추출 규칙.
# 지금은 쿠팡만 확인했다(STEP 1에서 실제로 이 패턴까지 리다이렉트되는 걸
# 검증함) — 다른 몰은 브릿지를 실제로 따라가 본 적이 없어 규칙을 못 넣는다.
_PRODUCT_ID_PATTERNS: dict[str, re.Pattern] = {
    "coupang.com": re.compile(r"/vp/products/(\d+)"),
}


class DanawaOffer(TypedDict):
    seller: str
    raw_seller: str
    price_krw: int
    delivery_text: str | None
    bridge_url: str | None
    resolved_url: str | None
    product_id: str | None


class DanawaResult(TypedDict):
    source_url: str
    product_name: str | None
    offers: list[DanawaOffer]
    fetched_at: str
    parse_status: str  # "ok" | "expired" | "partial" | "failed"


def normalize_seller(raw: str) -> str:
    return SELLER_ALIASES.get(raw.strip().lower(), raw.strip())


def normalize_danawa_url(url: str) -> str:
    """캐시 키용. 트레일링 슬래시(/info/?pcode= vs /info?pcode=)나 쿼리 순서
    차이로 같은 상품이 다른 캐시 항목이 되는 걸 막는다."""
    parts = urlsplit(url)
    query_pairs = sorted(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query_pairs), "")
    )


def _is_expired_page(html: str) -> bool:
    """STEP 1에서 발견한 "가격비교 서비스가 종료된 상품" 페이지 패턴.
    JS alert + location.replace가 있고 페이지가 짧다(정상 상품 페이지는
    120,000자 이상, 이 페이지는 150자)."""
    return len(html) < 1000 and "location.replace" in html


def _product_name(soup: BeautifulSoup) -> str | None:
    """대표 이미지의 alt="{상품명}_이미지" 패턴에서 뽑는다(STEP 1에서 실제로
    관찰한 패턴). 못 찾으면 <title>로 폴백 — 신뢰도는 이미지 alt보다 낮다."""
    img = soup.select_one('img[alt$="_이미지"]')
    if img and img.get("alt"):
        name = img["alt"][: -len("_이미지")].strip()
        if name:
            return name
    if soup.title and soup.title.string:
        text = soup.title.string.strip()
        if text:
            return text
    return None


def _seller_from_li(li) -> tuple[str, str] | None:
    """(raw_seller, normalized_seller)를 반환. 판매처를 특정할 수 없으면 None —
    광고/빈 슬롯 등 예상 밖의 li가 섞여도 예외 없이 건너뛰기 위함."""
    img = li.select_one(".box__logo img")
    if img and img.get("alt"):
        raw = img["alt"].strip()
        if raw:
            return raw, normalize_seller(raw)
    logo_span = li.select_one(".box__logo .text__logo")
    if logo_span is not None:
        raw = (logo_span.get("aria-label") or logo_span.get_text(strip=True) or "").strip()
        if raw:
            return raw, normalize_seller(raw)
    return None


def _price_from_li(li) -> int | None:
    price_el = li.select_one(".sell-price .text__num")
    if price_el is None:
        return None
    digits = re.sub(r"[^\d]", "", price_el.get_text())
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    if not (MIN_VALID_PRICE <= value <= MAX_VALID_PRICE):
        return None
    return value


def _delivery_text(li) -> str | None:
    el = li.select_one(".box__delivery")
    if el is None:
        return None
    text = el.get_text(strip=True)
    return text or None


def _bridge_url(li) -> str | None:
    link = li.select_one("a.link__full-cover")
    if link is None:
        return None
    href = link.get("href")
    return href or None


def _parse_offer(li) -> DanawaOffer | None:
    seller_info = _seller_from_li(li)
    if seller_info is None:
        return None
    raw_seller, seller = seller_info

    price_krw = _price_from_li(li)
    if price_krw is None:
        return None

    return {
        "seller": seller,
        "raw_seller": raw_seller,
        "price_krw": price_krw,
        "delivery_text": _delivery_text(li),
        "bridge_url": _bridge_url(li),
        "resolved_url": None,
        "product_id": None,
    }


def parse_danawa_html(source_url: str, html: str, fetched_at: str | None = None) -> DanawaResult:
    """네트워크 없이 순수하게 HTML만 파싱한다 — 테스트는 전부 이 함수를 통해서
    한다(fetch_danawa_offers는 이 함수를 감싸는 네트워크 래퍼일 뿐)."""
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

    if _is_expired_page(html):
        logger.info("danawa page expired (not an error): %s", source_url)
        return {
            "source_url": source_url,
            "product_name": None,
            "offers": [],
            "fetched_at": fetched_at,
            "parse_status": "expired",
        }

    soup = BeautifulSoup(html, "lxml")
    product_name = _product_name(soup)

    mall_list = soup.select_one("ul.list__mall-price")
    raw_items = mall_list.select("li.list-item") if mall_list is not None else []

    offers: list[DanawaOffer] = []
    for li in raw_items:
        offer = _parse_offer(li)
        if offer is not None:
            offers.append(offer)

    if not offers:
        status = "failed"
    elif len(offers) < len(raw_items):
        status = "partial"
    else:
        status = "ok"

    return {
        "source_url": source_url,
        "product_name": product_name,
        "offers": offers,
        "fetched_at": fetched_at,
        "parse_status": status,
    }


def _failed_result(source_url: str) -> DanawaResult:
    return {
        "source_url": source_url,
        "product_name": None,
        "offers": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "parse_status": "failed",
    }


# ---------------------------------------------------------------------------
# 네트워크 계층 — TTL 캐시 + in-flight 병합 + 동시성/도메인별 요청 간격 제한.
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    result: DanawaResult
    expires_at: float


class _TTLCache:
    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._store: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> DanawaResult | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                del self._store[key]
                return None
            return entry.result

    async def set(self, key: str, result: DanawaResult) -> None:
        async with self._lock:
            self._store[key] = _CacheEntry(result=result, expires_at=time.monotonic() + self._ttl)


class _DomainThrottle:
    def __init__(self, interval_sec: float) -> None:
        self._interval = interval_sec
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, domain: str) -> None:
        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last.get(domain)
            if last is not None:
                remaining = self._interval - (now - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last[domain] = time.monotonic()


_cache = _TTLCache(CACHE_TTL_SEC)
_inflight: dict[str, asyncio.Task] = {}
_inflight_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
_throttle = _DomainThrottle(PER_DOMAIN_INTERVAL_SEC)


async def _fetch_html(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response | None, str | None]:
    """(response, error) 반환. 403은 재시도하지 않고 즉시 포기 — 그 외
    (타임아웃/커넥션 오류/403 외 4xx·5xx)만 MAX_RETRIES 안에서 재시도한다."""
    last_error: str | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        if resp.status_code == 403:
            return resp, "403"
        if resp.status_code >= 400:
            last_error = f"HTTP {resp.status_code}"
            continue
        return resp, None

    return None, last_error


async def _fetch_and_parse(url: str, cache_key: str) -> DanawaResult:
    domain = urlsplit(url).netloc.lower()
    async with _semaphore:
        await _throttle.wait(domain)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp, error = await _fetch_html(client, url)

    if resp is None or error is not None:
        logger.info("danawa fetch failed: %s (%s)", url, error)
        result = _failed_result(url)
    else:
        result = parse_danawa_html(url, resp.text)

    # expired/failed도 캐시한다 — 재요청 자체가 (특히 차단 상황에서) 낭비다.
    await _cache.set(cache_key, result)
    return result


async def fetch_danawa_offers(url: str) -> DanawaResult:
    """다나와 상품 페이지 1건을 페치해 판매처별 가격을 파싱한다.

    bridge_url은 저장만 하고 절대 페치하지 않는다 — 판매처가 10개면 그만큼
    있는 bridge_url을 전부 따라가는 순간 후보 1개당 20+ 요청이 되어 버려서
    (STEP 1에서 확인) 차단 위험이 급격히 커진다. 최종 URL이 필요하면
    resolve_outlink()를 최종 추천 1건에 대해서만 별도로 호출할 것."""
    cache_key = normalize_danawa_url(url)

    cached = await _cache.get(cache_key)
    if cached is not None:
        return cached

    async with _inflight_lock:
        task = _inflight.get(cache_key)
        if task is None:
            task = asyncio.ensure_future(_fetch_and_parse(url, cache_key))
            _inflight[cache_key] = task

    try:
        return await task
    finally:
        async with _inflight_lock:
            if _inflight.get(cache_key) is task:
                del _inflight[cache_key]


# ---------------------------------------------------------------------------
# 아웃링크 해석 — 파이프라인에서 자동 호출하지 않는다(STEP 3 지시서 대기).
# ---------------------------------------------------------------------------


def extract_product_id(url: str) -> str | None:
    """알려진 도메인에서만 상품 ID를 뽑는다. 쿠팡 외에는 실제로 브릿지를
    따라가 본 적이 없어 규칙이 없다 — itemId/vendorItemId 등 부가 식별자는
    resolved_url 자체에 쿼리 파라미터로 남아있으니 필요하면 거기서 다시
    읽으면 된다(이 함수는 대표 productId 하나만 뽑는다)."""
    domain = urlsplit(url).netloc.lower()
    for host_suffix, pattern in _PRODUCT_ID_PATTERNS.items():
        if host_suffix in domain:
            match = pattern.search(urlsplit(url).path)
            if match:
                return match.group(1)
    return None


async def resolve_outlink(bridge_url: str) -> tuple[str | None, str | None]:
    """bridge_url(다나와 중계 페이지) 하나를 해석해 (resolved_url, product_id)를
    반환한다. 호출자가 명시적으로 불러야 한다 — fetch_danawa_offers()나 다른
    어디에서도 자동 호출되지 않는다.

    2번의 HTTP 요청이 필요하다:
      1) bridge_url을 페치해 HTML 안의 goLink("...") 문자열에서 다나와의
         제휴 리다이렉트 URL을 정규식으로 뽑는다(JS 실행 없이 가능 — STEP 1에서
         실측 확인).
      2) 그 제휴 리다이렉트 URL을 follow_redirects로 최종 목적지까지
         추적한다. 최종 응답 자체가 403이어도 상관없다 — 본문이 아니라
         `response.url`만 필요하기 때문이다(STEP 1에서 실측: 쿠팡 최종
         상품 페이지는 GET하면 403이지만, 리다이렉트 추적으로 그 URL을
         얻는 것 자체는 된다). 그래서 2번째 요청은 _fetch_html의 403-포기
         로직을 타지 않고, 상태코드와 무관하게 response.url을 그대로 쓴다.
    """
    bridge_domain = urlsplit(bridge_url).netloc.lower()
    async with _semaphore:
        await _throttle.wait(bridge_domain)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            resp, error = await _fetch_html(client, bridge_url)

    if resp is None:
        logger.info("danawa outlink resolve failed at bridge hop: %s (%s)", bridge_url, error)
        return None, None

    match = BRIDGE_TARGET_PATTERN.search(resp.text)
    if not match:
        return None, None
    affiliate_url = match.group(1)

    affiliate_domain = urlsplit(affiliate_url).netloc.lower()
    async with _semaphore:
        await _throttle.wait(affiliate_domain)
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                resp2 = await client.get(affiliate_url)
        except httpx.HTTPError as exc:
            logger.info("danawa outlink resolve failed at affiliate hop: %s (%s)", affiliate_url, exc)
            return None, None

    resolved_url = str(resp2.url)
    return resolved_url, extract_product_id(resolved_url)
