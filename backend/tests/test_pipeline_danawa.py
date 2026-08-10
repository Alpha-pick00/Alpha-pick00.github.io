"""STEP 3 파이프라인 연결 테스트. 네트워크 요청 금지 - 전부 monkeypatch로
실제 Tavily/LLM/다나와 호출을 막고, 픽스처처럼 만든 합성 HTML만 쓴다."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.debate import run_single_debate
from app.main import app
from app.price_table import (
    build_price_table,
    cheapest_linkable_raw_offer,
    enrich_decision,
    select_danawa_urls,
)
from app.schemas import AgentCandidate, AgentCandidates, Decision, SearchResult
from fetchers.danawa import parse_danawa_html

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
    # EE715(옥션)/EE128(G마켓)는 CMPNYC_MAP에서 domain은 있지만 url_rule=None
    # (B등급) - A등급이 전혀 없는 페이지를 만든다.
    html = _danawa_html(
        "테스트 상품",
        [_offer_li("옥션", "20,000", "EE715"), _offer_li("G마켓", "21,000", "EE128")],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    assert cheapest_linkable_raw_offer(result) is None

    original = Decision(
        product_name="테스트 상품",
        price="20,000원",
        retailer="옥션",
        url="https://www.auction.co.kr/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )
    enriched = asyncio.run(enrich_decision(original, result))

    assert enriched.price_source == "llm_guess"
    assert enriched.url == "https://www.auction.co.kr/guess"
    assert enriched.price == "20,000원"


# -- 4. 최저가가 B등급이면 링크는 A등급 최저가로 --------------------------------


def test_cheapest_linkable_offer_skips_cheaper_b_grade():
    html = _danawa_html(
        "테스트 상품",
        [
            _offer_li("옥션", "19,000", "EE715"),  # B등급, 더 저렴
            _offer_li("쿠팡", "23,000", "TP40F", link_pcode="555"),  # A등급
        ],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    table = build_price_table(result)
    assert table.offers[0].seller == "옥션"
    assert table.offers[0].price_krw == 19000
    assert table.offers[0].linkable is False
    assert table.offers[1].seller == "쿠팡"
    assert table.offers[1].linkable is True

    cheapest_linkable = cheapest_linkable_raw_offer(result)
    assert cheapest_linkable["seller"] == "쿠팡"
    assert cheapest_linkable["price_krw"] == 23000


# -- 5. domain=None offer의 trust는 None (0.3 아님) ----------------------------


def test_unknown_cmpnyc_domain_is_none_not_downgraded():
    html = _danawa_html("테스트 상품", [_offer_li("어떤판매처", "10,000", "ZZZZZ_UNKNOWN")])
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    table = build_price_table(result)
    offer = table.offers[0]
    assert offer.domain is None
    assert offer.trust is None
    assert offer.linkable is False


# -- 6. bridge_url이 응답 어디에도 노출되지 않는다 (반드시 검증) ---------------


def test_bridge_url_never_leaks_into_response(monkeypatch):
    _patch_llm_layer(monkeypatch)
    _patch_search(monkeypatch, "https://prod.danawa.com/info?pcode=1")

    html = _danawa_html(
        "테스트 상품",
        [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="555"), _offer_li("옥션", "24,000", "EE715")],
    )
    result = parse_danawa_html("https://prod.danawa.com/info?pcode=1", html)

    async def _fake_fetch(url):
        return result

    async def _fake_resolve_outlink(bridge_url):
        return "https://www.coupang.com/vp/products/555", "555"

    monkeypatch.setattr("fetchers.danawa.fetch_danawa_offers", _fake_fetch)
    monkeypatch.setattr("fetchers.danawa.resolve_outlink", _fake_resolve_outlink)

    resp = client.post("/decide", json={"query": "테스트 상품"})
    assert resp.status_code == 200
    body_text = resp.text

    assert "bridge_url" not in body_text
    assert "loadingBridge" not in body_text
    assert "cmpnyc" not in body_text
    # 응답에 나오는 URL은 실제로 해석된 최종 URL이어야 한다 - 다나와 중계
    # 도메인 자체가 등장하면 안 된다.
    assert "prod.danawa.com" not in body_text

    data = resp.json()
    assert data["decision"]["price_source"] == "danawa_offer"
    assert data["decision"]["url"] == "https://www.coupang.com/vp/products/555"


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


def test_select_danawa_urls_caps_at_three():
    results = [
        SearchResult(title=f"상품{i}", url=f"https://prod.danawa.com/info?pcode={i}", snippet="", score=float(i))
        for i in range(5)
    ]
    selected = select_danawa_urls(results)

    assert len(selected) == 3
    # score 내림차순 상위 3개 (4, 3, 2)만 남아야 한다.
    assert selected == [
        "https://prod.danawa.com/info?pcode=4",
        "https://prod.danawa.com/info?pcode=3",
        "https://prod.danawa.com/info?pcode=2",
    ]
