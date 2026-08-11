import json

from app.adk_pipeline import (
    _apply_challenge,
    _build_decision,
    _format_price_krw,
    _is_ambiguous,
    _judge_eligible_proposals,
    _merge_proposals,
    _urls_to_extract,
)
from app.schemas import ChallengeResult, ChallengeVerdict, ClarifyOptions, Proposal

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


# --- _is_ambiguous (Human-in-the-loop 트리거 기준) ------------------------


def test_is_ambiguous_false_when_nothing_found():
    assert _is_ambiguous("메로나", ClarifyOptions(brands=[], volumes=[], quantities=[])) is False


def test_is_ambiguous_false_when_single_option_each():
    options = ClarifyOptions(brands=["다이슨"], volumes=["500ml"], quantities=["1개"])
    assert _is_ambiguous("다이슨 청소기", options) is False


def test_is_ambiguous_true_when_multiple_brands_not_yet_in_query():
    options = ClarifyOptions(brands=["다이슨", "삼성"], volumes=[], quantities=[])
    assert _is_ambiguous("무선청소기", options) is True


def test_is_ambiguous_true_when_multiple_volumes_not_yet_in_query():
    options = ClarifyOptions(brands=["다이슨"], volumes=["64GB", "256GB"], quantities=[])
    assert _is_ambiguous("아이패드", options) is True


def test_is_ambiguous_true_when_multiple_quantities_not_yet_in_query():
    options = ClarifyOptions(brands=[], volumes=[], quantities=["1개", "6개"])
    assert _is_ambiguous("생수", options) is True


def test_is_ambiguous_false_when_brand_already_chosen_in_query():
    """사용자가 이미 브랜드를 골라 검색어에 반영했으면(예: HITL 재검색), 검색
    결과가 여전히 여러 브랜드를 섞어 보여줘도 다시 묻지 않는다."""
    options = ClarifyOptions(brands=["다이슨", "삼성"], volumes=[], quantities=[])
    assert _is_ambiguous("무선청소기 다이슨", options) is False


def test_is_ambiguous_false_when_volume_already_specified_in_query():
    options = ClarifyOptions(brands=[], volumes=["500ml", "1L"], quantities=[])
    assert _is_ambiguous("생수 500ml", options) is False


def test_is_ambiguous_false_when_quantity_already_specified_in_query():
    options = ClarifyOptions(brands=[], volumes=[], quantities=["10개", "30개"])
    assert _is_ambiguous("메로나 빙그레 70mL 10개", options) is False


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
