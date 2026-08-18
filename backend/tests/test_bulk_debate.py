"""app.debate.run_bulk_debate 회귀 테스트. 네트워크 요청 금지 - 전부 monkeypatch."""

import asyncio

from app.debate import run_bulk_debate
from app.schemas import BulkProposal, DecideResponse, Decision, Proposal, SearchResult


def _empty_bulk_proposal(agent: str) -> BulkProposal:
    return BulkProposal(agent=agent, options=[])


async def _fake_propose_bulk_empty(agent: str, query, results):
    return _empty_bulk_proposal(agent)


def test_run_bulk_debate_falls_back_to_single_debate_when_no_proposals_found(monkeypatch):
    """회귀 테스트(사용자 리포트, 2026-08-18: OCR로 읽은 지저분한 텍스트가
    숫자+단위를 포함해 대량구매로 잘못 분류됨 -> 옵션을 하나도 못 찾아
    "No successful proposals to organize"라는 안 다듬어진 예외가 그대로
    새어나감) - 제안이 완전히 0개여도 그 자리에서 실패하지 말고 단일상품
    파이프라인으로 폴백해야 한다."""

    async def _fake_search(query, max_results=10):
        return [SearchResult(title="더미", url="https://prod.danawa.com/info/?pcode=1", snippet="더미")]

    monkeypatch.setattr("app.debate.search_module.search", _fake_search)
    monkeypatch.setattr("app.debate.gpt.propose_bulk", lambda query, results: _fake_propose_bulk_empty("gpt", query, results))
    monkeypatch.setattr(
        "app.debate.gemini.propose_bulk", lambda query, results: _fake_propose_bulk_empty("gemini", query, results)
    )
    monkeypatch.setattr(
        "app.debate.deepseek.propose_bulk", lambda query, results: _fake_propose_bulk_empty("deepseek", query, results)
    )

    fallback_result = DecideResponse(
        query="테스트",
        proposals=[
            Proposal(
                agent="gpt",
                product_name="테스트 상품",
                price="1,000원",
                retailer="쿠팡",
                url="https://example.com",
                reasoning="-",
            )
        ],
        decision=Decision(
            product_name="테스트 상품",
            price="1,000원",
            retailer="쿠팡",
            url="https://example.com",
            reasoning="-",
            chosen_agent="gpt",
        ),
    )

    async def _fake_run_single_debate(query, skip_clarify=False):
        return fallback_result

    monkeypatch.setattr("app.debate.run_single_debate", _fake_run_single_debate)

    result = asyncio.run(run_bulk_debate("테스트 상품 250ml"))

    assert result is fallback_result


def test_run_bulk_debate_falls_back_to_danawa_direct_search_when_tavily_empty(monkeypatch):
    """회귀 테스트(사용자 리포트, 2026-08-18: "다나와에 검색하면 나오는데 뭐가
    문제인거야?" - Tavily(danawa.com 한정 검색)가 실제로 다나와에 있는 상품을
    못 찾는 경우가 있었다) - Tavily 결과가 비면 다나와 직접 검색으로 한 번 더
    채워서 propose_bulk에 넘겨야 한다."""

    async def _empty_search(query, max_results=10):
        return []

    async def _fake_danawa_items(query, limit=5):
        return [
            {"pcode": "123", "product_name": "코카콜라 350ml", "total_mall_count": 10},
            {"pcode": "456", "product_name": "펩시 350ml", "total_mall_count": 5},
        ]

    monkeypatch.setattr("app.debate.search_module.search", _empty_search)
    monkeypatch.setattr("app.debate.price_table_module._search_danawa_items", _fake_danawa_items)

    seen_results: list[list[SearchResult]] = []

    async def _fake_propose_bulk_gpt(query, results):
        seen_results.append(results)
        return _empty_bulk_proposal("gpt")

    async def _fake_propose_bulk_gemini(query, results):
        return _empty_bulk_proposal("gemini")

    async def _fake_propose_bulk_deepseek(query, results):
        return _empty_bulk_proposal("deepseek")

    monkeypatch.setattr("app.debate.gpt.propose_bulk", _fake_propose_bulk_gpt)
    monkeypatch.setattr("app.debate.gemini.propose_bulk", _fake_propose_bulk_gemini)
    monkeypatch.setattr("app.debate.deepseek.propose_bulk", _fake_propose_bulk_deepseek)

    async def _fake_run_single_debate(query, skip_clarify=False):
        return DecideResponse(
            query=query,
            proposals=[],
            decision=Decision(
                product_name="-", price="-", retailer="-", url="https://example.com", reasoning="-", chosen_agent="gpt"
            ),
        )

    monkeypatch.setattr("app.debate.run_single_debate", _fake_run_single_debate)

    asyncio.run(run_bulk_debate("음료수 350ml"))

    assert len(seen_results) == 1
    urls = {r.url for r in seen_results[0]}
    assert "https://prod.danawa.com/info/?pcode=123" in urls
    assert "https://prod.danawa.com/info/?pcode=456" in urls
