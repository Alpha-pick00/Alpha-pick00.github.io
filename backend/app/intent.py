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


def needs_clarification(query: str) -> bool:
    return bool(BUY_INTENT_PATTERN.search(query)) and not is_bulk_query(query)
