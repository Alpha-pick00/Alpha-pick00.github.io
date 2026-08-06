from fastapi import FastAPI, HTTPException

from .debate import run_brand_price, run_debate
from .schemas import (
    BrandPriceResponse,
    BulkDecideResponse,
    ClarifyResponse,
    DecideRequest,
    DecideResponse,
)

app = FastAPI(title="Etiquette Purchase Decision API")

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
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc