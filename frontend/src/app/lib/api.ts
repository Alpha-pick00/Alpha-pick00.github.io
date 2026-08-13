export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export type AgentName = 'gpt' | 'gemini' | 'deepseek';

export interface Proposal {
  agent: AgentName;
  product_name: string | null;
  price: string | null;
  retailer: string | null;
  url: string | null;
  reasoning: string | null;
  error: string | null;
  verified?: boolean | null;
  challenge_note?: string | null;
  proposed_by?: AgentName[] | null;
}

export interface Decision {
  product_name: string;
  price: string;
  retailer: string;
  url: string;
  reasoning: string;
  chosen_agent: AgentName;
}

export interface DecideResponse {
  mode: 'single';
  query: string;
  proposals: Proposal[];
  decision: Decision;
}

export interface BrandOption {
  brand: string;
  product_name: string;
  price: string;
  retailer: string;
  url: string;
  reasoning?: string | null;
  delivery_note?: string | null;
}

export interface BulkProposal {
  agent: AgentName;
  options: BrandOption[];
  error: string | null;
}

export interface BulkDecision {
  options: BrandOption[];
  reasoning: string;
}

export interface PriceRange {
  min: string;
  max: string;
}

export interface BulkDecideResponse {
  mode: 'bulk';
  query: string;
  proposals: BulkProposal[];
  decision: BulkDecision;
  price_range: PriceRange | null;
}

export interface ClarifyFacet {
  label: string;
  options: string[];
  // 다른 facet(어느 것이든 - 브랜드로 한정 안 됨)에서 뭘 고르면, 추가 요청
  // 없이 이 매핑으로 이 facet의 보이는 옵션을 즉시 좁힌다(2026-08-14 일반화:
  // 브랜드="삼성전자" -> 시리즈가 갤럭시 계열만이었던 걸, 시리즈="초코파이
  // 바나나" -> 용량이 그 시리즈에 실제로 있는 값만으로도 확장). 키는 다른
  // facet의 옵션 문자열, 값은 그 선택이 주어졌을 때 이 facet에서 유효한 옵션들.
  options_by_selection?: Record<string, string[]> | null;
}

export interface ClarifyOptions {
  brands: string[];
  products: string[];
  volumes: string[];
  quantities: string[];
  facets: ClarifyFacet[];
}

export interface ClarifyResponse {
  mode: 'clarify';
  query: string;
  options: ClarifyOptions;
}

export interface BrandPriceResponse {
  mode: 'brand_price';
  query: string;
  brand: string;
  option: BrandOption | null;
  error: string | null;
}

export type DecideResult =
  | DecideResponse
  | BulkDecideResponse
  | ClarifyResponse
  | BrandPriceResponse;

export interface OcrResult {
  text: string;
  confidence: number | null;
  latency_ms: number | null;
  block_count: number;
  error: string | null;
}

export interface OcrCleanupResult {
  cleaned_text: string | null;
  search_query: string | null;
  notes: string | null;
  error: string | null;
}

export interface OcrExtractResponse {
  ocr: OcrResult;
  cleaned: OcrCleanupResult | null;
}

export class ApiError extends Error {}

export interface DanawaStreamCandidate {
  type: 'candidate';
  product_name: string | null;
  price: string | null;
  retailer: string | null;
  url: string | null;
}

export interface DanawaStreamFinal {
  type: 'final';
  result: DecideResult;
}

export interface DanawaStreamError {
  type: 'error';
  message: string;
}

export type DanawaStreamEvent = DanawaStreamCandidate | DanawaStreamFinal | DanawaStreamError;

