import sqlite3
import time

from app import search_cache
from app.schemas import SearchResult

RESULT = [SearchResult(title="상품", url="https://coupang.com/vp/products/1", snippet="설명")]


def _backdate(db_path, query_key: str, created_at: float) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE search_cache SET created_at = ? WHERE query_key = ?", (created_at, query_key))
    conn.commit()
    conn.close()


def test_cosine_similarity_parallel_orthogonal_opposite():
    assert search_cache._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert search_cache._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert search_cache._cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_find_similar_returns_best_match_above_threshold_and_bumps_hits(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT, embedding=[1.0, 0.0])

    match = search_cache.find_similar([1.0, 0.0])

    assert match is not None
    key, results, score = match
    assert key == "무선 이어폰"
    assert results[0].url == RESULT[0].url
    assert score == 1.0

    conn = sqlite3.connect(tmp_path / "cache.db")
    hits = conn.execute("SELECT hits FROM search_cache WHERE query_key = ?", ("무선 이어폰",)).fetchone()[0]
    assert hits == 1


def test_find_similar_returns_none_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT, embedding=[1.0, 0.0])

    match = search_cache.find_similar([0.0, 1.0])  # 직교 = 완전 무관

    assert match is None


def test_find_similar_excludes_expired_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT, embedding=[1.0, 0.0])
    _backdate(tmp_path / "cache.db", "무선 이어폰", time.time() - search_cache.TTL_SECONDS - 1)

    match = search_cache.find_similar([1.0, 0.0])

    assert match is None


def test_find_similar_skips_rows_without_embedding(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT)  # embedding 없이 저장(레거시 행 시뮬레이션)

    match = search_cache.find_similar([1.0, 0.0])

    assert match is None


def test_find_similar_returns_none_on_empty_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")

    assert search_cache.find_similar([1.0, 0.0]) is None


def test_set_without_embedding_preserves_existing_embedding(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT, embedding=[1.0, 0.0])

    search_cache.set("무선 이어폰", RESULT, embedding=None)  # refresh()가 embedding 없이 호출하는 경우

    match = search_cache.find_similar([1.0, 0.0])
    assert match is not None


def test_set_stores_embedding_on_new_insert(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "DB_PATH", tmp_path / "cache.db")
    search_cache.set("무선 이어폰", RESULT, embedding=[1.0, 0.0])

    conn = sqlite3.connect(tmp_path / "cache.db")
    embedding_json = conn.execute(
        "SELECT embedding FROM search_cache WHERE query_key = ?", ("무선 이어폰",)
    ).fetchone()[0]
    assert embedding_json == "[1.0, 0.0]"


def test_connect_migrates_legacy_schema_without_embedding_column(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE search_cache (
            query_key TEXT PRIMARY KEY,
            results_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            hits INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(search_cache, "DB_PATH", db_path)

    search_cache.get("아무 질의")  # _connect()를 트리거 — 예외 없이 마이그레이션돼야 함

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(search_cache)")}
    assert "embedding" in columns
