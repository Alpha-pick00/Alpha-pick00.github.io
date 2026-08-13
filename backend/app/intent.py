import re

# 단위 뒤에 (?![a-zA-Z가-힣])를 붙여, "64GB"의 "G"처럼 단위 한 글자가 다른 단어(용량
# 스펙 등) 중간에서 잘못 걸리는 걸 막는다 — 단위 바로 뒤에 또 다른 글자가 오면 매치 안 함.
# 개수 단위와 용량/무게 단위를 따로 둔다 — Human-in-the-loop에서 "이 질의에 이미
# 용량/개수가 명시돼 있는지"를 각각 따로 판단해야 하기 때문(has_volume_spec/
# has_count_spec). is_bulk_query()는 근사치 휴리스틱이며, "노트북 1대"처럼 스펙
# 비교가 필요한 항목도 걸릴 수 있다.
_COUNT_UNIT_PATTERN = re.compile(r"\d+\s*(개|병|팩|박스|세트|캔|봉지|포|장|권|벌|족|대)(?![a-zA-Z가-힣])")
_VOLUME_UNIT_PATTERN = re.compile(
    r"\d+\s*(ml|ML|mL|L|리터|밀리리터|kg|KG|Kg|g|G|그램|킬로)(?![a-zA-Z가-힣])"
)
BULK_SPEC_PATTERN = re.compile(
    f"{_COUNT_UNIT_PATTERN.pattern}|{_VOLUME_UNIT_PATTERN.pattern}"
)

# "사고싶다"류 구매 의도 문구. 역시 근사치 휴리스틱.
BUY_INTENT_PATTERN = re.compile(r"(사고\s*싶|사려고|구매하고\s*싶|구매하려|사줘|살래)")


def is_bulk_query(query: str) -> bool:
    return bool(BULK_SPEC_PATTERN.search(query))


# "음료수", "과자"처럼 짧고 숫자가 없는 검색어는 브랜드/스펙을 전혀 안 정한 넓은
# 카테고리 검색일 가능성이 높다(2026-08-12, AI 상세검색 요청) - 근사치 휴리스틱이며,
# "노트북"처럼 원래도 애매했던 검색어를 더 적극적으로 걸러내는 효과가 있다.
# 오탐(구체적인데 짧은 검색어)이 있어도 위험하지 않다 - 이 함수를 쓰는 호출자들은
# 전부 "아무 facet도 못 찾으면 원래 경로로 그대로 진행"하도록 설계돼 있다.
#
# 2 -> 4(2026-08-15, "카테고리별로 human in the loop을 다르게 구현해야 할 것
# 같은데... 냉장고 살 때랑 콜라 살 때 쓰는 메타데이터가 다르다") - 카테고리마다
# 메타데이터(facet)가 다른 문제는 AI 상세검색(check_clarify_facets, 실제 검색
# 결과 상품명에서 DeepSeek이 즉석에서 카테고리별 facet을 뽑는 경로)이 이미
# 해결한다. 이 경로가 더 많은 질의에서 우선 시도되도록 범위를 "삼성 냉장고
# 스탠드형"처럼 짧지만 구체성이 붙기 시작한 질의까지 넓힌다 - 여전히 숫자(스펙)가
# 있으면 제외되고, facet을 못 찾으면 원래 경로로 그대로 진행되므로 위험 없음.
SHORT_QUERY_TOKEN_LIMIT = 4
_HAS_DIGIT_PATTERN = re.compile(r"\d")


def _is_short_bare_query(query: str) -> bool:
    tokens = query.strip().split()
    return 0 < len(tokens) <= SHORT_QUERY_TOKEN_LIMIT and not _HAS_DIGIT_PATTERN.search(query)


def needs_clarification(query: str) -> bool:
    if is_bulk_query(query):
        return False
    return bool(BUY_INTENT_PATTERN.search(query)) or _is_short_bare_query(query)


# 상품과 무관한 인사말/잡담의 닫힌 집합 - 전체 질의가 이 중 하나와 정확히
# 일치할 때만 매치되도록 앵커(^...$)를 건다("테스트 상품"처럼 이 단어들을
# 포함하되 실제 상품명인 질의까지 오탐하지 않기 위함 - "테스트"는 기존 테스트
# 스위트에서 이미 "못 찾은 상품 검색어"로 쓰이고 있어 일부러 뺐다).
_GREETING_PATTERN = re.compile(
    r"^(안녕(하세요|하십니까)?|안뇽|하이|hi|hello|헬로+우?|반가워(요)?|반갑습니다|"
    r"고마워(요)?|감사합니다|고맙습니다|땡큐|thanks?|thank\s*you|"
    r"ㅎㅇ|잘\s*가|bye|goodbye|뭐\s*해(요)?|뭐하고\s*있어|ㅋ+|ㅎ+|ㅇㅇ)[\s!.?~♡]*$",
    re.IGNORECASE,
)


def is_non_product_chitchat(query: str) -> bool:
    """상품 검색이 아닌 인사말/잡담을 순수 로컬 정규식으로 감지한다 - 네트워크나
    LLM 호출이 전혀 없다(사용자 요청, 2026-08-15: "자기가 상품으로 인식못하는
    말을 들으면 처리해야하는 속도를 높여줘" - "하이" 같은 입력이 전에는 검색 ->
    clarify 추출(GPT+Gemini) -> 그마저 실패하면 전체 debate 파이프라인(정제+검색+
    제안 3개+검증+심사)까지 끝까지 흘러가며 완전히 헛수고인 호출을 여러 번 거친
    뒤에야 실패했다). 닫힌 인사말 집합에 전체 문자열이 정확히 일치할 때만 True라
    실제 상품명을 오탐할 위험이 낮다."""
    return bool(_GREETING_PATTERN.match(query.strip()))


def has_count_spec(query: str) -> bool:
    """질의에 이미 개수(1개/6병/2박스 등)가 명시돼 있는지 — Human-in-the-loop에서
    사용자가 이미 답한 기준을 검색 결과가 완전히 못 걸러내도 다시 안 물어보기 위함."""
    return bool(_COUNT_UNIT_PATTERN.search(query))


def has_volume_spec(query: str) -> bool:
    """질의에 이미 용량/무게(500ml/1kg 등)가 명시돼 있는지 — has_count_spec과 같은 이유."""
    return bool(_VOLUME_UNIT_PATTERN.search(query))
