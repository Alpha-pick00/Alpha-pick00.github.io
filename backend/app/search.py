import asyncio

import httpx

from . import naver_shopping
from .config import settings
from .schemas import SearchResult

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
        results.append(SearchResult(title=r["title"], url=r["url"], snippet=text))
    return results


async def search(query: str, max_results: int = 12) -> list[SearchResult]:
    """네이버쇼핑 API(가격/판매처/브랜드가 정제된 필드로 옴) + Tavily 스크래핑(쿠팡 등
    네이버쇼핑 미제휴 판매처 커버)을 합쳐서 반환한다. 한쪽이 실패해도 다른 쪽 결과는
    그대로 쓸 수 있도록 개별적으로 예외를 흡수한다."""
    naver_task = naver_shopping.search(query)
    tavily_task = _tavily_search(query, max_results)
    naver_results, tavily_results = await asyncio.gather(
        naver_task, tavily_task, return_exceptions=True
    )

    if isinstance(naver_results, BaseException):
        naver_results = []
    if isinstance(tavily_results, BaseException):
        tavily_results = []

    seen_urls = {r.url for r in naver_results}
    merged = list(naver_results)
    merged += [r for r in tavily_results if r.url not in seen_urls]
    return merged


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
