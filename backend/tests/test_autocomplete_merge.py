"""app.autocomplete.suggest_merged (로컬 SQLite 인덱스 + 다나와 실시간 자동완성 병합)
테스트. 네트워크 호출은 fetchers.danawa_autocomplete.autocomplete_danawa를
monkeypatch로 막는다 - 실제 요청이 나가면 conftest의 소켓 차단 fixture가 잡는다."""

from __future__ import annotations

import asyncio

from app import autocomplete


def _patch(monkeypatch, local: list[str], danawa: list[str]):
    monkeypatch.setattr(autocomplete, "suggest", lambda prefix, limit=8: local)

    async def _fake_danawa(prefix, limit=8):
        return danawa

    monkeypatch.setattr(autocomplete, "autocomplete_danawa", _fake_danawa)


def test_suggest_merged_appends_danawa_only_terms_after_local(monkeypatch):
    _patch(monkeypatch, local=["로컬상품1", "로컬상품2"], danawa=["다나와전용상품", "로컬상품1"])

    result = asyncio.run(autocomplete.suggest_merged("아무거나"))

    # 로컬 인덱스가 먼저, 로컬에 없던 다나와 제안(다나와전용상품)만 뒤에 덧붙는다.
    # 로컬에 이미 있던 "로컬상품1"은 다나와 쪽에도 있어도 중복으로 다시 넣지 않는다.
    assert result == ["로컬상품1", "로컬상품2", "다나와전용상품"]


def test_suggest_merged_dedupes_case_insensitively(monkeypatch):
    _patch(monkeypatch, local=["SSD"], danawa=["ssd", "외장하드"])

    result = asyncio.run(autocomplete.suggest_merged("아무거나2"))

    assert result == ["SSD", "외장하드"]


def test_suggest_merged_respects_limit(monkeypatch):
    _patch(monkeypatch, local=["로컬A", "로컬B"], danawa=["다나와A", "다나와B", "다나와C"])

    result = asyncio.run(autocomplete.suggest_merged("아무거나3", limit=3))

    assert result == ["로컬A", "로컬B", "다나와A"]


def test_suggest_merged_falls_back_to_local_when_danawa_empty(monkeypatch):
    # autocomplete_danawa는 실패 시 항상 빈 리스트를 반환하는 계약(fetchers 쪽에서
    # 이미 보장) - 여기서는 그 빈 리스트가 들어왔을 때 로컬 결과만으로 정상
    # 동작하는지만 확인한다.
    _patch(monkeypatch, local=["로컬만있음"], danawa=[])

    result = asyncio.run(autocomplete.suggest_merged("아무거나4"))

    assert result == ["로컬만있음"]


def test_suggest_merged_returns_empty_for_blank_prefix(monkeypatch):
    _patch(monkeypatch, local=["안뜨면안됨"], danawa=["역시안뜨면안됨"])

    assert asyncio.run(autocomplete.suggest_merged("   ")) == []
