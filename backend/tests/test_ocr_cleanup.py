import asyncio

from app.ocr import cleanup


def _fake_response(content: str):
    class _Message:
        pass

    message = _Message()
    message.content = content

    class _Choice:
        pass

    choice = _Choice()
    choice.message = message

    class _Response:
        choices = [choice]

    return _Response()


def test_clean_returns_result_on_first_success(monkeypatch):
    call_count = 0

    class _FakeCompletions:
        async def create(self, **kwargs):
            nonlocal call_count
            call_count += 1
            return _fake_response('{"cleaned_text": "코카콜라 350ml", "search_query": "코카콜라 350ml", "notes": ""}')

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(cleanup, "AsyncOpenAI", lambda **kwargs: _FakeClient())

    result = asyncio.run(cleanup.clean("코카콜라\n350ml\n탄산음료"))

    assert result.search_query == "코카콜라 350ml"
    assert result.error is None
    assert call_count == 1


def test_clean_retries_once_then_succeeds(monkeypatch):
    """일시적 오류(rate limit 등)는 재시도하면 성공할 수 있다(사용자 리포트,
    2026-08-14: "정제를 안하고 모든 텍스트를 다 보내는 경우") - 첫 시도가
    실패해도 바로 원본으로 폴백하지 말고 한 번 더 시도해야 한다."""
    call_count = 0

    class _FakeCompletions:
        async def create(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("rate limited")
            return _fake_response('{"cleaned_text": "펩시 250ml", "search_query": "펩시 250ml", "notes": ""}')

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(cleanup, "AsyncOpenAI", lambda **kwargs: _FakeClient())
    monkeypatch.setattr(cleanup, "_RETRY_DELAY_SECONDS", 0)

    result = asyncio.run(cleanup.clean("PEPSI\n250 ml\n나트륨 7mg 0%"))

    assert result.search_query == "펩시 250ml"
    assert result.error is None
    assert call_count == 2


def test_clean_falls_back_to_local_cleanup_after_repeated_failure(monkeypatch):
    """재시도까지 다 실패하면, 정제 안 된 원본을 통째로 넘기는 대신 코드 레벨
    노이즈 필터(영양정보/바코드 등 제거)를 거친 텍스트를 cleaned_text로
    돌려줘야 한다 - 프론트의 폴백 체인(search_query -> cleaned_text -> 원본
    ocr.text)이 원본까지 새지 않고 여기서 멈추게 하기 위함."""
    call_count = 0

    class _FakeCompletions:
        async def create(self, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("groq unavailable")

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(cleanup, "AsyncOpenAI", lambda **kwargs: _FakeClient())
    monkeypatch.setattr(cleanup, "_RETRY_DELAY_SECONDS", 0)

    raw = "PEPSI\n250 ml (110 kcal)\n영양정보\n나트륨 7mg 0%\n제조원 판매원 롯데칠성음료"
    result = asyncio.run(cleanup.clean(raw))

    assert call_count == cleanup._MAX_ATTEMPTS
    assert result.error is not None
    assert result.cleaned_text is not None
    assert "PEPSI" in result.cleaned_text
    assert "나트륨" not in result.cleaned_text
    assert "제조원" not in result.cleaned_text


def test_fallback_local_cleanup_filters_noise_lines():
    raw = (
        "솔의눈\nPine bud Drink\n스위스산솔싹추출액\n240 ml (75 kcal)\n"
        "솔잎추출농축액 0.126 %\n제조원 롯데칠성음료\n12345678901234"
    )

    cleaned = cleanup._fallback_local_cleanup(raw)

    assert "솔의눈" in cleaned
    assert "Pine bud Drink" in cleaned
    assert "제조원" not in cleaned
    assert "12345678901234" not in cleaned


def test_fallback_local_cleanup_never_returns_empty_for_nonblank_input():
    """전부 노이즈로 보이는 극단적인 경우에도 빈 문자열을 반환하면 안 된다 -
    검색어가 아예 없어지는 것보다는 원본 앞부분이라도 남기는 게 낫다."""
    raw = "1234567890\n80.0%\nkcal"

    cleaned = cleanup._fallback_local_cleanup(raw)

    assert cleaned.strip() != ""
