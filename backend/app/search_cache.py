"""검색 결과 캐시 — 같은 질의가 반복되면 Tavily/Merchant를 다시 호출하지 않고
캐시된 결과를 재사용한다.

"전체 카탈로그를 미리 다 긁어두는" 배치 방식이 아니라 "질의가 들어올 때만, 그
질의만" 수집하는 게 이미 이 서비스의 기본 구조다(search()가 사용자 질의 하나당
한 번만 호출됨). 이 모듈은 그 위에 캐시를 얹어 *반복되는* 질의의 API 호출만
줄인다 — 인기 질의를 우선 갱신하는 2단계(Zipf 기반 우선순위)를 위해 hits
카운터도 함께 쌓아둔다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from .schemas import SearchResult

DB_PATH = Path(__file__).resolve().parent / "data" / "search_cache.db"

TTL_SECONDS = 6 * 60 * 60  # 6시간 — 가격이 그새 바뀔 순 있지만 매 요청마다 다시 긁을 정도는 아니다
FETCH_SIZE = 12  # search()의 max_results 인자 중 가장 큰 값. 이 크기로 캐시해두고
# 더 적은 max_results를 요청하는 호출(bulk/clarify/brand_price)은 앞에서 잘라 쓴다.


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_cache (
            query_key TEXT PRIMARY KEY,
            results_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            hits INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def get(query: str) -> list[SearchResult] | None:
    """캐시가 없거나 TTL이 지났으면 None — 호출부는 이때 새로 검색해야 한다."""
    key = _normalize(query)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT results_json, created_at FROM search_cache WHERE query_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        results_json, created_at = row
        if time.time() - created_at > TTL_SECONDS:
            return None
        conn.execute("UPDATE search_cache SET hits = hits + 1 WHERE query_key = ?", (key,))
        conn.commit()
    finally:
        conn.close()
    return [SearchResult(**item) for item in json.loads(results_json)]


def set(query: str, results: list[SearchResult]) -> None:
    """빈 결과는 캐시하지 않는다 — 일시적 검색 실패가 TTL 동안 그대로 굳어버리는 것을 막기 위해."""
    if not results:
        return
    key = _normalize(query)
    results_json = json.dumps([r.model_dump() for r in results])
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache (query_key, results_json, created_at, hits)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(query_key) DO UPDATE SET
                results_json = excluded.results_json,
                created_at = excluded.created_at
            """,
            (key, results_json, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
