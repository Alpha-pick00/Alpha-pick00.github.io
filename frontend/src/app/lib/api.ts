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
  // 브랜드가 아닌 facet에만 채워진다(2026-08-13) - 사용자가 브랜드를 고르면
  // 추가 요청 없이 이 매핑으로 이 facet의 보이는 옵션을 그 브랜드에 맞게 즉시
  // 좁힌다(예: 브랜드="삼성전자" -> 시리즈가 갤럭시 계열만).
  options_by_brand?: Record<string, string[]> | null;
}

export interface ClarifyOptions {
  brands: string[];
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
export async function decideDanawaOnlyStream(
  query: string,
  onEvent: (event: DanawaStreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_URL}/decide/danawa-only/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
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
