from typing import Literal

from pydantic import BaseModel

AgentName = Literal["gpt", "gemini", "deepseek"]
AuthProvider = Literal["google", "kakao", "naver"]


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: float | None = None


class Proposal(BaseModel):
    agent: AgentName
    product_name: str | None = None
    price: str | None = None
    retailer: str | None = None
    url: str | None = None
    reasoning: str | None = None
    error: str | None = None
    verified: bool | None = None
    challenge_note: str | None = None
    proposed_by: list[AgentName] | None = None


class AgentCandidate(BaseModel):
    product_name: str
    price_krw: int | None = None
    retailer: str | None = None
    url: str | None = None
    reasoning: str | None = None


class AgentCandidates(BaseModel):
    agent: AgentName
    candidates: list[AgentCandidate] = []
    error: str | None = None


class RefinedQuery(BaseModel):
    query: str
    error: str | None = None


class ChallengeVerdict(BaseModel):
    url: str | None = None
    verified: bool
    note: str = ""


class ChallengeResult(BaseModel):
    verdicts: list[ChallengeVerdict] = []
    error: str | None = None


class Decision(BaseModel):
    product_name: str
    price: str
    retailer: str
    url: str
    reasoning: str
    chosen_agent: AgentName


class JudgeVerdict(BaseModel):
    """judge LlmAgent의 output_schema — chosen_agent 없이 선택한 상품만 반환하고,
    실제 chosen_agent는 adk_pipeline이 url로 역매칭해서 채운다(제안자가 여럿일
    수 있어 LLM에게 단일 리터럴을 직접 고르게 하지 않는다)."""

    product_name: str
    price: str
    retailer: str
    url: str
    reasoning: str


class DecideRequest(BaseModel):
    query: str
    brand: str | None = None
    # Human-in-the-loop으로 브랜드/용량/개수를 이미 하나 골라 검색어에 이어붙여
    # 재검색하는 요청이면 True — is_bulk_query()/needs_clarification() 같은
    # "첫 질의가 애매한지" 판단용 휴리스틱을 건너뛴다. 이미 특정 상품을 좁혀가는
    # 중인데, 예컨대 "80ml"처럼 용량이 붙은 재검색어가 새 대량구매 질의로
    # 오판되는 걸 막기 위함.
    skip_intent_check: bool = False


class DecideResponse(BaseModel):
    mode: Literal["single"] = "single"
    query: str
    proposals: list[Proposal]
    decision: Decision


class BrandOption(BaseModel):
    brand: str
    product_name: str
    price: str
    retailer: str
    url: str
    reasoning: str | None = None
    delivery_note: str | None = None


class BulkProposal(BaseModel):
    agent: AgentName
    options: list[BrandOption] = []
    error: str | None = None


class BulkDecision(BaseModel):
    options: list[BrandOption]
    reasoning: str


class PriceRange(BaseModel):
    min: str
    max: str


class BulkDecideResponse(BaseModel):
    mode: Literal["bulk"] = "bulk"
    query: str
    proposals: list[BulkProposal]
    decision: BulkDecision
    price_range: PriceRange | None = None


class ClarifyOptions(BaseModel):
    brands: list[str] = []
    volumes: list[str] = []
    quantities: list[str] = []


class ClarifyResponse(BaseModel):
    mode: Literal["clarify"] = "clarify"
    query: str
    options: ClarifyOptions


class BrandPriceResponse(BaseModel):
    mode: Literal["brand_price"] = "brand_price"
    query: str
    brand: str
    option: BrandOption | None = None
    error: str | None = None


DecideResultUnion = DecideResponse | BulkDecideResponse | ClarifyResponse | BrandPriceResponse


class OcrResult(BaseModel):
    text: str = ""
    confidence: float | None = None
    latency_ms: int | None = None
    block_count: int = 0
    error: str | None = None


class OcrCleanupResult(BaseModel):
    cleaned_text: str | None = None
    search_query: str | None = None
    notes: str | None = None
    error: str | None = None


class OcrExtractResponse(BaseModel):
    ocr: OcrResult
    cleaned: OcrCleanupResult | None = None


class User(BaseModel):
    provider: AuthProvider
    provider_user_id: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: User


class GoogleAuthRequest(BaseModel):
    access_token: str  # Google OAuth2 토큰 클라이언트(팝업)가 내려주는 access token


class OAuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str
    state: str | None = None  # 네이버는 토큰 교환 시 state가 필요하다


class HistoryEntry(BaseModel):
    id: str
    query: str
    timestamp: float
    result: DecideResultUnion


class SaveHistoryRequest(BaseModel):
    query: str
    result: DecideResultUnion
