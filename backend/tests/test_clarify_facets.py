"""AI 상세검색(2026-08-12) 테스트 - "음료수"처럼 짧고 애매한 검색어를 DeepSeek이
다나와 검색 결과 상품명에 근거해 facet(카테고리/브랜드/용량 등)으로 좁혀나가게
제안하는 기능(원래 Qwen으로 붙였다가 계정 활성화 문제로 DeepSeek로 옮겼다).
네트워크 요청 금지 - 전부 monkeypatch."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.debate import check_clarify_facets, run_danawa_only_debate_stream, run_debate, run_debate_stream
from app.intent import is_non_product_chitchat, needs_clarification
from app.main import app
from app.schemas import ClarifyFacet

client = TestClient(app)


# -- intent.needs_clarification: 짧고 숫자 없는 검색어 휴리스틱 -----------------


def test_needs_clarification_true_for_short_bare_category_word():
    assert needs_clarification("음료수") is True


def test_needs_clarification_true_for_two_word_bare_query():
    assert needs_clarification("과자 선물") is True


def test_needs_clarification_false_for_query_with_digit():
    # "테스트 상품 15" 처럼 숫자가 섞이면 이미 구체적인 스펙 검색으로 본다.
    assert needs_clarification("아이폰 15") is False


def test_needs_clarification_false_for_long_specific_query():
    assert needs_clarification("삼성전자 갤럭시 버즈3 프로 그래파이트") is False


def test_needs_clarification_false_for_bulk_spec_query():
    # 단위/수량이 붙으면 is_bulk_query가 우선이라 clarify로 새지 않는다(기존 동작).
    assert needs_clarification("생수 500ml") is False


def test_needs_clarification_still_true_for_buy_intent_phrase():
    # 기존(2026-08-10 이전) 동작 - "사고싶다"류 문구는 길이/숫자와 무관하게 그대로 유지.
    assert needs_clarification("이거 진짜 사고 싶은데 뭐가 좋을까") is True


# -- intent.is_non_product_chitchat: 인사말/잡담 즉시 감지(속도 개선) -------------


def test_is_non_product_chitchat_true_for_bare_greeting():
    assert is_non_product_chitchat("하이") is True
    assert is_non_product_chitchat("안녕하세요") is True
    assert is_non_product_chitchat("Hi") is True
    assert is_non_product_chitchat("ㅋㅋㅋ") is True


def test_is_non_product_chitchat_false_for_real_short_product_query():
    # "테스트 상품"은 기존 테스트 스위트에서 "못 찾은 상품 검색어"로 쓰이는
    # 문구다 - 잡담으로 오탐하면 안 된다(needs_clarification은 여전히 True).
    assert is_non_product_chitchat("테스트 상품") is False
    assert is_non_product_chitchat("음료수") is False
    assert is_non_product_chitchat("아이폰 15") is False


def test_is_non_product_chitchat_false_when_greeting_word_is_substring():
    # 전체 문자열이 인사말과 정확히 일치할 때만 True - 부분 문자열은 오탐하지 않는다.
    assert is_non_product_chitchat("하이마트 에어컨") is False


# -- 회귀: 잡담 입력은 검색/LLM 호출 없이 즉시 실패한다(속도 개선) -----------------


def test_check_clarify_facets_returns_empty_immediately_for_greeting(monkeypatch):
    async def _boom_search(query, limit=3):
        raise AssertionError("잡담 입력인데 search_danawa가 호출됐다")

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _boom_search)

    async def _boom_facets(query, names):
        raise AssertionError("잡담 입력인데 extract_facets_from_names가 호출됐다")

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _boom_facets)

    result = asyncio.run(check_clarify_facets("하이"))

    assert result.options.facets == []


def test_run_debate_stream_fails_fast_for_greeting_without_any_search_or_llm_call(monkeypatch):
    async def _boom_search(query, max_results=12):
        raise AssertionError("잡담 입력인데 search가 호출됐다")

    monkeypatch.setattr("app.search.search", _boom_search)
    monkeypatch.setattr("app.debate._any_llm_key_configured", lambda: True)

    async def _collect():
        return [event async for event in run_debate_stream("안녕하세요")]

    events = asyncio.run(_collect())

    assert events == [{"type": "error", "message": "적절한 상품 후보를 찾지 못했습니다."}]


def test_run_debate_raises_immediately_for_greeting(monkeypatch):
    async def _boom_search(query, max_results=12):
        raise AssertionError("잡담 입력인데 search가 호출됐다")

    monkeypatch.setattr("app.search.search", _boom_search)
    monkeypatch.setattr("app.debate._any_llm_key_configured", lambda: True)

    try:
        asyncio.run(run_debate("하이"))
        raise AssertionError("RuntimeError가 발생해야 한다")
    except RuntimeError as exc:
        assert str(exc) == "적절한 상품 후보를 찾지 못했습니다."


# -- app.agents.deepseek.extract_facets_from_names ---------------------------


def test_extract_facets_from_names_parses_deepseek_json_response(monkeypatch):
    from app.agents import deepseek

    class _FakeMessage:
        content = '{"facets": {"카테고리": ["탄산음료", "주스", "생수"], "용량": ["500ml", "1.5L"]}}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    facets = asyncio.run(deepseek.extract_facets_from_names("음료수", ["코카콜라 350ml", "칠성사이다 190ml"]))

    assert len(facets) == 2
    labels = {f.label for f in facets}
    assert labels == {"카테고리", "용량"}


def test_extract_facets_from_names_sorts_brand_options_by_popularity(monkeypatch):
    """사용자 요청(2026-08-12: "브랜드도 인기순으로 정렬") - LLM이 알려준 순서를
    그대로 믿지 않고, 실제 상품명에 몇 번 등장하는지로 다시 정렬해야 한다."""
    from app.agents import deepseek

    class _FakeMessage:
        # LLM은 "매일유업"을 먼저 말했지만, 실제 상품명에는 "롯데칠성음료"가 더 많이 등장한다.
        content = '{"facets": {"브랜드": ["매일유업", "롯데칠성음료"]}}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    names = [
        "롯데칠성음료 칠성사이다 190ml",
        "롯데칠성음료 펩시 500ml",
        "롯데칠성음료 밀키스 250ml",
        "매일유업 초코우유 200ml",
    ]
    facets = asyncio.run(deepseek.extract_facets_from_names("음료수", names))

    assert len(facets) == 1
    assert facets[0].options == ["롯데칠성음료", "매일유업"]


def test_extract_facets_from_names_allows_more_brand_options_than_other_facets(monkeypatch):
    """사용자 요청(2026-08-12: "브랜드가 2,3개 정도만 뜨는데 ... 찾기 기능도
    있었으면") - 브랜드/제조사 기준은 다른 기준(상한 6개)보다 훨씬 넓게(15개까지) 보여준다."""
    from app.agents import deepseek

    many_brands = [f"브랜드{i}" for i in range(20)]
    many_volumes = [f"{i}00ml" for i in range(20)]

    class _FakeMessage:
        content = f'{{"facets": {{"브랜드": {many_brands!r}, "용량": {many_volumes!r}}}}}'.replace("'", '"')

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    facets = asyncio.run(deepseek.extract_facets_from_names("음료수", ["상품 1"]))

    by_label = {f.label: f for f in facets}
    assert len(by_label["브랜드"].options) == 15
    assert len(by_label["용량"].options) == 6


def test_extract_facets_from_names_drops_facets_with_only_one_distinct_option(monkeypatch):
    """사용자 요청(2026-08-13: "카테고리에 스마트폰은 있으면 안되고") - 값이
    하나뿐인 기준은 골라도 아무것도 안 좁혀지니 애초에 응답에서 빠져야 한다."""
    from app.agents import deepseek

    class _FakeMessage:
        content = '{"facets": {"카테고리": ["스마트폰"], "브랜드": ["삼성전자", "APPLE"]}}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    facets = asyncio.run(deepseek.extract_facets_from_names("핸드폰", ["삼성전자 갤럭시S25", "APPLE 아이폰17"]))

    labels = {f.label for f in facets}
    assert labels == {"브랜드"}


def test_extract_facets_from_names_strips_purchase_type_terms_from_container_form(monkeypatch):
    """사용자 리포트(2026-08-14: 음료 검색에서 용기형태 선택지로 "업소용"이
    나옴 - 페트/캔이 나와야 정상) - LLM이 구매유형 수식어를 용기형태로 잘못
    묶어 보내도, "업소용" 같은 알려진 비-용기형태 값은 코드에서 걸러내야 한다."""
    from app.agents import deepseek

    class _FakeMessage:
        content = '{"facets": {"용기형태": ["업소용", "페트", "캔"]}}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    names = ["코카콜라 업소용 페트 1.5L", "코카콜라 캔 250ml"]
    facets = asyncio.run(deepseek.extract_facets_from_names("콜라", names))

    assert len(facets) == 1
    assert facets[0].label == "용기형태"
    assert "업소용" not in facets[0].options
    assert set(facets[0].options) == {"페트", "캔"}


def test_extract_facets_from_names_drops_container_form_facet_when_only_purchase_type_terms(monkeypatch):
    """용기형태로 뽑힌 값 전부가 알려진 비-용기형태 값이면(필터 후 1개 이하만
    남으면), 애초에 값이 하나뿐인 기준과 동일하게 그 facet 자체를 버려야 한다."""
    from app.agents import deepseek

    class _FakeMessage:
        content = '{"facets": {"용기형태": ["업소용", "가정용"], "브랜드": ["코카콜라", "펩시"]}}'

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeResponse()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(deepseek, "_client", lambda: _FakeClient())

    facets = asyncio.run(deepseek.extract_facets_from_names("콜라", ["코카콜라 업소용", "펩시 가정용"]))

    labels = {f.label for f in facets}
    assert labels == {"브랜드"}


def test_check_clarify_facets_attaches_facet_crossfilter_symmetrically(monkeypatch):
    """사용자 요청(2026-08-13: "삼성전자를 누르면은 시리즈에 삼성전자에 관한것만
    APPLE을 누르면 시리즈에 아이폰만" -> 2026-08-14: "시리즈에 초코파이 바나나를
    골랐다면 용량에 없는것들은 선택할수 없게" - 브랜드 전용이었던 걸 모든 facet
    쌍으로 일반화했다) - 검색을 다시 하지 않고, 이미 받아온 상품명만으로 옵션을
    다른 facet 값별로 미리 나눠서 응답에 실어줘야 한다. 양방향(브랜드->시리즈,
    시리즈->브랜드)으로 다 계산돼야 한다."""

    async def _fake_search_danawa(query, limit=3):
        return [
            {"pcode": "1", "product_name": "삼성전자 갤럭시S25 256GB", "total_mall_count": None},
            {"pcode": "2", "product_name": "삼성전자 갤럭시Z 폴드8 512GB", "total_mall_count": None},
            {"pcode": "3", "product_name": "APPLE 아이폰17 256GB", "total_mall_count": None},
            {"pcode": "4", "product_name": "APPLE 아이폰17 프로 512GB", "total_mall_count": None},
        ]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        return [
            ClarifyFacet(label="브랜드", options=["삼성전자", "APPLE"]),
            ClarifyFacet(label="시리즈", options=["갤럭시S25", "갤럭시Z 폴드8", "아이폰17", "아이폰17 프로"]),
        ]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("핸드폰"))

    by_label = {f.label: f for f in result.options.facets}
    assert by_label["브랜드"].options_by_selection == {
        "갤럭시S25": ["삼성전자"],
        "갤럭시Z 폴드8": ["삼성전자"],
        "아이폰17": ["APPLE"],
        "아이폰17 프로": ["APPLE"],
    }
    assert by_label["시리즈"].options_by_selection == {
        "삼성전자": ["갤럭시S25", "갤럭시Z 폴드8"],
        "APPLE": ["아이폰17", "아이폰17 프로"],
    }


