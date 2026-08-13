import asyncio
import json
import logging
from contextlib import asynccontextmanager

import jwt

logging.basicConfig(level=logging.INFO)
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import TypeAdapter

from . import autocomplete, danawa, history, popularity_scheduler
from .agents import gpt as gpt_agent
from .auth import google as google_auth
from .auth import kakao as kakao_auth
from .auth import naver as naver_auth
from .auth.session import issue_session_token, verify_session_token
from .debate import run_brand_price, run_debate, run_debate_stream, run_single_debate, run_single_debate_stream
from .ocr import cleanup as ocr_cleanup
from .ocr import google_vision as google_vision_ocr
from .schemas import (
    AuthResponse,
    BrandPriceResponse,
    BulkDecideResponse,
    ClarifyAskRequest,
    ClarifyAskResponse,
    ClarifyMatchRequest,
    ClarifyMatchResponse,
    ClarifyResponse,
    DecideRequest,
    DecideResponse,
    DecideResultUnion as DecideResult,
    GoogleAuthRequest,
    HistoryEntry,
    OAuthCodeRequest,
    OcrExtractResponse,
    SaveHistoryRequest,
    User,
)

_decide_result_adapter = TypeAdapter(DecideResult)

@asynccontextmanager
async def lifespan(app: FastAPI):
    popularity_scheduler.start()
    yield
    popularity_scheduler.stop()


app = FastAPI(title="αlpha Pick Purchase Decision API", lifespan=lifespan)

# GitHub Pages(정적 프론트엔드)에서 이 API를 브라우저로 직접 호출하므로 CORS 허용이 필요하다.
# 인증이 없는 API라 origin을 넓게 열어도 데이터 유출 위험은 없지만, "*"로 두면 아무 사이트나
# 이 API(유료 LLM 호출)를 자기 페이지에 박아 넣고 우리 예산을 소모시킬 수 있어 알려진
# origin으로만 제한한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://alpha-pick00.github.io",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

autocomplete.seed()

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


async def _resolve_danawa_urls(result: DecideResult) -> DecideResult:
    """최종 추천 URL이 다나와 가격비교 페이지면, 사용자가 실제로 구매할 수
    있는 최저가 판매처 링크로 바꿔치기한다 — 다나와 페이지 자체는 여러 판매처를
    나열만 할 뿐 바로 살 수 있는 곳이 아니다(danawa.py 참고). 다나와가 아니거나
    해석에 실패하면 원래 값 그대로 둔다. 최종 결과에만 적용하고 proposals의
    나머지 후보 URL은 그대로 둔다 — 사용자가 실제로 클릭할 하나만 바꾸면 된다."""
    if isinstance(result, DecideResponse):
        result.decision.url, result.decision.retailer = await danawa.resolve_lowest_price(
            result.decision.url, result.decision.retailer
        )
    elif isinstance(result, BulkDecideResponse):
        resolved = await asyncio.gather(
            *(danawa.resolve_lowest_price(o.url, o.retailer) for o in result.decision.options)
        )
        for option, (url, retailer) in zip(result.decision.options, resolved):
            option.url, option.retailer = url, retailer
    elif isinstance(result, BrandPriceResponse) and result.option:
        result.option.url, result.option.retailer = await danawa.resolve_lowest_price(
            result.option.url, result.option.retailer
        )
    return result


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/autocomplete", response_model=list[str])
def get_autocomplete(q: str, limit: int = 8) -> list[str]:
    return autocomplete.suggest(q, limit)


@app.post("/clarify/match", response_model=ClarifyMatchResponse)
async def clarify_match(request: ClarifyMatchRequest) -> ClarifyMatchResponse:
    """대화형 HITL — 사용자가 clarify 선택지를 버튼 대신 채팅으로 타이핑했을 때,
    그 문장이 현재 옵션 중 뭘 가리키는지 해석하고 자연스러운 답장(reply)도 함께
    받는다 — 봇의 응답이 고정 문구가 아니라 실제 LLM이 생성한 문장이 되도록.
    matched가 실패/불확실하면 None — 프론트는 버튼이 항상 그대로 남아있으므로
    이 경우 다시 물어보면 된다."""
    matched, reply = await gpt_agent.match_clarify_reply(request.message, request.options)
    return ClarifyMatchResponse(matched=matched, reply=reply)


@app.post("/clarify/ask", response_model=ClarifyAskResponse)
async def clarify_ask(request: ClarifyAskRequest) -> ClarifyAskResponse:
    """이번 라운드에 물어볼 축(브랜드/제품/용량/개수)의 후보들을 실제 상담원처럼
    자연스러운 질문 문장으로 바꾼다 — 프론트가 "브랜드를 선택하면 좁혀드려요"
    같은 고정 라벨 대신 이 문장을 채팅 말풍선으로 먼저 보여준다."""
    message = await gpt_agent.generate_clarify_question(request.query, request.options)
    return ClarifyAskResponse(message=message)


@app.get("/auth/me", response_model=User)
def auth_me(user: User = Depends(get_current_user)) -> User:
    return user


@app.get("/history", response_model=list[HistoryEntry])
def get_history(user: User = Depends(get_current_user)) -> list[HistoryEntry]:
    return history.list_entries(user)


@app.post("/history", response_model=HistoryEntry)
def save_history(
    request: SaveHistoryRequest, user: User = Depends(get_current_user)
) -> HistoryEntry:
    return history.add_entry(user, request.query, request.result)


@app.delete("/history/{entry_id}")
def delete_history_entry(entry_id: str, user: User = Depends(get_current_user)) -> dict[str, str]:
    history.delete_entry(user, entry_id)
    return {"status": "ok"}


@app.delete("/history")
def delete_all_history(user: User = Depends(get_current_user)) -> dict[str, str]:
    history.clear_entries(user)
    return {"status": "ok"}


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
        elif request.skip_intent_check:
            result = await run_single_debate(request.query)
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

    result = await _resolve_danawa_urls(result)
    background_tasks.add_task(autocomplete.record_terms, _autocomplete_terms(request, result))
    return result


@app.post("/decide/stream")
async def decide_stream(request: DecideRequest) -> StreamingResponse:
    """/decide와 같은 일을 하지만, 검색 완료·에이전트별 제안 완료·심사 단계마다
    한 줄씩(NDJSON) 흘려보낸다. 그래야 프론트가 세 에이전트를 다 기다리지 않고
    먼저 끝난 제안부터 화면에 보여줄 수 있다. 응답 헤더가 이미 200으로 나간
    뒤라 실패해도 HTTP 상태 코드를 바꿀 수 없으므로, 에러도 "error" 이벤트로
    흘려보낸다 — 프론트는 이 타입을 보고 에러 처리한다."""

    async def event_generator():
        try:
            if request.brand:
                result: DecideResult = await run_brand_price(request.query, request.brand)
                result = await _resolve_danawa_urls(result)
                yield json.dumps({"type": "final", "result": result.model_dump()}) + "\n"
            else:
                result = None
                stream = (
                    run_single_debate_stream(request.query)
                    if request.skip_intent_check
                    else run_debate_stream(request.query)
                )
                async for event in stream:
                    if event["type"] == "final":
                        result = await _resolve_danawa_urls(
                            _decide_result_adapter.validate_python(event["result"])
                        )
                        event["result"] = result.model_dump()
                    yield json.dumps(event) + "\n"
        except (RuntimeError, ValueError) as exc:
            # RuntimeError: 제안 전부 실패, ValueError: judge 응답에서 JSON을 못 찾음
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
            return
        except Exception:
            # 외부 LLM API 오류 등 예상 못한 실패는 내부 정보를 노출하지 않고 감싼다.
            yield json.dumps(
                {"type": "error", "message": "구매 결정을 처리하는 중 오류가 발생했습니다."}
            ) + "\n"
            return

        if result is not None:
            asyncio.create_task(
                asyncio.to_thread(autocomplete.record_terms, _autocomplete_terms(request, result))
            )

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
