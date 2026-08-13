"""검증 D — 네트워크 요청 0건. httpx를 직접 import하지 않는다.

D-1~D-3: 검증 A에서 이미 받아둔 5개 게이트웨이 URL 문자열(아래 GATEWAY_URLS
상수로 하드코딩 — scripts/verify_outlink_resolution.py 실행 결과에서 그대로
가져온 것, 재요청 없음)을 urllib.parse로만 해부한다.

D-4: 저장된 5개 다나와 HTML 픽스처에서 44개 offer 전체의 bridge_url을
parse_danawa_html()(순수 함수, 네트워크 없음)로 뽑고, 쿼리 파라미터의
cmpnyc 코드를 검증 A에서 이미 확인된 5개 (cmpnyc -> 목적지) 매핑과
대조한다. 모르는 cmpnyc는 추측하지 않고 "불명"으로 남긴다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa import parse_danawa_html  # noqa: E402  (순수 함수만 사용, 네트워크 없음)

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

# 검증 A(scripts/verify_outlink_resolution.py) 실행 결과에서 그대로 가져온
# 문자열. 여기서는 절대 다시 fetch하지 않는다 — urllib.parse로 해부만 한다.
GATEWAY_URLS = {
    "쿠팡 (affiliate_url, 참고용 - 이미 리다이렉트로 해결됨)":
        "https://link.coupang.com/re/PCSDANAWAPCSDP?pageKey=9509930958&ctag=9509930958"
        "&lptag=V71054700153&itemId=1052228937&vendorItemId=71054700153&spec=10305199"
        "&service_id=estimatedn",
    "옥션": "https://link.auction.co.kr/gate/pcs?item-no=F551543272&sub-id=2"
        "&service-code=10000000&service_id=estimatedn",
    "G마켓": "https://link.gmarket.co.kr/gate/pcs?item-no=4191126895&sub-id=1001"
        "&service-code=10000000&lcd=100000056&service_id=elecdn",
    "11번가": "https://11pcs.11st.co.kr/?appLnkWyCd=04&prdNo=8852665861"
        "&goUrl=https%3A%2F%2Fm.11st.co.kr%2Fproducts%2Fma%2F8852665861"
        "&XSITE=1000000081&service_id=pcdn",
    "네이버(호갱마켓 outlink)": "https://smartstore.naver.com/inflow/ep/gw"
        "?url=%2Finflow%2Fep%2Fdanawa%2Fproducts%2F11131570506&service_id=elecdn",
}

DOMAIN_PATTERN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.IGNORECASE)


def looks_like_url_or_domain(value: str) -> bool:
    if value.startswith("http://") or value.startswith("https://"):
        return True
    first_segment = value.split("/", 1)[0]
    return bool(DOMAIN_PATTERN.match(first_segment))


def section_d1_d2_d3() -> None:
    print("=" * 70)
    print("D-1. 게이트웨이 URL 쿼리 파라미터 해부")
    print("=" * 70)
    for label, url in GATEWAY_URLS.items():
        parts = urlsplit(url)
        print(f"\n[{label}]")
        print(f"  host: {parts.netloc}  path: {parts.path}")
        for key, raw_value in parse_qsl(parts.query, keep_blank_values=True):
            decoded_once = unquote(raw_value)
            decoded_twice = unquote(decoded_once)
            flag = " <- URL/도메인으로 보임" if looks_like_url_or_domain(decoded_once) else ""
            print(f"    {key} = {decoded_once!r}{flag}")
            if decoded_twice != decoded_once:
                flag2 = " <- URL/도메인으로 보임" if looks_like_url_or_domain(decoded_twice) else ""
                print(f"      (2차 디코딩: {decoded_twice!r}{flag2})")

    print("\n" + "=" * 70)
    print("D-2. 몰별 목적지 추출 규칙")
    print("=" * 70)
    print(
        """
  11번가   : goUrl 파라미터에 완전한 URL이 URL-인코딩되어 그대로 들어있음
             -> https://m.11st.co.kr/products/ma/8852665861
             (경로의 8852665861 == 다나와 bridge_url의 link_pcode와 일치, 검증됨)

  쿠팡     : (D 대상 아님) 검증 A에서 이미 HTTP 리다이렉트로 완전히 해결됨
             pageKey=9509930958 == 최종 product_id와 일치

  옥션     : item-no=F551543272  <- URL이 아니라 ID만 있음
             (== bridge_url의 link_pcode와 일치)
             옥션의 표준 상품 URL 패턴은 이 데이터만으로 검증 불가 -> 불명

  G마켓    : item-no=4191126895  <- URL이 아니라 ID만 있음
             (== bridge_url의 link_pcode와 일치)
             G마켓의 표준 상품 URL 패턴은 이 데이터만으로 검증 불가 -> 불명

  네이버   : url=/inflow/ep/danawa/products/11131570506  <- 경로만, 도메인/상점slug 없음
             (11131570506 == bridge_url의 link_pcode와 일치, 상품 고유번호로 추정)
             스마트스토어 URL은 보통 smartstore.naver.com/{상점slug}/products/{번호}
             형태인데 상점slug가 이 게이트웨이 URL 어디에도 없음 -> 불명
