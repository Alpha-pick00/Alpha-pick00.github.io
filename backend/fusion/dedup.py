"""에이전트별 후보 배열을 병합해 동일 상품을 하나의 후보로 합친다.

동일 상품 판별 우선순위:
1. URL 정규화 후 완전 일치
2. (판매처, 가격) 완전 일치
3. 상품명 유사도(rapidfuzz token_set_ratio >= NAME_SIMILARITY_THRESHOLD)
"""

from __future__ import annotations

from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz

from app.schemas import AgentCandidate

# utm_*만 순수 광고 추적용으로 보고 제거한다. spec·itemId처럼 상품/옵션 자체를
# 가리키는 파라미터까지 지우면 서로 다른 상품이 같은 URL로 오인 합쳐질 수 있어
# 보수적으로 접근한다 — 다른 트래커를 추가로 지워야 하면 이 튜플만 늘리면 된다.
_TRACKING_PREFIXES = ("utm_",)

NAME_SIMILARITY_THRESHOLD = 85


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query_pairs),
            "",
        )
    )


def _majority(values: list, canonical_value):
    """가장 많은 표를 받은 값을 반환한다. 동률이면 canonical_value(대표 후보의 값)를 우선한다."""
    counter = Counter(values)
    max_count = max(counter.values())
    tied = [v for v, c in counter.items() if c == max_count]
    if len(tied) == 1:
        return tied[0]
    return canonical_value if canonical_value in tied else tied[0]


class _Group:
    def __init__(self, agent: str, candidate: AgentCandidate) -> None:
        self.members: list[tuple[str, AgentCandidate]] = [(agent, candidate)]
        self.norm_url = normalize_url(candidate.url)

    def add(self, agent: str, candidate: AgentCandidate) -> None:
        self.members.append((agent, candidate))
        if not self.norm_url:
            self.norm_url = normalize_url(candidate.url)

    def matches(self, candidate: AgentCandidate) -> bool:
        norm_url = normalize_url(candidate.url)
        if norm_url and self.norm_url and norm_url == self.norm_url:
            return True
        for _, member in self.members:
            if (
                candidate.price_krw is not None
                and member.price_krw == candidate.price_krw
                and candidate.retailer
                and (candidate.retailer or "") == (member.retailer or "")
            ):
                return True
        for _, member in self.members:
            if (
                fuzz.token_set_ratio(candidate.product_name, member.product_name)
                >= NAME_SIMILARITY_THRESHOLD
            ):
                return True
        return False

    def to_dict(self) -> dict:
        # URL이 가장 짧은(=파라미터가 적은) 멤버를 대표 후보로 삼아 동률 시 근거로 쓴다.
        canonical = min(self.members, key=lambda m: len(m[1].url or ""))[1]

        product_name = _majority(
            [m.product_name for _, m in self.members], canonical.product_name
        )

        retailers = [m.retailer for _, m in self.members if m.retailer]
        retailer = _majority(retailers, canonical.retailer) if retailers else None

        prices = [m.price_krw for _, m in self.members if m.price_krw is not None]
        price_krw = _majority(prices, canonical.price_krw) if prices else None

        urls = [m.url for _, m in self.members if m.url]
        url = _majority(urls, canonical.url) if urls else None

        return {
            "product_name": product_name,
            "price_krw": price_krw,
            "url": url,
            "retailer": retailer,
            "reasons": [m.reasoning for _, m in self.members if m.reasoning],
            "proposed_by": [a for a, _ in self.members],
            "signals": {},
            "final_score": 0.0,
        }


def merge_candidates(entries: list[tuple[str, AgentCandidate]]) -> list[dict]:
    """entries: [(agent_name, candidate), ...]. 이미 유효성 필터링된 후보만 들어온다고 가정한다."""
    groups: list[_Group] = []
    for agent, candidate in entries:
        target = next((g for g in groups if g.matches(candidate)), None)
        if target is None:
            groups.append(_Group(agent, candidate))
        else:
            target.add(agent, candidate)
    return [group.to_dict() for group in groups]