def test_check_clarify_facets_crossfilter_works_between_non_brand_facets(monkeypatch):
    """사용자 요청(2026-08-14: "내가 만약 시리즈에 초코파이 바나나를 골랏다면
    용량에 없는것들은 선택할수없게 해야해") - 브랜드가 아니어도(시리즈 -> 용량)
    facet 사이 연관이 계산돼야 한다."""

    async def _fake_search_danawa(query, limit=3):
        return [
            {"pcode": "1", "product_name": "오리온 초코파이 바나나 468g", "total_mall_count": None},
            {"pcode": "2", "product_name": "오리온 초코파이 바나나 234g", "total_mall_count": None},
            {"pcode": "3", "product_name": "오리온 초코파이 오리지널 336g", "total_mall_count": None},
            {"pcode": "4", "product_name": "오리온 초코파이 오리지널 672g", "total_mall_count": None},
        ]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        return [
            ClarifyFacet(label="시리즈", options=["초코파이 바나나", "초코파이 오리지널"]),
            ClarifyFacet(label="용량", options=["468g", "234g", "336g", "672g"]),
        ]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("초코파이"))

    by_label = {f.label: f for f in result.options.facets}
    assert by_label["용량"].options_by_selection == {
        "초코파이 바나나": ["468g", "234g"],
        "초코파이 오리지널": ["336g", "672g"],
    }


