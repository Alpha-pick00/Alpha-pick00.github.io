#!/usr/bin/env python3
"""URL 목록을 받아 각 페이지에서 가격을 "구조화된 데이터"로 뽑아낼 수 있는지 실측한다.

온디맨드 가격 페처를 만들기 전에, 정적 HTTP GET만으로 얼마나 많은 후보 URL이
schema.org JSON-LD / OpenGraph 가격 태그로 커버되는지, CSS 셀렉터 파싱이
필요한지, 헤드리스 브라우저(JS 렌더링)가 필요한지, 아예 접근이 막히는지를
도메인별로 분류해 CSV로 남긴다.

이 스크립트 자체는 가격을 "채택"하지 않는다 — 실측/분류가 목적이다.

사용법:
    python scripts/probe_structured_data.py scripts/urls.txt --csv scripts/probe_result.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 실측 단계에서 IP 차단을 당하면 아무것도 못 하게 되므로 보수적으로 고정한다.
# 이 값을 임의로 올리지 않는다.
CONCURRENCY = 5
PER_DOMAIN_INTERVAL_SEC = 1.0
REQUEST_TIMEOUT = 15.0

# 서로 다른 상품인지 아닌지의 기준. backend/fusion/dedup.py의
# PRICE_COMPAT_TOLERANCE(5%)와 같은 기준을 써서, "목록 페이지라 가격이
# 여러 개 섞여 나온 것"과 "변형 옵션이라 가격이 살짝 다른 것"을 구분한다.
LISTING_PAGE_PRICE_SPREAD_THRESHOLD = 0.05
LISTING_PAGE_MIN_DISTINCT_PRICES = 2

STATUS_JSONLD = "JSONLD"
STATUS_OG = "OG"
STATUS_CSS_NEEDED = "CSS_NEEDED"
STATUS_HEADLESS_NEEDED = "HEADLESS_NEEDED"
STATUS_FAIL = "FAIL"

_PRICE_TEXT_PATTERN = re.compile(r"(?:₩|원)\s*\d[\d,]{2,}|\d[\d,]{2,}\s*원")
_PRODUCT_TYPES = {"Product", "Offer", "AggregateOffer"}


@dataclass
class ProbeResult:
    url: str
    domain: str
    status: str
    http_status: int | None = None
    prices: list[float] = field(default_factory=list)
    many_prices_maybe_listing_page: bool = False
    error: str | None = None
    elapsed_ms: int | None = None


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _flatten_jsonld(data):
    if isinstance(data, list):
        for item in data:
            yield from _flatten_jsonld(item)
    elif isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _flatten_jsonld(item)


def _coerce_price(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _prices_from_offers(offers) -> list[float]:
    found: list[float] = []
    if offers is None:
        return found
    items = offers if isinstance(offers, list) else [offers]
    for item in items:
        if isinstance(item, dict):
            p = _coerce_price(item.get("price"))
            if p is not None:
                found.append(p)
    return found


def extract_jsonld_prices(html: str) -> list[float]:
    """페이지의 모든 <script type="application/ld+json"> 블록에서 offers.price를 모은다.
    상품 페이지는 보통 가격이 1개(±변형 옵션) 나오고, 목록/전시 페이지는
    서로 다른 여러 상품의 가격이 한꺼번에 나온다 — 그 차이를 그대로 신호로 남긴다."""
    soup = BeautifulSoup(html, "lxml")
    prices: list[float] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _flatten_jsonld(data):
            if not isinstance(node, dict):
                continue
            node_types = node.get("@type")
            node_types = node_types if isinstance(node_types, list) else [node_types]
            if node.get("price") is not None:
                p = _coerce_price(node.get("price"))
                if p is not None:
                    prices.append(p)
            if "offers" in node:
                prices.extend(_prices_from_offers(node.get("offers")))
    return prices


def extract_og_prices(html: str) -> list[float]:
    soup = BeautifulSoup(html, "lxml")
    prices: list[float] = []
    for prop in ("og:price:amount", "product:price:amount"):
        for tag in soup.find_all("meta", attrs={"property": prop}):
            p = _coerce_price(tag.get("content"))
            if p is not None:
                prices.append(p)
    return prices


def _looks_like_price_text_present(html: str) -> bool:
    return bool(_PRICE_TEXT_PATTERN.search(html))


def _is_listing_page(prices: list[float]) -> bool:
    distinct = sorted(set(prices))
    if len(distinct) < LISTING_PAGE_MIN_DISTINCT_PRICES:
        return False
    spread = (max(distinct) - min(distinct)) / max(distinct)
    return spread > LISTING_PAGE_PRICE_SPREAD_THRESHOLD


def classify(html: str) -> tuple[str, list[float], bool]:
    jsonld_prices = extract_jsonld_prices(html)
    if jsonld_prices:
        return STATUS_JSONLD, jsonld_prices, _is_listing_page(jsonld_prices)

    og_prices = extract_og_prices(html)
    if og_prices:
        return STATUS_OG, og_prices, _is_listing_page(og_prices)

    if _looks_like_price_text_present(html):
        return STATUS_CSS_NEEDED, [], False

    return STATUS_HEADLESS_NEEDED, [], False


class DomainThrottle:
    """도메인별로 마지막 요청 시각을 기억해 최소 간격을 보장한다."""

    def __init__(self, interval_sec: float) -> None:
        self._interval = interval_sec
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, domain: str) -> None:
        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last_request.get(domain)
            if last is not None:
                elapsed = now - last
                remaining = self._interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request[domain] = time.monotonic()


async def probe_one(
    client: httpx.AsyncClient,
    url: str,
    throttle: DomainThrottle,
    semaphore: asyncio.Semaphore,
) -> ProbeResult:
    domain = _domain(url)
    async with semaphore:
        await throttle.wait(domain)
        start = time.monotonic()
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            return ProbeResult(
                url=url, domain=domain, status=STATUS_FAIL, error=f"timeout: {exc}"
            )
        except httpx.HTTPError as exc:
            return ProbeResult(
                url=url, domain=domain, status=STATUS_FAIL, error=f"{type(exc).__name__}: {exc}"
            )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if response.status_code >= 400:
            return ProbeResult(
                url=url,
                domain=domain,
                status=STATUS_FAIL,
                http_status=response.status_code,
                error=f"HTTP {response.status_code}",
                elapsed_ms=elapsed_ms,
            )

        status, prices, is_listing = classify(response.text)
        return ProbeResult(
            url=url,
            domain=domain,
            status=status,
            http_status=response.status_code,
            prices=prices,
            many_prices_maybe_listing_page=is_listing,
            elapsed_ms=elapsed_ms,
        )


async def probe_all(urls: list[str]) -> list[ProbeResult]:
    throttle = DomainThrottle(PER_DOMAIN_INTERVAL_SEC)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"}

    async with httpx.AsyncClient(
        headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True
    ) as client:
        tasks = [probe_one(client, url, throttle, semaphore) for url in urls]
        return await asyncio.gather(*tasks)


def print_domain_summary(results: list[ProbeResult]) -> None:
    by_domain: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        by_domain[r.domain][r.status] += 1

    print(f"\n{'domain':40s} {'JSONLD':>7s} {'OG':>5s} {'CSS':>5s} {'HEADLESS':>9s} {'FAIL':>5s} {'total':>6s}")
    for domain in sorted(by_domain):
        c = by_domain[domain]
        total = sum(c.values())
        print(
            f"{domain:40s} {c[STATUS_JSONLD]:>7d} {c[STATUS_OG]:>5d} "
            f"{c[STATUS_CSS_NEEDED]:>5d} {c[STATUS_HEADLESS_NEEDED]:>9d} {c[STATUS_FAIL]:>5d} {total:>6d}"
        )

    fail_reasons: Counter = Counter()
    for r in results:
        if r.status == STATUS_FAIL:
            key = str(r.http_status) if r.http_status else (r.error or "unknown").split(":")[0]
            fail_reasons[key] += 1
    if fail_reasons:
        print("\nFAIL 원인별 개수:")
        for reason, count in fail_reasons.most_common():
            print(f"  {reason}: {count}")

    listing_flagged = [r for r in results if r.many_prices_maybe_listing_page]
    if listing_flagged:
        print(f"\nmany_prices_maybe_listing_page 플래그: {len(listing_flagged)}건")
        for r in listing_flagged:
            print(f"  [{r.domain}] {r.url} prices={r.prices}")


def write_csv(results: list[ProbeResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "url",
                "domain",
                "status",
                "http_status",
                "prices",
                "many_prices_maybe_listing_page",
                "error",
                "elapsed_ms",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.url,
                    r.domain,
                    r.status,
                    r.http_status if r.http_status is not None else "",
                    ";".join(str(p) for p in r.prices),
                    r.many_prices_maybe_listing_page,
                    r.error or "",
                    r.elapsed_ms if r.elapsed_ms is not None else "",
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "URL 목록 파일을 읽어 도메인당 1초 간격 + 동시 5개 제한으로 순회하며 "
            "JSON-LD/OpenGraph 구조화 가격 데이터를 뽑을 수 있는지 실측한다."
        )
    )
    parser.add_argument("urls_file", type=Path, help="한 줄에 URL 하나씩 담긴 텍스트 파일")
    parser.add_argument("--csv", type=Path, default=None, help="결과를 저장할 CSV 경로")
    args = parser.parse_args()

    urls = [
        line.strip()
        for line in args.urls_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        print(f"{args.urls_file}에 URL이 없습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"{len(urls)}개 URL 실측 시작 (동시 {CONCURRENCY}개, 도메인당 {PER_DOMAIN_INTERVAL_SEC}초 간격)...")
    results = asyncio.run(probe_all(urls))

    print_domain_summary(results)

    if args.csv:
        write_csv(results, args.csv)
        print(f"\nCSV 저장: {args.csv}")


if __name__ == "__main__":
    main()
