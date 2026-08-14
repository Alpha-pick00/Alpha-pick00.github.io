import asyncio
import json

from app.adk_pipeline import (
    _apply_challenge,
    _augment_search_query,
    _build_decision,
    _danawa_tables_from_state,
    _finalize_with_danawa,
    _format_price_krw,
    _is_danawa_product_url,
    _judge_eligible_proposals,
    _merge_proposals,
    _urls_to_extract,
)
from app.agents.base import CHALLENGE_INSTRUCTIONS, build_challenge_prompt
from app.category import CategoryClassification
from app.price_table import build_price_table
from app.schemas import ChallengeResult, ChallengeVerdict, Decision, Proposal, SearchResult
from fetchers.danawa import parse_danawa_html

COUPANG_URL = "https://coupang.com/vp/products/1"
ELEVENST_URL = "https://11st.co.kr/products/2"


def _raw_candidate(product_name: str, price_krw: int, url: str) -> dict:
    return {"product_name": product_name, "price_krw": price_krw, "retailer": "쿠팡", "url": url}


def _merged_candidate(url: str, proposed_by: list[str], product_name: str = "무선 마우스") -> dict:
    return {
        "product_name": product_name,
        "price_krw": 12900,
        "url": url,
        "retailer": "쿠팡",
        "reasons": ["근거"],
        "proposed_by": proposed_by,
        "signals": {},
        "final_score": 0.0,
        "flags": {"shared_url": False, "shared_url_count": 0},
    }


# --- _format_price_krw -------------------------------------------------


def test_format_price_krw_with_value():
    assert _format_price_krw(12900) == "12,900원"


def test_format_price_krw_none():
    assert _format_price_krw(None) == ""


# --- _merge_proposals ----------------------------------------------------


def test_merge_proposals_combines_all_agents():
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("무선 마우스", 12900, COUPANG_URL)]),
        "gemini": json.dumps([_raw_candidate("무선 마우스", 12900, COUPANG_URL)]),
        "deepseek": json.dumps([]),
    }

    merged = _merge_proposals(raw_by_agent)

    assert len(merged) == 1
    assert merged[0]["proposed_by"] == ["gpt", "gemini"]


def test_merge_proposals_skips_agent_with_malformed_json():
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("무선 마우스", 12900, COUPANG_URL)]),
        "gemini": "이건 JSON이 아닙니다",
        "deepseek": None,
    }

    merged = _merge_proposals(raw_by_agent)

    assert len(merged) == 1
    assert merged[0]["proposed_by"] == ["gpt"]


def test_merge_proposals_all_empty_returns_empty_list():
    raw_by_agent = {"gpt": json.dumps([]), "gemini": None, "deepseek": ""}

    assert _merge_proposals(raw_by_agent) == []


def test_merge_proposals_filters_generic_listing_url():
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("무선 마우스", 12900, "https://coupang.com/search?q=마우스")]),
        "gemini": None,
        "deepseek": None,
    }

    assert _merge_proposals(raw_by_agent) == []


def test_merge_proposals_filters_candidate_with_empty_url():
    """url이 빈 후보를 그대로 통과시키면, 실제로 살 수 있는 페이지가 없는
    후보가 심사까지 흘러가 judge가 존재하지 않는 URL을 스스로 지어내
    채우는 문제로 이어진다 — 애초에 후보 풀에 들어오지 못하게 막는다."""
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("무선 마우스", 12900, "")]),
        "gemini": None,
        "deepseek": None,
    }

    assert _merge_proposals(raw_by_agent) == []


# --- _apply_challenge ------------------------------------------------------


def test_apply_challenge_matches_verdict_by_url_even_when_order_differs():
    candidates = [
        _merged_candidate(COUPANG_URL, ["gpt"], "상품A"),
        _merged_candidate(ELEVENST_URL, ["gemini"], "상품B"),
    ]
    # 검증 결과 순서가 후보 순서와 뒤바뀜 — url로 정확히 매칭돼야 한다.
    challenge = ChallengeResult(
        verdicts=[
            ChallengeVerdict(url=ELEVENST_URL, verified=False, note="상품B 우려"),
            ChallengeVerdict(url=COUPANG_URL, verified=True, note="상품A 통과"),
        ]
    )

    proposals = _apply_challenge(candidates, challenge)

    a = next(p for p in proposals if p.url == COUPANG_URL)
    b = next(p for p in proposals if p.url == ELEVENST_URL)
    assert a.verified is True and a.challenge_note == "상품A 통과"
    assert b.verified is False and b.challenge_note == "상품B 우려"


