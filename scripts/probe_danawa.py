"""다나와 상품 페이지에 '판매처별 가격'이 정적 HTML에 실제로 들어있는지
일회성으로 조사한다. 이전 실측(scripts/probe_result.csv)에서 나온
prod.danawa.com URL 6개 전부를 대상으로 한다.

1차 조사(단순 문자열/텍스트노드 검색)에서는 "쿠팡" 등 판매처명이 전부 상단
내비게이션/이미지 출처 표기에서만 매칭되고 실제 가격표는 못 찾았는데, 원인은
판매처명이 텍스트 노드가 아니라 <img alt="..."> 속성이나 aria-label 속성에
들어있었기 때문이었다(BeautifulSoup의 string= 검색은 속성값을 안 봄). 수동
조사로 실제 구조(ul.list__mall-price > li.list-item)를 찾은 뒤 이 스크립트를
그 구조에 맞게 다시 작성했다.

이 스크립트는 조사용이다 — 파싱 전략을 여기서 확정하지 않는다. backend는
건드리지 않는다.
"""

from __future__ import annotations

import re
import time

import httpx
from bs4 import BeautifulSoup

# scripts/probe_structured_data.py와 동일한 UA (일관성 있게 실측하기 위함)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# scripts/probe_result.csv에서 domain == prod.danawa.com인 6개 URL 그대로.
URLS = [
    "https://prod.danawa.com/info/?pcode=31162997",
    "https://prod.danawa.com/info?pcode=1151074",
    "https://prod.danawa.com/info?pcode=1152054",
    "https://prod.danawa.com/info?pcode=16559657",
    "https://prod.danawa.com/info?pcode=17171645",
    "https://prod.danawa.com/info?pcode=59537216",
]

PRICE_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})+")
BRIDGE_TARGET_PATTERN = re.compile(r'goLink\("([^"]+)"\)')


def fetch(url: str) -> httpx.Response | None:
    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            return client.get(url)
    except httpx.HTTPError as exc:
        print(f"  [요청 실패] {type(exc).__name__}: {exc}")
        return None


def _seller_name(li) -> str | None:
    img = li.select_one(".box__logo img")
    if img and img.get("alt"):
        return img["alt"].strip()
    logo_span = li.select_one(".box__logo .text__logo")
    if logo_span:
        return (logo_span.get("aria-label") or logo_span.get_text(strip=True) or "").strip() or None
    return None


def parse_mall_price_list(soup: BeautifulSoup) -> list[dict]:
    mall_list = soup.select_one("ul.list__mall-price")
    if mall_list is None:
        return []
    offers = []
    for li in mall_list.select("li.list-item"):
        seller = _seller_name(li)
        price_el = li.select_one(".sell-price .text__num")
        price_text = price_el.get_text(strip=True) if price_el else None
        link_el = li.select_one("a.link__full-cover")
        href = link_el.get("href") if link_el else None
        cmpnyc = None
        if href:
            m = re.search(r"cmpnyc=([^&]+)", href)
            cmpnyc = m.group(1) if m else None
        offers.append({"seller": seller, "price_text": price_text, "outlink": href, "cmpnyc": cmpnyc})
    return offers


def check_expired(html: str) -> bool:
    return "location.replace" in html and "danawa.com" in html and len(html) < 1000


def analyze(url: str) -> None:
    print(f"\n{'=' * 90}\nURL: {url}\n{'=' * 90}")

    resp = fetch(url)
    if resp is None:
        print("  1) HTTP 상태코드: 요청 자체 실패(네트워크/타임아웃)")
        return

    status = resp.status_code
    print(f"  1) HTTP 상태코드: {status}")
    if status == 403:
        print("  [중단] 403 — 다나와도 봇 차단. 이 URL은 더 분석하지 않음.")
        return
    if status >= 400:
        print(f"  [중단] {status} — 정상 응답 아님.")
        return

    html = resp.text
    html_len = len(html)
    print(f"  HTML 길이: {html_len:,}자")

    if check_expired(html):
        print("  [정보] 서비스 종료/삭제된 상품 페이지로 보임(JS alert + location.replace, 짧은 HTML).")
        print(f"     본문: {html!r}")
        return

    # 2) 판매처명 원문 등장 횟수 (참고용 — 실제 판매처명은 속성값에도 들어있어
    # 이 숫자만으로 있다/없다를 판단하지 않는다)
    seller_hits = re.findall(r"쿠팡|11번가|G마켓|지마켓|옥션|SSG|롯데|인터파크|위메프|티몬", html)
    print(f"  2) 판매처명류 원문 등장 횟수(참고): {len(seller_hits)}건")

    # 3) 가격 패턴 개수
    price_matches = PRICE_PATTERN.findall(html)
    print(f"  3) 가격 패턴(\\d{{1,3}}(,\\d{{3}})+) 개수: {len(price_matches)}")

    # 6) XHR 의심 정황
    xhr_suspect = len(price_matches) == 0 and html_len > 50_000
    print(f"  6) XHR 의심(가격 0개 + HTML {html_len:,}자 > 50,000): {xhr_suspect}")

    soup = BeautifulSoup(html, "lxml")
    offers = parse_mall_price_list(soup)

    print(f"\n  4)/5) ul.list__mall-price 파싱 결과: 판매처 {len(offers)}건")
    for o in offers:
        print(
            f"    seller={o['seller']!r} price_text={o['price_text']!r} "
            f"cmpnyc={o['cmpnyc']} outlink_is_bridge={'bridge/loadingBridge.html' in (o['outlink'] or '')}"
        )
    if offers:
        first = offers[0]
        li = soup.select_one("ul.list__mall-price li.list-item")
        snippet = li.get_text(" ", strip=True)[:300] if li else ""
        print(f"\n  스니펫(첫 판매처 블록, 300자): {snippet!r}")
        print(f"  아웃링크 원본 예시: {first['outlink']}")


def main() -> None:
    for i, url in enumerate(URLS, 1):
        print(f"\n[{i}/{len(URLS)}]", end="")
        analyze(url)
        if i < len(URLS):
            time.sleep(1.0)  # 6개뿐이지만 조사 단계에서도 예의상 간격을 둔다


if __name__ == "__main__":
    main()
