import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  checkClarifyFacets,
  decide,
  decideStream,
  extractOcr,
  fetchServerHistory,
  saveServerHistory,
  deleteServerHistoryEntry,
  clearServerHistory,
  looksAmbiguous,
  recordPreference,
  ApiError,
  type DecideResult,
  type DecideStage,
  type Proposal,
  type ServerHistoryEntry,
} from '../lib/api';
import { getStoredToken } from '../lib/auth';
import { useAuth } from './AuthContext';
import {
  deleteHistoryEntry,
  clearHistory,
  loadHistory,
  saveHistoryEntry,
  type HistoryEntry,
} from '../lib/history';
import type { ClarifyStep } from '../components/SearchResults';

const fromServerEntry = (entry: ServerHistoryEntry): HistoryEntry => ({
  id: entry.id,
  query: entry.query,
  timestamp: entry.timestamp * 1000, // 서버는 초 단위, 프론트는 Date.now() 기준 ms 단위로 통일
  result: entry.result,
});

export type TurnStatus = 'loading' | 'result' | 'error';

// ChatGPT/Claude 스타일 대화 스레드의 한 왕복(사용자 메시지 -> AI 오케스트레이션 답변).
// displayQuery는 사용자 말풍선에 그대로 보여줄 텍스트, requestQuery/brand는
// 실제로 서버에 던진 값 - 브랜드 선택 턴은 이 둘이 다르다(말풍선엔 "삼성"만
// 보이지만 실제 요청은 원래 검색어+브랜드 조합이라 재시도 시 필요).
export interface ChatTurn {
  id: string;
  displayQuery: string;
  requestQuery: string;
  brand?: string;
  // AI 상세검색 드릴다운 체인의 맨 처음 검색어(속도 개선, 2026-08-13) - "핸드폰"
  // -> "핸드폰 삼성전자"로 좁혀가는 동안 이 값은 계속 "핸드폰"으로 고정된다.
  // checkClarifyFacets가 이걸 base_query로 보내 백엔드 캐시를 재사용한다.
  baseQuery: string;
  status: TurnStatus;
  result: DecideResult | null;
  errorMessage: string;
  // AI 오케스트레이션(adk_pipeline: 정제→검색→제안→검증→심사) 진행 상태 -
  // decideStream이 이 턴을 처리하는 동안 status/proposal 이벤트로 채워진다.
  streamingStage: DecideStage | null;
  streamingProposals: Proposal[];
  // 메시지 시간 표시(사용자 요청, "클로드 너처럼 날짜기능") - epoch ms.
  // loadFromHistory는 실제 기록 시각을 쓰고, 그 외엔 턴 생성 시각.
  createdAt: number;
}

interface SearchContextValue {
  turns: ChatTurn[];
  isBusy: boolean;
  ocrBusy: boolean;
  history: HistoryEntry[];
  // 사용자 페르소나(2026-08-15) - 이번 세션에서 지금까지 고른 {facet 라벨: 값}.
  // SearchResults가 옵션 버튼에 "선호" 표시를 붙이는 데 쓴다 - 실제 옵션 순서
  // 반영(우선순위를 앞으로 당기는 것)은 백엔드(check_clarify_facets)가 이미
  // 하므로, 여기서는 순수하게 시각적 표시 용도다.
  sessionPreferences: Record<string, string>;
  sendMessage: (q: string) => Promise<void>;
  selectBrand: (turnId: string, brand: string) => Promise<void>;
  selectFacets: (turnId: string, selected: Record<string, string>) => Promise<void>;
  selectClarifyOption: (turnId: string, step: Exclude<ClarifyStep, 'brand'>, value: string) => Promise<void>;
  retryTurn: (turnId: string) => Promise<void>;
  editTurn: (turnId: string, newQuery: string) => Promise<void>;
  handleImageUpload: (file: File) => Promise<void>;
  handleReset: () => void;
  loadFromHistory: (entry: HistoryEntry) => void;
  deleteFromHistory: (id: string) => void;
  clearAllHistory: () => void;
}

