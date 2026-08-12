"""STEP 3/6 파이프라인 연결 테스트. 네트워크 요청 금지 - 전부 monkeypatch로
실제 Tavily/LLM/다나와 호출을 막고, 픽스처처럼 만든 합성 HTML만 쓴다."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.debate import run_danawa_only_debate, run_danawa_only_debate_stream, run_single_debate
from app.main import app
from app.price_table import (
    MAX_DANAWA_URLS,
    _extract_quantity_tokens,
    _is_single_product_family,
    _query_param,
    build_danawa_candidates,
    build_price_table,
    cheapest_linkable_raw_offer,
    enrich_decision,
    exclude_price_comparison_site_as_final_pick,
    fetch_price_tables,
    select_danawa_urls,
)
from app.schemas import AgentCandidate, AgentCandidates, Decision, Proposal, SearchResult
from fetchers.danawa import parse_danawa_html, with_total_mall_count

client = TestClient(app)


def _offer_li(alt: str, price_text: str, cmpnyc: str, link_pcode: str = "999") -> str:
    return f"""
    <li class="list-item">
      <div class="box__logo"><img src="x.png" alt="{alt}"></div>
      <div class="box__price"><div class="sell-price"><span class="text__num">{price_text}</span></div></div>
      <div class="box__delivery">무료배송</div>
      <a class="link__full-cover" href="https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc={cmpnyc}&link_pcode={link_pcode}"></a>
    </li>
    """


def _danawa_html(product_name: str, offers_html: list[str]) -> str:
    offers_block = "".join(offers_html)
    return f"""
    <html><body>
    <img alt="{product_name}_이미지" src="x.png">
    <ul class="list__mall-price">{offers_block}</ul>
    </body></html>
    """


def _fake_agent(agent: str, product_name="테스트 상품", price_krw=23000, retailer="쿠팡", url="https://www.coupang.com/vp/products/1"):
    async def _propose(query, results):
        return AgentCandidates(
            agent=agent,
            candidates=[
                AgentCandidate(
                    product_name=product_name, price_krw=price_krw, retailer=retailer, url=url, reasoning="테스트 근거"
                )
            ],
        )

    return _propose


async def _fake_decide(query, proposals):
    return Decision(
        product_name="테스트 상품",
        price="23,000원",
        retailer="쿠팡",
        url="https://www.coupang.com/vp/products/1",
        reasoning="테스트 근거",
        chosen_agent="gpt",
    )


def _patch_llm_layer(monkeypatch):
    monkeypatch.setattr("app.agents.gpt.propose", _fake_agent("gpt"))
    monkeypatch.setattr("app.agents.gemini.propose", _fake_agent("gemini"))
    monkeypatch.setattr("app.agents.deepseek.propose", _fake_agent("deepseek"))
    monkeypatch.setattr("app.agents.judge.decide", _fake_decide)
    # run_debate()가 LLM 키 유무로 run_single_debate/run_danawa_only_debate를
    # 자동 분기하는데(로컬 실험용, .env에 키가 없으면 다나와 전용 경로로 빠짐),
    # 이 테스트들은 LLM 경로 자체를 검증하는 게 목적이라 개발자 로컬 .env
    # 상태와 무관하게 항상 LLM 경로를 타도록 강제한다.
    monkeypatch.setattr("app.debate._any_llm_key_configured", lambda: True)
    # 실제 sqlite 자동완성 인덱스에 테스트 검색어가 쌓이지 않도록 무력화한다 -
    # /decide의 BackgroundTasks가 record_terms를 실제로 실행하기 때문.
    monkeypatch.setattr("app.autocomplete.record_terms", lambda terms: None)


def _patch_search(monkeypatch, danawa_url: str | None):
    results = []
    if danawa_url:
        results.append(SearchResult(title="다나와", url=danawa_url, snippet="", score=0.9))

    async def _search(query, max_results=12):
        return results

    monkeypatch.setattr("app.search.search", _search)
    # B - 다나와 직접 검색(search_danawa)도 기본적으로 빈 리스트로 막는다.
    # 안 막으면 이 테스트들이 Tavily 경로만 검증하려는 의도와 무관하게
    # search.danawa.com으로 실제 DNS 조회가 나간다(conftest의 소켓 차단은
    # connect()만 막고 getaddrinfo()는 못 막음) - 직접 검색 자체를 검증하는
    # 테스트는 이 함수를 안 쓰고 따로 patch한다.
    async def _search_danawa(query, limit=3):
        return []

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)


# -- 1. 다나와 페치 실패해도 /decide 200 --------------------------------------


def test_decide_returns_200_when_danawa_fetch_fails(monkeypatch):
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, "https://prod.danawa.com/info?pcode=1")

    async def _boom(url):
        raise RuntimeError("network exploded")

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _boom)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["price_table"] is None
    assert data["decision"]["price_source"] == "llm_guess"


# -- 2. 다나와 페치 타임아웃돼도 LLM 결과만으로 정상 응답 ----------------------


def test_decide_returns_llm_only_when_danawa_times_out(monkeypatch):
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, "https://prod.danawa.com/info?pcode=1")

    async def _timeout(url):
        raise asyncio.TimeoutError()

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _timeout)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["price_table"] is None
    assert data["decision"]["product_name"] == "테스트 상품"


# -- 3. A등급이 하나도 없을 때 링크 없는 추천을 만들지 않는다 ------------------


def test_no_a_grade_offer_leaves_decision_unreplaced():
    # TW627F(호갱마켓)/TY6C4(우리집식탁매니저)는 CMPNYC_MAP에서 domain은
    # 있지만(smartstore.naver.com) url_rule=None(B등급, E-2가 429로 중단돼
    # 미검증) - A등급이 전혀 없는 페이지를 만든다. (EE715/EE128은 옥션/G마켓
    # resolve_outlink 재검증 후 A등급으로 바뀌어서 더 이상 이 용도로 못 쓴다.)
    html = _danawa_html(
        "테스트 상품",
        [_offer_li("호갱마켓", "20,000", "TW627F"), _offer_li("우리집식탁매니저", "21,000", "TY6C4")],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    assert cheapest_linkable_raw_offer(result) is None

    original = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="호갱마켓",
        url="https://smartstore.naver.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )
    enriched = asyncio.run(enrich_decision(original, result))

    assert enriched.price_source == "llm_guess"
    assert enriched.url == "https://smartstore.naver.com/guess"
    assert enriched.price == "20,000원"


# -- 4. 최저가가 B등급이면 링크는 A등급 최저가로 --------------------------------


def test_cheapest_linkable_offer_skips_cheaper_b_grade():
    html = _danawa_html(
        "테스트 상품",
        [
            _offer_li("호갱마켓", "19,000", "TW627F"),  # B등급, 더 저렴
            _offer_li("쿠팡", "23,000", "TP40F", link_pcode="555"),  # A등급
        ],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    table = build_price_table(result)
    assert table.offers[0].seller == "호갱마켓"
    assert table.offers[0].price_krw == 19000
    assert table.offers[0].linkable is False
    assert table.offers[1].seller == "쿠팡"
    assert table.offers[1].linkable is True

    cheapest_linkable = cheapest_linkable_raw_offer(result)
    assert cheapest_linkable["seller"] == "쿠팡"
    assert cheapest_linkable["price_krw"] == 23000


def test_gmarket_and_auction_are_a_grade_after_resolve_outlink_reverification():
    # 맥북에어 M2 실사례(2026-08-11): 옥션/G마켓이 domain은 알아도 url_rule=None
    # 이라 A등급에서 통째로 빠져서, 실제로는 더 비싼 11번가/롯데ON이 "최저가"로
    # 추천되는 문제가 있었다. resolve_outlink()가 옥션/G마켓 bridge_url에서도
    # 정상 동작한다는 걸 실측 확인하고 redirect_resolved로 바꿨다 - 회귀 방지용.
    html = _danawa_html(
        "테스트 상품",
        [
            _offer_li("옥션", "1,300,000", "EE715"),
            _offer_li("G마켓", "1,310,000", "EE128"),
            _offer_li("11번가", "1,880,000", "TH201", link_pcode="999"),
        ],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    by_seller = {o.seller: o for o in table.offers}
    assert by_seller["옥션"].linkable is True
    assert by_seller["G마켓"].linkable is True

    cheapest = cheapest_linkable_raw_offer(result)
    assert cheapest["seller"] == "옥션"
    assert cheapest["price_krw"] == 1300000


def test_emart_and_hmall_are_a_grade_after_reverification():
    # 미확인 소형몰 재검증(2026-08-11, 사용자 요청 "지금 가격들이 최저가들이
    # 아닌데"에 대한 대응). CMPNYC_MAP의 미검증 11종 bridge_url로 resolve_outlink()를
    # 실제 호출해봤더니 - 스마트스토어 계열(TY6C4 등)은 게이트웨이가 429라
    # 여전히 미검증, 이마트몰/현대Hmall만 실제 상품 페이지 도달을 확인해 승격.
    html = _danawa_html(
        "테스트 상품",
        [
            _offer_li("이마트몰", "1,200,000", "EE311"),
            _offer_li("현대Hmall", "1,250,000", "ED907"),
            _offer_li("우리집식탁매니저", "1,100,000", "TY6C4"),  # 여전히 B등급(스마트스토어 게이트웨이 429)
        ],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    by_seller = {o.seller: o for o in table.offers}
    assert by_seller["이마트몰"].linkable is True
    assert by_seller["현대Hmall"].linkable is True
    assert by_seller["우리집식탁매니저"].linkable is False


# -- 5. domain=None offer의 trust는 None (0.3 아님) ----------------------------


def test_unknown_cmpnyc_domain_is_none_not_downgraded():
    html = _danawa_html("테스트 상품", [_offer_li("어떤판매처", "10,000", "ZZZZZ_UNKNOWN")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    table = build_price_table(result)
    offer = table.offers[0]
    assert offer.domain is None
    assert offer.trust is None
    assert offer.linkable is False


# -- 6. 응답 URL은 bridge_url 자체다 (robots.txt 재확인 이후 방향이 바뀐 계약) ---


def test_decide_response_url_is_the_danawa_bridge_url_itself(monkeypatch):
    """(2026-08-12) prod.danawa.com/robots.txt의 `Disallow: /bridge/`를 발견해서
    resolve_purchase_url()이 서버에서 /bridge/를 직접 페치해 최종 판매처 URL을
    알아내던 방식(구 danawa.resolve_outlink())을 폐기했다 - 이제 bridge_url
    문자열 자체를 그대로 돌려준다. 예전엔 정반대로 "bridge_url/loadingBridge/
    cmpnyc/prod.danawa.com이 응답에 절대 안 나와야 한다"는 테스트였다 - 방향이
    바뀐 것 자체가 회귀 방지 대상이라 이름과 내용을 새 계약에 맞게 다시 썼다."""
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, "https://prod.danawa.com/info?pcode=1")

    html = _danawa_html(
        "테스트 상품",
        [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="555"), _offer_li("옥션", "24,000", "EE715")],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    async def _fake_fetch(url):
        return result

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["decision"]["price_source"] == "danawa_offer"
    assert data["decision"]["url"] == (
        "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=555"
    )


# -- 7. 기존 응답 필드가 전부 유지되는가 ----------------------------------------


def test_existing_response_fields_are_preserved(monkeypatch):
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, None)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["mode"] == "single"
    assert data["query"] == "테스트 상품"
    assert isinstance(data["proposals"], list)
    assert len(data["proposals"]) == 3
    for field in ("product_name", "price", "retailer", "url", "reasoning", "chosen_agent"):
        assert field in data["decision"]
    # 새 필드는 추가됐지만 기존 필드는 하나도 사라지지 않았다.
    assert "price_source" in data["decision"]
    assert "price_table" in data


# -- 8. 다나와 URL이 4개 이상일 때 3개로 잘리는가 -------------------------------


# -- STEP 6: 상품명 완전 일치 + 가격 없음 -> 다나와 가격으로 채워지는가 ----


def test_name_match_fills_price_when_llm_price_missing():
    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="777")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="테스트 상품",
        price="가격 정보 없음",
        retailer="다나와",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "danawa_offer"
    assert enriched.price == "23,000원"
    assert enriched.retailer == "쿠팡"
    assert enriched.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=777"


# -- STEP 6: 모델명 충돌(V8 vs V15)이면 매칭 실패 -------------------------------


def test_model_token_conflict_blocks_match_despite_high_fuzzy_ratio():
    html = _danawa_html("다이슨 V15 무선청소기", [_offer_li("쿠팡", "500,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="다이슨 V8 무선청소기",
        price="400,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"
    assert enriched.url == "https://example.com/guess"


# -- STEP 6: 수량 충돌(24개 vs 12개)이면 매칭 실패 ------------------------------


def test_quantity_token_conflict_blocks_match():
    html = _danawa_html("테스트 상품 12개", [_offer_li("쿠팡", "10,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="테스트 상품 24개",
        price="20,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"


# -- PART 4-1: 스펙 토큰 family 가드 (실제 100개 배치에서 관측된 케이스) -------


def test_chip_generation_conflict_blocks_match_ipad_air():
    html = _danawa_html("APPLE 2025 iPad Air 11 M3 (128GB)", [_offer_li("쿠팡", "1,000,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="APPLE 2024 iPad Air 11 M2 (128GB)",
        price="989,970원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"


def test_chip_generation_conflict_blocks_match_ipad_pro():
    html = _danawa_html("APPLE 2025 iPad Pro 13 M5 (256GB)", [_offer_li("쿠팡", "2,000,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="APPLE 2024 iPad Pro 13 M4 (256GB)",
        price="1,900,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"


def test_spec_token_on_one_side_only_still_matches():
    html = _danawa_html("iPad Air M2 128GB", [_offer_li("쿠팡", "900,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="iPad Air M2",
        price="900,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "danawa_offer"


def test_multiple_values_in_same_family_but_identical_sets_still_matches():
    # "12GB"(램)와 "256GB"(저장용량)이 둘 다 #GB family에 묶이는데, 값
    # 집합이 양쪽 다 동일하면 충돌이 아니어야 한다 - 자기 자신과 비교해도
    # 실패하면 안 된다는 최소 불변식.
    html = _danawa_html(
        "삼성전자 갤럭시탭S10 울트라 (램12GB,256GB)", [_offer_li("쿠팡", "1,200,000", "TP40F", link_pcode="1")]
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="삼성전자 갤럭시탭S10 울트라 (램12GB,256GB)",
        price="1,190,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "danawa_offer"


def test_different_multi_value_specs_in_same_family_conflict():
    html = _danawa_html("삼성전자 갤럭시탭S10 (램12GB,256GB)", [_offer_li("쿠팡", "1,000,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="삼성전자 갤럭시탭S10 (램8GB,128GB)",
        price="800,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"


def test_same_spec_token_matches():
    html = _danawa_html("갤럭시 버즈3 프로 SM-R630N", [_offer_li("쿠팡", "230,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="갤럭시 버즈3 프로 SM-R630N",
        price="235,000원",
        retailer="쿠팡",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "danawa_offer"


# -- PART 1: 배타 토큰 충돌(백미 vs 발아현미)이면 매칭 실패 (실제 관측 케이스) --


def test_exclusive_token_conflict_blocks_match_end_to_end():
    html = _danawa_html("햇반 발아현미 210g (24개)", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    decision = Decision(
        product_name="햇반 백미 210g (24개)",
        price="25,900원",
        retailer="마켓컬리",
        url="https://www.kurly.com/goods/1",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    enriched = asyncio.run(enrich_decision(decision, result))

    assert enriched.price_source == "llm_guess"
    assert enriched.retailer == "마켓컬리"


# -- STEP 6: "무이자 12개월"이 수량 토큰으로 오인되지 않는가 --------------------


def test_installment_months_not_mistaken_for_quantity_token():
    tokens = _extract_quantity_tokens("최대 12개월 무이자할부 *결제 금액에 따라 다름")
    assert tokens == set()
    # 진짜 수량 표기는 여전히 잡아야 한다.
    assert _extract_quantity_tokens("210g (24개)") == {"210G", "24개"}


# -- STEP 6: decision.url이 danawa.com이면 A등급 offer로 교체되는가 ------------


def test_exclude_price_comparison_site_as_final_pick_replaces_with_a_grade_offer():
    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="999")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=42", html)
    table = build_price_table(result)

    decision = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="다나와",
        url="https://prod.danawa.com/info?pcode=42",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    replaced = asyncio.run(exclude_price_comparison_site_as_final_pick(decision, [], [(table, result)]))

    assert replaced.price_source == "danawa_offer"
    assert replaced.retailer == "쿠팡"
    assert replaced.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=999"


def test_exclude_leaves_bridge_passthrough_url_untouched():
    """실제로 잡았던 버그(2026-08-12) 회귀 테스트 - resolve_purchase_url()이
    bridge_url(prod.danawa.com/bridge/...)을 그대로 돌려주게 되면서, 호스트가
    danawa.com 서브도메인이라는 이유만으로 exclude_price_comparison_site_as_final_pick()이
    "다나와 자신이 최종 판매처로 뽑혔다"고 오인해 멀쩡한 danawa_offer 추천을
    엉뚱한 LLM 추측(fallback_proposal, 완전히 다른 상품일 수도 있음)으로
    갈아치우고 있었다. retailer가 "다나와"가 아니라 실제 판매처(쿠팡)면
    손대지 않아야 한다."""
    decision = Decision(
        product_name="테스트 상품",
        price="23,000원",
        retailer="쿠팡",
        url="https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=999",
        reasoning="다나와 실측 최저가",
        chosen_agent="gpt",
        price_source="danawa_offer",
    )
    fallback_proposal = Proposal(
        agent="gemini",
        product_name="전혀 다른 상품",
        price="99,000원",
        retailer="G마켓",
        url="https://item.gmarket.co.kr/Item?goodscode=1",
        reasoning="대체 제안",
    )

    replaced = asyncio.run(exclude_price_comparison_site_as_final_pick(decision, [fallback_proposal], []))

    assert replaced.retailer == "쿠팡"
    assert replaced.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=999"
    assert replaced.price_source == "danawa_offer"


def test_exclude_danawa_falls_back_to_other_proposal_when_no_a_grade_match():
    # pcode가 다른 페이지라 매칭 자체가 안 되는 상황(=A등급 후보 없음).
    html = _danawa_html("다른 상품", [_offer_li("옥션", "10,000", "EE715")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    decision = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="다나와",
        url="https://prod.danawa.com/info?pcode=999",  # table의 pcode(1)와 다름
        reasoning="테스트",
        chosen_agent="gpt",
    )
    fallback_proposal = Proposal(
        agent="gemini",
        product_name="테스트 상품",
        price="21,000원",
        retailer="G마켓",
        url="https://item.gmarket.co.kr/Item?goodscode=1",
        reasoning="대체 제안",
    )

    replaced = asyncio.run(exclude_price_comparison_site_as_final_pick(decision, [fallback_proposal], [(table, result)]))

    assert replaced.price_source == "llm_guess"  # 검증된 게 아니라 다른 LLM 추측일 뿐


def test_exclude_enuri_falls_back_to_other_proposal():
    # PART 4-3: 에누리도 다나와와 동일하게 취급 - 아직 어댑터가 없어 pcode
    # 매칭 단계는 없고, 바로 다른 에이전트 제안으로 넘어가야 한다.
    decision = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="에누리",
        url="https://www.enuri.com/direct/product.jsp?g_code=1",
        reasoning="테스트",
        chosen_agent="gpt",
    )
    fallback_proposal = Proposal(
        agent="gemini",
        product_name="테스트 상품",
        price="21,000원",
        retailer="G마켓",
        url="https://item.gmarket.co.kr/Item?goodscode=1",
        reasoning="대체 제안",
    )

    replaced = asyncio.run(exclude_price_comparison_site_as_final_pick(decision, [fallback_proposal], []))

    assert replaced.price_source == "llm_guess"
    assert replaced.retailer == "G마켓"
    assert "enuri.com" not in replaced.url


def test_exclude_leaves_non_comparison_domain_untouched():
    decision = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="쿠팡",
        url="https://www.coupang.com/vp/products/1",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    replaced = asyncio.run(exclude_price_comparison_site_as_final_pick(decision, [], []))

    assert replaced.url == "https://www.coupang.com/vp/products/1"
    assert replaced.retailer == "쿠팡"
    assert replaced.price_source == "llm_guess"


def test_select_danawa_urls_caps_at_max_danawa_urls():
    results = [
        SearchResult(title=f"상품{i}", url=f"https://prod.danawa.com/info?pcode={i}", snippet="", score=float(i))
        for i in range(7)
    ]
    selected = select_danawa_urls(results)

    assert len(selected) == MAX_DANAWA_URLS == 5
    # score 내림차순 상위 5개(6,5,4,3,2)만 남아야 한다.
    assert selected == [
        "https://prod.danawa.com/info?pcode=6",
        "https://prod.danawa.com/info?pcode=5",
        "https://prod.danawa.com/info?pcode=4",
        "https://prod.danawa.com/info?pcode=3",
        "https://prod.danawa.com/info?pcode=2",
    ]


# -- PART 4-2: 다나와 후보를 judge 선택지 풀에 직접 추가 -----------------------


def test_build_danawa_candidates_produces_agent_danawa_proposal():
    html = _danawa_html("전혀 다른 상품명", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    proposals = asyncio.run(build_danawa_candidates([(table, result)], agent_candidates=[]))

    assert len(proposals) == 1
    assert proposals[0].agent == "danawa"
    assert proposals[0].product_name == "전혀 다른 상품명"
    assert proposals[0].price == "23,000원"
    assert proposals[0].retailer == "쿠팡"
    assert proposals[0].url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=1"


def test_build_danawa_candidates_skips_page_without_a_grade_offer(monkeypatch):
    html = _danawa_html("B등급만 있는 상품", [_offer_li("호갱마켓", "20,000", "TW627F")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    proposals = asyncio.run(build_danawa_candidates([(table, result)], agent_candidates=[]))

    assert proposals == []


def test_build_danawa_candidates_records_consensus_with_matching_llm_agent():
    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)
    table = build_price_table(result)

    gpt_candidates = AgentCandidates(
        agent="gpt",
        candidates=[
            AgentCandidate(
                product_name="테스트 상품", price_krw=23000, retailer="쿠팡",
                url="https://www.coupang.com/vp/products/1", reasoning="gpt 근거",
            )
        ],
    )

    proposals = asyncio.run(build_danawa_candidates([(table, result)], agent_candidates=[gpt_candidates]))

    assert len(proposals) == 1
    assert "gpt" in proposals[0].reasoning
    assert "합의" in proposals[0].reasoning


def test_judge_choosing_danawa_sets_price_source_and_real_url(monkeypatch):
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, "https://prod.danawa.com/info?pcode=1")

    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    async def _fake_fetch(url):
        return result

    async def _judge_picks_danawa(query, proposals):
        danawa_pick = next(p for p in proposals if p.agent == "danawa")
        return Decision(
            product_name=danawa_pick.product_name,
            price=danawa_pick.price,
            retailer=danawa_pick.retailer,
            url=danawa_pick.url,
            reasoning="다나와 실측가가 가장 신뢰도 높음",
            chosen_agent="danawa",
        )

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)
    monkeypatch.setattr("app.agents.judge.decide", _judge_picks_danawa)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["decision"]["chosen_agent"] == "danawa"
    assert data["decision"]["price_source"] == "danawa_offer"
    assert data["decision"]["url"] == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=1"
    # 노출 스키마의 proposals는 LLM 3개 그대로 - 다나와 후보는 judge 선택지
    # 풀에만 들어가고 응답 구조 자체는 안 바뀐다.
    assert len(data["proposals"]) == 3
    assert all(p["agent"] != "danawa" for p in data["proposals"])


# -- B-3a/B-3b: "N몰" 표기와 상세페이지 10개 offer 사이의 정직한 표기 --------------


def _three_offer_result() -> dict:
    html = _danawa_html(
        "테스트 상품",
        [
            _offer_li("쿠팡", "10,000", "A"),
            _offer_li("11번가", "11,000", "B"),
            _offer_li("G마켓", "12,000", "C"),
        ],
    )
    return parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)


def test_parse_danawa_html_defaults_total_mall_count_to_none():
    result = _three_offer_result()
    assert result["total_mall_count"] is None
    assert result["offers_shown"] == 3
    assert result["is_partial"] is False


def test_with_total_mall_count_marks_partial_when_total_exceeds_shown():
    result = _three_offer_result()
    merged = with_total_mall_count(result, 150)
    assert merged["total_mall_count"] == 150
    assert merged["is_partial"] is True
    # 원본은 그대로다 - 순수 함수(새 dict 반환)여야 한다
    assert result["total_mall_count"] is None


def test_with_total_mall_count_not_partial_when_total_equals_shown():
    result = _three_offer_result()
    merged = with_total_mall_count(result, 3)
    assert merged["is_partial"] is False


def test_with_total_mall_count_none_stays_not_partial():
    result = _three_offer_result()
    merged = with_total_mall_count(result, None)
    assert merged["total_mall_count"] is None
    assert merged["is_partial"] is False


def test_build_price_table_exposes_partial_coverage_fields():
    result = _three_offer_result()
    merged = with_total_mall_count(result, 150)

    table = build_price_table(merged)

    assert table.total_mall_count == 150
    assert table.offers_shown == 3
    assert table.is_partial is True
    assert table.price_label == "확인된 최저가"


def test_build_price_table_price_label_stays_default_when_not_partial():
    result = _three_offer_result()

    table = build_price_table(result)

    assert table.is_partial is False
    assert table.price_label == "최저가"


# -- 로컬 성능 실측 배선: fetch_price_tables가 Tavily + 다나와 직접검색을 합집합으로 쓴다 --


def _fetch_returning(pcode_to_name: dict[str, str], fetched_urls: list[str]):
    async def _fake_fetch(url):
        fetched_urls.append(url)
        pcode = _query_param(url, "pcode")
        name = pcode_to_name.get(pcode, f"상품{pcode}")
        html = _danawa_html(name, [_offer_li("쿠팡", "10,000", "A")])
        return parse_danawa_html(url, html)

    return _fake_fetch


def test_fetch_price_tables_merges_tavily_and_direct_search_urls_deduped_by_pcode(monkeypatch):
    async def _search_danawa(query, limit=3):
        return [{"pcode": "2", "product_name": "직접검색상품", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    fetched_urls: list[str] = []
    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fetch_returning({}, fetched_urls))

    results = [SearchResult(title="다나와", url="https://prod.danawa.com/info?pcode=1", snippet="", score=0.9)]
    tables = asyncio.run(fetch_price_tables("테스트 쿼리", results))

    pcodes_fetched = {_query_param(u, "pcode") for u in fetched_urls}
    assert pcodes_fetched == {"1", "2"}
    assert len(tables) == 2


def test_fetch_price_tables_dedupes_when_both_sources_return_same_pcode(monkeypatch):
    async def _search_danawa(query, limit=3):
        return [{"pcode": "1", "product_name": "중복상품", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    fetched_urls: list[str] = []
    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fetch_returning({}, fetched_urls))

    results = [SearchResult(title="다나와", url="https://prod.danawa.com/info?pcode=1", snippet="", score=0.9)]
    tables = asyncio.run(fetch_price_tables("테스트 쿼리", results))

    assert len(fetched_urls) == 1  # pcode 기준 중복이라 한 번만 페치
    assert len(tables) == 1


def test_fetch_price_tables_falls_back_to_tavily_when_direct_search_blocked(monkeypatch):
    from fetchers.danawa_search import DanawaSearchBlocked

    async def _search_danawa(query, limit=3):
        raise DanawaSearchBlocked(403, query)

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    fetched_urls: list[str] = []
    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fetch_returning({}, fetched_urls))

    results = [SearchResult(title="다나와", url="https://prod.danawa.com/info?pcode=1", snippet="", score=0.9)]
    tables = asyncio.run(fetch_price_tables("테스트 쿼리", results))

    assert len(tables) == 1  # 차단되어도 Tavily 경로는 살아있다


def test_fetch_price_tables_caps_total_urls_at_max_danawa_urls(monkeypatch):
    async def _search_danawa(query, limit=5):
        return [
            {"pcode": str(p), "product_name": f"검색상품{p}", "total_mall_count": None} for p in (10, 11, 12, 13, 14)
        ]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    fetched_urls: list[str] = []
    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fetch_returning({}, fetched_urls))

    results = [SearchResult(title="다나와", url="https://prod.danawa.com/info?pcode=1", snippet="", score=0.9)]
    tables = asyncio.run(fetch_price_tables("테스트 쿼리", results))

    assert len(fetched_urls) == MAX_DANAWA_URLS == 5
    assert {_query_param(u, "pcode") for u in fetched_urls} == {"1", "10", "11", "12", "13"}


# -- run_danawa_only_debate: LLM 호출 0번, 규칙 기반 다나와 전용 경로 ---------------


def _forbid_llm_calls(monkeypatch):
    """gpt/gemini/deepseek/judge 중 하나라도 불리면 테스트가 즉시 실패하게 만든다 -
    "LLM 호출 0번"이라는 계약을 실제로 검증하기 위함."""

    async def _boom(*args, **kwargs):
        raise AssertionError("LLM이 호출됐다 - run_danawa_only_debate는 LLM을 절대 부르면 안 된다")

    monkeypatch.setattr("app.agents.gpt.propose", _boom)
    monkeypatch.setattr("app.agents.gemini.propose", _boom)
    monkeypatch.setattr("app.agents.deepseek.propose", _boom)
    monkeypatch.setattr("app.agents.judge.decide", _boom)


def _patch_direct_danawa_search(monkeypatch, pcode: str | None):
    """run_danawa_only_debate는 Tavily를 아예 안 쓰고 search_danawa()만으로
    pcode를 찾으므로(속도 최적화 2차 - Tavily 15~20초 병목 제거), 이 테스트들은
    _patch_search가 아니라 search_danawa 자체를 직접 목킹해야 한다."""
    items = [{"pcode": pcode, "product_name": "테스트 상품", "total_mall_count": None}] if pcode else []

    async def _search_danawa(query, limit=5):
        return items

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)


def test_run_danawa_only_debate_never_calls_any_llm(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, "1")

    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "10,000", "TP40F")])

    async def _fake_fetch(url):
        return parse_danawa_html(url, html)

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    result = asyncio.run(run_danawa_only_debate("테스트 상품"))

    assert result.proposals == []
    assert result.decision.chosen_agent == "danawa"
    assert result.decision.price_source == "danawa_offer"
    assert result.decision.retailer == "쿠팡"
    assert result.decision.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=999"
    assert result.price_table is not None


def test_run_danawa_only_debate_raises_when_no_price_table(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, None)  # 다나와 URL 자체를 못 찾는 경우

    try:
        asyncio.run(run_danawa_only_debate("존재하지 않는 상품"))
        raise AssertionError("RuntimeError가 났어야 한다")
    except RuntimeError as exc:
        assert "찾지 못했다" in str(exc)


def test_run_danawa_only_debate_raises_when_no_a_grade_offer(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, "1")

    # bridge_url의 cmpnyc가 CMPNYC_MAP에 없는 미확인 판매처 - linkable=False뿐이라
    # A등급이 하나도 없다.
    html = _danawa_html("테스트 상품", [_offer_li("미확인몰", "10,000", "UNKNOWN_CODE_XYZ")])

    async def _fake_fetch(url):
        return parse_danawa_html(url, html)

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    try:
        asyncio.run(run_danawa_only_debate("테스트 상품"))
        raise AssertionError("RuntimeError가 났어야 한다")
    except RuntimeError as exc:
        assert "A등급" in str(exc)


def test_decide_danawa_only_endpoint_returns_502_on_no_price_table(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, None)

    resp = client.post("/decide/danawa-only", json={"query": "존재하지 않는 상품"})

    assert resp.status_code == 502


def test_decide_danawa_only_endpoint_returns_200_with_no_proposals(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, "1")

    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "10,000", "TP40F")])

    async def _fake_fetch(url):
        return parse_danawa_html(url, html)

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    resp = client.post("/decide/danawa-only", json={"query": "테스트 상품"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["proposals"] == []
    assert data["decision"]["chosen_agent"] == "danawa"


def test_decide_auto_routes_to_danawa_only_when_no_llm_key_configured(monkeypatch):
    # 일부러 _patch_llm_layer를 안 쓴다 - gpt/gemini/deepseek/judge를 mock하지
    # 않은 채로도(=진짜로 안 불려야) 200이 나와야 라우팅이 제대로 됐다는 뜻이다.
    # 잘못 라우팅되면 mock 안 된 진짜 LLM 호출이 conftest의 네트워크 차단에
    # 걸려 502가 난다.
    monkeypatch.setattr("app.debate._any_llm_key_configured", lambda: False)
    monkeypatch.setattr("app.autocomplete.record_terms", lambda terms: None)
    _patch_direct_danawa_search(monkeypatch, "1")

    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "10,000", "TP40F")])

    async def _fake_fetch(url):
        return parse_danawa_html(url, html)

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    # 메인 /decide 엔드포인트로 쐈는데도(=/decide/danawa-only가 아니다) LLM 키가
    # 없으면 자동으로 다나와 전용 경로를 타야 한다.
    resp = client.post("/decide", json={"query": "테스트 상품"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["proposals"] == []
    assert data["decision"]["chosen_agent"] == "danawa"


# -- run_danawa_only_debate: 변형(같은 상품) vs 애매모호(다른 상품) 분기 -------------


def _patch_direct_danawa_search_multi(monkeypatch, items: list[dict]):
    async def _search_danawa(query, limit=5):
        return items

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)


def test_is_single_product_family_true_for_spec_variants():
    # 실측(2026-08-11): "맥북에어 m2" 색상/용량 변형끼리 이름 유사도 88.6~100.
    names = [
        "APPLE 맥북에어13 M2 8코어 CPU, 8코어 GPU 실버 (램8GB, SSD 256GB)",
        "APPLE 맥북에어13 M2 8코어 CPU, 10코어 GPU 그레이 (램8GB, SSD 512GB)",
    ]
    from app.schemas import PriceTable

    tables = [(PriceTable(product_name=n, offers=[]), {}) for n in names]
    assert _is_single_product_family(tables) is True


def test_is_single_product_family_false_for_different_products():
    # 실측(2026-08-11): "노트북" 검색 후보(브랜드/모델 자체가 다름) 이름 유사도 32.9~46.5.
    names = ["LG전자 2026 그램 프로16 16Z95U-GS5WK", "MSI 벡터 A16 HX A8WHG-R9 QHD+"]
    from app.schemas import PriceTable

    tables = [(PriceTable(product_name=n, offers=[]), {}) for n in names]
    assert _is_single_product_family(tables) is False


def test_run_danawa_only_debate_prefers_cheapest_variant_over_richest_table(monkeypatch):
    """맥북에어 M2 실측 버그 재현/회귀 테스트 - pcode=2 페이지가 offer 2개로
    더 "풍부"해도(예전 pick_primary라면 이걸 골랐을 것), 실제 최저가는
    offer 1개뿐인 pcode=1 쪽이면 그쪽을 최종 추천으로 써야 한다."""
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search_multi(
        monkeypatch,
        [
            {"pcode": "1", "product_name": "테스트 상품 실버 256GB", "total_mall_count": None},
            {"pcode": "2", "product_name": "테스트 상품 그레이 256GB", "total_mall_count": None},
        ],
    )

    html_by_pcode = {
        "1": _danawa_html("테스트 상품 실버 256GB", [_offer_li("쿠팡", "1,300,000", "TP40F")]),
        "2": _danawa_html(
            "테스트 상품 그레이 256GB",
            [
                _offer_li("쿠팡", "1,600,000", "TP40F"),
                _offer_li("11번가", "1,650,000", "TH201", link_pcode="123"),
            ],
        ),
    }

    async def _fake_fetch(url):
        pcode = _query_param(url, "pcode")
        return parse_danawa_html(url, html_by_pcode[pcode])

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    result = asyncio.run(run_danawa_only_debate("테스트 상품"))

    assert result.mode == "single"
    assert result.decision.price == "1,300,000원"
    assert result.decision.product_name == "테스트 상품 실버 256GB"


def test_run_danawa_only_debate_returns_options_for_ambiguous_query(monkeypatch):
    """"노트북"처럼 검색어가 서로 다른 상품에 걸쳐 있으면 하나를 억지로
    고르지 않고 BulkDecideResponse(가격 오름차순 후보 목록)를 반환한다."""
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search_multi(
        monkeypatch,
        [
            {"pcode": "1", "product_name": "LG전자 그램 노트북", "total_mall_count": None},
            {"pcode": "2", "product_name": "MSI 게이밍 노트북", "total_mall_count": None},
        ],
    )

    html_by_pcode = {
        "1": _danawa_html("LG전자 그램 노트북", [_offer_li("쿠팡", "2,000,000", "TP40F")]),
        "2": _danawa_html("MSI 게이밍 노트북", [_offer_li("11번가", "1,500,000", "TH201", link_pcode="123")]),
    }

    async def _fake_fetch(url):
        pcode = _query_param(url, "pcode")
        return parse_danawa_html(url, html_by_pcode[pcode])

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    result = asyncio.run(run_danawa_only_debate("노트북"))

    assert result.mode == "bulk"
    assert [o.brand for o in result.decision.options] == ["MSI 게이밍 노트북", "LG전자 그램 노트북"]
    assert result.decision.options[0].price == "1,500,000원"
    assert result.decision.options[0].url == "https://m.11st.co.kr/products/ma/123"


def test_decide_danawa_only_endpoint_returns_bulk_mode_for_ambiguous_query(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search_multi(
        monkeypatch,
        [
            {"pcode": "1", "product_name": "LG전자 그램 노트북", "total_mall_count": None},
            {"pcode": "2", "product_name": "MSI 게이밍 노트북", "total_mall_count": None},
        ],
    )

    html_by_pcode = {
        "1": _danawa_html("LG전자 그램 노트북", [_offer_li("쿠팡", "2,000,000", "TP40F")]),
        "2": _danawa_html("MSI 게이밍 노트북", [_offer_li("11번가", "1,500,000", "TH201", link_pcode="123")]),
    }

    async def _fake_fetch(url):
        pcode = _query_param(url, "pcode")
        return parse_danawa_html(url, html_by_pcode[pcode])

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    resp = client.post("/decide/danawa-only", json={"query": "노트북"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "bulk"
    assert len(data["decision"]["options"]) == 2


# -- run_danawa_only_debate_stream: 끝나는 대로 하나씩 + 마지막에 final ---------


def test_run_danawa_only_debate_stream_yields_candidates_in_completion_order(monkeypatch):
    """사용자 요청(2026-08-11, "1개 서치 완료되면 1개 올려줘 먼저") 회귀 테스트 -
    pcode=1이 더 늦게 끝나도록 인위로 지연시켜, candidate 이벤트가 입력 순서가
    아니라 완료 순서로 나오는지 확인한다(asyncio.as_completed 계약)."""
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search_multi(
        monkeypatch,
        [
            {"pcode": "1", "product_name": "테스트 상품 A", "total_mall_count": None},
            {"pcode": "2", "product_name": "테스트 상품 B", "total_mall_count": None},
        ],
    )

    html_by_pcode = {
        "1": _danawa_html("테스트 상품 A", [_offer_li("쿠팡", "20,000", "TP40F")]),
        "2": _danawa_html("테스트 상품 B", [_offer_li("쿠팡", "10,000", "TP40F")]),
    }

    async def _fake_fetch(url):
        pcode = _query_param(url, "pcode")
        if pcode == "1":
            await asyncio.sleep(0.05)
        return parse_danawa_html(url, html_by_pcode[pcode])

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    async def _collect():
        return [event async for event in run_danawa_only_debate_stream("테스트 상품")]

    events = asyncio.run(_collect())

    candidate_events = [e for e in events if e["type"] == "candidate"]
    final_events = [e for e in events if e["type"] == "final"]

    assert len(candidate_events) == 2
    assert candidate_events[0]["product_name"] == "테스트 상품 B"
    assert candidate_events[1]["product_name"] == "테스트 상품 A"
    assert events[-1]["type"] == "final"
    assert len(final_events) == 1
    assert final_events[0]["result"]["mode"] == "single"
    assert final_events[0]["result"]["decision"]["price"] == "10,000원"


def test_decide_danawa_only_stream_endpoint_returns_sse_events(monkeypatch):
    _forbid_llm_calls(monkeypatch)
    _patch_direct_danawa_search(monkeypatch, "1")

    html = _danawa_html("테스트 상품", [_offer_li("쿠팡", "10,000", "TP40F")])

    async def _fake_fetch(url):
        return parse_danawa_html(url, html)

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)

    resp = client.post("/decide/danawa-only/stream", json={"query": "테스트 상품"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in resp.text.split("\n\n") if line.strip()]
    events = [json.loads(line[len("data: "):]) for line in lines]

    assert events[0]["type"] == "candidate"
    assert events[-1]["type"] == "final"
    assert events[-1]["result"]["decision"]["chosen_agent"] == "danawa"
