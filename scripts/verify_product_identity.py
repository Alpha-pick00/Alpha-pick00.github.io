"""검증 C — 같은 pcode 아래 묶인 offer들이 실제로 동일 상품(같은 용량/수량/
옵션)을 가리키는지 확인한다. 네트워크 요청 없음 — 저장된 픽스처만 읽는다.

각 li.list-item의 전체 텍스트(가격 숫자 제외)를 출력해서 눈으로 비교할 수
있게 하고, product_name에서 뽑은 수량/용량 토큰과 다른 값이 li 안에 있으면
자동으로 플래그한다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from bs4 import BeautifulSoup  # noqa: E402
from fetchers.danawa import _product_name, _price_from_li, _seller_from_li  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

# 용량/수량 토큰 추출 패턴 — 가격(원/won) 숫자와 겹치지 않도록 단위를 명시한다.
QTY_PATTERNS = [
    re.compile(r"(\d+)\s*개입"),
    # "12개월"(무이자 할부 개월 수)을 수량으로 오인하지 않도록 "개" 뒤에
    # "입"도 "월"도 오지 않는 경우만 수량 토큰으로 본다.
    re.compile(r"(\d+)\s*개(?!입)(?!월)"),
    re.compile(r"(\d+)\s*(GB|TB)", re.IGNORECASE),
    re.compile(r"(\d+)\s*(g|kg|ml|L)\b"),
]


def _extract_tokens(text: str) -> set[str]:
    tokens = set()
    for pattern in QTY_PATTERNS:
        for m in pattern.finditer(text):
            tokens.add(m.group(0).replace(" ", ""))
    return tokens


def main() -> None:
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        product_name = _product_name(soup)
        name_tokens = _extract_tokens(product_name or "")

        mall_list = soup.select_one("ul.list__mall-price")
        items = mall_list.select("li.list-item") if mall_list else []

        print("=" * 70)
        print(f"{filename}")
        print(f"  product_name: {product_name}")
        print(f"  product_name 수량/용량 토큰: {name_tokens or '(없음)'}")
        print("=" * 70)

        mismatches = []
        sample_count = min(3, len(items))
        for idx, li in enumerate(items):
            seller_info = _seller_from_li(li)
            seller = seller_info[1] if seller_info else "?"
            price = _price_from_li(li)

            # 가격 텍스트를 제거한 나머지 li 텍스트에서 옵션 토큰을 찾는다.
            li_copy_text = li.get_text(" ", strip=True)
            price_el = li.select_one(".sell-price .text__num")
            if price_el is not None:
                li_copy_text = li_copy_text.replace(price_el.get_text(strip=True), "")
            li_tokens = _extract_tokens(li_copy_text)

            extra_tokens = li_tokens - name_tokens
            if extra_tokens:
                mismatches.append((seller, price, extra_tokens, li_copy_text))

            if idx < sample_count:
                print(f"  샘플[{idx}] seller={seller} price={price}")
                print(f"    li 전체 텍스트: {li_copy_text[:200]}")

        if mismatches:
            print(f"\n  [!] product_name과 다른 수량/용량 토큰이 li에서 발견됨 ({len(mismatches)}건):")
            for seller, price, extra, text in mismatches:
                print(f"    - seller={seller} price={price} extra_tokens={extra}")
                print(f"      li 텍스트: {text[:200]}")
        else:
            print("\n  옵션 불일치 자동 탐지: 없음 (product_name 토큰과 다른 수량/용량 언급 없음)")
        print()


if __name__ == "__main__":
    main()
