from openai import AsyncOpenAI

from ..agents.base import parse_json_object
from ..config import settings
from ..schemas import OcrCleanupResult

CLEANUP_INSTRUCTIONS = (
    "당신은 OCR로 추출한 텍스트를 정리하는 도우미입니다. OCR 특성상 줄바꿈이 뒤섞이거나, "
    "같은 내용이 중복되거나, 순서가 뒤틀려 있을 수 있습니다. "
    "아래 OCR 원본 텍스트를 읽기 쉽게 정리하세요. "
    "이미지를 직접 보는 게 아니므로 원본에 없는 내용을 새로 지어내지 말고, "
    "원본에 있는 내용만 재배열하고 중복을 제거하세요. "
    "추가로 이 텍스트가 상품 포장/라벨/영수증이라면, 쇼핑 검색엔진에 그대로 넣었을 때 "
    "가장 정확한 결과가 나올 검색어를 만드세요 — 브랜드명과 상품명(용량·모델명 등 "
    "식별에 필요한 스펙 포함)만 남기고, 가격/바코드/영양정보/광고 문구/중복 표기는 "
    "전부 제외하세요. 상품을 특정할 수 없으면 search_query를 빈 문자열로 두세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"cleaned_text": "정리된 텍스트", '
    '"search_query": "쇼핑 검색에 바로 쓸 짧은 검색어(브랜드+상품명, 불필요한 정보 제외)", '
    '"notes": "정리하면서 처리한 내용(중복 제거, 줄바꿈 정리 등). 없으면 빈 문자열"}'
)


async def clean(raw_text: str) -> OcrCleanupResult:
    if not raw_text.strip():
        return OcrCleanupResult(error="정리할 OCR 텍스트가 없습니다.")

    try:
        client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_api_base)
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "user", "content": f"{CLEANUP_INSTRUCTIONS}\n\nOCR 원본 텍스트:\n{raw_text}"}
            ],
        )
        data = parse_json_object(response.choices[0].message.content or "")
        return OcrCleanupResult(**data)
    except Exception as exc:
        return OcrCleanupResult(error=str(exc))
