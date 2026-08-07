import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import autocomplete
from .auth import google as google_auth
from .auth import kakao as kakao_auth
from .auth import naver as naver_auth
from .auth.session import issue_session_token, verify_session_token
from .debate import run_brand_price, run_debate
from .ocr import cleanup as ocr_cleanup
from .ocr import google_vision as google_vision_ocr
from .schemas import (
    AuthResponse,
    BrandPriceResponse,
    BulkDecideResponse,
    ClarifyResponse,
    DecideRequest,
    DecideResponse,
    GoogleAuthRequest,
    OAuthCodeRequest,
    OcrExtractResponse,
    User,
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

autocomplete.seed()

DecideResult = DecideResponse | BulkDecideResponse | ClarifyResponse | BrandPriceResponse

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        return verify_session_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="세션이 만료되었거나 유효하지 않습니다.") from exc


def _autocomplete_terms(request: DecideRequest, result: DecideResult) -> list[str]:
    """검색어 + 파이프라인이 이미 만들어낸 모든 상품/브랜드 후보를 자동완성 인덱스에 반영한다.

    judge가 최종 선택한 하나만 남기면, 각 에이전트가 실제 검색 결과에서 찾아낸
    나머지 후보와 clarify 단계에서 뽑힌 브랜드/용량/수량은 그냥 버려진다.
    검색 1건당 이미 검증된 상품 단어가 여러 개 나오므로 전부 모은다.
    """
    terms = [request.query]

    if isinstance(result, DecideResponse):
        terms.append(result.decision.product_name)
        terms.extend(p.product_name for p in result.proposals if p.error is None)

    elif isinstance(result, BulkDecideResponse):
        for option in result.decision.options:
            terms.append(option.brand)
            terms.append(option.product_name)
        for proposal in result.proposals:
            if proposal.error is not None:
                continue
            for option in proposal.options:
                terms.append(option.brand)
                terms.append(option.product_name)

    elif isinstance(result, ClarifyResponse):
        terms.extend(result.options.brands)
        terms.extend(result.options.volumes)
        terms.extend(result.options.quantities)

    elif isinstance(result, BrandPriceResponse) and result.option:
        terms.append(result.option.product_name)

    return terms


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/autocomplete", response_model=list[str])
def get_autocomplete(q: str, limit: int = 8) -> list[str]:
    return autocomplete.suggest(q, limit)


@app.get("/auth/me", response_model=User)
def auth_me(user: User = Depends(get_current_user)) -> User:
    return user


@app.post("/auth/google", response_model=AuthResponse)
async def auth_google(request: GoogleAuthRequest) -> AuthResponse:
    try:
        user = await google_auth.fetch_user(request.access_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"구글 로그인에 실패했습니다: {exc}") from exc
    return AuthResponse(token=issue_session_token(user), user=user)


@app.post("/auth/kakao", response_model=AuthResponse)
async def auth_kakao(request: OAuthCodeRequest) -> AuthResponse:
    try:
        user = await kakao_auth.exchange_code(request.code, request.redirect_uri)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"카카오 로그인에 실패했습니다: {exc}") from exc
    return AuthResponse(token=issue_session_token(user), user=user)


@app.post("/auth/naver", response_model=AuthResponse)
async def auth_naver(request: OAuthCodeRequest) -> AuthResponse:
    try:
        user = await naver_auth.exchange_code(request.code, request.state)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"네이버 로그인에 실패했습니다: {exc}") from exc
    return AuthResponse(token=issue_session_token(user), user=user)


@app.post("/ocr/extract", response_model=OcrExtractResponse)
async def ocr_extract(image: UploadFile) -> OcrExtractResponse:
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="이미지 파일이 비어 있습니다.")

    ocr_result = await google_vision_ocr.extract_text(image_bytes)
    cleaned = await ocr_cleanup.clean(ocr_result.text) if not ocr_result.error else None
    return OcrExtractResponse(ocr=ocr_result, cleaned=cleaned)


@app.post("/decide", response_model=DecideResult)
async def decide(request: DecideRequest, background_tasks: BackgroundTasks) -> DecideResult:
    try:
        if request.brand:
            result = await run_brand_price(request.query, request.brand)
        else:
            result = await run_debate(request.query)
    except (RuntimeError, ValueError) as exc:
        # RuntimeError: 제안 전부 실패, ValueError: judge 응답에서 JSON을 못 찾음
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # 외부 LLM API 오류 등 예상 못한 실패는 내부 정보를 노출하지 않고 502로 감싼다.
        raise HTTPException(
            status_code=502, detail="구매 결정을 처리하는 중 오류가 발생했습니다."
        ) from exc

    background_tasks.add_task(autocomplete.record_terms, _autocomplete_terms(request, result))
    return result
