"""검증 E-3 — CMPNYC_MAP을 반영해 44개 offer를 재집계한다. 네트워크 요청 0건,
저장된 픽스처 + backend/fetchers/danawa_mall_map.py만 사용한다.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa import parse_danawa_html  # noqa: E402
from fetchers.danawa_mall_map import CMPNYC_MAP  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]


def main() -> None:
    all_offers = []
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        result = parse_danawa_html(f"file://{filename}", html)
        all_offers.extend(result["offers"])

    total = len(all_offers)
    url_ok = 0
    domain_only = 0
    unknown = 0
    domain_counter: Counter = Counter()
    unknown_sellers: Counter = Counter()

    for offer in all_offers:
        bridge_url = offer.get("bridge_url")
        cmpnyc = None
        if bridge_url:
            params = dict(parse_qsl(urlsplit(bridge_url).query, keep_blank_values=True))
            cmpnyc = params.get("cmpnyc")

        mapping = CMPNYC_MAP.get(cmpnyc) if cmpnyc else None
        if mapping is None:
            unknown += 1
            unknown_sellers[offer["seller"]] += 1
            continue

        domain = mapping["domain"]
        url_rule = mapping["url_rule"]

        if domain:
            domain_counter[domain] += 1
        else:
            unknown_sellers[offer["seller"]] += 1

        if url_rule is not None:
            url_ok += 1
        elif domain is not None:
            domain_only += 1
        else:
            unknown += 1

    print(f"총 offer 수: {total}건\n")
    print(f"1) URL 완전 해석 가능 (구매 링크 생성 가능): {url_ok}건 ({url_ok / total:.1%})")
    print(f"2) 도메인만 판별 가능 (신뢰도 등급 부여 가능, 링크는 불가): {domain_only}건 ({domain_only / total:.1%})")
    print(f"3) 완전 불명 (domain도 url_rule도 없음): {unknown}건 ({unknown / total:.1%})")

    print("\n도메인별 분포 (domain이 확인된 offer 기준):")
    for domain, count in domain_counter.most_common():
        print(f"  {domain:30s} {count:>3d}건")

    naver_total = sum(c for d, c in domain_counter.items() if "smartstore.naver.com" in d)
    print(f"\n  smartstore.naver.com 경유: {naver_total}건 / {total}건")

    print("\n완전 불명 판매처 (domain조차 없음):")
    for seller, count in unknown_sellers.most_common():
        print(f"  {seller:20s} {count:>3d}건")


if __name__ == "__main__":
    main()