def test_check_clarify_facets_orders_facets_from_macro_to_micro(monkeypatch):
    """사용자 요청(2026-08-14: "거시적인 선택에서 미시적인 선택으로 점차
    줄여나가게") - LLM이 낸 순서와 무관하게 카테고리/브랜드 같은 넓은 기준이
    용량/특징 같은 좁은 기준보다 먼저 오도록 정렬해야 한다."""

    async def _fake_search_danawa(query, limit=3):
        return [{"pcode": "1", "product_name": "오리온 초코파이 바나나 468g", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        # 일부러 미시적인 것부터 거꾸로 반환한다 - 정렬이 실제로 라벨 순서를
        # 바꾸는지 확인하려면 원래 순서가 이미 macro->micro면 안 된다.
        return [
            ClarifyFacet(label="특징", options=["저당", "고당"]),
            ClarifyFacet(label="용량", options=["468g", "234g"]),
            ClarifyFacet(label="브랜드", options=["오리온", "롯데"]),
        ]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("초코파이"))

    assert [f.label for f in result.options.facets] == ["브랜드", "용량", "특징"]


def test_extract_facets_from_names_returns_empty_on_no_product_names():
    from app.agents import deepseek

    facets = asyncio.run(deepseek.extract_facets_from_names("음료수", []))
    assert facets == []


def test_extract_facets_from_names_swallows_client_errors(monkeypatch):
    from app.agents import deepseek

    class _BoomClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("API 키 없음")

    monkeypatch.setattr(deepseek, "_client", lambda: _BoomClient())

    facets = asyncio.run(deepseek.extract_facets_from_names("음료수", ["코카콜라 350ml"]))
    assert facets == []


# -- app.debate.check_clarify_facets ------------------------------------------


def test_check_clarify_facets_skips_search_for_specific_query(monkeypatch):
    """구체적인 검색어는 needs_clarification()이 False라 다나와 검색조차 시도하지
    않아야 한다 - search_danawa가 불리면 바로 실패하도록 걸어서 확인한다."""

    async def _boom(query, limit=3):
        raise AssertionError("구체적인 검색어인데 search_danawa가 호출됐다")

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _boom)

    result = asyncio.run(check_clarify_facets("아이폰 15 프로 256기가"))

    assert result.options.facets == []


