from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .debate import run_brand_price, run_debate
from .ocr import cleanup as ocr_cleanup
from .ocr import google_vision as google_vision_ocr
from .schemas import (
    BrandPriceResponse,
    BulkDecideResponse,
    ClarifyResponse,
    DecideRequest,
    DecideResponse,
    OcrExtractResponse,
)

app = FastAPI(title="Etiquette Purchase Decision API")

# GitHub Pages(정적 프론트엔드)에서 이 API를 브라우저로 직접 호출하므로 CORS 허용이 필요하다.
# 인증이 없는 API라 origin을 넓게 열어도 데이터 유출 위험은 없지만, "*"로 두면 아무 사이트나
# 이 API(유료 LLM 호출)를 자기 페이지에 박아 넣고 우리 예산을 소모시킬 수 있어 알려진
# origin으로만 제한한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cherry-pick00.github.io",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

DecideResult = DecideResponse | BulkDecideResponse | ClarifyResponse | BrandPriceResponse


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr/extract", response_model=OcrExtractResponse)
async def ocr_extract(image: UploadFile) -> OcrExtractResponse:
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="이미지 파일이 비어 있습니다.")

    ocr_result = await google_vision_ocr.extract_text(image_bytes)
    cleaned = await ocr_cleanup.clean(ocr_result.text) if not ocr_result.error else None
    return OcrExtractResponse(ocr=ocr_result, cleaned=cleaned)


@app.post("/decide", response_model=DecideResult)
async def decide(request: DecideRequest) -> DecideResult:
    try:
        if request.brand:
            return await run_brand_price(request.query, request.brand)
        return await run_debate(request.query)
    except (RuntimeError, ValueError) as exc:
        # RuntimeError: 제안 전부 실패, ValueError: judge 응답에서 JSON을 못 찾음
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # 외부 LLM API 오류 등 예상 못한 실패는 내부 정보를 노출하지 않고 502로 감싼다.
        raise HTTPException(
            status_code=502, detail="구매 결정을 처리하는 중 오류가 발생했습니다."
        ) from exc