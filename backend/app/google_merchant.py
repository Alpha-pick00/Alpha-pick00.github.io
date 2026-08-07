import asyncio

from .config import settings
from .schemas import SearchResult

CONTENT_API_SCOPE = "https://www.googleapis.com/auth/content"


def _list_products_sync(query: str, max_results: int) -> list[SearchResult]:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        settings.google_service_account_file, scopes=[CONTENT_API_SCOPE]
    )
    client = build("content", "v2.1", credentials=credentials, cache_discovery=False)

    query_lower = query.lower()
    results: list[SearchResult] = []
    request = client.products().list(merchantId=settings.google_merchant_id, maxResults=50)
    while request is not None and len(results) < max_results:
        response = request.execute()
        for item in response.get("resources", []):
            link = item.get("link") or ""
            title = item.get("title") or ""
            if not link or query_lower not in title.lower():
                continue
            price = item.get("price") or {}
            price_text = (
                f"{price['value']} {price['currency']}" if price.get("value") else "가격 정보 없음"
            )
            results.append(SearchResult(title=title, url=link, snippet=price_text))
        request = client.products().list_next(request, response)
    return results[:max_results]


async def search(query: str, max_results: int = 15) -> list[SearchResult]:
    """Google Merchant Center(Content API for Shopping)에 등록된 내 상품 피드를 검색한다.

    주의: 이 API는 경쟁사·타 쇼핑몰 상품을 검색하는 기능이 아니다. Merchant
    Center 계정 소유자가 직접 업로드한 자신의 상품 카탈로그만 products.list로
    조회할 수 있고, 임의 키워드로 웹 전체나 다른 판매자의 상품을 찾는 엔드포인트는
    Content API에 존재하지 않는다. Étiquette는 자체 판매 상품이 없으므로,
    이 함수는 GOOGLE_MERCHANT_ID 계정에 실제 상품 피드가 등록되기 전까지는
    (기술적으로 연동되어 있어도) 사실상 항상 빈 결과를 반환한다.
    """
    if not (settings.google_merchant_id and settings.google_service_account_file):
        return []
    try:
        return await asyncio.to_thread(_list_products_sync, query, max_results)
    except Exception:
        return []
