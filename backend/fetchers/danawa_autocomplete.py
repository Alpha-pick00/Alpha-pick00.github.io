"""다나와 실시간 자동완성(JSONP) 어댑터.

다나와 홈페이지가 로드하는 searchAutocompleteLayer_UTF8.js를 실측해 찾은 진짜
엔드포인트 - www.danawa.com/globaljs/com/danawa/common/searchAutocompleteResult.json.php
(JSONP, callback 파라미터). Referer 헤더가 없으면 403이 뜨는 것도 실측 확인했다.

robots.txt(www.danawa.com)에는 search.danawa.com과 달리 Crawl-delay가 없다 -
애초에 이 엔드포인트 자체가 사용자가 타이핑할 때마다(디바운스만 걸고) 매번
부르도록 설계된 자동완성 API라서다. 그래도 예의상 짧은 TTL 캐시 +
도메인별 최소 간격을 둔다(danawa_search.py와 동일 패턴).

이 모듈은 app.autocomplete(로컬 SQLite 인덱스)를 대체하지 않는다 - 그 위에
"다나와에 실제로 있는 상품이면 자동완성에도 뜨게" 보강하는 용도다. 실패하면
(타임아웃/차단/파싱 실패 등 전부) 예외 없이 빈 리스트를 반환해, 로컬 인덱스만으로도
자동완성이 그대로 동작하도록 한다."""

from __future__ import annotations

import json
import logging
import time
from typing import TypedDict
from urllib.parse import quote

import asyncio

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

AUTOCOMPLETE_URL_TEMPLATE = (
    "https://www.danawa.com/globaljs/com/danawa/common/searchAutocompleteResult.json.php"
    "?q={query}&callback=akc"
)
REQUEST_TIMEOUT = 3.0  # 다나와 자신도 2000ms 타임아웃을 쓴다 - 우리도 비슷하게 짧게.
DOMAIN_INTERVAL_SEC = 0.3  # robots.txt에 명시된 값은 없음 - 예의상 두는 최소 간격.
CACHE_TTL_SEC = 300  # 자동완성은 검색결과보다 훨씬 자주 바뀔 필요가 없다.


class _CacheEntry(TypedDict):
    keywords: list[str]
    expires_at: float


class _TTLCache:
    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._store: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> list[str] | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry["expires_at"] < time.monotonic():
                del self._store[key]
                return None
            return entry["keywords"]

    async def set(self, key: str, keywords: list[str]) -> None:
        async with self._lock:
            self._store[key] = {"keywords": keywords, "expires_at": time.monotonic() + self._ttl}


class _Throttle:
    def __init__(self, interval_sec: float) -> None:
        self._interval = interval_sec
        self._last: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last is not None:
                remaining = self._interval - (now - self._last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last = time.monotonic()


_cache = _TTLCache(CACHE_TTL_SEC)
_throttle = _Throttle(DOMAIN_INTERVAL_SEC)


def _parse_jsonp(text: str) -> list[str]:
    """`akc({"keyword":[{"keyword":"...","code":""}, ...]});` 형태를 파싱한다.
    괄호 안쪽만 JSON으로 읽는다 - 콜백 함수명은 우리가 고정으로 보냈으니
    이름 자체는 무시해도 된다."""
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start + 1 : end])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        # 실측(2026-08-11): 쿼리가 깨진 인코딩으로 들어가는 등 비정상 입력에는
        # {"keyword":[...]}가 아니라 빈 배열 등 다른 형태가 오기도 했다.
        return []
    items = data.get("keyword", [])
    if not isinstance(items, list):
        return []
    return [item["keyword"] for item in items if isinstance(item, dict) and item.get("keyword")]


async def autocomplete_danawa(prefix: str, limit: int = 8) -> list[str]:
    """다나와 실시간 자동완성 키워드를 최대 limit개 가져온다. 어떤 이유로든
    실패하면(타임아웃/403/파싱 실패 등) 예외를 던지지 않고 빈 리스트를
    반환한다 - 이 모듈은 항상 "있으면 좋은" 보강 데이터다."""
    prefix = prefix.strip()
    if not prefix:
        return []

    cache_key = prefix.lower()
    cached = await _cache.get(cache_key)
    if cached is not None:
        return cached[:limit]

    await _throttle.wait()
    url = AUTOCOMPLETE_URL_TEMPLATE.format(query=quote(prefix))
    try:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.danawa.com/",
                "Accept": "*/*",
            },
            timeout=REQUEST_TIMEOUT,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.info("danawa autocomplete request failed: %r (%s)", prefix, exc)
        return []

    if resp.status_code != 200:
        logger.info("danawa autocomplete blocked/failed: %r (HTTP %s)", prefix, resp.status_code)
        return []

    keywords = _parse_jsonp(resp.text)
    await _cache.set(cache_key, keywords)
    return keywords[:limit]
