import asyncio
import logging

import httpx

from . import embeddings, google_merchant, search_cache
from .config import settings
from .schemas import SearchResult

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# frontend/src/app/components/About.tsx의 "We Compare across" 목록과 동일 (15개 플랫폼)
RETAILER_DOMAINS = [
    "coupang.com",
    "shopping.naver.com",
    "kurly.com",
    "ssg.com",
    "gmarket.co.kr",
    "cjonstyle.com",
    "11st.co.kr",
    "gsshop.com",
    "hyundaihmall.com",
    "auction.co.kr",
    "aliexpress.com",
    "daisomall.co.kr",
    "lotteimall.com",
    "interpark.com",
    "danawa.com",
]

# 상품 상세/가격 정보가 없는 콘텐츠 도메인. include_domains에 danawa.com처럼 상위
# 도메인을 넣으면 이 서브도메인들이 검색 순위를 독점해 실제 쇼핑몰 상품 페이지를
# 밀어내는 현상이 있어 명시적으로 제외한다.
EXCLUDE_DOMAINS = [
    "dpg.danawa.com",  # 다나와 매거진/리뷰 블로그, 가격 정보 없음
    "search.danawa.com",  # 검색결과 목록 페이지 (is_generic_listing_url로도 걸리지만 애초에 제외)
    "adcr.shopping.naver.com",  # 네이버쇼핑 광고 클릭 리다이렉트, 상품 정보 없음
]


async def _tavily_search(query: str, max_results: int) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TAVILY_URL,
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_domains": RETAILER_DOMAINS,
                "exclude_domains": EXCLUDE_DOMAINS,
                "include_raw_content": "text",
            },
        )
        response.raise_for_status()
        data = response.json()

    results = []
    for r in data.get("results", []):
        raw = r.get("raw_content") or ""
        snippet = r.get("content", "")
        # raw_content가 있으면 스니펫보다 정보가 많으므로 우선 사용(토큰 절약을 위해 앞부분만)
        text = raw[:1500] if raw else snippet
        results.append(SearchResult(title=r["title"], url=r["url"], snippet=text, score=r.get("score")))
    return results


async def _fetch(query: str) -> list[SearchResult]:
    """Tavily 스크래핑 + Google Merchant(내 상품 피드) 결과를 실제로 호출해 병합한다.
    google_merchant.search()는 설정이 없거나 계정에 매칭되는 상품이 없으면
    빈 리스트를 반환하므로, 지금은 사실상 Tavily 결과만 나온다(google_merchant
    모듈의 docstring 참고). 캐시를 거치지 않는 순수 조회 — search()의 캐시 미스
    경로와 refresh()의 강제 갱신 경로가 이 함수를 공유한다."""
    merchant_task = google_merchant.search(query)
    tavily_task = _tavily_search(query, search_cache.FETCH_SIZE)
    merchant_results, tavily_results = await asyncio.gather(
        merchant_task, tavily_task, return_exceptions=True
    )

    if isinstance(merchant_results, BaseException):
        merchant_results = []
    if isinstance(tavily_results, BaseException):
        tavily_results = []

    seen_urls = {r.url for r in merchant_results}
    merged = list(merchant_results)
    merged += [r for r in tavily_results if r.url not in seen_urls]
    return merged


async def search(query: str, max_results: int = 12) -> list[SearchResult]:
    """같은 질의가 반복되면 search_cache에서 재사용한다 — 항상 FETCH_SIZE만큼
    받아서 캐시해두고, 더 적은 max_results를 요청한 호출은 앞에서 잘라 쓴다.
    완전 일치가 없으면 의미(임베딩) 기반으로 비슷한 질의의 캐시를 재사용한다 —
    실패해도 Tavily 조회로 그대로 폴백한다."""
    cached = search_cache.get(query)
    if cached is not None:
        return cached[:max_results]

    query_embedding: list[float] | None = None
    if settings.semantic_cache_enabled and settings.openai_api_key:
        try:
            query_embedding = await embeddings.embed_query(query)
            match = search_cache.find_similar(query_embedding)
            if match is not None:
                _, results, _ = match
                return results[:max_results]
        except Exception:
            logger.warning("의미 기반 캐시 조회 실패, Tavily로 폴백", exc_info=True)

    merged = await _fetch(query)
    search_cache.set(query, merged, embedding=query_embedding)
    return merged[:max_results]


async def refresh(query: str) -> None:
    """TTL을 기다리지 않고 캐시를 강제로 새로 채운다 — 인기 질의 우선 갱신
    스케줄러(popularity_scheduler)가 사용."""
    merged = await _fetch(query)
    search_cache.set(query, merged)


async def extract(url: str) -> str | None:
    """URL 하나의 전체 페이지 본문을 가져온다. 후보를 하나로 좁힌 뒤 가격을 재확인할 때 사용."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TAVILY_EXTRACT_URL,
            json={"api_key": settings.tavily_api_key, "urls": [url]},
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not results:
        return None
    return results[0].get("raw_content")
