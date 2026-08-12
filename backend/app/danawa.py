"""다나와 상품 페이지를 실제 최저가 판매처 링크로 해석한다.

다나와 단독 도메인으로 검색을 좁힌 뒤(search.py), 최종 추천 URL이 다나와
가격비교 페이지(prod.danawa.com/info?pcode=...)를 그대로 가리키는 문제가 있었다
— 이 페이지 자체는 여러 판매처를 나열만 할 뿐 특정 상품을 바로 살 수 있는
페이지가 아니다. 실제 "최저가 판매처로 바로가기" 링크는 페이지 로드 후
자바스크립트가 내부 AJAX(getAllPriceCompareMallList.ajax.php)로 채워 넣는
부분이라 Tavily의 정적 텍스트 추출로는 보이지 않는다. 이 모듈은 그 AJAX
엔드포인트를 직접 호출해(브라우저 렌더링 없이) 최저가로 표시된 판매처의 실제
링크와 이름을 뽑아낸다.
"""

import logging
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PRICE_LIST_URL = "https://prod.danawa.com/info/ajax/getAllPriceCompareMallList.ajax.php"

_PCODE_PATTERN = re.compile(r"^\d+$")


def _extract_pcode(url: str) -> str | None:
    """다나와 상품 상세 페이지(prod.danawa.com/info?pcode=...)의 pcode를 뽑는다.
    다나와의 다른 페이지(plan.danawa.com 기획전, mauto.danawa.com 뉴스 등)는
    해당하지 않아 None을 반환 — 호출부는 이 경우 원래 URL을 그대로 쓴다."""
    parts = urlsplit(url)
    if parts.netloc != "prod.danawa.com":
        return None
    pcode = parse_qs(parts.query).get("pcode", [None])[0]
    if pcode and _PCODE_PATTERN.match(pcode):
        return pcode
    return None


def _parse_lowest_price_link(html: str) -> tuple[str, str] | None:
    """AJAX 응답 HTML에서 다나와가 직접 "최저가"로 표시한(class="price lowest")
    항목의 실제 이동 링크와 판매처 이름(로고 alt 텍스트)을 뽑는다. 구조가 안
    맞으면(다나와가 마크업을 바꿨거나 판매처가 아예 없으면) None."""
    soup = BeautifulSoup(html, "html.parser")
    price_el = soup.select_one(".price.lowest")
    if price_el is None:
        return None
    link = price_el.find_parent("a")
    href = link.get("href") if link else None
    if not href:
        return None

    item = price_el.find_parent(class_="diff_item")
    retailer = ""
    if item is not None:
        img = item.select_one(".d_mall img[alt]")
        if img is not None:
            retailer = img.get("alt", "")

    return href, retailer


async def resolve_lowest_price(url: str, retailer: str) -> tuple[str, str]:
    """url이 다나와 상품 페이지면 실제 최저가 판매처의 바로가기 링크로 바꿔서
    반환한다. 다나와 상품 페이지가 아니거나, 호출/파싱 중 무엇이든 실패하면
    원래 (url, retailer)를 그대로 반환한다 — 잘못 바꾸는 것보다 다나와
    가격비교 페이지 그대로 두는 게 안전하다."""
    pcode = _extract_pcode(url)
    if pcode is None:
        return url, retailer

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                _PRICE_LIST_URL,
                data={"pcode": pcode},
                headers={
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            response.raise_for_status()
    except Exception:
        logger.warning("다나와 최저가 조회 실패, 가격비교 페이지 그대로 사용: %r", url, exc_info=True)
        return url, retailer

    resolved = _parse_lowest_price_link(response.text)
    if resolved is None:
        return url, retailer

    resolved_url, resolved_retailer = resolved
    return resolved_url, resolved_retailer or retailer
