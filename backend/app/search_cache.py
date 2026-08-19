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
import logging
import math
import re
import sqlite3
import time
from pathlib import Path

from .schemas import SearchResult

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "data" / "search_cache.db"

TTL_SECONDS = 6 * 60 * 60  # 6시간 — 가격이 그새 바뀔 순 있지만 매 요청마다 다시 긁을 정도는 아니다
# 12 -> 20(2026-08-19, 사용자 리포트 "10만원대 이어폰 추천해줘 했는데 아무것도
# 안뜨잖아") - "이어폰"처럼 경쟁이 치열한 넓은 카테고리는 다나와 한정 Tavily
# 결과 중 상당수가 "가격비교 중지 상품"(최저가 0원, 실제 구매 불가)이거나
# 카테고리 목록 페이지다(app.search._tavily_search가 이미 후자는 걸러낸다) -
# 12개만 받으면 살아있는(가격 확인 가능한) 상품이 하나도 안 남을 수 있다.
# 실측: 12개 요청 시 필터 후 5개 중 3개가 중지 상품이었는데, 20개 요청하니
# 13개가 남고 그중 9개가 살아있는 상품이었다.
FETCH_SIZE = 20  # search()의 max_results 인자 중 가장 큰 값. 이 크기로 캐시해두고
# 더 적은 max_results를 요청하는 호출(bulk/clarify/brand_price)은 앞에서 잘라 쓴다.

# 짧은 이커머스 질의는 임베딩 모델 특성상 서로 무관한 문장끼리도 0.7~0.8대로
# 몰리는 경향이 있다. 이 캐시는 실제 구매 추천에 쓰이므로, 오판으로 "무선
# 이어폰"에 "무선 청소기" 캐시를 잘못 재사용하면 단순 캐시 미스보다 훨씬 나쁜
# 실패(조용한 오답)가 된다 — recall보다 precision을 우선해 보수적으로 시작하고,
# NEAR_MISS 로그를 보며 점진적으로 낮춘다.
SIMILARITY_THRESHOLD = 0.92
NEAR_MISS_MARGIN = 0.07


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
            hits INTEGER NOT NULL DEFAULT 0,
            embedding TEXT
        )
        """
    )
    try:
        conn.execute("ALTER TABLE search_cache ADD COLUMN embedding TEXT")
    except sqlite3.OperationalError:
        pass  # 이미 embedding 컬럼이 있는 기존 DB
    return conn


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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


def find_similar(embedding: list[float]) -> tuple[str, list[SearchResult], float] | None:
    """완전 일치 미스 후, 의미상 가장 비슷한 캐시 행을 찾는다 — TTL 안 지난
    행 중 SIMILARITY_THRESHOLD 이상 코사인 유사도 최고점만 채택한다(찾으면
    해당 행 hits도 증가). 못 찾으면 None이며, 호출부는 이때 새로 검색해야 한다."""
    cutoff = time.time() - TTL_SECONDS
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT query_key, results_json, embedding FROM search_cache "
            "WHERE embedding IS NOT NULL AND created_at > ?",
            (cutoff,),
        ).fetchall()

        best_key: str | None = None
        best_results_json: str | None = None
        best_score = 0.0
        for query_key, results_json, embedding_json in rows:
            score = _cosine_similarity(embedding, json.loads(embedding_json))
            if score > best_score:
                best_key, best_results_json, best_score = query_key, results_json, score

        if best_key is None:
            return None

        if best_score < SIMILARITY_THRESHOLD:
            if best_score >= SIMILARITY_THRESHOLD - NEAR_MISS_MARGIN:
                logger.info("근접 미스 (score=%.3f, 미채택): %r", best_score, best_key)
            return None

        conn.execute("UPDATE search_cache SET hits = hits + 1 WHERE query_key = ?", (best_key,))
        conn.commit()
        logger.info("의미 기반 캐시 히트 (score=%.3f): %r", best_score, best_key)
    finally:
        conn.close()

    return best_key, [SearchResult(**item) for item in json.loads(best_results_json)], best_score


def top_queries(limit: int, min_hits: int = 1) -> list[str]:
    """hits 기준 상위 질의 목록 — 인기 질의 우선 갱신 스케줄러가 사용.
    set()이 hits를 초기화하지 않으므로, 갱신을 반복해도 인기 순위는 유지된다."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT query_key FROM search_cache WHERE hits >= ? ORDER BY hits DESC LIMIT ?",
            (min_hits, limit),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def set(query: str, results: list[SearchResult], embedding: list[float] | None = None) -> None:
    """빈 결과는 캐시하지 않는다 — 일시적 검색 실패가 TTL 동안 그대로 굳어버리는 것을 막기 위해.
    embedding을 안 넘기면(예: refresh()의 강제 갱신) 기존에 저장돼 있던 embedding을
    COALESCE로 보존한다 — 재검증 때마다 다시 계산할 필요가 없다."""
    if not results:
        return
    key = _normalize(query)
    results_json = json.dumps([r.model_dump() for r in results])
    embedding_json = json.dumps(embedding) if embedding is not None else None
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache (query_key, results_json, created_at, hits, embedding)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(query_key) DO UPDATE SET
                results_json = excluded.results_json,
                created_at = excluded.created_at,
                embedding = COALESCE(excluded.embedding, search_cache.embedding)
            """,
            (key, results_json, time.time(), embedding_json),
        )
        conn.commit()
    finally:
        conn.close()
