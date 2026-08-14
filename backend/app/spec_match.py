"""상품명 두 개가 "같은 상품"인지 판별할 때 쓰는 모델/스펙/수량 토큰 충돌
가드. 원래 app.price_table(다나와 실측가 매칭)에만 있었는데, fusion.dedup
(에이전트 간 후보 병합)도 같은 문제를 겪는다는 게 확인돼 여기로 뽑아 공유한다
(사용자 리포트, 2026-08-14: "핸드폰 케이스" 검색에서 옛날 모델이 섞여 나옴 -
"아이폰6 케이스" vs "아이폰15 케이스"처럼 모델 토큰만 다른 두 상품이
token_set_ratio 임계값을 넘어 같은 그룹으로 합쳐지고, 그룹 대표는 최저가
멤버라 구형 모델이 대표로 뽑힐 수 있었다). price_table.py가 fusion.dedup을
import하므로, 반대 방향 import(순환 참조)를 피하려면 이 로직은 둘 중 어느
쪽에도 속하지 않는 별도 모듈이어야 한다."""

from __future__ import annotations

import re
from collections import defaultdict

# 영숫자 혼합 토큰(SM-R630N, 16Z90U-KU7BK, V8 ...) - 하이픈으로 이어진 것도
# 하나의 토큰으로 묶는다.
_MODEL_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

# 한글 단어 바로 뒤에 숫자가 붙은 모델 토큰("아이폰15", "아이폰6", "갤럭시워치7") -
# 알파벳이 안 섞여 위 _MODEL_TOKEN_PATTERN(영숫자 혼합)로는 못 잡는 모델 세대
# 표기를 잡는다(사용자 리포트, 2026-08-14: "핸드폰 케이스" 검색에서 옛날 모델이
# 섞여 나옴 - "아이폰6 케이스" vs "아이폰15 케이스"는 숫자에 알파벳이 안 붙어
# 기존 규칙으로는 스펙 충돌을 못 잡았다). "1개"/"2개입"처럼 개수 단위가 바로
# 뒤에 오면 모델 표기가 아니라 수량 표기이므로 제외한다(수량은
# _QUANTITY_TOKEN_PATTERNS가 별도로 다룬다) - 안 그러면 "본품1개" vs "사은품2개"
# 같은 번들 수량 차이까지 모델 충돌로 오탐할 수 있다.
_KOREAN_MODEL_TOKEN_PATTERN = re.compile(
    r"[가-힣]+\d+(?!\s*(?:개입|개|장|벌|병|통|팩|세트|인용|%))"
)

# 수량/용량 토큰. "무이자 12개월"의 "12개"를 오탐하지 않도록 "개" 뒤에 "입"도
# "월"도 오지 않을 때만 수량으로 본다 - scripts/verify_product_identity.py에서
# 이 정확한 버그를 한 번 잡았던 걸 그대로 반영한다.
_QUANTITY_TOKEN_PATTERNS = [
    re.compile(r"\d+\s*개입"),
    re.compile(r"\d+\s*개(?!입)(?!월)"),
    re.compile(r"\d+\s*(?:GB|TB)", re.IGNORECASE),
    re.compile(r"\d+\s*(?:g|kg|ml|L)\b"),
]

_YEAR_MIN, _YEAR_MAX = 1990, 2035


def _is_year_token(token: str) -> bool:
    return len(token) == 4 and token.isdigit() and _YEAR_MIN <= int(token) <= _YEAR_MAX


def extract_spec_tokens(text: str) -> set[str]:
    """영숫자 혼합 토큰(SM-R630N, M2, 128GB), 4자리 연식(1990~2035), 한글+숫자
    모델 세대 표기(아이폰15, 갤럭시워치7)를 뽑는다. "1000mAh"처럼 단위가 붙은
    4자리는 연식 판정(순수 숫자만) 대상이 아니라 이미 영숫자 혼합 토큰 규칙으로
    잡힌다 - 별도 처리 불필요."""
    tokens = set()
    for match in _MODEL_TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        has_digit = any(c.isdigit() for c in token)
        has_alpha = any(c.isalpha() for c in token)
        if (has_digit and has_alpha) or _is_year_token(token):
            tokens.add(token.upper())
    for match in _KOREAN_MODEL_TOKEN_PATTERN.finditer(text):
        tokens.add(match.group(0))
    return tokens