def test_apply_challenge_falls_back_to_index_when_url_missing():
    candidates = [_merged_candidate(COUPANG_URL, ["gpt"])]
    challenge = ChallengeResult(verdicts=[ChallengeVerdict(url=None, verified=True, note="통과")])

    proposals = _apply_challenge(candidates, challenge)

    assert proposals[0].verified is True
    assert proposals[0].challenge_note == "통과"


def test_apply_challenge_empty_verdicts_leaves_all_unverified():
    candidates = [_merged_candidate(COUPANG_URL, ["gpt"]), _merged_candidate(ELEVENST_URL, ["gemini"])]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]))

    assert all(p.verified is None and p.challenge_note is None for p in proposals)


def test_apply_challenge_derives_agent_and_proposed_by_from_candidate():
    candidates = [_merged_candidate(COUPANG_URL, ["gpt", "deepseek"])]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]))

    assert proposals[0].agent == "gpt"
    assert proposals[0].proposed_by == ["gpt", "deepseek"]
    assert proposals[0].price == "12,900원"


def test_apply_challenge_empty_candidates_returns_empty_list():
    assert _apply_challenge([], ChallengeResult(verdicts=[])) == []


def test_apply_challenge_drops_expired_danawa_candidate_entirely():
    """가격비교가 중지된(다나와가 서비스 종료로 표시하는) 페이지는 verified=False로
    남기지 않고 결과에서 아예 빠져야 한다 — "가격미확인" 카드로 노출되면 안 된다."""
    candidates = [
        _merged_candidate(COUPANG_URL, ["gpt"], "상품A"),
        _merged_candidate(ELEVENST_URL, ["gemini"], "상품B"),
    ]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]), {ELEVENST_URL})

    assert len(proposals) == 1
    assert proposals[0].url == COUPANG_URL


def test_apply_challenge_all_candidates_expired_returns_empty_list():
    candidates = [_merged_candidate(COUPANG_URL, ["gpt"])]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]), {COUPANG_URL})

    assert proposals == []


# --- _is_danawa_product_url -------------------------------------------------


def test_is_danawa_product_url_matches_prod_danawa():
    assert _is_danawa_product_url("https://prod.danawa.com/info/?pcode=12345") is True


def test_is_danawa_product_url_rejects_other_domains():
    assert _is_danawa_product_url(COUPANG_URL) is False


def test_is_danawa_product_url_rejects_none_and_empty():
    assert _is_danawa_product_url(None) is False
    assert _is_danawa_product_url("") is False


# --- _build_decision (judge의 자유 텍스트보다 그라운딩된 후보 데이터를 우선) ---


def _proposal_for_decision(url: str, price: str = "12,900원", retailer: str = "쿠팡") -> Proposal:
    return Proposal(
        agent="gpt", product_name="무선 마우스", price=price, retailer=retailer, url=url, verified=True
    )


def test_build_decision_prefers_matched_candidate_fields_over_judge_raw_text():
    """judge가 raw_decision에 실제 후보와 다른 price/retailer/url을 지어내도
    (예: url이 빈 후보를 골랐을 때 그럴듯한 URL을 스스로 채우는 경우),
    최종 Decision은 실제로 검증된 matched 후보의 값을 써야 한다."""
    proposals = [_proposal_for_decision(COUPANG_URL, price="12,900원", retailer="쿠팡")]
    state = {
        "raw_decision": {
            "product_name": "무선 마우스",
            "price": "9,900원",  # 후보에 없는 값 — judge가 지어냄
            "retailer": "다나와",  # 후보에 없는 값 — judge가 지어냄
            "url": COUPANG_URL,
            "reasoning": "가장 저렴합니다.",
        }
    }

    decision = _build_decision(state, proposals)

    assert decision.price == "12,900원"
    assert decision.retailer == "쿠팡"
    assert decision.url == COUPANG_URL


def test_build_decision_falls_back_to_raw_when_matched_field_missing():
    proposals = [_proposal_for_decision(COUPANG_URL, price="", retailer="")]
    state = {
        "raw_decision": {
            "product_name": "무선 마우스",
            "price": "12,900원",
            "retailer": "쿠팡",
            "url": COUPANG_URL,
            "reasoning": "가장 저렴합니다.",
        }
    }

    decision = _build_decision(state, proposals)

    assert decision.price == "12,900원"
    assert decision.retailer == "쿠팡"


def test_build_decision_returns_none_without_raw_decision():
    assert _build_decision({}, [_proposal_for_decision(COUPANG_URL)]) is None


def test_build_decision_returns_none_without_proposals():
    assert _build_decision({"raw_decision": {"url": COUPANG_URL}}, []) is None


