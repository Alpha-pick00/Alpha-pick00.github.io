from app.exclusive_tokens import exclusive_tokens_conflict


def test_rice_type_conflict_blocks_match():
    # 실제 관측 케이스 - token_set_ratio=93.0으로 유사도 임계값(85)을 통과했었다.
    assert exclusive_tokens_conflict("햇반 백미 210g 24개", "햇반 발아현미 210g 24개") is True


def test_abbreviated_query_without_rice_type_still_matches():
    # 한쪽에만 있는 건 무시한다 - 쿼리가 축약된 것뿐일 수 있다.
    assert exclusive_tokens_conflict("햇반 210g 24개", "햇반 백미 210g 24개") is False


def test_spice_level_conflict_blocks_match():
    assert exclusive_tokens_conflict("진라면 순한맛", "진라면 매운맛") is True


def test_noodle_type_absent_on_one_side_matches():
    assert exclusive_tokens_conflict("신라면", "신라면 건면") is False


def test_vacuum_type_conflict_blocks_match():
    assert exclusive_tokens_conflict("다이슨 무선청소기", "다이슨 로봇청소기") is True


def test_substring_does_not_cause_spurious_conflict_within_same_group():
    # "발아현미" 안에 "현미"가 부분 문자열로 들어있다 - 긴 원소 우선 소비 처리로
    # 같은 텍스트 안에서 "발아현미"와 "현미"가 동시에 검출되면 안 된다.
    assert exclusive_tokens_conflict("햇반 발아현미 210g", "햇반 발아현미 210g") is False


def test_no_exclusive_tokens_on_either_side_no_conflict():
    assert exclusive_tokens_conflict("로지텍 MX Master 3S", "로지텍 MX Master 3S") is False