// /decide/danawa-only/stream(SSE) - 사용자 요청(2026-08-11: "1개 서치 완료되면
// 1개 올려줘 먼저"): 후보가 끝나는 대로 하나씩 onEvent로 넘긴다. EventSource는
// GET 전용이라 못 쓰고(이 엔드포인트는 POST + JSON body) fetch + ReadableStream을
// 직접 읽어 "data: {...}\n\n" 프레임을 파싱한다.
// baseQuery(2026-08-14, "이런식으로 가격 정보를 찾지 못하는 결과는 없어야해") -
// AI 상세검색으로 facet을 여러 개 이어붙인 아주 구체적인 검색어는 다나와
// 검색엔진에서 결과가 아예 안 나올 수 있다(실제 상품이 없어서가 아니라
// 검색어 자체의 문제). 그 조합의 맨 처음 검색어를 실어 보내면, 백엔드가 정확한
// 검색이 빈손일 때 이걸로 한 번 더 시도해 진짜 "못 찾았다" 화면을 최대한 줄인다.
export async function decideDanawaOnlyStream(
  query: string,
  onEvent: (event: DanawaStreamEvent) => void,
  baseQuery?: string
): Promise<void> {
  const response = await fetch(`${API_URL}/decide/danawa-only/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(baseQuery ? { query, base_query: baseQuery } : { query }),
  });

  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `요청이 실패했습니다 (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith('data: ')) continue;
      onEvent(JSON.parse(line.slice('data: '.length)) as DanawaStreamEvent);
    }
  }
}

// AI 상세검색(2026-08-12) - "음료수"처럼 짧고 애매한 검색어를 다나와 검색 결과에
// 근거해 DeepSeek이 카테고리/브랜드/용량 같은 기준(facet)으로 좁혀나가도록 제안한다.
// 백엔드가 needs_clarification()으로 한 번 더 걸러서, 명확한 검색어면 검색/LLM
// 호출 없이 즉시 facets: []로 끝난다(app/debate.py::check_clarify_facets 참고).
//
// looksAmbiguous()는 그 백엔드 검사(backend/app/intent.py::_is_short_bare_query)를
// 그대로 흉내낸 순수 클라이언트 프리필터다 - 명백히 구체적인 검색어(숫자가 있거나
// 단어가 3개 이상)에 대해서는 이 API를 아예 호출하지 않아서, 거의 모든 검색에서
// 왕복 하나조차 안 생기게 한다. 오탐(애매한데 여기서 걸러짐)이 있어도 위험하지
// 않다 - 그런 경우 사용자는 그냥 원래 검색 경로로 바로 넘어갈 뿐이다.
const HAS_DIGIT_PATTERN = /\d/;

export function looksAmbiguous(query: string): boolean {
  const trimmed = query.trim();
  if (!trimmed) return false;
  const tokens = trimmed.split(/\s+/);
  return tokens.length <= 2 && !HAS_DIGIT_PATTERN.test(trimmed);
}

// baseQuery(2026-08-13, "조금 더 빠르게" 요청) - 드릴다운 중(예: "핸드폰" ->
// "핸드폰 삼성전자")이면 그 체인의 맨 처음 검색어를 실어 보낸다. 백엔드가 매
// 라운드 새로 search.danawa.com을 때리는(10초 Crawl-delay) 대신 이미 캐시된
// base_query 결과를 재사용해 로컬 필터링만 하게 해준다(app/debate.py::check_clarify_facets).
export async function checkClarifyFacets(query: string, baseQuery?: string): Promise<ClarifyResponse> {
  const response = await fetch(`${API_URL}/decide/clarify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(baseQuery ? { query, base_query: baseQuery } : { query }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `요청이 실패했습니다 (${response.status})`);
  }

  return response.json();
}

export async function decide(query: string, brand?: string): Promise<DecideResult> {
  const response = await fetch(`${API_URL}/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(brand ? { query, brand } : { query }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `요청이 실패했습니다 (${response.status})`);
  }

  return response.json();
}

export type DecideStage = 'refining' | 'searching' | 'proposing' | 'challenging' | 'judging';

export type DecideStreamEvent =
  | { type: 'status'; stage: DecideStage }
  | { type: 'proposal'; proposal: Proposal }
  | { type: 'final'; result: DecideResult }
  | { type: 'error'; message: string };

/** /decide와 같은 일을 하지만, 서버가 단계별로 흘려보내는 NDJSON(줄바꿈으로 구분된 JSON)을
 * 그때그때 onEvent로 넘겨준다 — 세 에이전트를 다 기다리지 않고 먼저 끝난 제안부터 보여줄 수 있다. */
