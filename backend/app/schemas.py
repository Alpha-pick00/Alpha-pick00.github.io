from typing import Literal

from pydantic import BaseModel

# "danawa": PART 4-2(2026-08-11 지시서) - 다나와 A등급 최저가 후보가 judge의
# 선택 대상 풀에 직접 들어간다. 프론트엔드는 AGENT_LABEL[agent] || agent로
# 렌더링해(frontend/src/app/components/SearchResults.tsx) 모르는 값이 와도
# 원문 그대로 표시할 뿐 깨지지 않는다 - 확인 후 추가했다.
AgentName = Literal["gpt", "gemini", "deepseek", "danawa"]
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


class Decision(BaseModel):
    product_name: str
    price: str
    retailer: str
    url: str
    reasoning: str
    chosen_agent: AgentName
    # "danawa_offer": app.price_table이 다나와 실측 가격표의 A등급(링크 생성
    # 가능) offer와 대조해 price/url을 검증된 값으로 교체했다는 뜻.
    # "llm_guess"(기본값): 그런 대조 없이 LLM이 제안한 값 그대로.
    price_source: Literal["danawa_offer", "llm_guess"] = "llm_guess"


class DecideRequest(BaseModel):
    query: str
    brand: str | None = None


class PriceTableOffer(BaseModel):
    seller: str
    price_krw: int
    delivery_text: str | None = None
    domain: str | None = None
    trust: float | None = None
    linkable: bool
    rank: int


class PriceTable(BaseModel):
    source: str = "danawa"
    source_pcode: str | None = None
    product_name: str | None = None
    offers: list[PriceTableOffer]
    spread: float | None = None


class DecideResponse(BaseModel):
    mode: Literal["single"] = "single"
    query: str
    proposals: list[Proposal]
    decision: Decision
    price_table: PriceTable | None = None


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
