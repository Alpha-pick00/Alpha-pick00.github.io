import json

from app.adk_pipeline import _apply_challenge, _format_price_krw, _is_ambiguous, _merge_proposals
from app.schemas import ChallengeResult, ChallengeVerdict, ClarifyOptions

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