export async function decideStream(
  query: string,
  onEvent: (event: DecideStreamEvent) => void,
  brand?: string,
  signal?: AbortSignal,
  skipIntentCheck?: boolean
): Promise<void> {
  const response = await fetch(`${API_URL}/decide/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      ...(brand ? { brand } : {}),
      ...(skipIntentCheck ? { skip_intent_check: true } : {}),
    }),
    signal,
  });

  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `요청이 실패했습니다 (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) onEvent(JSON.parse(line) as DecideStreamEvent);
      newlineIndex = buffer.indexOf('\n');
    }
  }
}

export async function extractOcr(file: File): Promise<OcrExtractResponse> {
  const formData = new FormData();
  formData.append('image', file);

  const response = await fetch(`${API_URL}/ocr/extract`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `이미지 분석에 실패했습니다 (${response.status})`);
  }

  return response.json();
}

export interface ClarifyMatchResult {
  matched: string | null;
  /** LLM이 그때그때 생성한 자연어 답장 — 고정 문구가 아니라 실제 대화처럼
   * 매번 다르게 표현된다. 호출 자체가 실패해도 안내용 기본 문구가 채워져 있어
   * 항상 채팅에 뭔가 보여줄 수 있다. */
  reply: string;
}

const FALLBACK_CLARIFY_REPLY = '지금은 답장을 만들지 못했어요 — 아래 선택지 중에서 골라주시겠어요?';

/** clarify 화면에서 사용자가 버튼을 클릭하거나 채팅으로 타이핑했을 때, 그
 * 입력이 현재 옵션 중 뭘 가리키는지와 자연스러운 답장을 함께 서버(GPT)에
 * 물어본다. 실패/불확실하면 matched가 null — 호출부는 버튼이 항상 그대로
 * 남아있으므로 이 경우 채팅에 안내만 띄우면 된다. */
export async function matchClarifyOption(message: string, options: string[]): Promise<ClarifyMatchResult> {
  try {
    const response = await fetch(`${API_URL}/clarify/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, options }),
    });
    if (!response.ok) return { matched: null, reply: FALLBACK_CLARIFY_REPLY };
    return await response.json();
  } catch {
    return { matched: null, reply: FALLBACK_CLARIFY_REPLY };
  }
}

const FALLBACK_CLARIFY_QUESTION = '몇 가지 후보를 찾았어요 — 아래에서 골라주시겠어요?';

/** 이번 라운드에 물어볼 축(브랜드/제품/용량/개수)의 후보들을 실제 상담원처럼
 * 자연스러운 질문 문장으로 바꿔달라고 서버(GPT)에 요청한다 — "브랜드를
 * 선택하면 좁혀드려요" 같은 고정 라벨 대신 채팅 말풍선으로 먼저 보여줄 문장. */
export async function askClarifyQuestion(query: string, options: string[]): Promise<string> {
  try {
    const response = await fetch(`${API_URL}/clarify/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, options }),
    });
    if (!response.ok) return FALLBACK_CLARIFY_QUESTION;
    const data: { message: string } = await response.json();
    return data.message || FALLBACK_CLARIFY_QUESTION;
  } catch {
    return FALLBACK_CLARIFY_QUESTION;
  }
}

export async function fetchAutocomplete(query: string, signal?: AbortSignal): Promise<string[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];

  const response = await fetch(`${API_URL}/autocomplete?q=${encodeURIComponent(trimmed)}`, { signal });
  if (!response.ok) return [];
  return response.json();
}

// --- 로그인 계정별 검색 기록 (서버에 저장, 기기 상관없이 동일 계정이면 같은 기록) ---

export interface ServerHistoryEntry {
  id: string;
  query: string;
  timestamp: number; // 서버는 epoch seconds(float)로 내려준다
  result: DecideResult;
}

export async function fetchServerHistory(token: string): Promise<ServerHistoryEntry[]> {
  const response = await fetch(`${API_URL}/history`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) return [];
  return response.json();
}

export async function saveServerHistory(
  token: string,
  query: string,
  result: DecideResult
): Promise<ServerHistoryEntry | null> {
  const response = await fetch(`${API_URL}/history`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ query, result }),
  });
  if (!response.ok) return null;
  return response.json();
}

export async function deleteServerHistoryEntry(token: string, id: string): Promise<void> {
  await fetch(`${API_URL}/history/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function clearServerHistory(token: string): Promise<void> {
  await fetch(`${API_URL}/history`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
}
