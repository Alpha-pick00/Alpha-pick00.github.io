"""다나와 상품 5개(성공 케이스)의 판매처 분포를 집계한다. 네트워크 요청 없음 —
backend/tests/fixtures/danawa_offers_*.html(STEP 1/승인 후 STEP 2 검증 과정에서
이미 저장해 둔 실제 HTML)만 읽고, backend/fetchers/danawa.py의
parse_danawa_html()로 파싱한다. 일회성 집계 스크립트, backend는 건드리지 않음.
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa import parse_danawa_html  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

# 접근 불가/이중 탈락 쇼핑몰 커버리지 확인용 — normalize_seller()가 합치지 않고
# 원문 그대로 통과시키는 이름들이라 여러 표기를 다 잡아야 한다. 네이버쇼핑/컬리는
# 미리 답을 정해두지 않고 실제 seller/raw_seller 문자열에서 "네이버"/"컬리"가
# 들어간 건 전부 substring으로 찾아 그대로 집계한다(가정하지 않는다).
EXACT_COVERAGE_GROUPS = {
    "쿠팡": {"쿠팡"},
    "SSG 계열(전체)": {"SSG", "이마트몰", "신세계몰"},
    "  - SSG.COM": {"SSG"},
    "  - 이마트몰": {"이마트몰"},
    "  - 신세계몰": {"신세계몰"},
    "G마켓": {"G마켓"},
}
SUBSTRING_COVERAGE_GROUPS = {
    "네이버쇼핑(seller/raw_seller에 '네이버' 포함)": "네이버",
    "컬리(seller/raw_seller에 '컬리' 포함)": "컬리",
}


def main() -> None:
    all_offers = []
    per_product = []

    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        result = parse_danawa_html(f"file://{filename}", html)
        offers = result["offers"]
        all_offers.extend(offers)
        per_product.append((filename, result["product_name"], offers))

    print(f"총 offer 수: {len(all_offers)}건 (상품 {len(per_product)}개)\n")

    # 1) 판매처별 등장 횟수 (정규화 기준, 내림차순 전체)
    seller_counts = Counter(o["seller"] for o in all_offers)
    print("=" * 60)
    print("1) 판매처별 등장 횟수 (정규화된 seller 기준, 전체)")
    print("=" * 60)
    for seller, count in seller_counts.most_common():
        print(f"  {seller:20s} {count:>3d}건")

    # 2) 접근 불가 쇼핑몰 커버리지
    print("\n" + "=" * 60)
    print(f"2) 접근 불가/이중 탈락 쇼핑몰 커버리지 ({len(all_offers)}건 중)")
    print("=" * 60)
    for label, names in EXACT_COVERAGE_GROUPS.items():
        count = sum(seller_counts.get(n, 0) for n in names)
        print(f"  {label:40s} {count:>3d}건")
    for label, needle in SUBSTRING_COVERAGE_GROUPS.items():
        matches = [
            o for o in all_offers if needle in o["seller"] or needle in o["raw_seller"]
        ]
        print(f"  {label:40s} {len(matches):>3d}건")
        for m in matches:
            print(f"      -> seller={m['seller']!r} raw_seller={m['raw_seller']!r}")

    # 3) 상품당 판매처 수 분포
    print("\n" + "=" * 60)
    print("3) 상품당 판매처 수 분포")
    print("=" * 60)
    counts_per_product = []
    for filename, product_name, offers in per_product:
        n = len(offers)
        counts_per_product.append(n)
        print(f"  {filename:35s} offer={n:>2d}건  product_name={product_name}")
    print(f"  중앙값: {statistics.median(counts_per_product)}")

    # 4) 가격 스프레드 (상품별 최고가/최저가)
    print("\n" + "=" * 60)
    print("4) 가격 스프레드 (price_max / price_min)")
    print("=" * 60)
    for filename, product_name, offers in per_product:
        prices = [o["price_krw"] for o in offers]
        if not prices:
            print(f"  {filename:35s} offer 없음")
            continue
        p_min, p_max = min(prices), max(prices)
        spread = p_max / p_min if p_min else float("inf")
        print(
            f"  {filename:35s} min={p_min:>10,d} max={p_max:>10,d} "
            f"spread={spread:.3f} ({(spread - 1) * 100:.1f}% 차이)"
        )

    # 5) 최저가 판매처
    print("\n" + "=" * 60)
    print("5) 상품별 최저가 판매처")
    print("=" * 60)
    cheapest_sellers = []
    for filename, product_name, offers in per_product:
        if not offers:
            continue
        cheapest = min(offers, key=lambda o: o["price_krw"])
        cheapest_sellers.append(cheapest["seller"])
        print(f"  {filename:35s} 최저가 판매처={cheapest['seller']:15s} price={cheapest['price_krw']:,}원")

    cheapest_counts = Counter(cheapest_sellers)
    print(f"\n  최저가 판매처 집계: {dict(cheapest_counts)}")
    coupang_cheapest_ratio = cheapest_counts.get("쿠팡", 0) / len(cheapest_sellers) if cheapest_sellers else 0
    print(f"  쿠팡이 최저가인 비율: {coupang_cheapest_ratio:.1%} ({cheapest_counts.get('쿠팡', 0)}/{len(cheapest_sellers)})")


if __name__ == "__main__":
    main()
