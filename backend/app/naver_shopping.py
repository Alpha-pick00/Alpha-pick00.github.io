import html
import re

import httpx

from .config import settings
from .schemas import SearchResult

NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"

_TAG_PATTERN = re.compile(r"<.*?>")


def _clean_title(title: str) -> str:
    return html.unescape(_TAG_PATTERN.sub("", title or ""))


def _format_snippet(item: dict) -> str:
    lprice = item.get("lprice")
    parts = [f"최저가 {int(lprice):,}원" if lprice else "가격 정보 없음"]
    if item.get("mallName"):
        parts.append(f"판매처 {item['mallName']}")
    brand = item.get("brand") or item.get("maker")
    if brand:
        parts.append(f"브랜드 {brand}")
    return " / ".join(parts)


async def search(query: str, display: int = 15) -> list[SearchResult]:
    """네이버쇼핑 검색 API. 가격/판매처/브랜드가 이미 정제된 필드로 오기 때문에
    Tavily 스크래핑처럼 LLM이 페이지 본문에서 가격을 추측할 필요가 없다.
    단, 쿠팡은 정책상 네이버쇼핑 가격비교에 들어오지 않으므로 search.py에서
    Tavily 결과와 함께 합쳐서 써야 한다."""
    if not (settings.naver_client_id and settings.naver_client_secret):
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            NAVER_SHOP_URL,
            params={"query": query, "display": display, "sort": "sim"},
            headers={
                "X-Naver-Client-Id": settings.naver_client_id,
                "X-Naver-Client-Secret": settings.naver_client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("items", []):
        link = item.get("link") or ""
        if not link:
            continue
        results.append(
            SearchResult(
                title=_clean_title(item.get("title", "")),
                url=link,
                snippet=_format_snippet(item),
            )
        )
    return results
