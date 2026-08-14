from app.spec_match import extract_spec_tokens, model_or_quantity_conflict


def test_bare_korean_digit_model_suffix_is_extracted_as_spec_token():
    # 알파벳이 안 섞인 "아이폰15"/"아이폰6"은 기존 영숫자 혼합 규칙으로는 못
    # 잡혔다 - 한글+숫자 전용 패턴이 따로 잡아야 한다.
    assert "아이폰15" in extract_spec_tokens("아이폰15 케이스 투명 젤리")
    assert "아이폰6" in extract_spec_tokens("아이폰6 케이스 투명 젤리")


def test_different_iphone_generations_conflict():
    assert model_or_quantity_conflict("아이폰15 케이스", "아이폰6 케이스") is True


def test_same_iphone_generation_no_conflict():
    assert model_or_quantity_conflict("아이폰15 케이스 투명", "아이폰15 케이스 젤리") is False


def test_count_unit_suffix_not_mistaken_for_korean_model_token():
    # 숫자 바로 뒤에 개수 단위(벌)가 붙으면(공백 없이) 모델 세대 표기가 아니라
    # 수량 표기이므로, 한글+숫자 모델 토큰 추출 대상에서 제외해야 한다.
    assert "장갑1" not in extract_spec_tokens("장갑1벌 세트")
    assert model_or_quantity_conflict("장갑1벌 세트", "장갑2벌 세트") is False


def test_no_model_tokens_on_either_side_no_conflict():
    assert model_or_quantity_conflict("무선 마우스", "무선 마우스") is False
