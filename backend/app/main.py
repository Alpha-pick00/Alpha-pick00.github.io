from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .debate import run_brand_price, run_debate
from .schemas import (
    BrandPriceResponse,
    BulkDecideResponse,
    ClarifyResponse,
    DecideRequest,
    DecideResponse,
)

app = FastAPI(title="Etiquette Purchase Decision API")

# GitHub Pages(정적 프론트엔드)에서 이 API를 브라우저로 직접 호출하므로 CORS 허용이 필요하다.
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