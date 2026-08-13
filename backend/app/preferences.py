"""로그인 계정별 영구 페르소나(선호 facet 값) 저장.

카테고리마다 의미 있는 메타데이터(facet)가 다르다는 문제는 AI 상세검색
(check_clarify_facets)이 검색 결과에서 즉석에 뽑아내는 것으로 이미 해결한다.
이 모듈은 그 위에서 "이 사용자가 같은 facet 라벨에서 반복해서 어떤 값을
고르는가"를 계정에 누적해, 다음 검색에서도 그 값을 먼저 보여주는(하드 필터가
아니라 순서만 당기는 소프트 반영) 용도다 — history.py와 같은 SQLite 패턴을
그대로 따른다(사용자 키 = provider:provider_user_id).

세션 내(로그인 여부와 무관한) 선호도는 이 모듈이 아니라 프론트 SearchContext가
메모리에서만 들고 있다가 요청마다 함께 보낸다 — 짧은 세션 하나 때문에 영구
기록을 남길 이유가 없고, 그 세션 값은 request body(session_preferences)로
이미 매 요청에 실려온다."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .schemas import User

DB_PATH = Path(__file__).resolve().parent / "data" / "preferences.db"

# 계정당 라벨 하나에 너무 많은 값이 쌓여 상위 조회가 느려지는 걸 막는다 - 오래
# 안 고른 값부터 정리한다. 실사용에서 사용자 한 명이 같은 라벨로 이만큼 다른
# 값을 고를 일은 드물다.
MAX_VALUES_PER_LABEL = 20


def _user_key(user: User) -> str:
    return f"{user.provider}:{user.provider_user_id}"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            user_key TEXT NOT NULL,
            label TEXT NOT NULL,
            value TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_key, label, value)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preferences_user_label ON preferences (user_key, label, count DESC)"
    )
    return conn


def record(user: User, label: str, value: str) -> None:
    """facet(또는 브랜드/고정 축) 하나를 골랐을 때 호출 — 이미 있으면 count만
    올리고, 없으면 새로 만든다. 실패해도(예: DB 잠금) 검색 흐름을 막으면 안
    되므로 호출부가 실패를 조용히 삼키는 걸 전제로 예외를 그대로 던진다."""
    label = label.strip()
    value = value.strip()
    if not label or not value:
        return
    user_key = _user_key(user)
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO preferences (user_key, label, value, count, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_key, label, value)
            DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
            """,
            (user_key, label, value, now),
        )
        conn.execute(
            """
            DELETE FROM preferences
            WHERE user_key = ? AND label = ? AND value NOT IN (
                SELECT value FROM preferences
                WHERE user_key = ? AND label = ?
                ORDER BY count DESC, updated_at DESC LIMIT ?
            )
            """,
            (user_key, label, user_key, label, MAX_VALUES_PER_LABEL),
        )
        conn.commit()
    finally:
        conn.close()


def get_top_preferences(user: User) -> dict[str, str]:
    """라벨별로 가장 많이 고른 값 하나씩만 골라 {label: value} 맵으로 반환한다 -
    facet 옵션 정렬에 그대로 쓰기 좋은 형태. 아무 기록이 없으면 빈 dict."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT label, value FROM preferences p1
            WHERE user_key = ? AND count = (
                SELECT MAX(count) FROM preferences p2
                WHERE p2.user_key = p1.user_key AND p2.label = p1.label
            )
            GROUP BY label
            """,
            (_user_key(user),),
        ).fetchall()
    finally:
        conn.close()
    return {row[0]: row[1] for row in rows}