# --- _augment_search_query (검색 단계 카테고리 가중치) ----------------------


def test_augment_search_query_appends_detected_category():
    """Tavily에 보내는 검색어에 분류된 카테고리를 얹어, 검색엔진 랭킹을 그
    카테고리 쪽으로 미세 조정한다 — 강제 필터링이 아니라 원래 질의 키워드는
    그대로 남는 완만한 가중치."""
    query = _augment_search_query("초코파이 해태제과", CategoryClassification(category="식품"))

    assert query == "초코파이 해태제과 식품"


def test_augment_search_query_keeps_original_when_classification_failed():
    """카테고리 분류가 실패하면(category=None) 원래 질의를 그대로 둔다 —
    잘못된 키워드를 얹어 오히려 검색 결과를 왜곡시키는 것보다 안전하다."""
    query = _augment_search_query("초코파이 해태제과", CategoryClassification())

    assert query == "초코파이 해태제과"


# --- _urls_to_extract (challenge 전 실제 페이지 재조회 대상) ----------------


def test_urls_to_extract_returns_candidate_urls():
    candidates = [
        {"url": COUPANG_URL},
        {"url": ELEVENST_URL},
    ]
    assert _urls_to_extract(candidates) == [COUPANG_URL, ELEVENST_URL]


def test_urls_to_extract_skips_candidates_without_url():
    candidates = [{"url": None}, {"url": COUPANG_URL}, {}]
    assert _urls_to_extract(candidates) == [COUPANG_URL]


def test_urls_to_extract_caps_at_max_candidates():
    candidates = [{"url": f"https://coupang.com/vp/products/{i}"} for i in range(20)]
    urls = _urls_to_extract(candidates)
    assert len(urls) == 10


# --- _judge_eligible_proposals (verified=False 후보 judge 이전 필터링) -----


def _proposal(url: str, verified: bool | None) -> Proposal:
    return Proposal(agent="gpt", product_name="상품", price="1,000원", retailer="쿠팡", url=url, verified=verified)


def test_judge_eligible_proposals_filters_out_verified_false():
    proposals = [_proposal(COUPANG_URL, True), _proposal(ELEVENST_URL, False)]

    eligible = _judge_eligible_proposals(proposals)

    assert [p.url for p in eligible] == [COUPANG_URL]


def test_judge_eligible_proposals_keeps_unverified_candidates():
    proposals = [_proposal(COUPANG_URL, None)]

    assert _judge_eligible_proposals(proposals) == proposals


def test_judge_eligible_proposals_falls_back_to_full_list_when_all_rejected():
    proposals = [_proposal(COUPANG_URL, False), _proposal(ELEVENST_URL, False)]

    assert _judge_eligible_proposals(proposals) == proposals


# --- 다나와 실측가 주입(_DanawaFetchNode 포팅) ------------------------------
# PRESERVED FROM seungmin/lsm의 run_single_debate_price_table_variant를
# ADK 파이프라인으로 포팅(2026-08-16) - tests/test_pipeline_danawa.py의
# _danawa_html/_offer_li와 같은 합성 HTML 픽스처 패턴을 그대로 쓴다.


def test_merge_proposals_includes_danawa_agent():
    raw_by_agent = {
        "gpt": None,
        "gemini": None,
        "deepseek": None,
        "danawa": json.dumps([_raw_candidate("무선 마우스", 12900, COUPANG_URL)]),
    }

    merged = _merge_proposals(raw_by_agent)

    assert len(merged) == 1
    assert merged[0]["proposed_by"] == ["danawa"]


def test_apply_challenge_marks_danawa_sourced_candidate_verified_without_challenge_verdict():
    """다나와 실측가는 이미 검증된 데이터라, DeepSeek 검증 결과가 하나도
    없어도(verdicts=[]) verified=None(미검증)이 아니라 True로 강제돼야 한다."""
    candidates = [_merged_candidate(COUPANG_URL, ["danawa"], "상품A")]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]))

    assert proposals[0].verified is True
    assert "다나와" in proposals[0].challenge_note


def test_apply_challenge_danawa_consensus_candidate_ignores_deepseek_verdict():
    """다른 에이전트와 합의(병합)돼도 proposed_by에 danawa가 있으면 verified=True다 -
    DeepSeek이 그 URL을 우려로 표시했더라도 실측가가 있으면 덮어쓴다."""
    candidates = [_merged_candidate(COUPANG_URL, ["gpt", "danawa"], "상품A")]
    challenge = ChallengeResult(verdicts=[ChallengeVerdict(url=COUPANG_URL, verified=False, note="우려")])

    proposals = _apply_challenge(candidates, challenge)

    assert proposals[0].verified is True
    assert proposals[0].challenge_note != "우려"