const SearchContext = createContext<SearchContextValue | null>(null);

// facet/옵션 선택을 이어붙일 때 이미 있는 단어를 또 붙이지 않는다(사용자 요청,
// 2026-08-14: "다나와에서 '초코파이 오리온 초코파이 바나나 468g'에 대한 가격
// 정보를 찾지 못했다" - 시리즈 옵션 "초코파이 바나나" 자체가 이미 원래 검색어
// "초코파이"를 포함하고 있어서, 그냥 이어붙이면 "초코파이"가 두 번 들어가
// 검색이 이상하게 안 맞는 검색어가 됐다). 토큰(공백 기준) 단위로만 비교한다.
const dedupeAppend = (base: string, addition: string): string => {
  const baseTokens = base.trim().split(/\s+/).filter(Boolean);
  const seen = new Set(baseTokens.map((t) => t.toLowerCase()));
  const newTokens = addition
    .trim()
    .split(/\s+/)
    .filter((t) => t && !seen.has(t.toLowerCase()));
  return [...baseTokens, ...newTokens].join(' ');
};

// 고정 축(product/volume/quantity) -> 사용자 페르소나 라벨 매핑. AI
// 상세검색(facet)과 서로 다른 라벨 체계를 쓰므로("volume" vs 실제 facet 라벨
// "용량"), 향후 facet 재정렬에서 실제로 매칭될 수 있는 축(용량)만 공용 라벨로
// 옮겨 기록한다. product는 특정 상품명 그 자체라 재사용 가치가 낮아 기록하지 않는다.
const CLARIFY_STEP_PERSONA_LABEL: Partial<Record<Exclude<ClarifyStep, 'brand'>, string>> = {
  volume: '용량',
  quantity: '구매유형',
};

const newTurn = (
  displayQuery: string,
  requestQuery: string,
  brand?: string,
  baseQuery?: string
): ChatTurn => ({
  id: crypto.randomUUID(),
  displayQuery,
  requestQuery,
  brand,
  baseQuery: baseQuery || requestQuery,
  status: 'loading',
  result: null,
  errorMessage: '',
  streamingStage: null,
  streamingProposals: [],
  createdAt: Date.now(),
});

