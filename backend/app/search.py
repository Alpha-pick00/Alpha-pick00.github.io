import httpx

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


async def search(query: str, max_results: int = 5) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TAVILY_URL,
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_domains": RETAILER_DOMAINS,
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
