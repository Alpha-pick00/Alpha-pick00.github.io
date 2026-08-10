"""cmpnyc(다나와가 판매처 "회사"를 식별하는 내부 코드) -> 목적지 정보.

오프라인 1회 조사 결과(검증 A/D/E, scripts/verify_outlink_resolution.py +
scripts/decode_gateway_urls.py + scripts/build_cmpnyc_map.py 실행 로그로
확정). 런타임에 이 매핑을 만들기 위한 네트워크 요청은 없다 — 이 파일 자체가
그 결과물이다.

cmpnyc는 판매처 하나당 정확히 1개로 고정되어 있음을 44개 offer 표본에서
확인했다(검증 D). 그래서 "판매처 하나당 1번만 조사하면 그 뒤로는 재요청
없이 도메인을 판별할 수 있다"는 전제가 성립한다.

각 항목의 두 필드는 서로 다른 질문에 답한다 - 섞어서 해석하지 말 것:
  - domain: 이 offer가 "어느 몰 소속인가" (신뢰도 등급 부여에 씀).
    다나와가 실제로 반환한 제휴 리다이렉트 URL의 호스트에서 나온 사실이다
    (추측 아님) - 다만 domain이 채워져 있다고 해서 구매 링크를
    만들 수 있다는 뜻은 아니다. url_rule을 따로 봐야 한다.
  - url_rule: 이 offer의 "구매 링크를 실제로 조립할 수 있는가".
    None이면 domain을 알아도 링크를 만들 수 없다는 뜻 - 이 경우 STEP 3
    설계(2026-08-10 지시)에 따라 사용자에게 링크를 아예 주지 않는다.

url_rule 값의 의미:
  - "redirect_resolved": bridge -> 제휴링크를 follow_redirects로 추적하면
    최종 URL을 얻는다(최종 응답이 403이어도 response.url은 유효 - 쿠팡/SSG
    계열에서 실측 확인). app.price_table.resolve_purchase_url()이
    danawa.resolve_outlink()를 호출해 실제 네트워크 요청을 보낸다.
  - "template:{python format string}": 네트워크 요청 없이 bridge_url 자신의
    link_pcode 쿼리 파라미터를 그대로 대입하면 목적지 URL이 완성된다
    (11번가 - 검증 D에서 goUrl 파라미터의 목적지 상품 ID가 link_pcode와
    정확히 일치함을 확인했다. bridge를 열어 goUrl을 읽을 필요조차 없다).
  - None: 아직 확인된 규칙이 없다. domain이 채워져 있어도 링크는 못 만든다.

미검증 항목(domain=None, url_rule=None)에 대해 규칙을 추측해서 채우지 말 것 -
검증 E-2가 429 두 번째 발생으로 중단되어 15종 중 8종은 실제로 한 번도
열어보지 못했다.

TRUST_TIER: domain -> 신뢰도 점수. 다나와 판매처 목록 자체에는 평점/배지 등
신뢰도 신호가 전혀 없었다(검증 B) - 대신 outlink 도메인을 대리 지표로 쓴다.
domain=None인 offer는 등급을 매기지 말고 None으로 남긴다(0.3으로 강등 금지 -
모르는 것과 낮은 것은 다르다). domain은 있지만 아래 어느 집합에도 없으면 0.3.
"""

from __future__ import annotations

from typing import TypedDict


class MallMapping(TypedDict):
    seller: str
    domain: str | None
    url_rule: str | None


CMPNYC_MAP: dict[str, MallMapping] = {
    # --- 검증 A (STEP 3 사전검증)에서 실제 리다이렉트 추적으로 완전 확인 ---
    "TP40F": {"seller": "쿠팡", "domain": "coupang.com", "url_rule": "redirect_resolved"},

    # --- 검증 D (게이트웨이 쿼리 파라미터 해부)에서 확인 ---
    "TH201": {
        "seller": "11번가",
        "domain": "11st.co.kr",
        "url_rule": "template:https://m.11st.co.kr/products/ma/{link_pcode}",
    },

    # --- 검증 E-1: item-no -> 표준 URL 조립 가설, 미확정 ---
    # 옥션은 가설 URL이 403(봇 차단)으로 상품명 대조 자체가 불가해 가설을
    # 폐기했다. gateway_domain(link.auction.co.kr)은 실제로 받은 응답이므로
    # 몰 정체(domain)는 확신하지만, url_rule은 아직 없다.
    "EE715": {"seller": "옥션", "domain": "auction.co.kr", "url_rule": None},
    # G마켓은 옥션에서 403이 떠서 지시대로 시도조차 하지 않았다. domain은
    # gateway_domain(link.gmarket.co.kr) 근거로 채우지만 url_rule은 없다.
    "EE128": {"seller": "G마켓", "domain": "gmarket.co.kr", "url_rule": None},

    # --- 검증 E-2: 대표 offer 1건씩 리다이렉트 추적, 성공 ---
    "EE309": {"seller": "롯데ON", "domain": "lotteon.com", "url_rule": "redirect_resolved"},
    "TN118": {"seller": "SSG", "domain": "ssg.com", "url_rule": "redirect_resolved"},
    "TSB275": {"seller": "SK스토아", "domain": "skstoa.com", "url_rule": "redirect_resolved"},
    "TRB03": {"seller": "주식회사 신세계라이브쇼핑", "domain": "shinsegaetvshopping.com", "url_rule": "redirect_resolved"},
    "ED901": {"seller": "신세계몰", "domain": "shinsegaemall.ssg.com", "url_rule": "redirect_resolved"},

    # --- 검증 E-2: 429로 게이트웨이(smartstore.naver.com)까지만 확인, 그 이상 미확인 ---
    "TW627F": {"seller": "호갱마켓", "domain": "smartstore.naver.com", "url_rule": None},
    "TY6C4": {"seller": "우리집식탁매니저", "domain": "smartstore.naver.com", "url_rule": None},
    "TV91F9": {"seller": "곰돌이창고", "domain": "smartstore.naver.com", "url_rule": None},

    # --- 완전 미검증 (E-2가 두 번째 429로 중단되어 조사 못 함) ---
    "EE311": {"seller": "이마트몰", "domain": None, "url_rule": None},
    "ED903": {"seller": "롯데홈쇼핑", "domain": None, "url_rule": None},
    "ED907": {"seller": "현대Hmall", "domain": None, "url_rule": None},
    "TYBF5": {"seller": "newgods1", "domain": None, "url_rule": None},
    "PV203": {"seller": "컴오아시스", "domain": None, "url_rule": None},
    "TW7241": {"seller": "GL SHOP", "domain": None, "url_rule": None},
    "PF804": {"seller": "한솔컴퓨터", "domain": None, "url_rule": None},
    "PD908": {"seller": "㈜노트나인", "domain": None, "url_rule": None},
}


def lookup(cmpnyc: str) -> MallMapping | None:
    return CMPNYC_MAP.get(cmpnyc)


TRUST_TIER: dict[float, set[str]] = {
    1.0: {
        "coupang.com",
        "11st.co.kr",
        "gmarket.co.kr",
        "auction.co.kr",
        "ssg.com",
        "shinsegaemall.ssg.com",
        "emart.ssg.com",
        "lotteon.com",
        "shinsegaetvshopping.com",
        "skstoa.com",
    },
    0.7: {"smartstore.naver.com"},
    # 그 외 관측된 도메인은 0.3 (app.price_table._trust_for_domain의 fallback).
}