def test_check_clarify_facets_returns_facets_for_ambiguous_query(monkeypatch):
    async def _fake_search_danawa(query, limit=3):
        return [
            {"pcode": "1", "product_name": "코카콜라 350ml 24개", "total_mall_count": None},
            {"pcode": "2", "product_name": "칠성사이다 190ml", "total_mall_count": None},
        ]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        assert names == ["코카콜라 350ml 24개", "칠성사이다 190ml"]
        return [ClarifyFacet(label="카테고리", options=["탄산음료"])]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("음료수"))

    assert result.mode == "clarify"
    assert result.options.facets == [ClarifyFacet(label="카테고리", options=["탄산음료"])]


def test_check_clarify_facets_uses_wider_search_limit_than_the_fast_path(monkeypatch):
    """사용자 요청(2026-08-12: "브랜드가 2,3개 정도만 뜨는데") 회귀 테스트 -
    DANAWA_ONLY_SEARCH_LIMIT(3)를 그대로 쓰면 상품명 표본이 3개뿐이라 브랜드가
    3개를 넘을 수 없었다. check_clarify_facets는 별도로 늘린
    price_table.CLARIFY_SEARCH_LIMIT을 써야 한다."""
    from app import price_table as price_table_module

    seen_limits: list[int] = []

    async def _fake_search_danawa(query, limit=3):
        seen_limits.append(limit)
        return []

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    asyncio.run(check_clarify_facets("음료수"))

    assert seen_limits == [price_table_module.CLARIFY_SEARCH_LIMIT]
    assert price_table_module.CLARIFY_SEARCH_LIMIT > price_table_module.DANAWA_ONLY_SEARCH_LIMIT


