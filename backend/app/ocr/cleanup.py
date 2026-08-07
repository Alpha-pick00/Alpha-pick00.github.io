from google import genai
from google.genai import types

from ..agents.base import parse_json_object
from ..config import settings
from ..schemas import OcrCleanupResult

CLEANUP_INSTRUCTIONS = (
    "당신은 OCR로 추출한 텍스트를 정리하는 도우미입니다. OCR 특성상 줄바꿈이 뒤섞이거나, "
    "같은 내용이 중복되거나, 순서가 뒤틀려 있을 수 있습니다. "
    "아래 OCR 원본 텍스트를 읽기 쉽게 정리하세요. "
    "이미지를 직접 보는 게 아니므로 원본에 없는 내용을 새로 지어내지 말고, "
    "원본에 있는 내용만 재배열하고 중복을 제거하세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"cleaned_text": "정리된 텍스트", '
    '"notes": "정리하면서 처리한 내용(중복 제거, 줄바꿈 정리 등). 없으면 빈 문자열"}'
)

JSON_CONFIG = types.GenerateContentConfig(response_mime_type="application/json")


async def clean(raw_text: str) -> OcrCleanupResult:
    if not raw_text.strip():
        return OcrCleanupResult(error="정리할 OCR 텍스트가 없습니다.")

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{CLEANUP_INSTRUCTIONS}\n\nOCR 원본 텍스트:\n{raw_text}",
            config=JSON_CONFIG,
        )
        data = parse_json_object(response.text or "")
        return OcrCleanupResult(**data)
    except Exception as exc:
        return OcrCleanupResult(error=str(exc))
