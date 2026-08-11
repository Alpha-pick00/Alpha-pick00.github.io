"""PART 4-3 사전 조사 2단계 - scripts/enuri_urls.json에 모아둔 최대 6개 URL을
다나와 STEP 1과 동일한 절차로 조사한다. 요청 6건 이하, 순차, 2초 이상 간격,
재시도 없음, 403이면 즉시 중단. 어댑터 코드는 작성하지 않는다 - 구조 확인만.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
URLS_PATH = SCRIPT_DIR / "enuri_urls.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 5.0
INTERVAL_SEC = 2.0


def _is_expired_like(html: str) -> bool:
    return len(html) < 1000


async def probe_one(client: httpx.AsyncClient, url: str) -> dict:
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return {"url": url, "stage": "fetch_error", "error": f"{type(exc).__name__}: {exc}"}

    diag: dict = {"url": url, "status": resp.status_code, "final_url": str(resp.url)}
    if resp.status_code == 403:
        diag["stage"] = "403"
        return diag

    html = resp.text
    diag["html_length"] = len(html)
    diag["expired_like"] = _is_expired_like(html)
    diag["snippet_300"] = html[:300]

    soup = BeautifulSoup(html, "lxml")

    # 판매처명이 텍스트인지 img alt/aria-label인지 - 다나와에서 이걸로 첫 시도가
    # 실패했으니 둘 다 확인한다.
    imgs_with_alt = soup.select("img[alt]")
    diag["img_alt_samples"] = [img.get("alt") for img in imgs_with_alt[:10] if img.get("alt")]
    aria_label_els = soup.select("[aria-label]")
    diag["aria_label_samples"] = [el.get("aria-label") for el in aria_label_els[:10] if el.get("aria-label")]

    # 가격처럼 보이는 텍스트(콤마 3자리 + 원) 존재 여부
    price_like = re.findall(r"[\d,]{4,}\s*원", html)
    diag["price_like_text_samples"] = price_like[:10]

    # 판매처 이름 후보 키워드가 본문에 있는지
    known_sellers = ["쿠팡", "11번가", "G마켓", "옥션", "SSG", "롯데ON", "인터파크"]
    diag["known_seller_mentions"] = [s for s in known_sellers if s in html]

    # 아웃링크/중계 패턴 힌트
    links = soup.select("a[href]")
    outlink_like = [a.get("href") for a in links if a.get("href") and ("redirect" in a.get("href", "").lower() or "out" in a.get("href", "").lower() or "link" in a.get("href", "").lower())]
    diag["outlink_like_href_samples"] = outlink_like[:10]

    # JS 렌더링 정황 - body 텍스트가 유의미하게 짧은데 script 태그는 많은 경우
    body_text = soup.get_text(strip=True)
    diag["body_text_length"] = len(body_text)
    diag["script_tag_count"] = len(soup.select("script"))

    diag["stage"] = "ok"
    return diag


async def main() -> None:
    urls = json.loads(URLS_PATH.read_text(encoding="utf-8"))
    urls = urls[:6]

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as client:
        for i, url in enumerate(urls):
            if i > 0:
                await asyncio.sleep(INTERVAL_SEC)

            print("=" * 70)
            print(f"[{i + 1}/{len(urls)}] {url}")
            print("=" * 70)

            diag = await probe_one(client, url)
            for k, v in diag.items():
                print(f"  {k}: {v}")

            if diag.get("stage") == "403":
                print("\n!!! 403 감지 - 지시에 따라 즉시 중단 !!!")
                break
            print()


if __name__ == "__main__":
    asyncio.run(main())