def test_check_clarify_facets_searches_base_query_instead_of_query(monkeypatch):
    """속도 개선(2026-08-13: "조금 더 빠르게") - base_query가 오면 그걸로
    검색해야 한다(캐시 재사용/Crawl-delay 회피가 목적) - query 그대로 검색하면
    드릴다운마다 매번 새 검색어라 캐시가 안 맞는다."""
    seen_queries: list[str] = []

    async def _fake_search_danawa(query, limit=3):
        seen_queries.append(query)
        return [
            {"pcode": "1", "product_name": "삼성전자 갤럭시S25 256GB", "total_mall_count": None},
            {"pcode": "2", "product_name": "삼성전자 갤럭시Z 폴드8 512GB", "total_mall_count": None},
            {"pcode": "3", "product_name": "삼성전자 갤럭시A57 128GB", "total_mall_count": None},
            {"pcode": "4", "product_name": "APPLE 아이폰17 256GB", "total_mall_count": None},
            {"pcode": "5", "product_name": "APPLE 아이폰17 프로 512GB", "total_mall_count": None},
        ]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        return [ClarifyFacet(label="시리즈", options=names)]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("핸드폰 삼성전자", base_query="핸드폰"))

    assert seen_queries == ["핸드폰"]
    # base_query("핸드폰")의 넓은 표본에서 query("핸드폰 삼성전자")의 추가 단어
    # "삼성전자"로 로컬 필터링해야 하므로, APPLE 상품은 빠져야 한다(3개 남아
    # MIN_FILTERED_CLARIFY_ITEMS 이상이라 필터링이 그대로 적용된다).
    assert result.options.facets[0].options == [
        "삼성전자 갤럭시S25 256GB",
        "삼성전자 갤럭시Z 폴드8 512GB",
        "삼성전자 갤럭시A57 128GB",
    ]


def test_check_clarify_facets_enriches_minority_brand_series_via_per_brand_extraction(monkeypatch):
    """회귀 테스트(2026-08-13: "APLLE 을 선택했을때 시리즈 후보가 너무 적어") -
    한 번에 뽑으면 다수 브랜드(삼성전자)가 MAX_OPTIONS_PER_FACET 예산을 다 차지해
    소수 브랜드(APPLE) 시리즈가 아예 안 나올 수 있다. 브랜드별로 다시 뽑아서
    합쳐야 APPLE 시리즈도 온전히 나온다."""
    items = [
        {"pcode": "1", "product_name": "삼성전자 갤럭시S26 256GB", "total_mall_count": None},
        {"pcode": "2", "product_name": "삼성전자 갤럭시Z 폴드8 512GB", "total_mall_count": None},
        {"pcode": "3", "product_name": "APPLE 아이폰17 256GB", "total_mall_count": None},
    ]

    async def _fake_search_danawa(query, limit=3):
        return items

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names, required_labels=None):
        # 이 가짜 LLM은 "삼성전자 상품명만 들어오면" 삼성 시리즈만 뽑고(원래
        # 문제 상황 재현), 브랜드별로 좁혀 다시 부른 호출(required_labels가 옴)은
        # 그 안에 있는 브랜드만 반영한다 - 실제 DeepSeek이 브랜드가 섞인 채로
        # 부르면 다수 브랜드가 예산을 다 차지하는 상황을 흉내낸다.
        has_apple = any("apple" in n.lower() for n in names)
        has_samsung = any("삼성전자" in n for n in names)
        if required_labels:
            # 브랜드별 재추출 - required_labels(그대로 재사용해야 하는 라벨)를 지킨다.
            if has_apple and not has_samsung:
                return [ClarifyFacet(label=required_labels[0], options=["아이폰17"])]
            if has_samsung:
                return [ClarifyFacet(label=required_labels[0], options=["갤럭시S26", "갤럭시Z 폴드8"])]
            return []
        facets = [ClarifyFacet(label="브랜드", options=["삼성전자", "APPLE"])]
        if has_samsung:
            facets.append(ClarifyFacet(label="시리즈", options=["갤럭시S26", "갤럭시Z 폴드8"]))
        return facets

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("핸드폰"))

    by_label = {f.label: f for f in result.options.facets}
    # 원래 결합 호출(전체 상품명, 삼성 우세)로는 "아이폰17"이 안 나왔어야 하지만,
    # APPLE 전용 재추출 덕분에 병합돼 있어야 한다.
    assert "아이폰17" in by_label["시리즈"].options
    assert by_label["시리즈"].options_by_selection is not None
    assert by_label["시리즈"].options_by_selection["APPLE"] == ["아이폰17"]


