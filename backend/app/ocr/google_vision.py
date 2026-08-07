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
        result = (data.get("responses") or [{}])[0]

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
