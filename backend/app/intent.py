import re

# 숫자 + 한국어 수량/용량/무게 단위가 있으면 "브랜드만 고르면 되는" 구체적 구매 질의로 간주한다.
# 근사치 휴리스틱이며, "노트북 1대"처럼 스펙 비교가 필요한 항목도 걸릴 수 있다.
BULK_SPEC_PATTERN = re.compile(
    r"\d+\s*(개|병|팩|박스|세트|캔|봉지|포|장|권|벌|족|대"
    r"|ml|ML|mL|L|리터|밀리리터|kg|KG|Kg|g|G|그램|킬로)"
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
SHORT_QUERY_TOKEN_LIMIT = 2
_HAS_DIGIT_PATTERN = re.compile(r"\d")


def _is_short_bare_query(query: str) -> bool:
    tokens = query.strip().split()
    return 0 < len(tokens) <= SHORT_QUERY_TOKEN_LIMIT and not _HAS_DIGIT_PATTERN.search(query)


def needs_clarification(query: str) -> bool:
    if is_bulk_query(query):
        return False
    return bool(BUY_INTENT_PATTERN.search(query)) or _is_short_bare_query(query)
