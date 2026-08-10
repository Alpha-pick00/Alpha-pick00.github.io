"""STEP 5 라이브 스모크 테스트 - 실제 /decide 파이프라인(run_single_debate)을
5개 쿼리로 딱 1회씩만 실행한다. Tavily/LLM/다나와 전부 진짜 네트워크 요청.

계측은 관찰 전용(observe-only) - gpt/gemini/deepseek.propose와
price_table.fetch_price_tables를 시간 측정 래퍼로 감싸되, 반환값은 원본
그대로 통과시킨다(동작 변경 없음, funnel-telemetry 때와 같은 원칙).

403/429 감지: fetchers.danawa._fetch_html(다나와 상품 페이지 자체 + bridge
1번째 홉에서 쓰는 함수)을 감시한다. resolve_outlink()의 2번째 홉(제휴
리다이렉트 최종 목적지 확인)은 의도적으로 _fetch_html을 쓰지 않으므로
(최종 응답이 403이어도 정상 - STEP 1/검증 A에서 이미 확인된 정상 동작)
감시 대상에서 제외한다 - 여기서 403은 버그가 아니라 설계다.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import debate  # noqa: E402
from app import price_table as price_table_module  # noqa: E402
from app.agents import deepseek, gemini, gpt  # noqa: E402
from fetchers import danawa  # noqa: E402

QUERIES = [
    "햇반 백미 210g 24개",
    "갤럭시 버즈3 프로",
    "로지텍 MX Master 3S",
    "LG 그램 16인치",
    "다이슨 무선청소기",
]

LEAK_KEYWORDS = ("bridge_url", "loadingBridge", "cmpnyc", "prod.danawa.com")

timings: dict[str, float] = {}
blocked = {"hit": False, "status": None, "url": None}


def _wrap_timed(name, fn):
    async def _inner(*args, **kwargs):
        start = time.monotonic()
        try:
            return await fn(*args, **kwargs)
        finally:
            timings[name] = time.monotonic() - start

    return _inner


_orig_fetch_html = danawa._fetch_html


async def _fetch_html_watch(client, url):
    resp, error = await _orig_fetch_html(client, url)
    status = resp.status_code if resp is not None else None
    if status in (403, 429) and not blocked["hit"]:
        blocked["hit"] = True
        blocked["status"] = status
        blocked["url"] = url
    return resp, error


# 관찰 전용 계측 - 반환값은 원본 그대로, 동작 변경 없음.
gpt.propose = _wrap_timed("gpt", gpt.propose)
gemini.propose = _wrap_timed("gemini", gemini.propose)
deepseek.propose = _wrap_timed("deepseek", deepseek.propose)
price_table_module.fetch_price_tables = _wrap_timed("danawa", price_table_module.fetch_price_tables)
danawa._fetch_html = _fetch_html_watch


async def run_one(query: str) -> dict:
    timings.clear()
    start = time.monotonic()
    response = await debate.run_single_debate(query)
    total = time.monotonic() - start

    body = response.model_dump_json()
    leaks = [kw for kw in LEAK_KEYWORDS if kw in body]

    pt = response.price_table
    grades = {"A": 0, "B": 0, "C": 0}
    if pt is not None:
        for o in pt.offers:
            if o.linkable:
                grades["A"] += 1
            elif o.domain is not None:
                grades["B"] += 1
            else:
                grades["C"] += 1

    llm_times = [timings.get(k, 0.0) for k in ("gpt", "gemini", "deepseek")]
    llm_max = max(llm_times) if llm_times else 0.0
    danawa_time = timings.get("danawa", 0.0)

    return {
        "query": query,
        "total_sec": round(total, 2),
        "danawa_sec": round(danawa_time, 2),
        "llm_max_sec": round(llm_max, 2),
        "danawa_finished_before_llm": danawa_time <= llm_max,
        "price_table_present": pt is not None,
        "offer_count": len(pt.offers) if pt else 0,
        "grades": grades,
        "spread": pt.spread if pt else None,
        "price_source": response.decision.price_source,
        "decision_product_name": response.decision.product_name,
        "decision_retailer": response.decision.retailer,
        "decision_price": response.decision.price,
        "danawa_product_name": pt.product_name if pt else None,
        "danawa_cheapest_seller": (min(pt.offers, key=lambda o: o.price_krw).seller if pt and pt.offers else None),
        "danawa_cheapest_price": (min(pt.offers, key=lambda o: o.price_krw).price_krw if pt and pt.offers else None),
        "leaks": leaks,
    }


async def main() -> None:
    results = []
    for i, query in enumerate(QUERIES):
        if i > 0:
            await asyncio.sleep(2)

        print(f"=== [{i + 1}/{len(QUERIES)}] {query} ===", flush=True)
        try:
            r = await run_one(query)
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}", flush=True)
            results.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})
        else:
            results.append(r)
            for k, v in r.items():
                print(f"  {k}: {v}", flush=True)

        if blocked["hit"]:
            print(f"\n!!! 403/429 감지 (status={blocked['status']}, url={blocked['url']}) - 즉시 중단 !!!", flush=True)
            break
        print(flush=True)

    print("=" * 70)
    print("요약")
    print("=" * 70)
    for r in results:
        print(r)


if __name__ == "__main__":
    asyncio.run(main())