def test_check_clarify_facets_falls_back_to_unfiltered_when_too_few_matches(monkeypatch):
    """필터링 결과가 너무 적으면(MIN_FILTERED_CLARIFY_ITEMS 미만) 필터링을
    포기하고 base_query의 넓은 표본을 그대로 쓴다 - 추가 검색은 하지 않는다."""

    async def _fake_search_danawa(query, limit=3):
        return [{"pcode": "1", "product_name": "삼성전자 갤럭시S25 256GB", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        return [ClarifyFacet(label="시리즈", options=names)]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    result = asyncio.run(check_clarify_facets("핸드폰 없는브랜드", base_query="핸드폰"))

    # "없는브랜드"로 필터링하면 0개가 남아 MIN_FILTERED_CLARIFY_ITEMS(3) 미만이라
    # 필터링 전 표본(1개)을 그대로 써야 한다 - 빈 리스트가 되면 안 된다.
    assert result.options.facets[0].options == ["삼성전자 갤럭시S25 256GB"]


def test_check_clarify_facets_returns_empty_when_deepseek_finds_nothing(monkeypatch):
    async def _fake_search_danawa(query, limit=3):
        return [{"pcode": "1", "product_name": "테스트 상품", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)
    monkeypatch.setattr(
        "app.agents.deepseek.extract_facets_from_names", lambda query, names: asyncio.sleep(0, result=[])
    )

    result = asyncio.run(check_clarify_facets("테스트 상품"))

    assert result.options.facets == []


# -- POST /decide/clarify 엔드포인트 -------------------------------------------


def test_decide_clarify_endpoint_returns_clarify_response(monkeypatch):
    async def _fake_search_danawa(query, limit=3):
        return [{"pcode": "1", "product_name": "코카콜라 350ml", "total_mall_count": None}]

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _fake_search_danawa)

    async def _fake_extract_facets(query, names):
        return [ClarifyFacet(label="카테고리", options=["탄산음료", "주스"])]

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _fake_extract_facets)

    resp = client.post("/decide/clarify", json={"query": "음료수"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "clarify"
    assert data["options"]["facets"] == [
        {"label": "카테고리", "options": ["탄산음료", "주스"], "options_by_selection": None}
    ]


def test_decide_clarify_endpoint_empty_for_specific_query():
    resp = client.post("/decide/clarify", json={"query": "삼성전자 갤럭시 버즈3 프로"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["options"]["facets"] == []


# -- 회귀: run_danawa_only_debate*는 짧은 검색어에도 여전히 LLM을 절대 안 부른다 ----


def test_run_danawa_only_debate_stream_never_calls_deepseek_facets_even_for_short_query(monkeypatch):
    """check_clarify_facets()는 완전히 별도 진입점이고, run_danawa_only_debate_stream()
    자체는 needs_clarification()을 아예 모른다 - "음료수" 같은 짧은 검색어를 이
    경로로 직접 태워도 extract_facets_from_names가 호출되면 안 된다(LLM 호출 0번
    불변식 유지 확인 - 이 경로 자체는 deepseek.propose 등 다른 LLM 호출도 원래
    안 하지만, 이 테스트는 새로 추가한 facet 추출 쪽만 특정해서 확인한다)."""

    async def _boom(query, names):
        raise AssertionError("run_danawa_only_debate_stream이 facet 추출을 호출했다 - LLM 0회 불변식 위반")

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _boom)

    async def _search_danawa(query, limit=3):
        return []

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    async def _collect():
        return [event async for event in run_danawa_only_debate_stream("음료수")]

    events = asyncio.run(_collect())

    assert events == [
        {"type": "error", "message": "다나와에서 '음료수'에 대한 가격 정보를 찾지 못했다(검색/실측 모두 실패)."}
    ]


# -- 회귀: run_debate()의 LLM 키 미설정 우선순위 -------------------------------


def test_run_debate_routes_to_danawa_only_when_no_llm_key_even_for_short_query(monkeypatch):
    """2026-08-12에 needs_clarification()을 넓히면서 드러난 순서 버그의 회귀
    테스트 - LLM 키가 하나도 없으면(_any_llm_key_configured False) "테스트 상품"
    처럼 이제 clarify로도 보이는 짧은 검색어라도 run_clarify(facet 추출 호출)로
    새지 않고 그대로 run_danawa_only_debate로 가야 한다. run_clarify는
    _extract_clarify_options를 거쳐 2026-08-16부터 deepseek.extract_facets_from_names를
    부른다(예전엔 gpt.extract_options였음 - facet 통합으로 대상이 바뀜)."""
    monkeypatch.setattr("app.debate._any_llm_key_configured", lambda: False)

    async def _boom_facets(query, product_names, required_labels=None):
        raise AssertionError("LLM 키가 없는데 deepseek.extract_facets_from_names이 호출됐다")

    monkeypatch.setattr("app.agents.deepseek.extract_facets_from_names", _boom_facets)

    async def _search_danawa(query, limit=3):
        return []

    monkeypatch.setattr("fetchers.danawa_search.search_danawa", _search_danawa)

    try:
        asyncio.run(run_debate("테스트 상품"))
    except RuntimeError as exc:
        # 다나와 실측 데이터가 없어 못 찾았다는 정상적인 실패 - run_danawa_only_debate까지
        # 도달했다는 뜻이므로 이 테스트의 목적(run_clarify로 안 샜는지)엔 이걸로 충분하다.
        assert "가격 정보를 찾지 못했다" in str(exc)
