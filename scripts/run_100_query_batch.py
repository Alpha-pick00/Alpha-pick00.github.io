"""PART 2 실행 - queries_100.json의 100개 쿼리를 실제 /decide 파이프라인
(run_single_debate)으로 쿼리당 1회씩 돌리고 결과를 JSON으로 캐시한다.
재실행 방지를 위해 매 완료마다 즉시 디스크에 쓴다.

동시성: 상위 레벨에서 asyncio.Semaphore(5)로 쿼리 5개까지만 동시 실행한다.
다나와 자체의 동시성 제한(MAX_CONCURRENCY=3, 도메인당 0.5초 간격)은
fetchers/danawa.py 모듈 전역 세마포어로 이미 강제되고 있어 위 상위
동시성과 무관하게 계속 지켜진다 - 쿼리를 몇 개 동시에 돌리든 다나와
서버로 나가는 실제 동시 요청은 3건을 넘지 않는다.

관찰 전용 계측: search()에서 enuri.com URL을 봤으면 기록만 하고 페치하지
않는다(PART 3용). fetch_price_tables()가 반환한 원본 DanawaResult에서
CMPNYC_MAP에 없는 cmpnyc 코드를 보면 기록만 하고 절대 추가로 페치하지
않는다(뚫어보지 말라는 지시).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import debate  # noqa: E402
from app import price_table as price_table_module  # noqa: E402
from app import search as search_module  # noqa: E402
from app.agents import judge  # noqa: E402
from fetchers.danawa_mall_map import CMPNYC_MAP  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
QUERIES_PATH = SCRIPT_DIR / "queries_100.json"
RESULTS_PATH = SCRIPT_DIR / "results_100.json"
SIDE_DATA_PATH = SCRIPT_DIR / "results_100_side_data.json"

CONCURRENCY = 5

enuri_urls_seen: set[str] = set()
unknown_cmpnyc_seen: set[str] = set()
# query -> judge.decide()가 방금 반환한, danawa 보정이 아직 닿지 않은 원본
# decision + 3개 에이전트 proposals 스냅샷. enrich_decision()이 decision을
# in-place로 덮어써서 "보정 전 가격"이 응답에 안 남으므로, 여기서 따로
# 기록해야 "가격 변동 방향"을 계산할 수 있다.
pre_enrichment_snapshot: dict[str, dict] = {}

_orig_search = search_module.search
_orig_fetch_price_tables = price_table_module.fetch_price_tables
_orig_judge_decide = judge.decide


async def _search_watch(query, max_results=12):
    results = await _orig_search(query, max_results=max_results)
    for r in results:
        host = urlsplit(r.url).netloc.lower()
        if host == "enuri.com" or host.endswith(".enuri.com"):
            enuri_urls_seen.add(r.url)
    return results


async def _fetch_price_tables_watch(results):
    tables = await _orig_fetch_price_tables(results)
    for _table, raw in tables:
        for offer in raw["offers"]:
            bridge_url = offer.get("bridge_url")
            if not bridge_url:
                continue
            params = dict(parse_qsl(urlsplit(bridge_url).query, keep_blank_values=True))
            cmpnyc = params.get("cmpnyc")
            if cmpnyc and cmpnyc not in CMPNYC_MAP:
                unknown_cmpnyc_seen.add(cmpnyc)
    return tables


async def _judge_decide_watch(query, proposals):
    decision = await _orig_judge_decide(query, proposals)
    pre_enrichment_snapshot[query] = {
        "product_name": decision.product_name,
        "price": decision.price,
        "retailer": decision.retailer,
        "url": decision.url,
        "chosen_agent": decision.chosen_agent,
        "proposals": [p.model_dump() for p in proposals],
    }
    return decision


search_module.search = _search_watch
price_table_module.fetch_price_tables = _fetch_price_tables_watch
judge.decide = _judge_decide_watch


async def run_one(item: dict, sem: asyncio.Semaphore, results: list, lock: asyncio.Lock, idx: int, total: int) -> None:
    async with sem:
        query = item["query"]
        print(f"[{idx}/{total}] start: {query}", flush=True)
        try:
            response = await debate.run_single_debate(query)
        except Exception as exc:
            record = {**item, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[{idx}/{total}] ERROR: {query} -> {record['error']}", flush=True)
        else:
            record = {
                **item,
                "decision": response.decision.model_dump(),
                "price_table": response.price_table.model_dump() if response.price_table else None,
                "llm_original": pre_enrichment_snapshot.pop(query, None),
            }
            print(
                f"[{idx}/{total}] done: {query} -> "
                f"price_source={record['decision']['price_source']} "
                f"price_table={'있음' if record['price_table'] else '없음'}",
                flush=True,
            )

        async with lock:
            results.append(record)
            RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            SIDE_DATA_PATH.write_text(
                json.dumps(
                    {
                        "enuri_urls_seen": sorted(enuri_urls_seen),
                        "unknown_cmpnyc_seen": sorted(unknown_cmpnyc_seen),
                        "completed": len(results),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )


async def main() -> None:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list = []
    lock = asyncio.Lock()

    tasks = [
        run_one(item, sem, results, lock, idx + 1, len(queries)) for idx, item in enumerate(queries)
    ]
    await asyncio.gather(*tasks)

    print("=" * 70)
    print(f"완료: {len(results)}/{len(queries)}")
    print(f"enuri.com URL 관측: {len(enuri_urls_seen)}건")
    for u in sorted(enuri_urls_seen):
        print(f"  {u}")
    print(f"미검증 cmpnyc 신규 관측: {sorted(unknown_cmpnyc_seen)}")


if __name__ == "__main__":
    asyncio.run(main())
