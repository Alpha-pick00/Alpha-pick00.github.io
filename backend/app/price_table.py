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
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qsl, urlsplit

from fetchers import danawa
from fetchers.danawa_mall_map import CMPNYC_MAP, TRUST_TIER

from .schemas import Decision, PriceTable, PriceTableOffer, SearchResult

logger = logging.getLogger(__name__)

DANAWA_HOST = "prod.danawa.com"
MAX_DANAWA_URLS = 3

# fusion/dedup.py의 PRICE_COMPAT_TOLERANCE(0.05)와 동일한 취지 - 쿠폰/배송비
# 정도의 차이만 "같은 offer"로 본다. LLM 추천과 다나와 offer를 대조할 때 씀.
PRICE_MATCH_TOLERANCE = 0.05


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


def _price_to_int(price: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", price or "")
    return int(digits) if digits else None


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def _price_close(a: int, b: int) -> bool:
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= PRICE_MATCH_TOLERANCE


def _seller_matches_retailer(retailer: str | None, seller: str) -> bool:
    if not retailer:
        return False
    return seller in retailer or retailer in seller


async def enrich_decision(decision: Decision, raw_result: danawa.DanawaResult) -> Decision:
    """LLM judge가 고른 decision을 다나와 실측 가격표와 대조한다. A등급
    (linkable) offer 중 판매처/가격이 decision과 사실상 같은 게 있으면 -
    가격은 검증된 숫자로, url은 실제로 해석된 구매 링크로 교체하고
    price_source를 "danawa_offer"로 바꾼다. 일치하는 게 없으면 decision을
    그대로 둔다(price_source는 기본값 "llm_guess" 유지) - 다른 상품으로
    억지로 바꿔치기하지 않는다.

    링크를 못 만들면(resolve_purchase_url이 None) 교체하지 않는다 - "링크
    없는 추천"을 만들지 않기 위해서다(STEP 3 설계)."""
    decision_price = _price_to_int(decision.price)
    if decision_price is None:
        return decision

    decision_domain = _domain_from_url(decision.url)

    for offer in raw_result["offers"]:
        domain, url_rule = _domain_and_rule(offer)
        if url_rule is None:
            continue
        if not _price_close(decision_price, offer["price_krw"]):
            continue
        domain_matches = domain is not None and decision_domain is not None and decision_domain == domain
        seller_matches = _seller_matches_retailer(decision.retailer, offer["seller"])
        if not (domain_matches or seller_matches):
            continue

        resolved_url = await resolve_purchase_url(offer)
        if resolved_url is None:
            continue

        decision.price = f"{offer['price_krw']:,}원"
        decision.url = resolved_url
        decision.price_source = "danawa_offer"
        return decision

    return decision
