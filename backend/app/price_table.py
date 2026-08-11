"""다나와 어댑터(fetchers/danawa.py)를 파이프라인에 연결하는 계층.

STEP 3 설계(2026-08-10 지시서) 핵심:
- 다나와 페치는 LLM 호출과 asyncio.gather로 동시 실행한다(순차로 붙이면 그만큼
  느려지므로) — 이 모듈의 fetch_price_tables()가 그 진입점이다.
- 링크(구매 URL)를 못 만드는 offer도 가격표에서 버리지 않는다. 링크 생성
  가능 여부(linkable)와 판매처 신뢰도(trust)는 domain/url_rule을 아는지에
  달려 있고, 이 둘은 서로 다른 질문이다 - domain은 아는데 url_rule이 없는
  경우("몰은 확실한데 링크는 못 만든다")가 실제로 44개 offer 중 13개였다
  (검증 E).
- 44개 offer의 bridge_url을 파이프라인에서 해석하지 않는다. 최종 추천으로
  확정된 offer 1건에 대해서만 resolve_purchase_url()을 호출한다(lazy).
- 다나와 bridge URL이나 제휴 중계 URL은 이 모듈이 반환하는 어떤 값에도 담기지
  않는다 - PriceTableOffer 스키마 자체에 그 필드가 없고, 최종 추천에 쓰는
  resolve_purchase_url()도 완전히 해석된 최종 URL만 반환한다(실패 시 None).

STEP 6 설계(2026-08-11 지시서) 변경 - 매칭 키를 판매처+가격에서 상품명으로:
- STEP 5 라이브 검증에서 실패 5건 중 3건이 상품명은 완전 일치(100.0)였는데도
  판매처가 "다나와 가격비교" 자신이라 매칭이 원천 차단됐다. 다나와 페이지
  하나는 pcode 기준으로 특정 상품 하나를 가리키므로, LLM이 고른 상품과
  이름이 같으면 그 페이지의 10개 offer는 "그 상품의 가격표 그 자체"다 -
  판매처가 뭐든 상관없다.
- enrich_decision()은 이제 product_name만 본다(rapidfuzz token_set_ratio +
  모델명/규격·수량 토큰 충돌 가드). 가격 근접도·판매처 일치는 더 이상 보지
  않는다 - cheapest_linkable_raw_offer()가 A등급 중 최저가를 그냥 고른다.
- exclude_danawa_as_final_pick()은 별개 문제를 다룬다: 다나와 자신이 "판매처"로
  최종 추천되는 경우(라이브 검증에서 실제로 3/5 관찰됨) - 수수료 0%인 곳을
  추천하는 셈이라 pcode 일치로 확인된 자기 자신의 A등급 최저가로, 그것도
  없으면 다나와가 아닌 다른 에이전트 제안으로 바꾼다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qsl, urlsplit

from rapidfuzz import fuzz

from fetchers import danawa
from fetchers.danawa_mall_map import CMPNYC_MAP, TRUST_TIER
from fusion.dedup import NAME_SIMILARITY_THRESHOLD

from .exclusive_tokens import exclusive_tokens_conflict
from .schemas import Decision, PriceTable, PriceTableOffer, Proposal, SearchResult

logger = logging.getLogger(__name__)

DANAWA_HOST = "prod.danawa.com"
DANAWA_ROOT_DOMAIN = "danawa.com"
MAX_DANAWA_URLS = 3


def _query_param(url: str | None, name: str) -> str | None:
    if not url:
        return None
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)).get(name)


def _domain_and_rule(offer: danawa.DanawaOffer) -> tuple[str | None, str | None]:
    """offer의 bridge_url에서 cmpnyc를 뽑아 CMPNYC_MAP과 대조한다. 네트워크
    없음 - 이미 페치해 둔 bridge_url 문자열만 파싱한다."""
    cmpnyc = _query_param(offer.get("bridge_url"), "cmpnyc")
    mapping = CMPNYC_MAP.get(cmpnyc) if cmpnyc else None
    if mapping is None:
        return None, None
    return mapping["domain"], mapping["url_rule"]


def _trust_for_domain(domain: str | None) -> float | None:
    """domain을 모르면 등급도 모른다 - None으로 남긴다(0.3으로 강등 금지,
    검증 E 지시서). domain은 알지만 TRUST_TIER 어디에도 없으면 0.3."""
    if domain is None:
        return None
    for tier, domains in TRUST_TIER.items():
        if domain in domains:
            return tier
    return 0.3


def select_danawa_urls(results: list[SearchResult], limit: int = MAX_DANAWA_URLS) -> list[str]:
    """Tavily 결과 중 다나와 상품 페이지만, score 내림차순으로 최대 limit개."""
    candidates = [r for r in results if urlsplit(r.url).netloc.lower() == DANAWA_HOST]
    candidates.sort(key=lambda r: r.score if r.score is not None else float("-inf"), reverse=True)
    return [r.url for r in candidates[:limit]]


def build_price_table(result: danawa.DanawaResult) -> PriceTable | None:
    """순수 함수 - 이미 페치된 DanawaResult를 등급 매긴 PriceTable로 바꾼다.
    네트워크 없음. parse_status가 ok/partial이고 offer가 하나 이상일 때만
    PriceTable을 만든다."""
    if result["parse_status"] not in ("ok", "partial") or not result["offers"]:
        return None

    sorted_offers = sorted(result["offers"], key=lambda o: o["price_krw"])
    graded: list[PriceTableOffer] = []
    for rank, offer in enumerate(sorted_offers, start=1):
        domain, url_rule = _domain_and_rule(offer)
        graded.append(
            PriceTableOffer(
                seller=offer["seller"],
                price_krw=offer["price_krw"],
                delivery_text=offer["delivery_text"],
                domain=domain,
                trust=_trust_for_domain(domain),
                linkable=url_rule is not None,
                rank=rank,
            )
        )

    prices = [o.price_krw for o in graded]
    spread = round(max(prices) / min(prices), 3) if min(prices) else None
    pcode = _query_param(result["source_url"], "pcode")

    return PriceTable(
        source_pcode=pcode,
        product_name=result["product_name"],
        offers=graded,
        spread=spread,
    )


async def fetch_price_tables(
    results: list[SearchResult],
) -> list[tuple[PriceTable, danawa.DanawaResult]]:
    """LLM 호출들과 asyncio.gather로 나란히 실행되는 걸 전제로 한 진입점.
    무슨 일이 있어도 예외를 던지지 않는다 - 실패하면 빈 리스트를 반환해
    본 파이프라인(LLM 기반 추천)을 절대 막지 않는다.

    (PriceTable, DanawaResult) 튜플로 반환하는 이유: PriceTable은 응답에
    그대로 노출되는 공개 스키마라 bridge_url이 없다. 최종 추천 확정 후
    resolve_purchase_url()을 부르려면 원본 DanawaOffer(bridge_url 포함)가
    필요해서 함께 들고 다닌다 - bridge_url은 이 튜플 밖으로 나가지 않는다."""
    urls = select_danawa_urls(results)
    if not urls:
        return []

    try:
        raw_results = await asyncio.gather(
            *(danawa.fetch_danawa_offers(u) for u in urls), return_exceptions=True
        )
    except Exception:
        logger.exception("danawa price table fetch crashed entirely")
        return []

    tables: list[tuple[PriceTable, danawa.DanawaResult]] = []
    for r in raw_results:
        if isinstance(r, BaseException):
            logger.info("danawa fetch failed for one url: %r", r)
            continue
        try:
            table = build_price_table(r)
        except Exception:
            logger.exception("failed to build price table from danawa result")
            continue
        if table is not None:
            tables.append((table, r))
    return tables


def pick_primary(
    tables: list[tuple[PriceTable, danawa.DanawaResult]],
) -> tuple[PriceTable, danawa.DanawaResult] | None:
    """여러 다나와 URL이 페치됐을 때 offer가 가장 많은(=가장 풍부한) 페이지를
    대표 가격표로 쓴다."""
    if not tables:
        return None
    return max(tables, key=lambda pair: len(pair[0].offers))


def cheapest_linkable_raw_offer(result: danawa.DanawaResult) -> danawa.DanawaOffer | None:
    """A등급(linkable) offer 중 최저가 원본(bridge_url 포함)을 찾는다.
    없으면 None - 이 경우 "링크 있는 추천"을 만들 수 없다는 뜻이다."""
    linkable = [
        offer for offer in result["offers"] if _domain_and_rule(offer)[1] is not None
    ]
    if not linkable:
        return None
    return min(linkable, key=lambda o: o["price_krw"])


async def resolve_purchase_url(offer: danawa.DanawaOffer) -> str | None:
    """최종 추천으로 확정된 offer 1건에 대해서만 호출한다(lazy) - 파이프라인
    다른 어디에서도 자동 호출되지 않는다.

    url_rule이 "template:..."이면 네트워크 요청 없이 bridge_url의
    link_pcode를 그대로 대입해 조립한다(11번가 - 검증 E-1/D에서 확인:
    goUrl 파라미터의 목적지 상품 ID가 다나와 자신의 link_pcode와 일치했다).
    "redirect_resolved"면 danawa.resolve_outlink()로 실제 2-hop 요청을
    보낸다(쿠팡/SSG/롯데ON/SK스토아/신세계라이브쇼핑/신세계몰 - 검증 A/E-2에서
    확인). 반환값은 항상 완전히 해석된 최종 URL이거나 None - bridge_url이나
    제휴 중계 URL이 새어나가는 경로는 없다."""
    domain, url_rule = _domain_and_rule(offer)
    if url_rule is None:
        return None

    if url_rule.startswith("template:"):
        template = url_rule[len("template:") :]
        link_pcode = _query_param(offer.get("bridge_url"), "link_pcode")
        if not link_pcode:
            return None
        return template.format(link_pcode=link_pcode)

    if url_rule == "redirect_resolved":
        bridge_url = offer.get("bridge_url")
        if not bridge_url:
            return None
        resolved_url, _ = await danawa.resolve_outlink(bridge_url)
        return resolved_url

    logger.warning("unknown url_rule %r for domain %r - not resolving", url_rule, domain)
    return None


# 영숫자 혼합 토큰(SM-R630N, 16Z90U-KU7BK, V8 ...) - 하이픈으로 이어진 것도
# 하나의 토큰으로 묶는다.
_MODEL_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

# 수량/용량 토큰. "무이자 12개월"의 "12개"를 오탐하지 않도록 "개" 뒤에 "입"도
# "월"도 오지 않을 때만 수량으로 본다 - scripts/verify_product_identity.py에서
# 이 정확한 버그를 한 번 잡았던 걸 그대로 반영한다.
_QUANTITY_TOKEN_PATTERNS = [
    re.compile(r"\d+\s*개입"),
    re.compile(r"\d+\s*개(?!입)(?!월)"),
    re.compile(r"\d+\s*(?:GB|TB)", re.IGNORECASE),
    re.compile(r"\d+\s*(?:g|kg|ml|L)\b"),
]


def _extract_model_tokens(text: str) -> set[str]:
    tokens = set()
    for match in _MODEL_TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        has_digit = any(c.isdigit() for c in token)
        has_alpha = any(c.isalpha() for c in token)
        if has_digit and has_alpha:
            tokens.add(token.upper())
    return tokens


def _extract_quantity_tokens(text: str) -> set[str]:
    tokens = set()
    for pattern in _QUANTITY_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            tokens.add(re.sub(r"\s+", "", match.group(0)).upper())
    return tokens


def _tokens_conflict(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """양쪽 다 토큰이 있는데 겹치는 게 하나도 없으면 충돌(다른 모델/다른
    수량)로 본다. 한쪽만 토큰이 있으면(그 정보를 안 적었을 뿐) 무시한다."""
    if not tokens_a or not tokens_b:
        return False
    return tokens_a.isdisjoint(tokens_b)


def _product_name_matches(decision_name: str, danawa_name: str) -> bool:
    if fuzz.token_set_ratio(decision_name, danawa_name) < NAME_SIMILARITY_THRESHOLD:
        return False
    if _tokens_conflict(_extract_model_tokens(decision_name), _extract_model_tokens(danawa_name)):
        return False
    if _tokens_conflict(_extract_quantity_tokens(decision_name), _extract_quantity_tokens(danawa_name)):
        return False
    # 백미/발아현미처럼 순한글 단어 하나가 결정적 차이인 경우 - token_set_ratio는
    # 공통 토큰이 많으면 이런 차이를 그냥 덮어버린다(실측 93.0점, 85 통과).
    if exclusive_tokens_conflict(decision_name, danawa_name):
        return False
    return True


def _is_danawa_domain(url: str | None) -> bool:
    if not url:
        return False
    host = urlsplit(url).netloc.lower()
    return host == DANAWA_ROOT_DOMAIN or host.endswith("." + DANAWA_ROOT_DOMAIN)


async def enrich_decision(decision: Decision, raw_result: danawa.DanawaResult) -> Decision:
    """LLM judge가 고른 decision을 다나와 실측 가격표와 대조한다. 매칭 키는
    상품명이다(판매처+가격 아님 - STEP 5 라이브 검증에서 판매처 기준이 진짜
    같은 상품 3건을 전부 놓쳤다). 다나와 페이지 하나는 pcode로 특정 상품
    하나를 가리키므로, 이름이 같으면 그 페이지의 offer 전부가 그 상품의
    가격표다 - 판매처가 뭐든 상관없이 A등급 중 최저가를 쓴다.

    이름이 안 맞거나(rapidfuzz + 모델/수량 토큰 가드), A등급 offer가 없거나,
    링크 해석이 실패하면 손대지 않는다(price_source="llm_guess" 유지) -
    다른 상품으로 억지로 바꿔치기하지 않는다."""
    danawa_name = raw_result.get("product_name")
    if not danawa_name or not decision.product_name:
        return decision
    if not _product_name_matches(decision.product_name, danawa_name):
        return decision

    offer = cheapest_linkable_raw_offer(raw_result)
    if offer is None:
        return decision  # A등급이 없다 - 링크 없는 추천은 내지 않는다.

    resolved_url = await resolve_purchase_url(offer)
    if resolved_url is None:
        return decision

    decision.price = f"{offer['price_krw']:,}원"
    decision.retailer = offer["seller"]
    decision.url = resolved_url
    decision.price_source = "danawa_offer"
    return decision


def _find_table_by_pcode(
    tables: list[tuple[PriceTable, danawa.DanawaResult]], pcode: str
) -> tuple[PriceTable, danawa.DanawaResult] | None:
    for table, raw in tables:
        if _query_param(raw["source_url"], "pcode") == pcode:
            return table, raw
    return None


async def exclude_danawa_as_final_pick(
    decision: Decision,
    proposals: list[Proposal],
    tables: list[tuple[PriceTable, danawa.DanawaResult]],
) -> Decision:
    """다나와는 수수료 0%라 최종 추천 판매처가 될 수 없다(이 어댑터를 만든
    이유 자체가 그거다) - 그런데 라이브 검증에서 judge가 실제로 다나와
    자신을 "판매처"로 고르는 사례가 3/5 관찰됐다. decision.url이 danawa.com이면:
    1) pcode가 일치하는(=같은 상품이 확실한) 페치 결과가 있으면 그 A등급
       최저가로 교체한다(상품명 대조 불필요 - pcode 일치가 더 강한 증거).
    2) 없으면 다나와가 아닌 다른 에이전트 제안으로 넘어간다(price_source는
       여전히 llm_guess - 검증된 게 아니라 그냥 다른 LLM 추측이다).
    3) 그것도 없으면 다나와 URL을 그대로 두고 경고 로그만 남긴다 - 노출은
       불가피하다."""
    if not _is_danawa_domain(decision.url):
        return decision

    pcode = _query_param(decision.url, "pcode")
    match = _find_table_by_pcode(tables, pcode) if pcode else None
    if match is not None:
        _, raw_result = match
        offer = cheapest_linkable_raw_offer(raw_result)
        if offer is not None:
            resolved_url = await resolve_purchase_url(offer)
            if resolved_url is not None:
                decision.price = f"{offer['price_krw']:,}원"
                decision.retailer = offer["seller"]
                decision.url = resolved_url
                decision.price_source = "danawa_offer"
                return decision

    for proposal in proposals:
        if proposal.error is not None or not proposal.url or not proposal.product_name:
            continue
        if _is_danawa_domain(proposal.url):
            continue
        decision.product_name = proposal.product_name
        decision.price = proposal.price or decision.price
        decision.retailer = proposal.retailer or decision.retailer
        decision.url = proposal.url
        decision.reasoning = proposal.reasoning or decision.reasoning
        return decision

    logger.warning(
        "final decision still points at danawa.com and no non-danawa fallback exists "
        "(url=%s) - exposing it to the user is unavoidable here", decision.url
    )
    return decision

    return decision