def test_apply_challenge_non_danawa_candidate_unaffected_by_danawa_override():
    candidates = [_merged_candidate(COUPANG_URL, ["gpt"], "상품A")]

    proposals = _apply_challenge(candidates, ChallengeResult(verdicts=[]))

    assert proposals[0].verified is None
    assert proposals[0].challenge_note is None


# --- 쿠팡 교차 확인(build_challenge_prompt, 2026-08-16) ----------------------


def test_build_challenge_prompt_without_coupang_results_matches_prior_output():
    without_coupang = build_challenge_prompt("무선 마우스", [], [])
    with_empty_list = build_challenge_prompt("무선 마우스", [], [], None, [])

    assert without_coupang == with_empty_list
    # 결과 블록 자체는 안 붙지만, CHALLENGE_INSTRUCTIONS의 사용법 설명 문구는 항상 포함된다.
    assert "쿠팡 교차 확인 검색 결과(참고용)" not in without_coupang


def test_build_challenge_prompt_includes_coupang_block_when_provided():
    coupang_results = [SearchResult(title="쿠팡 무선 마우스", url=COUPANG_URL, snippet="12,900원")]

    prompt = build_challenge_prompt("무선 마우스", [], [], None, coupang_results)

    assert "쿠팡 교차 확인 검색 결과(참고용)" in prompt
    assert COUPANG_URL in prompt


def test_challenge_instructions_treat_coupang_signal_as_soft():
    assert "곧바로 false로 판단하지 마세요" in CHALLENGE_INSTRUCTIONS
    assert "쿠팡" in CHALLENGE_INSTRUCTIONS


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


def _danawa_price_table_pair(product_name: str, offers_html: list[str], pcode: str = "1"):
    html = _danawa_html(product_name, offers_html)
    result = parse_danawa_html(f"https://prod.danawa.com/info?pcode={pcode}", html)
    return build_price_table(result), result


def test_danawa_tables_from_state_round_trips_price_table():
    table, result = _danawa_price_table_pair(
        "테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")]
    )
    state = {"danawa_tables": [[table.model_dump(), result]]}

    restored = _danawa_tables_from_state(state)

    assert len(restored) == 1
    restored_table, restored_result = restored[0]
    assert restored_table.product_name == "테스트 상품"
    assert restored_result["product_name"] == "테스트 상품"


def test_danawa_tables_from_state_empty_when_missing():
    assert _danawa_tables_from_state({}) == []


def test_finalize_with_danawa_sets_price_source_when_judge_chose_danawa():
    table, result = _danawa_price_table_pair(
        "테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="1")]
    )
    decision = Decision(
        product_name="테스트 상품",
        price="23,000원",
        retailer="쿠팡",
        url="https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=1",
        reasoning="테스트",
        chosen_agent="danawa",
    )

    updated, price_table = asyncio.run(_finalize_with_danawa(decision, [], [(table, result)]))

    assert updated.price_source == "danawa_offer"
    assert price_table is not None
    assert price_table.product_name == "테스트 상품"


def test_finalize_with_danawa_enriches_matching_llm_decision():
    """judge가 이름이 일치하는 다나와 실측가를 고르지 않았어도(chosen_agent="gpt"),
    상품명이 맞으면 enrich_decision이 가격/URL을 실측치로 덮어쓴다."""
    table, result = _danawa_price_table_pair(
        "테스트 상품", [_offer_li("쿠팡", "23,000", "TP40F", link_pcode="777")]
    )
    decision = Decision(
        product_name="테스트 상품",
        price="가격 정보 없음",
        retailer="다나와",
        url="https://example.com/guess",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    updated, price_table = asyncio.run(_finalize_with_danawa(decision, [], [(table, result)]))

    assert updated.price_source == "danawa_offer"
    assert updated.price == "23,000원"
    assert updated.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TP40F&link_pcode=777"
    assert price_table is not None


def test_finalize_with_danawa_leaves_decision_unchanged_when_no_tables():
    decision = Decision(
        product_name="테스트 상품",
        price="10,000원",
        retailer="쿠팡",
        url="https://coupang.com/vp/products/1",
        reasoning="테스트",
        chosen_agent="gpt",
    )

    updated, price_table = asyncio.run(_finalize_with_danawa(decision, [], []))

    assert updated.price_source == "llm_guess"
    assert updated.url == "https://coupang.com/vp/products/1"
    assert price_table is None