"""
    )

    print("=" * 70)
    print("D-3. 추출 불가 케이스 — path segment 확인")
    print("=" * 70)
    for label in ("옥션", "G마켓", "네이버(호갱마켓 outlink)"):
        parts = urlsplit(GATEWAY_URLS[label])
        print(f"  [{label}] path={parts.path!r} -> ", end="")
        if parts.path in ("/gate/pcs", "/inflow/ep/gw"):
            print("path에는 목적지 정보 없음 (범용 게이트웨이 경로), 전부 query에만 있음")
        else:
            print("path 직접 확인 필요")
    print(
        "\n  결론: 옥션/G마켓/네이버 3개 몰은 쿼리 파라미터에 '상품 ID'는 있지만"
        "\n  '완전한 URL'은 없다. ID로부터 실제 상품 페이지 URL을 만드는 공식은"
        "\n  이 데이터만으로는 검증할 수 없으므로 추측하지 않고 전부 '불명'으로 보고한다."
    )


def section_d4() -> None:
    print("\n" + "=" * 70)
    print("D-4. 44개 offer 전체 bridge_url -> cmpnyc 코드 기준 도메인 재집계")
    print("=" * 70)

    # 검증 A에서 이미 실제로 리다이렉트를 추적해 확인한 5개 (cmpnyc -> 목적지)
    # 매핑. 여기서 재사용만 한다 - 새 요청 없음. cmpnyc는 다나와가 판매처
    # "회사"를 식별하는 내부 코드로 보이며(D-1에서 관찰), bridge_url 쿼리에
    # 그대로 노출돼 있어 네트워크 없이 파싱 가능하다.
    KNOWN_CMPNYC_TO_DESTINATION = {
        "TP40F": "www.coupang.com (검증 A에서 완전 해결)",
        "EE715": "link.auction.co.kr/gate/pcs (게이트웨이까지만 확인, 최종 도메인 불명)",
        "EE128": "link.gmarket.co.kr/gate/pcs (게이트웨이까지만 확인, 최종 도메인 불명)",
        "TH201": "m.11st.co.kr (goUrl 파라미터로 완전 해결)",
        "TW627F": "smartstore.naver.com/inflow/ep/gw (게이트웨이까지만 확인, "
                  "스마트스토어 경유는 확인됨)",
    }

    all_offers = []
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        result = parse_danawa_html(f"file://{filename}", html)
        for offer in result["offers"]:
            all_offers.append((filename, offer))

    print(f"\n총 offer 수: {len(all_offers)}건\n")

    cmpnyc_by_seller: dict[str, Counter] = defaultdict(Counter)
    destination_counts: Counter = Counter()
    unknown_cmpnyc: Counter = Counter()

    for filename, offer in all_offers:
        bridge_url = offer["bridge_url"]
        seller = offer["seller"]
        if not bridge_url:
            destination_counts["bridge_url 없음"] += 1
            continue
        parts = urlsplit(bridge_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        cmpnyc = params.get("cmpnyc")
        if cmpnyc is None:
            destination_counts["cmpnyc 파라미터 없음"] += 1
            continue
        cmpnyc_by_seller[seller][cmpnyc] += 1

        destination = KNOWN_CMPNYC_TO_DESTINATION.get(cmpnyc)
        if destination is not None:
            destination_counts[destination] += 1
        else:
            destination_counts[f"불명 (cmpnyc={cmpnyc}, seller={seller})"] += 1
            unknown_cmpnyc[cmpnyc] += 1

    print("-- 판매처별로 관찰된 cmpnyc 코드 (같은 판매처가 여러 cmpnyc를 쓰는지 확인) --")
    for seller, counter in sorted(cmpnyc_by_seller.items()):
        codes = ", ".join(f"{code}x{n}" for code, n in counter.most_common())
        flag = "  <- 코드가 여러 개!" if len(counter) > 1 else ""
        print(f"  {seller:20s} {codes}{flag}")

    print("\n-- 목적지(추정) 기준 44건 집계 --")
    for destination, count in destination_counts.most_common():
        print(f"  {count:>3d}건  {destination}")

    naver_count = sum(
        c for dest, c in destination_counts.items() if "smartstore.naver.com" in dest
    )
    print(f"\n  ★ smartstore.naver.com 경유로 확인된 건수: {naver_count}건 / 44건")
    print(
        "    (판매처명에 '네이버'가 포함된 offer는 이전 집계에서 0건이었지만,\n"
        "     bridge_url의 cmpnyc 코드가 TW627F(호갱마켓)와 일치하는 offer는\n"
        "     실제로는 스마트스토어 경유임이 검증 A에서 확인됐다)"
    )

    if unknown_cmpnyc:
        print(f"\n  cmpnyc 코드가 알려지지 않아 '불명' 처리된 고유 코드 수: {len(unknown_cmpnyc)}개")
        print("  (검증 A에서 실제로 리다이렉트를 추적한 적 없는 코드들 - 추측하지 않음)")


if __name__ == "__main__":
    section_d1_d2_d3()
    section_d4()