def _token_family(token: str) -> str:
    """숫자 런(연속된 숫자열)을 #로 치환해 "같은 종류의 스펙"인지 판별하는
    키를 만든다. M2/M3 -> M#, 2024/2025 -> #, SM-R630N/SM-R631N -> SM-R#N.

    자릿수가 다른 숫자는 한 글자씩 치환하면(M2->M#, 하지만 V8->V#, V15->V##)
    같은 계열인데 family가 갈라져 충돌을 놓친다 - 실제로 "다이슨 V8" vs
    "다이슨 V15"가 이 방식으로는 안 걸렸다(자릿수 1개 vs 2개). 숫자 런
    전체를 한 번에 치환해야 64GB/128GB, V8/V15처럼 자릿수가 다른 값도
    같은 family로 묶여서 비교된다.

    PART 4-1: 기존의 "완전히 disjoint일 때만 충돌" 판정은 {M2,128GB} vs
    {M3,128GB}처럼 토큰 하나(128GB)만 겹쳐도 나머지(M2 vs M3)를 그냥
    통과시켰다(실측: iPad Air M2/M3, iPad Pro M4/M5가 그렇게 새어나갔다).
    family 단위로 쪼개면 "같은 종류인데 값이 다른" 경우를 개별적으로 잡는다."""
    return re.sub(r"\d+", "#", token)


def spec_tokens_conflict(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """양쪽에 같은 family가 모두 있는데 값 집합이 다르면 충돌. 한쪽에만 있는
    family는 무시한다(모델명/수량 가드와 같은 논리).

    값 집합이 완전히 같으면(예: "램12GB,256GB"처럼 RAM·저장용량이 둘 다
    #GB family로 묶여도 양쪽 다 {12GB,256GB}로 동일) 충돌이 아니다 - 이걸
    먼저 확인하지 않고 "한쪽에 값이 2개 이상이면 무조건 충돌"로 처리했더니
    같은 문자열을 자기 자신과 비교해도 실패하는 버그가 실측(100개 배치
    재판정)에서 나왔다. "M2와 M4가 한 이름에 같이 있는" 것처럼 진짜
    모호한 경우는 값 집합이 다를 때만 문제이므로, 값 집합 비교 하나로
    충분하다 - 값이 다르면(한쪽이 모호한 다중값이든 아니든) 보수적으로
    충돌 처리된다."""
    by_family_a: dict[str, set[str]] = defaultdict(set)
    for token in tokens_a:
        by_family_a[_token_family(token)].add(token)
    by_family_b: dict[str, set[str]] = defaultdict(set)
    for token in tokens_b:
        by_family_b[_token_family(token)].add(token)

    for family in set(by_family_a) & set(by_family_b):
        if by_family_a[family] != by_family_b[family]:
            return True
    return False


def extract_quantity_tokens(text: str) -> set[str]:
    tokens = set()
    for pattern in _QUANTITY_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            tokens.add(re.sub(r"\s+", "", match.group(0)).upper())
    return tokens


def tokens_conflict(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """양쪽 다 토큰이 있는데 겹치는 게 하나도 없으면 충돌(다른 모델/다른
    수량)로 본다. 한쪽만 토큰이 있으면(그 정보를 안 적었을 뿐) 무시한다."""
    if not tokens_a or not tokens_b:
        return False
    return tokens_a.isdisjoint(tokens_b)


def model_or_quantity_conflict(name_a: str, name_b: str) -> bool:
    """상품명 두 개가 스펙 토큰(모델/규격)이나 수량 토큰에서 충돌하면 True.
    exclusive_tokens_conflict(순한글 배타 어휘)와는 별개 축이라 호출자가
    필요에 따라 둘 다 조합해서 쓴다(app.price_table, fusion.dedup)."""
    if spec_tokens_conflict(extract_spec_tokens(name_a), extract_spec_tokens(name_b)):
        return True
    if tokens_conflict(extract_quantity_tokens(name_a), extract_quantity_tokens(name_b)):
        return True
    return False
