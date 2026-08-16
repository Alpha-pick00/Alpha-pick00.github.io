import asyncio
import json

import app.adk_pipeline as adk_pipeline_module
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
    _pick_and_verify_relaxed,
    _relaxed_fallback_decision,
    _skip_judge_if_single_candidate,
    _urls_to_extract,
    _verify_relaxed_verdict,
)
from app.agents.base import CHALLENGE_INSTRUCTIONS, build_challenge_prompt
from app.category import CategoryClassification
from app.price_table import build_price_table
from app.schemas import ChallengeResult, ChallengeVerdict, Decision, JudgeVerdict, Proposal, SearchResult
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


def test_merge_proposals_filters_danawa_comparison_page_url():
    """2026-08-16, 그라운딩 회귀 파일럿에서 발견: Qwen·DeepSeek이 다나와
    가격비교 페이지 자체(prod.danawa.com/info?pcode=...)를 후보로 제안하면서
    retailer="다나와"(판매처가 아니라 가격비교 사이트 자신), price=""로
    채웠다 - 이 페이지는 실제 구매 가능한 판매처로 연결되지 않으므로
    애초에 후보 풀에 못 들어오게 막는다(진짜 구매 링크인 /bridge/
    loadingBridge.html은 이 패턴에 안 걸려 그대로 통과한다)."""
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("위닉스 뽀송 DHC-167IPW", 0, "https://prod.danawa.com/info?pcode=1982936")]),
        "gemini": None,
        "deepseek": None,
    }

    assert _merge_proposals(raw_by_agent) == []


def test_merge_proposals_filters_danawa_mobile_comparison_page_url():
    """2026-08-17, 재검증 파일럿에서 발견: prod.danawa.com/info만 정규식으로
    걸렀더니 같은 문제의 모바일 페이지 변형(m.danawa.com/product/product.html)
    이 그대로 통과했다("LG 그램 16인치 2024" 질의에서 retailer="다나와",
    price="" 재현) - is_danawa_comparison_page를 도메인 기반(다나와 도메인 +
    /bridge/ 아님)으로 일반화한 뒤에는 이 변형도 걸러져야 한다."""
    raw_by_agent = {
        "gpt": json.dumps(
            [_raw_candidate("LG전자 2024 그램16", 0, "https://m.danawa.com/product/product.html?code=45320081")]
        ),
        "gemini": None,
        "deepseek": None,
    }

    assert _merge_proposals(raw_by_agent) == []


def test_merge_proposals_keeps_danawa_bridge_purchase_link():
    """/bridge/loadingBridge.html은 다나와가 최종 판매처로 리다이렉트하는
    실제 구매 링크라 가격비교 페이지 필터에 걸리면 안 된다."""
    bridge_url = "https://prod.danawa.com/bridge/loadingBridge.html?pcode=1&cmpnyc=EE715"
    raw_by_agent = {
        "gpt": json.dumps([_raw_candidate("무선 마우스", 12900, bridge_url)]),
        "gemini": None,
        "deepseek": None,
    }

    merged = _merge_proposals(raw_by_agent)

    assert len(merged) == 1
    assert merged[0]["url"] == bridge_url


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


def test_build_decision_propagates_verified_from_matched_proposal():
    """Decision.verified(2026-08-16 추가)는 matched proposal의 challenge 검증
    결과를 그대로 물려받아야 한다 - 프론트/API 소비자가 이 답이 실제로
    그라운딩 검증을 통과했는지 알 수 있게 하기 위함."""
    proposals = [_proposal_for_decision(COUPANG_URL)]  # verified=True 고정
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

    assert decision.verified is True


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


# --- 네이버쇼핑 교차 확인(build_challenge_prompt, 2026-08-16) ----------------


def test_build_challenge_prompt_without_naver_results_matches_prior_output():
    without_naver = build_challenge_prompt("무선 마우스", [], [])
    with_empty_list = build_challenge_prompt("무선 마우스", [], [], None, None, [])

    assert without_naver == with_empty_list
    assert "네이버쇼핑 교차 확인 검색 결과(참고용)" not in without_naver


def test_build_challenge_prompt_includes_naver_block_when_provided():
    naver_url = "https://shopping.naver.com/products/1"
    naver_results = [SearchResult(title="네이버 무선 마우스", url=naver_url, snippet="12,900원")]

    prompt = build_challenge_prompt("무선 마우스", [], [], None, None, naver_results)

    assert "네이버쇼핑 교차 확인 검색 결과(참고용)" in prompt
    assert naver_url in prompt