export const SearchProvider = ({ children }: { children: React.ReactNode }) => {
  const { user } = useAuth();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  // 사용자 페르소나(2026-08-15, "냉장고 살 때랑 콜라 살 때 쓰는 메타데이터가
  // 다르다" -> "사용자 페르소나 기반으로 상품 매핑") - 이번 세션에서 지금까지
  // 고른 facet/축 값을 {라벨: 값}으로 누적한다. 현재 드릴다운 체인(baseQuery)에
  // 갇히지 않고 세션 전체(예: 폰 검색에서 "삼성" 고른 뒤, 완전히 새로 시작한
  // 이어폰 검색에도)에 걸쳐 유지된다. 로그인 계정에는 추가로 영구 저장한다
  // (rememberPreference 참고) - 세션 값은 새로고침하면 사라지지만, 계정 값은
  // 다음 방문에도 /decide/clarify가 자동으로 다시 불러와 반영한다.
  const [sessionPreferences, setSessionPreferences] = useState<Record<string, string>>({});

  // 로그인 상태가 바뀌면 기록 소스를 전환한다 — 로그인하면 그 계정의 서버 기록을
  // 불러오고, 로그아웃하면 이 브라우저의 로컬 기록으로 되돌아간다.
  useEffect(() => {
    if (!user) {
      setHistory(loadHistory());
      return;
    }
    const token = getStoredToken();
    if (!token) return;
    fetchServerHistory(token).then((entries) => setHistory(entries.map(fromServerEntry)));
  }, [user]);

  const persistHistoryEntry = async (q: string, data: DecideResult) => {
    if (user) {
      const token = getStoredToken();
      if (!token) return;
      const saved = await saveServerHistory(token, q, data);
      if (saved) {
        setHistory((prev) => [fromServerEntry(saved), ...prev]);
      }
      return;
    }
    setHistory(saveHistoryEntry(q, data));
  };

  const patchTurn = (id: string, patch: Partial<ChatTurn>) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  };

  // 페르소나 한 줄(라벨:값) 기록 - 세션 상태는 즉시 반영해 바로 다음
  // checkClarifyFacets 호출부터 쓰이고, 로그인 계정에는 fire-and-forget으로
  // 영구 저장한다(실패해도 검색 흐름에 영향 없음).
  const rememberPreference = (label: string, value: string) => {
    setSessionPreferences((prev) => ({ ...prev, [label]: value }));
    if (user) {
      const token = getStoredToken();
      if (token) recordPreference(token, label, value).catch(() => {});
    }
  };

  // 턴 하나의 실제 검색/조회를 실행하고 그 턴만 갱신한다. sendMessage(새 턴 추가)/
  // selectBrand/selectFacets/selectClarifyOption(후속 턴 추가)/retryTurn(기존 턴
  // 재실행) 전부 이 위에서 돈다. AI 오케스트레이션(adk_pipeline, decideStream)이
  // 이 함수 안쪽(백엔드 API 호출)에서 한 턴을 처리하는 stateless 단계를 맡는다 -
  // 턴/히스토리/baseQuery 관리는 이 함수 바깥(sendMessage 등 호출부)의 책임이다.
  //
  // skipIntentCheck - 이미 브랜드를 골랐거나(brand) 이전 턴에서 축적된 검색어로
  // 이어가는 드릴다운 후속 턴(requestQuery !== baseQuery)이면 백엔드의 내부
  // clarify 재판정(needs_clarification)을 건너뛴다 - 안 그러면 이미 한 번 답한
  // 축(브랜드/용량 등)에 대해 서버가 또 clarify를 띄우는 재질문 버그가 생긴다
  // (2026-08 통합 병합 승인안의 "skip_internal_clarify" 요구사항을 기존
  // skip_intent_check 플래그로 구현).
  //
  // personaOverride - 바로 이 턴을 만든 선택(예: 방금 rememberPreference로 기록한
  // 라벨:값)을 checkClarifyFacets 호출에 즉시 반영하기 위한 값이다. setState는
  // 비동기라 rememberPreference 직후 곧바로 runTurn을 불러도 이 함수가 캡처한
  // sessionPreferences는 아직 리렌더 전 값(반영 안 됨)일 수 있어, 호출부가 방금
  // 배운 값을 명시적으로 얹어 보낸다.
  const runTurn = async (
    id: string,
    requestQuery: string,
    brand?: string,
    baseQuery?: string,
    personaOverride?: Record<string, string>
  ) => {
    if (brand) {
      try {
        const data = await decide(requestQuery, brand);
        patchTurn(id, { status: 'result', result: data });
        persistHistoryEntry(requestQuery, data).catch(() => {});
      } catch (err) {
        patchTurn(id, {
          status: 'error',
          errorMessage:
            err instanceof ApiError ? err.message : '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
        });
      }
      return;
    }

    const skipIntentCheck = requestQuery !== (baseQuery ?? requestQuery);

    try {
      // AI 상세검색(2026-08-12) - "음료수"처럼 짧고 애매한 검색어면 다나와 실측
      // 가격 스트림을 바로 태우기 전에 먼저 물어본다. looksAmbiguous()가
      // 대부분의(구체적인) 검색어를 걸러내므로 이 호출 자체가 거의 항상 스킵된다.
      // 실패해도(.catch) 조용히 원래 검색으로 넘어간다 - AI 상세검색은 있으면
      // 좋은 보조 기능이지 필수 경로가 아니다. 후속 턴(skipIntentCheck)에서는
      // 이미 한 축을 답했으므로 다시 묻지 않는다.
      if (!skipIntentCheck && looksAmbiguous(requestQuery)) {
        const persona = { ...sessionPreferences, ...personaOverride };
        const clarify = await checkClarifyFacets(requestQuery, baseQuery, persona, getStoredToken()).catch(
          () => null
        );
        if (clarify && clarify.options.facets.length > 0) {
          patchTurn(id, { status: 'result', result: clarify });
          return;
        }
      }

      let finalResult: DecideResult | null = null;
      let streamError: string | null = null;
      await decideStream(
        requestQuery,
        (event) => {
          if (event.type === 'status') {
            patchTurn(id, { streamingStage: event.stage });
          } else if (event.type === 'proposal') {
            setTurns((prev) =>
              prev.map((t) =>
                t.id === id ? { ...t, streamingProposals: [...t.streamingProposals, event.proposal] } : t
              )
            );
          } else if (event.type === 'final') {
            finalResult = event.result;
          } else if (event.type === 'error') {
            streamError = event.message;
          }
        },
        undefined,
        undefined,
        skipIntentCheck
      );

      if (streamError || !finalResult) {
        throw new ApiError(streamError || '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }
      patchTurn(id, { status: 'result', result: finalResult });
      persistHistoryEntry(requestQuery, finalResult).catch(() => {});
    } catch (err) {
      patchTurn(id, {
        status: 'error',
        errorMessage:
          err instanceof ApiError ? err.message : '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
      });
    }
  };

  const sendMessage = async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    const turn = newTurn(trimmed, trimmed);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, undefined, turn.baseQuery);
  };

  // clarify 카드에서 브랜드를 고르면 "새 메시지를 보낸 것"처럼 대화에 이어붙인다 -
  // 원래 검색어는 그대로 두고 브랜드만 골라 재조회하는 후속 질문 취급.
  const selectBrand = async (turnId: string, brand: string) => {
    const origin = turns.find((t) => t.id === turnId);
    if (!origin) return;
    rememberPreference('브랜드', brand);
    const turn = newTurn(brand, origin.requestQuery, brand);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, turn.brand);
  };

  // AI 상세검색 카드에서 기준(facet) 옵션을 하나 고르면 원래 검색어 뒤에 덧붙여
  // 새 메시지처럼 이어붙인다. brand 파라미터를 안 써서(run_brand_price가 아니라)
  // 일반 검색 경로를 그대로 타므로, 조합한 검색어가 여전히 애매하면 runTurn의
  // clarify 선체크가 다시 걸려 자연스럽게 여러 턴에 걸쳐 좁혀나갈 수 있다.
  // baseQuery는 origin에서 그대로 물려받는다(origin.requestQuery가 아니라) -
  // 드릴다운 체인 전체가 맨 처음 검색어 하나로 고정돼야 백엔드가 매번 그
  // 하나만 캐시해서 재사용할 수 있다(속도 개선, 2026-08-13).
  //
  // selected가 {라벨: 값}으로 넘어온다(사용자 페르소나, 2026-08-15) - 값
  // 배열이 아니라 라벨을 같이 받아야 어느 facet에서 이 값을 골랐는지 세션/계정
  // 페르소나에 정확히 기록할 수 있다.
  const selectFacets = async (turnId: string, selected: Record<string, string>) => {
    const origin = turns.find((t) => t.id === turnId);
    const values = Object.values(selected);
    if (!origin || values.length === 0) return;
    Object.entries(selected).forEach(([label, value]) => rememberPreference(label, value));
    const combined = values.reduce((acc, value) => dedupeAppend(acc, value), origin.requestQuery).trim();
    const turn = newTurn(values.join(' · '), combined, undefined, origin.baseQuery);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, undefined, turn.baseQuery, selected);
  };

  // 고정 축(제품/용량/개수) clarify 카드에서 옵션 하나를 고르거나 채팅으로
  // 매칭됐을 때 - selectFacets와 같은 방식으로 검색어에 이어붙여 후속 턴을
  // 만든다(run_brand_price로 단축하지 않고 일반 검색 경로를 그대로 탄다).
  //
  const selectClarifyOption = async (turnId: string, step: Exclude<ClarifyStep, 'brand'>, value: string) => {
    const origin = turns.find((t) => t.id === turnId);
    if (!origin) return;
    const personaLabel = CLARIFY_STEP_PERSONA_LABEL[step];
    const personaOverride = personaLabel ? { [personaLabel]: value } : undefined;
    if (personaLabel) rememberPreference(personaLabel, value);
    const combined = dedupeAppend(origin.requestQuery, value).trim();
    const turn = newTurn(value, combined, undefined, origin.baseQuery);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, undefined, turn.baseQuery, personaOverride);
  };

  const retryTurn = async (turnId: string) => {
    const turn = turns.find((t) => t.id === turnId);
    if (!turn) return;
    patchTurn(turnId, { status: 'loading', errorMessage: '', streamingStage: null, streamingProposals: [] });
    await runTurn(turnId, turn.requestQuery, turn.brand, turn.baseQuery);
  };

  // 내 메시지 편집(사용자 요청, "클로드 너처럼 ... 편집기능") - 클로드처럼 편집한
  // 턴 이후에 이어지던 턴들은 그 편집 전 맥락으로 답한 것이라 더 이상 유효하지
  // 않으므로 버리고, 편집한 턴을 새 루트 질문 취급해 처음부터 다시 실행한다.
  // id는 그대로 유지해 리스트에서 자리가 안 바뀌게 한다.
  const editTurn = async (turnId: string, newQuery: string) => {
    const trimmed = newQuery.trim();
    if (!trimmed) return;
    const index = turns.findIndex((t) => t.id === turnId);
    if (index === -1) return;
    const edited: ChatTurn = { ...newTurn(trimmed, trimmed), id: turnId };
    setTurns((prev) => [...prev.slice(0, index), edited]);
    await runTurn(edited.id, edited.requestQuery, undefined, edited.baseQuery);
  };

  const handleImageUpload = async (file: File) => {
    setOcrBusy(true);
    try {
      const { ocr, cleaned } = await extractOcr(file);
      const extractedText = (cleaned?.search_query || cleaned?.cleaned_text || ocr.text || '').trim();
      if (!extractedText) {
        setTurns((prev) => [
          ...prev,
          {
            ...newTurn('(이미지)', ''),
            status: 'error',
            errorMessage: ocr.error || '이미지에서 텍스트를 찾지 못했습니다.',
          },
        ]);
        return;
      }
      await sendMessage(extractedText);
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        {
          ...newTurn('(이미지)', ''),
          status: 'error',
          errorMessage:
            err instanceof ApiError ? err.message : '이미지 분석 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
        },
      ]);
    } finally {
      setOcrBusy(false);
    }
  };

  const handleReset = () => {
    setTurns([]);
  };

  const loadFromHistory = (entry: HistoryEntry) => {
    setTurns([
      {
        ...newTurn(entry.query, entry.query),
        status: 'result',
        result: entry.result,
        createdAt: entry.timestamp,
      },
    ]);
  };

  const deleteFromHistory = (id: string) => {
    if (user) {
      const token = getStoredToken();
      if (token) deleteServerHistoryEntry(token, id).catch(() => {});
      setHistory((prev) => prev.filter((h) => h.id !== id));
      return;
    }
    setHistory(deleteHistoryEntry(id));
  };

  const clearAllHistory = () => {
    if (user) {
      const token = getStoredToken();
      if (token) clearServerHistory(token).catch(() => {});
      setHistory([]);
      return;
    }
    setHistory(clearHistory());
  };

  const isBusy = ocrBusy || turns.some((t) => t.status === 'loading');

  return (
    <SearchContext.Provider
      value={{
        turns,
        isBusy,
        ocrBusy,
        history,
        sessionPreferences,
        sendMessage,
        selectBrand,
        selectFacets,
        selectClarifyOption,
        retryTurn,
        editTurn,
        handleImageUpload,
        handleReset,
        loadFromHistory,
        deleteFromHistory,
        clearAllHistory,
      }}
    >
      {children}
    </SearchContext.Provider>
  );
};

export const useSearch = () => {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearch는 SearchProvider 내부에서만 사용할 수 있습니다.');
  return ctx;
};
