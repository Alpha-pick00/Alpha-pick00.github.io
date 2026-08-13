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
}

interface SearchContextValue {
  turns: ChatTurn[];
  isBusy: boolean;
  ocrBusy: boolean;
  history: HistoryEntry[];
  sendMessage: (q: string) => Promise<void>;
  selectBrand: (turnId: string, brand: string) => Promise<void>;
  selectFacets: (turnId: string, values: string[]) => Promise<void>;
  selectClarifyOption: (turnId: string, value: string) => Promise<void>;
  retryTurn: (turnId: string) => Promise<void>;
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
});

export const SearchProvider = ({ children }: { children: React.ReactNode }) => {
  const { user } = useAuth();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());

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
  const runTurn = async (id: string, requestQuery: string, brand?: string, baseQuery?: string) => {
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
        const clarify = await checkClarifyFacets(requestQuery, baseQuery).catch(() => null);
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
  const selectFacets = async (turnId: string, values: string[]) => {
    const origin = turns.find((t) => t.id === turnId);
    if (!origin || values.length === 0) return;
    const combined = values.reduce((acc, value) => dedupeAppend(acc, value), origin.requestQuery).trim();
    const turn = newTurn(values.join(' · '), combined, undefined, origin.baseQuery);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, undefined, turn.baseQuery);
  };

  // 고정 축(제품/용량/개수) clarify 카드에서 옵션 하나를 고르거나 채팅으로
  // 매칭됐을 때 - selectFacets와 같은 방식으로 검색어에 이어붙여 후속 턴을
  // 만든다(run_brand_price로 단축하지 않고 일반 검색 경로를 그대로 탄다).
  const selectClarifyOption = async (turnId: string, value: string) => {
    const origin = turns.find((t) => t.id === turnId);
    if (!origin) return;
    const combined = dedupeAppend(origin.requestQuery, value).trim();
    const turn = newTurn(value, combined, undefined, origin.baseQuery);
    setTurns((prev) => [...prev, turn]);
    await runTurn(turn.id, turn.requestQuery, undefined, turn.baseQuery);
  };

  const retryTurn = async (turnId: string) => {
    const turn = turns.find((t) => t.id === turnId);
    if (!turn) return;
    patchTurn(turnId, { status: 'loading', errorMessage: '', streamingStage: null, streamingProposals: [] });
    await runTurn(turnId, turn.requestQuery, turn.brand, turn.baseQuery);
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
        sendMessage,
        selectBrand,
        selectFacets,
        selectClarifyOption,
        retryTurn,
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
