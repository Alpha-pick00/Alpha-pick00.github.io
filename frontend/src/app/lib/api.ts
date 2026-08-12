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

export interface ClarifyOptions {
  brands: string[];
  products: string[];
  volumes: string[];
  quantities: string[];
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
