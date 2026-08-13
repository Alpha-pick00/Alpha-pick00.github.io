"""검증 E-2 — 미검증 cmpnyc 15종 각각 대표 bridge_url 1건씩만 해석해서
cmpnyc -> 목적지 매핑표를 만든다. 코드당 정확히 1건, 총 15건 이하.
간격 3초(429 발생 시 5초로 증가), 재시도 없음, 403/429는 그 코드만
"불명"으로 두고 계속 진행, 429가 두 번째 발생하면 전체 중단.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa import BRIDGE_TARGET_PATTERN, USER_AGENT, parse_danawa_html  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

TIMEOUT = 5.0
BASE_INTERVAL_SEC = 3.0
BUMPED_INTERVAL_SEC = 5.0

# 검증 A/D에서 이미 확인된 cmpnyc는 재요청하지 않는다.
ALREADY_KNOWN = {"TP40F", "TH201", "EE715", "EE128", "TW627F"}

DEST_PARAM_CANDIDATES = ("goUrl", "url", "item-no", "prdNo", "itemId", "pageKey", "goodscode")


async def resolve_bridge(bridge_url: str) -> dict:
    diag: dict = {}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(bridge_url)
        except httpx.HTTPError as exc:
            diag["stage"] = "bridge_error"
            diag["error"] = f"{type(exc).__name__}: {exc}"
            return diag

    diag["bridge_status"] = resp.status_code
    if resp.status_code in (403, 429):
        diag["stage"] = f"bridge_{resp.status_code}"
        return diag

    match = BRIDGE_TARGET_PATTERN.search(resp.text)
    if not match:
        diag["stage"] = "bridge_no_golink_match"
        return diag

    affiliate_url = match.group(1)
    diag["affiliate_url"] = affiliate_url
    parts = urlsplit(affiliate_url)
    diag["gateway_domain"] = parts.netloc
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    diag["gateway_params"] = {k: v for k, v in params.items() if k in DEST_PARAM_CANDIDATES}

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            resp2 = await client.get(affiliate_url)
        except httpx.HTTPError as exc:
            diag["stage"] = "affiliate_error"
            diag["error"] = f"{type(exc).__name__}: {exc}"
            return diag

    diag["affiliate_status"] = resp2.status_code
    if resp2.status_code == 429:
        diag["stage"] = "affiliate_429"
        return diag

    diag["resolved_url"] = str(resp2.url)
    diag["resolved_domain"] = urlsplit(str(resp2.url)).netloc
    diag["stage"] = "ok"
    return diag


async def main() -> None:
    all_offers = []
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        result = parse_danawa_html(f"file://{filename}", html)
        all_offers.extend(result["offers"])

    representatives: dict[str, dict] = {}
    for offer in all_offers:
        bridge_url = offer.get("bridge_url")
        if not bridge_url:
            continue
        params = dict(parse_qsl(urlsplit(bridge_url).query, keep_blank_values=True))
        cmpnyc = params.get("cmpnyc")
        if cmpnyc is None or cmpnyc in ALREADY_KNOWN or cmpnyc in representatives:
            continue
        representatives[cmpnyc] = {"seller": offer["seller"], "raw_seller": offer["raw_seller"], "bridge_url": bridge_url}

    print(f"미검증 cmpnyc 대표 offer {len(representatives)}건 처리 시작\n")

    interval = BASE_INTERVAL_SEC
    count_429 = 0
    results: dict[str, dict] = {}

    for idx, (cmpnyc, info) in enumerate(representatives.items()):
        if idx > 0:
            await asyncio.sleep(interval)

        print("=" * 70)
        print(f"[{idx + 1}/{len(representatives)}] cmpnyc={cmpnyc} seller={info['seller']} (raw={info['raw_seller']!r})")
        print("=" * 70)

        diag = await resolve_bridge(info["bridge_url"])
        results[cmpnyc] = {**info, **diag}
        for key, value in diag.items():
            print(f"  {key}: {value}")

        stage = diag.get("stage", "")
        if stage in ("bridge_429", "affiliate_429"):
            count_429 += 1
            print(f"  -> 429 감지 ({count_429}번째), 간격을 {BUMPED_INTERVAL_SEC}초로 늘린다")
            interval = BUMPED_INTERVAL_SEC
            if count_429 >= 2:
                print("\n  !!! 두 번째 429 - 지시에 따라 검증 E-2 전체를 여기서 중단한다 !!!")
                break
        print()

    print("\n" + "=" * 70)
    print("E-2 요약")
    print("=" * 70)
    for cmpnyc, r in results.items():
        print(f"  {cmpnyc:8s} seller={r['seller']:20s} stage={r.get('stage')} "
              f"gateway_domain={r.get('gateway_domain')} resolved_domain={r.get('resolved_domain')} "
              f"gateway_params={r.get('gateway_params')}")


if __name__ == "__main__":
    asyncio.run(main())
