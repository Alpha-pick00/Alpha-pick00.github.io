import time

import httpx

from ..config import settings
from ..schemas import OcrResult

_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


async def extract_text(image_bytes: bytes) -> OcrResult:
    if not settings.google_vision_api_key:
        return OcrResult(error="GOOGLE_VISION_API_KEY가 설정되지 않았습니다.")

    import base64

    body = {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode()},
                "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
                "imageContext": {"languageHints": ["ko", "en"]},
            }
        ]
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _ENDPOINT,
                params={"key": settings.google_vision_api_key},
                json=body,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        data = response.json()

        # 요청 전체가 거부되면(예: 사진 용량 초과, API 키 무효, 쿼터 초과)
        # "responses" 배열 없이 최상위에 {"error": {...}}만 온다 - 예전 코드는
        # 이 경우를 안 보고 바로 `(data.get("responses") or [{}])[0]`로 빈 dict를
        # 만들어버려서, 실제로는 API가 에러를 냈는데도 "텍스트 없음"으로 조용히
        # 잘못 처리했다(사용자 리포트, 2026-08-14: "구글 비전에서는 제대로
        # 읽었었는데 텍스트를 찾지 못했습니다 라고 뜸" - 5712x4284 고해상도 사진
        # 여러 장에서 재현됨, 용량 초과로 요청 전체가 거부됐을 가능성이 높음).
        top_level_error = data.get("error")
        if top_level_error:
            message = top_level_error.get("message") or f"Vision API 오류(status {response.status_code})"
            return OcrResult(latency_ms=latency_ms, error=message)

        responses = data.get("responses")
        if not responses:
            return OcrResult(
                latency_ms=latency_ms,
                error=f"Vision API가 예상치 못한 응답을 반환했습니다(status {response.status_code}).",
            )
        result = responses[0]

        if "error" in result:
            return OcrResult(latency_ms=latency_ms, error=result["error"].get("message"))

        full_text_annotation = result.get("fullTextAnnotation") or {}
        text = full_text_annotation.get("text", "")

        confs: list[float] = []
        block_count = 0
        for page in full_text_annotation.get("pages", []):
            for block in page.get("blocks", []):
                block_count += 1
                for paragraph in block.get("paragraphs", []):
                    for word in paragraph.get("words", []):
                        if isinstance(word.get("confidence"), (int, float)):
                            confs.append(word["confidence"])

        confidence = (sum(confs) / len(confs)) if confs else None

        return OcrResult(
            text=text,
            confidence=confidence,
            latency_ms=latency_ms,
            block_count=block_count,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return OcrResult(latency_ms=latency_ms, error=str(exc))
