"""인기 질의 우선 갱신 — 2단계.

검색 트래픽은 실제로는 소수의 질의에 몰리는 경향이 있다(Zipf 법칙). 그 소수만
TTL(search_cache.TTL_SECONDS, 6시간)을 기다리지 않고 주기적으로 미리 갱신해
항상 신선하게 유지하고, 나머지 롱테일 질의는 지금처럼 요청이 들어올 때 TTL
기준으로 갱신되도록 그대로 둔다 — 캐시 전체를 등분으로 갱신하는 대신, 자주
찾는 질의에만 자원을 집중한다.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import search as search_module
from . import search_cache

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MINUTES = 60
TOP_N = 20
MIN_HITS = 2  # 한 번만 검색된 질의까지 갱신 대상에 넣지 않는다 — 우연한 1회성 질의 낭비 방지
REQUEST_SPACING_SECONDS = 1  # Tavily에 한꺼번에 몰아치지 않도록 호출 사이 간격을 둔다

_scheduler: AsyncIOScheduler | None = None


async def _refresh_popular_queries() -> None:
    queries = search_cache.top_queries(limit=TOP_N, min_hits=MIN_HITS)
    if not queries:
        return
    logger.info("인기 질의 갱신 대상 %d건: %s", len(queries), queries)
    for query in queries:
        try:
            await search_module.refresh(query)
        except Exception:
            logger.exception("인기 질의 갱신 실패: %r", query)
        await asyncio.sleep(REQUEST_SPACING_SECONDS)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _refresh_popular_queries,
        "interval",
        minutes=REFRESH_INTERVAL_MINUTES,
        id="refresh_popular_queries",
    )
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