def test_build_challenge_prompt_includes_both_coupang_and_naver_blocks():
    coupang_results = [SearchResult(title="쿠팡", url=COUPANG_URL, snippet="12,900원")]
    naver_results = [SearchResult(title="네이버", url="https://shopping.naver.com/products/1", snippet="12,900원")]

    prompt = build_challenge_prompt("무선 마우스", [], [], None, coupang_results, naver_results)

    assert "쿠팡 교차 확인 검색 결과(참고용)" in prompt
    assert "네이버쇼핑 교차 확인 검색 결과(참고용)" in prompt


def test_challenge_instructions_treat_naver_signal_as_soft():
    assert "곧바로 false로 판단하지 마세요" in CHALLENGE_INSTRUCTIONS
    assert "네이버쇼핑" in CHALLENGE_INSTRUCTIONS


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
        "테스트 상품", [_offer_li("옥션", "23,000", "EE715", link_pcode="777")]
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
    assert updated.url == "https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=EE715&link_pcode=777"
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


# --- _skip_judge_if_single_candidate (judge LLM 호출 생략, 속도 개선) -----------


class _FakeCallbackContext:
    def __init__(self, state: dict):
        self.state = state


def test_skip_judge_returns_verdict_matching_the_only_candidate():
    proposals = [_proposal(COUPANG_URL, True)]
    ctx = _FakeCallbackContext({"proposals": [p.model_dump() for p in proposals]})

    response = _skip_judge_if_single_candidate(ctx, None)

    assert response is not None
    verdict = json.loads(response.content.parts[0].text)
    assert verdict["url"] == COUPANG_URL
    assert verdict["product_name"] == "상품"
    assert verdict["price"] == "1,000원"
    assert verdict["retailer"] == "쿠팡"
    assert verdict["reasoning"]


def test_skip_judge_none_when_no_candidates():
    ctx = _FakeCallbackContext({"proposals": []})

    assert _skip_judge_if_single_candidate(ctx, None) is None


def test_skip_judge_none_when_multiple_candidates():
    proposals = [_proposal(COUPANG_URL, True), _proposal(ELEVENST_URL, True)]
    ctx = _FakeCallbackContext({"proposals": [p.model_dump() for p in proposals]})

    assert _skip_judge_if_single_candidate(ctx, None) is None


def test_skip_judge_uses_only_eligible_candidate_when_others_rejected():
    proposals = [_proposal(COUPANG_URL, True), _proposal(ELEVENST_URL, False)]
    ctx = _FakeCallbackContext({"proposals": [p.model_dump() for p in proposals]})

    response = _skip_judge_if_single_candidate(ctx, None)

    assert response is not None
    verdict = json.loads(response.content.parts[0].text)
    assert verdict["url"] == COUPANG_URL


def test_skip_judge_none_when_the_only_candidate_is_missing_a_required_field():
    incomplete = Proposal(agent="gpt", product_name="상품", price="", retailer="쿠팡", url=COUPANG_URL)
    ctx = _FakeCallbackContext({"proposals": [incomplete.model_dump()]})

    assert _skip_judge_if_single_candidate(ctx, None) is None


# --- relaxed fallback 하드닝(2026-08-16, "구매링크를 안띄워주는거야" 버그의 근본 -----
# 원인이었던 경로 - challenge 검증을 우회할 수 없도록 게이팅한다) ------------------


def _relaxed_verdict(url: str = COUPANG_URL, product_name: str = "무선 마우스") -> JudgeVerdict:
    return JudgeVerdict(
        product_name=product_name, price="12,900원", retailer="쿠팡", url=url, reasoning="가장 관련성이 높습니다."
    )


def _patch_no_cross_check_signals(monkeypatch):
    """쿠팡/네이버 소프트 신호 자체는 이 테스트들의 관심사가 아니므로 항상
    빈 리스트로 고정해 challenge_candidates에 전달되는 인자만 신경 쓴다."""

    async def _empty(query: str) -> list[SearchResult]:
        return []

    monkeypatch.setattr(adk_pipeline_module.search_module, "search_coupang", _empty)
    monkeypatch.setattr(adk_pipeline_module.search_module, "search_naver", _empty)


