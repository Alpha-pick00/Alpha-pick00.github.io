import httpx
import pytest

from app.ocr import google_vision

_RealAsyncClient = httpx.AsyncClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def factory(**kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(google_vision.httpx, "AsyncClient", factory)
    monkeypatch.setattr(google_vision.settings, "google_vision_api_key", "test-key")


def test_extract_text_surfaces_top_level_batch_error(monkeypatch):
    """회귀 테스트(2026-08-14, 사용자 리포트: "구글 비전에서는 제대로 읽었었는데
    텍스트를 찾지 못했습니다 라고 뜸") - 요청 전체가 거부되면(사진 용량 초과,
    API 비활성화, 쿼터 초과 등) Vision이 "responses" 배열 없이 최상위에
    {"error": {...}}만 돌려준다. 예전 코드는 이걸 못 보고 빈 텍스트/에러 없음으로
    잘못 처리해 사용자에게 "텍스트를 찾지 못했습니다"라는 오해를 주는 메시지가
    떴다 - 실제로는 API 자체가 실패한 것이었다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "Cloud Vision API has not been used in project 123 before or it is disabled.",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )

    _patch_client(monkeypatch, handler)

    import asyncio

    result = asyncio.run(google_vision.extract_text(b"fake-image-bytes"))

    assert result.text == ""
    assert result.error is not None
    assert "disabled" in result.error


def test_extract_text_surfaces_missing_responses_array(monkeypatch):
    """responses가 아예 없는(빈 딕셔너리 등) 예상 밖 응답도 조용히 "텍스트 없음"
    으로 삼키지 않고 에러로 표시해야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _patch_client(monkeypatch, handler)

    import asyncio

    result = asyncio.run(google_vision.extract_text(b"fake-image-bytes"))

    assert result.text == ""
    assert result.error is not None


def test_extract_text_still_surfaces_per_image_error(monkeypatch):
    """개별 이미지 처리 실패(배치 자체는 성공, 그 이미지만 에러)는 기존처럼
    responses[0].error에서 그대로 잡혀야 한다 - 이번 수정으로 회귀 없어야 함."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"responses": [{"error": {"code": 3, "message": "Bad image data."}}]},
        )

    _patch_client(monkeypatch, handler)

    import asyncio

    result = asyncio.run(google_vision.extract_text(b"fake-image-bytes"))

    assert result.text == ""
    assert result.error == "Bad image data."


def test_extract_text_returns_text_on_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "responses": [
                    {
                        "fullTextAnnotation": {
                            "text": "삼성전자 갤럭시 케이스",
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "paragraphs": [
                                                {"words": [{"confidence": 0.9}, {"confidence": 0.8}]}
                                            ]
                                        }
                                    ]
                                }
                            ],
                        }
                    }
                ]
            },
        )

    _patch_client(monkeypatch, handler)

    import asyncio

    result = asyncio.run(google_vision.extract_text(b"fake-image-bytes"))

    assert result.text == "삼성전자 갤럭시 케이스"
    assert result.error is None
    assert result.block_count == 1
    assert result.confidence == pytest.approx(0.85)
