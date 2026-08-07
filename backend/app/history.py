"""로그인 계정별 검색 기록.

비로그인 사용자는 프론트엔드가 localStorage에 기록을 저장하지만(기기별),
로그인한 사용자는 계정(provider + provider_user_id)에 묶어 서버에 저장해
어느 기기/브라우저에서 로그인해도 같은 기록을 본다.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .schemas import DecideResultUnion, HistoryEntry, User

DB_PATH = Path(__file__).resolve().parent / "data" / "history.db"

MAX_ENTRIES_PER_USER = 50


def _user_key(user: User) -> str:
    return f"{user.provider}:{user.provider_user_id}"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            user_key TEXT NOT NULL,
            query TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_user ON history (user_key, created_at DESC)"
    )
    return conn


def add_entry(user: User, query: str, result: DecideResultUnion) -> HistoryEntry:
    entry = HistoryEntry(
        id=str(uuid.uuid4()),
        query=query,
        timestamp=time.time(),
        result=result,
    )
    user_key = _user_key(user)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO history (id, user_key, query, result_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (entry.id, user_key, entry.query, entry.result.model_dump_json(), entry.timestamp),
        )
        # 사용자당 최근 N개만 유지 — 오래된 기록은 저장 공간을 위해 정리한다.
        conn.execute(
            """
            DELETE FROM history
            WHERE user_key = ? AND id NOT IN (
                SELECT id FROM history WHERE user_key = ?
                ORDER BY created_at DESC LIMIT ?
            )
            """,
            (user_key, user_key, MAX_ENTRIES_PER_USER),
        )
        conn.commit()
    finally:
        conn.close()
    return entry


def list_entries(user: User) -> list[HistoryEntry]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, query, result_json, created_at FROM history WHERE user_key = ? ORDER BY created_at DESC",
            (_user_key(user),),
        ).fetchall()
    finally:
        conn.close()
    return [
        HistoryEntry(id=row[0], query=row[1], result=json.loads(row[2]), timestamp=row[3])
        for row in rows
    ]


def delete_entry(user: User, entry_id: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM history WHERE id = ? AND user_key = ?", (entry_id, _user_key(user))
        )
        conn.commit()
    finally:
        conn.close()


def clear_entries(user: User) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM history WHERE user_key = ?", (_user_key(user),))
        conn.commit()
    finally:
        conn.close()