def test_verify_relaxed_verdict_matches_challenge_verdict_by_url(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        return [ChallengeVerdict(url=verdict.url, verified=True, note="검색 결과와 일치")]

    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    verified = asyncio.run(_verify_relaxed_verdict("무선 마우스", verdict, []))

    assert verified is True


def test_verify_relaxed_verdict_returns_none_when_challenge_infra_fails(monkeypatch):
    """challenge_candidates가 빈 리스트(API 오류/파싱 실패)를 돌려주면
    "검증 안 됨"으로 취급해야지, 검증 실패를 "그라운딩 우려"와 혼동해 후보를
    폐기해서는 안 된다."""
    _patch_no_cross_check_signals(monkeypatch)

    async def _fake_challenge(*args, **kwargs):
        return []

    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    verified = asyncio.run(_verify_relaxed_verdict("무선 마우스", _relaxed_verdict(), []))

    assert verified is None


def test_pick_and_verify_relaxed_discards_candidate_rejected_by_challenge(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_pick(query, search_results):
        return verdict

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        return [ChallengeVerdict(url=verdict.url, verified=False, note="검색 결과 어디에도 이 가격이 없음")]

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    result = asyncio.run(_pick_and_verify_relaxed("무선 마우스", []))

    assert result is None


def test_pick_and_verify_relaxed_keeps_candidate_when_verified_true(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_pick(query, search_results):
        return verdict

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        return [ChallengeVerdict(url=verdict.url, verified=True, note="검색 결과와 일치")]

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    result = asyncio.run(_pick_and_verify_relaxed("무선 마우스", []))

    assert result == (verdict, True)


def test_relaxed_fallback_decision_returns_verified_decision_without_caveat(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_pick(query, search_results):
        return verdict

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        return [ChallengeVerdict(url=verdict.url, verified=True, note="검색 결과와 일치")]

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    decision = asyncio.run(_relaxed_fallback_decision("무선 마우스", []))

    assert decision is not None
    assert decision.verified is True
    assert "낮은 확신" not in decision.reasoning


def test_relaxed_fallback_decision_none_when_short_query_rejected_and_cannot_broaden(monkeypatch):
    """질의가 2단어 이하면 broadened_query == query라 재검색을 건너뛴다 - 1라운드가
    challenge에서 명백히 탈락하면 더 시도할 게 없으므로 정직하게 포기해야 한다
    (하드닝 전에는 이 경로가 검증 없이 그대로 최종 응답이 됐다)."""
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_pick(query, search_results):
        return verdict

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        return [ChallengeVerdict(url=verdict.url, verified=False, note="검색 결과 어디에도 이 가격이 없음")]

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    decision = asyncio.run(_relaxed_fallback_decision("마우스", []))

    assert decision is None


def test_relaxed_fallback_decision_broadens_query_after_challenge_rejection(monkeypatch):
    """1라운드 후보가 challenge에서 명백히 탈락하면(verified=False), 완전히
    포기하기 전에 넓힌 질의로 한 번 더 시도한다 - 후보를 아예 못 찾았을 때와
    같은 재시도 경로를 탄다."""
    _patch_no_cross_check_signals(monkeypatch)
    rejected = _relaxed_verdict(url=COUPANG_URL, product_name="무선 마우스 A")
    accepted = _relaxed_verdict(url=ELEVENST_URL, product_name="무선 마우스 B")

    call_count = {"pick": 0}

    async def _fake_pick(query, search_results):
        call_count["pick"] += 1
        return rejected if call_count["pick"] == 1 else accepted

    async def _fake_challenge(query, candidates, search_results, candidate_pages, coupang_results, naver_results):
        url = candidates[0]["url"]
        verified = url == accepted.url
        return [ChallengeVerdict(url=url, verified=verified, note="")]

    async def _fake_broadened_search(query):
        return [SearchResult(title="넓힌 검색", url=ELEVENST_URL, snippet="12,900원")]

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)
    monkeypatch.setattr(adk_pipeline_module.search_module, "search", _fake_broadened_search)

    decision = asyncio.run(_relaxed_fallback_decision("무선 마우스 정확한 모델명", []))

    assert decision is not None
    assert decision.url == ELEVENST_URL
    assert decision.verified is True
    assert call_count["pick"] == 2
    assert "검색 범위를 넓혀" in decision.reasoning


def test_relaxed_fallback_decision_marks_unverified_with_caveat_when_challenge_infra_fails(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)
    verdict = _relaxed_verdict()

    async def _fake_pick(query, search_results):
        return verdict

    async def _fake_challenge(*args, **kwargs):
        return []  # 검증 인프라 장애 시뮬레이션

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)
    monkeypatch.setattr(adk_pipeline_module.deepseek_module, "challenge_candidates", _fake_challenge)

    decision = asyncio.run(_relaxed_fallback_decision("무선 마우스", []))

    assert decision is not None
    assert decision.verified is None
    assert "낮은 확신" in decision.reasoning


def test_relaxed_fallback_decision_none_when_no_candidate_found_at_all(monkeypatch):
    _patch_no_cross_check_signals(monkeypatch)

    async def _fake_pick(query, search_results):
        return None

    monkeypatch.setattr(adk_pipeline_module.gpt_module, "pick_most_relevant", _fake_pick)

    decision = asyncio.run(_relaxed_fallback_decision("마우스", []))

    assert decision is None
