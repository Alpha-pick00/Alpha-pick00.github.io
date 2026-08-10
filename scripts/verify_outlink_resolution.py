"""검증 A — 5개 상품의 "최저가 offer" 딱 5건에 대해서만 bridge_url을
실제로 해석(resolve)해본다. STEP 3 설계 확정 전 사전 검증이며, 이 파일은
scripts/ 아래 일회성 스크립트다 (backend/fetchers/danawa.py의 resolve_outlink는
호출하지 않는다 — 재시도 로직이 섞여 있어 "재시도 없음" 요구사항과 맞지 않으므로
이 스크립트에서 로직을 그대로 풀어써서 매 홉의 상태를 낱낱이 기록한다).

요청 규칙: 상품 5개 순차 처리, 상품 사이 최소 2초 간격, 홉마다 재시도 없음,
403이면 그 자리에서 전체 중단.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa import (  # noqa: E402
    BRIDGE_TARGET_PATTERN,
    REQUEST_TIMEOUT,
    USER_AGENT,
    extract_product_id,
    parse_danawa_html,
)

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

MIN_INTERVAL_SEC = 2.0
LISTING_HINTS = ("search", "list", "category", "goodslist", "srch")


def classify_page_type(url: str) -> str:
    path_and_query = (urlsplit(url).path + "?" + urlsplit(url).query).lower()
    if any(hint in path_and_query for hint in LISTING_HINTS):
        return "목록/검색 결과로 추정"
    return "상세 페이지로 추정 (휴리스틱, 육안 확인 권장)"


async def resolve_one(bridge_url: str) -> dict:
    diag: dict = {"bridge_url": bridge_url}

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True
    ) as client:
        try:
            resp = await client.get(bridge_url)
        except httpx.HTTPError as exc:
            diag["stage"] = "bridge_fetch_error"
            diag["error"] = f"{type(exc).__name__}: {exc}"
            return diag

    diag["bridge_status"] = resp.status_code
    if resp.status_code == 403:
        diag["stage"] = "bridge_403"
        diag["bridge_html_snippet"] = resp.text[:300]
        return diag

    match = BRIDGE_TARGET_PATTERN.search(resp.text)
    if not match:
        diag["stage"] = "bridge_no_golink_match"
        diag["bridge_html_snippet"] = resp.text[:300]
        return diag

    affiliate_url = match.group(1)
    diag["affiliate_url"] = affiliate_url

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True
    ) as client:
        try:
            resp2 = await client.get(affiliate_url)
        except httpx.HTTPError as exc:
            diag["stage"] = "affiliate_fetch_error"
            diag["error"] = f"{type(exc).__name__}: {exc}"
            return diag

    resolved_url = str(resp2.url)
    diag["affiliate_final_status"] = resp2.status_code
    diag["resolved_url"] = resolved_url
    diag["resolved_domain"] = urlsplit(resolved_url).netloc
    diag["product_id"] = extract_product_id(resolved_url)
    diag["page_type"] = classify_page_type(resolved_url)
    diag["stage"] = "ok"
    return diag


async def main() -> None:
    cheapest_items = []
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        result = parse_danawa_html(f"file://{filename}", html)
        cheapest = min(result["offers"], key=lambda o: o["price_krw"])
        cheapest_items.append((filename, result["product_name"], cheapest))

    for idx, (filename, product_name, offer) in enumerate(cheapest_items):
        if idx > 0:
            await asyncio.sleep(MIN_INTERVAL_SEC)

        print("=" * 70)
        print(f"[{idx + 1}/5] {filename}")
        print(f"  product_name={product_name}")
        print(f"  cheapest offer: seller={offer['seller']} price={offer['price_krw']:,}원")
        print("=" * 70)

        if offer["bridge_url"] is None:
            print("  bridge_url 없음 -> 이 offer는 해석 불가, 스킵")
            continue

        diag = await resolve_one(offer["bridge_url"])
        for key, value in diag.items():
            print(f"  {key}: {value}")

        if diag.get("stage") == "bridge_403":
            print("\n!!! 403 감지 - 지시에 따라 검증 A 전체를 여기서 즉시 중단한다 !!!")
            break
        print()


if __name__ == "__main__":
    asyncio.run(main())
