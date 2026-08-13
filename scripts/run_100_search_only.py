"""B-4 - PART 2와 동일한 100개 쿼리로 search_danawa()만 단독 실행한다.
LLM 호출 없음, 상세페이지 페치 없음 - 검색 1회씩만. search.danawa.com의
Crawl-delay(10초)를 그대로 지키므로 100건이면 최소 약 17분 걸린다 -
간격을 줄이지 않는다. 403/429(DanawaSearchBlocked)를 만나면 그 즉시
전체 중단하고, 그 시점까지 모은 결과만 저장한다."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fetchers.danawa_search import DanawaSearchBlocked, search_danawa  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
QUERIES_PATH = SCRIPT_DIR / "queries_100.json"
OUTPUT_PATH = SCRIPT_DIR / "results_100_search_only.json"


async def main() -> None:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))

    results: list[dict] = []
    blocked_at: dict | None = None

    for i, q in enumerate(queries):
        query = q["query"]
        started = datetime.now(timezone.utc).isoformat()
        try:
            items = await search_danawa(query, limit=5)
        except DanawaSearchBlocked as exc:
            print(f"\n!!! [{i + 1}/100] BLOCKED (HTTP {exc.status_code}) on query={query!r} - 즉시 전체 중단 !!!", flush=True)
            blocked_at = {"index": i, "query": query, "status_code": exc.status_code}
            break

        record = {
            "index": i,
            "query": query,
            "category": q["category"],
            "pcode_count": len(items),
            "items": items,
            "fetched_at": started,
        }
        results.append(record)
        print(f"[{i + 1}/100] {query!r} ({q['category']}) -> {len(items)}건", flush=True)

        # 매 쿼리마다 즉시 저장 - 중간에 죽어도 그때까지 결과는 남는다.
        OUTPUT_PATH.write_text(
            json.dumps({"results": results, "blocked_at": blocked_at}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    OUTPUT_PATH.write_text(
        json.dumps({"results": results, "blocked_at": blocked_at}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n완료: {len(results)}/100건 처리, blocked_at={blocked_at}")


if __name__ == "__main__":
    asyncio.run(main())
