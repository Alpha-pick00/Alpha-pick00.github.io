"""검증 E-1 — 옥션/G마켓 표준 상품 URL 패턴 가설을 딱 2건만 요청해서 검증한다.
가설이 맞는지 확인하는 게 목적이며, 틀리면 그 자리에서 폐기하고 "불명"으로
보고한다 (다른 패턴을 추측하지 않는다). 2초 간격, 재시도 없음, 403이면 즉시
전체 중단.
"""

from __future__ import annotations

import asyncio

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 5.0
INTERVAL_SEC = 2.0

# 검증 D에서 확인한 item-no를 그대로 대입한 가설 URL. 다나와 상품명과 대조한다.
CASES = [
    {
        "mall": "옥션",
        "url": "https://itempage3.auction.co.kr/DetailView.aspx?itemno=F551543272",
        "danawa_product_name": "오뚜기 맛있는 오뚜기밥 흰밥 210g (24개)",
        "match_tokens": ["오뚜기밥", "오뚜기"],
    },
    {
        "mall": "G마켓",
        "url": "http://item.gmarket.co.kr/Item?goodscode=4191126895",
        "danawa_product_name": "APPLE 2022 iPad Air 5세대 (256GB)",
        "match_tokens": ["iPad Air", "아이패드"],
    },
]


def extract_title_hint(html: str) -> str:
    import re

    og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html, re.IGNORECASE)
    if og:
        return og.group(1)
    title = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    return title.group(1).strip() if title else ""


async def main() -> None:
    for idx, case in enumerate(CASES):
        if idx > 0:
            await asyncio.sleep(INTERVAL_SEC)

        print("=" * 70)
        print(f"[{case['mall']}] {case['url']}")
        print("=" * 70)

        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get(case["url"])
            except httpx.HTTPError as exc:
                print(f"  요청 실패: {type(exc).__name__}: {exc}")
                print("  -> 가설 폐기, 불명으로 보고")
                continue

        print(f"  status: {resp.status_code}")
        print(f"  final url: {resp.url}")

        if resp.status_code == 403:
            print("\n  !!! 403 감지 - 지시에 따라 검증 E-1 전체를 여기서 즉시 중단한다 !!!")
            return

        if resp.status_code != 200:
            print(f"  {resp.status_code} 응답 -> 가설 폐기, 불명으로 보고")
            continue

        title_hint = extract_title_hint(resp.text)
        print(f"  페이지 title/og:title: {title_hint!r}")
        print(f"  다나와 product_name: {case['danawa_product_name']!r}")

        matched = any(token in title_hint for token in case["match_tokens"])
        print(f"  일치 판정: {'일치 -> 가설 채택' if matched else '불일치 -> 가설 폐기, 불명으로 보고'}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
