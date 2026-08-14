"""데모/시연용 정적 최종결과(Decision) 캐시 - 사용자 요청(2026-08-16, "여기서
상세검색까지 누르면 바로 정규식으로 찾을수있게 0.1초만에 해줘" -> "다른건 다
빼주고 아이폰관련해서만 넣어줘"): AI 상세검색(facet_cache)에서 facet을 다 고른
뒤 넘어가는 최종 검색(/decide/stream -> run_single_debate_stream, 정제+검색+
제안 3개+검증+심사 전체)은 실측 ~9~15초가 걸린다 - 이 캐시에 있는 조합이면 그
전체를 건너뛰고 즉시 최종 결과를 낸다.

아래 값은 지어낸 게 아니라 2026-08-16에 아이폰의 facet 기본값 조합(프론트가
자동으로 강조 표시하는 - 각 facet의 첫 번째 옵션, facet_cache의
options_by_selection 교차필터까지 그대로 반영한 조합: 시리즈=아이폰 17,
용량=256GB, 구매유형=자급제)으로 실제 /decide/stream 전체 파이프라인을 진짜로
돌려 캡처한 실제 최종 결정(danawa 실측 가격/판매처/구매링크 포함)이다. 상품
가격은 시간이 지나면 바뀌므로 이 캐시도 facet_cache처럼 주기적으로
재캡처해야 하는 스냅샷이다 - 목록에 없는 조합은 지금까지처럼 실제
파이프라인을 그대로 탄다.

매칭은 전체 문자열이 아니라 토큰 집합(순서 무관, 대소문자 무시)으로 한다 -
AI 상세검색은 facet을 어떤 순서로 클릭하든 dedupeAppend가 같은 단어 집합을
다른 순서로 이어붙일 수 있어서다(예: "아이폰 17 256GB 자급제"나 "아이폰
자급제 17 256GB"나 실제로는 같은 선택)."""

from __future__ import annotations

# 2026-08-16 캡처 - 아이폰 facet 기본 조합의 실제 /decide/stream 최종 결과
# 그대로(가짜 데이터 아님). tokens는 매칭용 정렬된 토큰 튜플.
STATIC_DECISIONS: dict[str, dict] = {'아이폰': {'query': '아이폰 17 256GB 자급제',
         'tokens': ('17', '256gb', '아이폰', '자급제'),
         'result': {'mode': 'single',
                    'query': '아이폰 17 256GB 자급제',
                    'proposals': [{'agent': 'danawa',
                                   'product_name': 'APPLE 아이폰17 256GB, 자급제 해외구매',
                                   'price': '1,384,180원',
                                   'retailer': '롯데ON',
                                   'url': 'https://prod.danawa.com/bridge/loadingBridge.html?cate1=224&cate2=48419&cate3=48829&cate4=0&pcode=97954535&cmpnyc=EE309&safe_trade=4&fee_type=T&link_pcode=LO2547816886&package=0&setpc=0&r=17866887027112',
                                   'reasoning': None,
                                   'error': None,
                                   'verified': True,
                                   'challenge_note': '다나와 실측 가격표에서 확인된 A등급(구매 링크 검증됨) 후보',
                                   'proposed_by': ['danawa']}],
                    'decision': {'product_name': 'APPLE 아이폰17 256GB, 자급제 해외구매',
                                 'price': '1,384,180원',
                                 'retailer': '롯데ON',
                                 'url': 'https://prod.danawa.com/bridge/loadingBridge.html?cate1=0&cate2=0&cate3=0&cate4=0&pcode=97954535&cmpnyc=TTC2B7&safe_trade=4&fee_type=N&link_pcode=12702845959&package=0&setpc=0&r=17866891094745',
                                 'reasoning': '다른 유효한 제안이 없어 danawa의 후보를 그대로 채택했습니다.',
                                 'chosen_agent': 'danawa',
                                 'price_source': 'danawa_offer'},
                    'price_table': {'source': 'danawa',
                                    'source_pcode': '97954535',
                                    'product_name': 'APPLE 아이폰17 256GB, 자급제 해외구매',
                                    'offers': [{'seller': '얼리텍',
                                                'price_krw': 1354900,
                                                'delivery_text': '무료배송',
                                                'domain': None,
                                                'trust': None,
                                                'linkable': False,
                                                'rank': 1},
                                               {'seller': '롯데ON',
                                                'price_krw': 1384180,
                                                'delivery_text': '무료배송',
                                                'domain': 'lotteon.com',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 2},
                                               {'seller': 'G마켓',
                                                'price_krw': 1388030,
                                                'delivery_text': '무료배송',
                                                'domain': 'gmarket.co.kr',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 3},
                                               {'seller': '11번가',
                                                'price_krw': 1488470,
                                                'delivery_text': '무료배송',
                                                'domain': '11st.co.kr',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 4},
                                               {'seller': 'SSG',
                                                'price_krw': 1504000,
                                                'delivery_text': '무료배송',
                                                'domain': 'ssg.com',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 5},
                                               {'seller': '롯데홈쇼핑',
                                                'price_krw': 1509900,
                                                'delivery_text': '무료배송',
                                                'domain': 'lotteimall.com',
                                                'trust': 0.3,
                                                'linkable': False,
                                                'rank': 6},
                                               {'seller': '신세계몰',
                                                'price_krw': 1512000,
                                                'delivery_text': '무료배송',
                                                'domain': 'shinsegaemall.ssg.com',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 7},
                                               {'seller': '옥션',
                                                'price_krw': 1532540,
                                                'delivery_text': '무료배송',
                                                'domain': 'auction.co.kr',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 8},
                                               {'seller': '이마트몰',
                                                'price_krw': 1533984,
                                                'delivery_text': '무료배송',
                                                'domain': 'emart.ssg.com',
                                                'trust': 1.0,
                                                'linkable': True,
                                                'rank': 9},
                                               {'seller': 'CJ온스타일',
                                                'price_krw': 1550000,
                                                'delivery_text': '무료배송',
                                                'domain': None,
                                                'trust': None,
                                                'linkable': False,
                                                'rank': 10}],
                                    'spread': 1.144,
                                    'total_mall_count': None,
                                    'offers_shown': 10,
                                    'is_partial': False,
                                    'price_label': '최저가'}}}}


_TOKENS_TO_RESULT: dict[tuple[str, ...], dict] = {
    entry["tokens"]: entry["result"] for entry in STATIC_DECISIONS.values()
}


def lookup(query: str) -> dict | None:
    """query의 토큰 집합이 캡처해둔 조합과 정확히 일치하면(순서/대소문자 무관)
    그 실제 최종 결과(DecideResponse 딕셔너리)를 즉시 반환한다(검색/LLM 호출
    없음) - 없으면 None이며, 호출부는 이때 기존처럼 실제 debate 파이프라인을
    타야 한다."""
    tokens = tuple(sorted(t.lower() for t in query.strip().split()))
    return _TOKENS_TO_RESULT.get(tokens)
